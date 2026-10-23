"""The AI run (D187, D295): `mailrobbe ai run`, a run of kind ai in the job table with its steps.

    check       tasks a run that died left running wait again; valid results go back into
                documents an import made again (store.reapply_results); the vision service the
                waiting tasks need or may use is checked: refused (D181), reachable, its model
                offered. A missing model, or a vision service tasks need and cannot have, stops
                the run before it takes a task; one "auto" could use and cannot leaves everything
                to Tesseract, whose languages are checked too. When transcribe tasks wait, the
                transcriber's files must be in MAILROBBE_AI_MODEL_DIR: what is missing is
                downloaded now (D291), the step counting its bytes; files that cannot be had stop
                the run before it takes a task, a stop keeps what came. The text service is
                checked when summaries wait: a missing model stops the run, one that is not
                set, refused, or (while other tasks wait too) not answering leaves the
                summaries waiting
    ocr         the waiting OCR tasks one at a time, highest priority first, then the documents
                carried by most mails (D186): the bytes read from the MBOX file, pages rendered
                in small batches from the first page not read yet (ai.ocr.render, a child
                process), each page read by Tesseract or the vision model, kept in
                ai_task.partial and committed, so a stop loses at most the pages in work; at most
                max_pages pages per document and pass. Then store.store_ocr_result, the task done,
                ai_calibration updated
    transcribe  the waiting transcribe tasks in the same order, the step counting documents: the
                transcriber loaded once (Parakeet with transcribe_threads threads), each
                recording's bytes decoded in a child process (ai.audio.decode, at most
                max_minutes of it), its speech cut into pieces and each piece read, its lines
                kept in ai_task.partial with the second reached and committed, so a stop loses
                at most the piece in work and the next run goes on from there (D293). Then
                store.store_transcript_result, the task done, ai_calibration updated per minute
                of recording. A file without sound or without speech is done without a text
    summarize   the waiting summaries of mails and documents one at a time (ai.summarize.step,
                D300 to D306), after OCR and transcription so a text recognised in this run is
                what they read; a long text part by part, each part kept, so a stop continues
                at the next part
    entities    the entities phase of the import (D84), which also computes the entity figures,
    signals     and the signals phase (D135), when a document's text changed in this run

A run with --aliases (AiOptions.aliases, D321) takes no task: its check reads the candidate pairs
of the alias check and makes the text service usable, which must be one on this machine (D322);
its step aliases (ai.aliases.step) asks about one pair at a time and keeps each verdict, so a
stop continues with the pairs not yet checked.

A run started for some documents or mails (AiOptions.documents, AiOptions.mails, D280, D307)
takes only their tasks, of every kind, and leaves the rest of the queue waiting.

The engine of a task (D182) is its own, or for "auto" the run's choice; "auto" reads a PDF with
Tesseract and an image with the vision model when one is usable, and reads a Tesseract page that
is uncertain again with the vision model, keeping that page unless it failed or came back empty.
Tesseract reads tesseract_workers pages at once, the vision model concurrency pages.

Failures (D184): an unreadable file, a page rendering that fails, a recording that cannot be
decoded or a transcriber failing on it is an attempt of the task; a page whose answer is invalid
is tried AI_TASK_ATTEMPTS times and then kept with its error; a task fails after
AI_TASK_ATTEMPTS attempts. A service that does not answer fails nothing: the page waits
WAIT_FIRST seconds, doubling up to WAIT_MAX, and after WAIT_LIMIT without an answer the run
stops. A missing model, a missing Tesseract or transcriber files that cannot be had stop the
run. A stop request (dashboard, Ctrl-C, SIGTERM) ends the run between pages or pieces; the task
in work waits again with what it read. A stop or failure before the transcribe step skips it. A
remote vision or text service (D181) logs every request in ai_send_log, and the run stops once its
tokens exceed MAILROBBE_AI_REMOTE_TOKEN_BUDGET. Keys are never logged or stored.

The recognisers, the service check, the decoder and the transcriber are ai.ocr, ai.services and
ai.audio, reached through Engines so the tests hand in doubles.

Exit status: 0 when the queue is done, 130 when stopped by request (the next run continues), 1
when it could not start, a service did not answer for WAIT_LIMIT, the token budget is used up,
a model, Tesseract or the transcriber's files are missing, or the signals phase failed.
"""

import asyncio
import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from mailrobbe.ai import services
from mailrobbe.ai.aliases.step import AliasStep
from mailrobbe.ai.audio import decode, parakeet
from mailrobbe.ai.audio.decode import SAMPLE_RATE, Decoded
from mailrobbe.ai.audio.parakeet import ModelState, Piece
from mailrobbe.ai.model import (
    AI_STEPS,
    AI_TASK_ATTEMPTS,
    TRANSCRIBE_MODEL,
    AiOptions,
    AiProgress,
    OcrEngine,
    OcrPage,
    Partial,
    Service,
    ServiceCheck,
    TranscriptPartial,
    TranscriptSegment,
    configured_services,
    locality,
    page_text,
    refusal,
    transcript_text,
)
from mailrobbe.ai.model import (
    Protocol as ServiceProtocol,
)
from mailrobbe.ai.ocr import render, tesseract, vision
from mailrobbe.ai.prompts import load_prompts
from mailrobbe.ai.store import reapply_results, store_ocr_result, store_transcript_result
from mailrobbe.ai.summarize.step import SummarizeStep
from mailrobbe.attachments.content import AttachmentChanged, document_sources, read_attachment
from mailrobbe.config import Settings
from mailrobbe.db.session import create_engine, create_sessionmaker
from mailrobbe.enums import AiTaskKind, JobKind, JobOrigin, JobStatus
from mailrobbe.importer.cli import _compute_signals, _scan_entities
from mailrobbe.jobrun import EXIT_INTERRUPTED, JobRun, Step, describe, job_run
from mailrobbe.jobs import application_name

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FAILED = 1
# The steps of a run in order: the entities phase computes the entity figures at its end, so
RUN_STEPS = AI_STEPS
RENDER_BATCH = 4  # pages rendered at once (at least as many as are read at once)
WAIT_FIRST = 30.0  # seconds before asking a service again that did not answer (D184)
WAIT_MAX = 600.0  # the pause doubles up to this
WAIT_LIMIT = 1800.0  # without an answer for this long, the run stops


# The seam to ai.ocr and ai.services -----------------------------------------------------------


class RenderedPage(Protocol):
    @property
    def number(self) -> int: ...
    @property
    def png(self) -> bytes: ...


class Rendering(Protocol):
    @property
    def pages_total(self) -> int | None: ...
    @property
    def pages(self) -> Sequence[RenderedPage]: ...


Samples = npt.NDArray[np.int16]


class Transcribing(Protocol):
    """ai.audio.parakeet.Transcriber as the run uses it."""

    def pieces(self, samples: Samples, *, start: float = 0.0) -> list[Piece]: ...
    def read(
        self, samples: Samples, piece: Piece, *, uncertain: float
    ) -> list[TranscriptSegment]: ...


@dataclass(frozen=True, slots=True)
class EngineErrors:
    """The exceptions of ai.services, ai.ocr and ai.audio the run tells apart."""

    unreachable: type[Exception]  # the service did not answer: wait, fail nothing
    model_missing: type[Exception]  # the service does not offer the model: stop
    answer: type[Exception]  # an invalid answer for one page: an attempt of the page
    render: type[Exception]  # the file cannot be rendered: an attempt of the task
    tesseract_missing: type[Exception]  # stop
    decode: type[Exception]  # the recording gives no sound: an attempt of the task
    model_files: type[Exception]  # the transcriber's files are missing and cannot be had: stop


@dataclass(frozen=True, slots=True)
class Engines:
    """What the run calls to render, recognise, check, decode and transcribe (ai.ocr,
    ai.services, ai.audio)."""

    # render(data, kind, *, purpose, first, count, timeout, memory) -> Rendering
    render: Callable[..., Rendering]
    # tesseract(png, number, *, languages, uncertain, timeout) -> OcrPage
    tesseract: Callable[..., OcrPage]
    # languages(languages): raises tesseract_missing unless Tesseract has them all
    languages: Callable[[str], None]
    # vision(service, png, number, *, prompts, protocol, timeout) -> OcrPage
    vision: Callable[..., OcrPage]
    # check(service, settings, *, test) -> ServiceCheck, never raises
    check: Callable[..., ServiceCheck]
    # the prompts of ai.toml, with their version
    prompts: Callable[[], Any]
    # decode(data, *, timeout, memory, max_seconds) -> Decoded, in a child process
    decode: Callable[..., Decoded]
    # transcriber(model_dir, *, threads) -> Transcribing, loaded once per run
    transcriber: Callable[..., Transcribing]
    # model_state(model_dir) -> ModelState; download_model(model_dir, *, progress, stop)
    model_state: Callable[[Path], ModelState]
    download_model: Callable[..., None]
    errors: EngineErrors


def default_engines() -> Engines:
    """ai.ocr, ai.services and ai.audio."""
    return Engines(
        render=render.render,
        tesseract=tesseract.read_page,
        languages=tesseract.check_languages,
        vision=vision.read_page,
        check=services.check_service,
        prompts=load_prompts,
        decode=decode.decode,
        transcriber=parakeet.Transcriber,
        model_state=parakeet.model_state,
        download_model=parakeet.download_model,
        errors=EngineErrors(
            unreachable=services.Unreachable,
            model_missing=services.ModelMissing,
            answer=services.AnswerError,
            render=render.RenderError,
            tesseract_missing=tesseract.TesseractMissing,
            decode=decode.DecodeError,
            model_files=parakeet.ModelMissing,
        ),
    )


# The run --------------------------------------------------------------------------------------


@dataclass(slots=True)
class AiSummary:
    """Printed as JSON by `mailrobbe ai run`."""

    status: str  # done, stopped or failed
    message: str  # one line, also job.message
    queued: int = 0  # tasks waiting at the start, OCR and transcribe
    done: int = 0  # finished with a text
    no_text: int = 0  # finished without writing found, or without speech
    failed: int = 0
    pages: int = 0  # read by this run
    minutes: float = 0.0  # of recordings transcribed by this run
    documents: int = 0  # documents whose text changed: new texts and results put back
    tokens_in: int = 0
    tokens_out: int = 0
    vision: str | None = None  # display URL of the vision service the run used
    elapsed_seconds: float = 0.0
    summaries_queued: int = 0  # summarize tasks waiting at the start (D300)
    summaries: int = 0  # summaries stored
    summaries_failed: int = 0
    text: str | None = None  # display URL of the text service the run used
    aliases_queued: int = 0  # candidate pairs of a run with --aliases (D321)
    aliases: int = 0  # pairs checked
    aliases_same: int = 0  # of them judged one person
    aliases_failed: int = 0


@dataclass(frozen=True, slots=True)
class AiRun:
    summary: AiSummary
    exit_code: int


class _Ended(Exception):
    """The run ends now (a stop, a missing model, a service gone): the task in work waits."""

    def __init__(self, status: JobStatus, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.exit_code = exit_code


class _Attempt(Exception):
    """The task in work failed this attempt (English reason)."""


async def run_ai(
    settings: Settings,
    options: AiOptions,
    *,
    origin: JobOrigin = JobOrigin.CLI,
    engines: Engines | None = None,
) -> AiRun:
    """One run of `mailrobbe ai run`; jobrun.RunRefused when it cannot start (also while an
    import is alive)."""
    progress = AiProgress()

    async def report(_db: AsyncConnection) -> AiProgress:
        return progress.model_copy()  # the run adds its steps

    engine = create_engine(settings.database_url, application_name(JobKind.AI))
    try:
        async with job_run(
            engine,
            JobKind.AI,
            origin,
            options,
            phase="check",
            figures=report,
            excluded=(JobKind.IMPORT,),
        ) as job:
            job.steps.plan(*RUN_STEPS)
            work = _Run(job, settings, options, progress, engines, engine)
            result = await work.run()
            job.end(JobStatus(result.summary.status), result.summary.message)
    finally:
        await engine.dispose()
    return result


@dataclass(slots=True)
class _Task:
    """The task in work, with its document and the pages read so far."""

    id: int
    sha256: str
    engine: str  # the task's choice: auto, tesseract or vision
    document_id: int
    kind: str  # pdf or image
    name: str
    partial: Partial
    estimate: int  # pages the ocr step counted for it
    fresh: list[OcrPage] = field(default_factory=list)  # read by this run
    data: bytes = b""


@dataclass(slots=True)
class _Recording:
    """The transcribe task in work, with its document and the lines read so far."""

    id: int
    sha256: str
    document_id: int
    name: str
    partial: TranscriptPartial


# Tasks a run that died left running, of every kind: holding the lock, no other run is alive
# (D187).
_REQUEUE = text("UPDATE ai_task SET status = 'waiting' WHERE status = 'running'")
# A run for some documents or mails only (AiOptions.documents, AiOptions.mails) leaves the other
# tasks waiting, of every kind: a run for one mail reads no document (ai.summarize.step too).
_ONLY = (
    "((cardinality(CAST(:documents AS bigint[])) = 0"
    " AND cardinality(CAST(:mails AS bigint[])) = 0)"
    " OR ({task}.target = 'document' AND {task}.target_sha256 IN"
    " (SELECT sha256 FROM document WHERE id = ANY(CAST(:documents AS bigint[]))))"
    " OR ({task}.target = 'mail' AND {task}.target_sha256 IN"
    " (SELECT raw_sha256 FROM mail WHERE id = ANY(CAST(:mails AS bigint[])))))"
)
# The waiting tasks of one kind; pages, vision and auto concern OCR.
_WAITING = text(f"""
    SELECT count(*) AS tasks,
        COALESCE(sum(GREATEST(0, LEAST(COALESCE(d.pages, 1), :max_pages)
            - jsonb_array_length(COALESCE(t.partial -> 'pages', '[]'::jsonb)))), 0) AS pages,
        count(*) FILTER (WHERE t.engine = 'vision') AS vision,
        count(*) FILTER (WHERE t.engine = 'auto') AS auto
    FROM ai_task t LEFT JOIN document d ON d.sha256 = t.target_sha256
    WHERE t.kind = CAST(:kind AS ai_task_kind) AND t.status = 'waiting'
      AND {_ONLY.format(task="t")}
""")
# Transcribe tasks this run will take, before _REQUEUE: whether the check needs the model.
_RECORDINGS = text(f"""
    SELECT EXISTS (SELECT 1 FROM ai_task t
                   WHERE t.kind = 'transcribe' AND t.status IN ('waiting', 'running')
                     AND {_ONLY.format(task="t")})
""")
_TAKE = text(f"""
    UPDATE ai_task t SET status = 'running', job_id = :job_id, started_at = now()
    WHERE t.id = (
        SELECT w.id FROM ai_task w LEFT JOIN document d ON d.sha256 = w.target_sha256
        WHERE w.kind = CAST(:kind AS ai_task_kind) AND w.status = 'waiting'
          AND {_ONLY.format(task="w")}
        ORDER BY w.priority DESC, d.mails DESC NULLS LAST, w.id
        LIMIT 1 FOR UPDATE OF w SKIP LOCKED)
    RETURNING t.id, t.target_sha256, t.engine, t.partial
""")
_DOCUMENT = text("""
    SELECT id, kind::text AS kind, COALESCE(name, '') AS name,
        LEAST(COALESCE(pages, 1), :max_pages) AS estimate
    FROM document WHERE sha256 = :sha256
""")
# An earlier valid result that read only some pages: the next pass continues after it (D182).
_EARLIER = text("""
    SELECT engine, pages, pages_total FROM ai_result
    WHERE kind = 'ocr' AND target_sha256 = :sha256 AND state = 'valid'
""")
_PARTIAL = text("UPDATE ai_task SET partial = CAST(:partial AS jsonb) WHERE id = :id")
_BACK = text("UPDATE ai_task SET status = 'waiting' WHERE id = :id")
_DONE = text("""
    UPDATE ai_task SET status = 'done', result_id = :result_id, partial = '{}'::jsonb,
        error = NULL, finished_at = now()
    WHERE id = :id
""")
_ATTEMPT = text("""
    UPDATE ai_task SET attempts = attempts + 1, error = :error,
        status = CASE WHEN attempts + 1 >= :attempts THEN CAST('failed' AS ai_task_status)
                      ELSE CAST('waiting' AS ai_task_status) END,
        finished_at = CASE WHEN attempts + 1 >= :attempts THEN now() END,
        partial = CASE WHEN :clear THEN '{}'::jsonb ELSE partial END
    WHERE id = :id
    RETURNING status::text
""")
_FAIL = text("""
    UPDATE ai_task SET status = 'failed', error = :error, finished_at = now() WHERE id = :id
""")
# A running mean of the seconds per page (D188).
_CALIBRATE = text("""
    INSERT INTO ai_calibration (kind, engine, model, unit, seconds_per_unit, samples)
    VALUES ('ocr', :engine, :model, 'page', CAST(:seconds AS float8) / CAST(:pages AS integer),
        :pages)
    ON CONFLICT (kind, engine, model) DO UPDATE SET
        seconds_per_unit = (ai_calibration.seconds_per_unit * ai_calibration.samples
            + CAST(:seconds AS float8)) / (ai_calibration.samples + CAST(:pages AS integer)),
        samples = ai_calibration.samples + CAST(:pages AS integer), unit = 'page',
        updated_at = now()
""")
# The transcriber's running mean of the seconds per minute of a recording (D295), weighted by
# the seconds of the recordings measured, which samples counts.
_CALIBRATE_MINUTES = text("""
    INSERT INTO ai_calibration (kind, engine, model, unit, seconds_per_unit, samples)
    VALUES ('transcribe', 'parakeet', :model, 'minute',
        60 * CAST(:seconds AS float8) / CAST(:heard AS integer), :heard)
    ON CONFLICT (kind, engine, model) DO UPDATE SET
        seconds_per_unit = (ai_calibration.seconds_per_unit * ai_calibration.samples
            + 60 * CAST(:seconds AS float8)) / (ai_calibration.samples + CAST(:heard AS integer)),
        samples = ai_calibration.samples + CAST(:heard AS integer), unit = 'minute',
        updated_at = now()
""")
_SENT = text("""
    INSERT INTO ai_send_log (service_url, kind, target_sha256, bytes, job_id)
    VALUES (:service_url, 'ocr', :sha256, :bytes, :job_id)
""")


class _Run:
    """The steps of one run, keeping its figures."""

    def __init__(
        self,
        job: JobRun,
        settings: Settings,
        options: AiOptions,
        progress: AiProgress,
        engines: Engines | None,
        engine: AsyncEngine,
    ) -> None:
        self.job = job
        self.settings = settings
        self.options = options
        self.progress = progress
        self._engines = engines
        self.engine = engine
        self.sessionmaker: async_sessionmaker[AsyncSession] = create_sessionmaker(engine)
        self.summary = AiSummary("failed", "")
        self.started = time.monotonic()
        self.vision: Service | None = None  # usable: checked, allowed, its model offered
        self.protocol: str | None = None
        self.remote = False
        self.remote_tokens = 0
        self.unanswered: float | None = None  # monotonic: since when no service answered
        self.pages_waiting = 0  # the ocr step's total at its start
        self.ocr_waiting = 0  # OCR tasks waiting after the check
        self.recordings_waiting = 0  # transcribe tasks waiting after the check: the step's total
        self._prompts: Any = None
        self.summaries = SummarizeStep(self, _ONLY)
        self.aliases = AliasStep(self)

    @property
    def engines(self) -> Engines:
        if self._engines is None:
            self._engines = default_engines()
        return self._engines

    async def run(self) -> AiRun:
        if self.options.aliases:
            return await self._alias_run()
        self.job.steps.skip("aliases")
        try:
            try:
                await self._check()
                await self._ocr()
            except _Ended:
                self.job.steps.skip("transcribe")
                raise
            await self._transcribe()
            await self._summarize()
            code = EXIT_OK
            self.summary.status, self.summary.message = JobStatus.DONE, self._line()
        except _Ended as ended:
            if not self.summaries.begun:
                self.job.steps.skip("summarize")
            code = ended.exit_code
            self.summary.status = ended.status
            self.summary.message = f"{self._line()}; {ended.message}"
            if ended.exit_code != EXIT_INTERRUPTED:
                log.error("%s", ended.message)
        if self.summary.documents and not self.job.stop.is_set():
            failure = await self._phases()
            if failure is not None and code == EXIT_OK:
                code = EXIT_FAILED
                self.summary.status = JobStatus.FAILED
                self.summary.message = f"{self.summary.message}; {failure}"
        else:
            self.job.steps.skip("entities", "signals")
        if code == EXIT_INTERRUPTED:
            log.info("stopped: run `mailrobbe ai run` again to continue")
        self.summary.elapsed_seconds = round(time.monotonic() - self.started, 1)
        return AiRun(self.summary, code)

    def _line(self) -> str:
        """The run's figures in one line, for job.message; the summary takes its minutes from
        the progress here."""
        summary = self.summary
        summary.minutes = round(self.progress.minutes, 2)
        minutes = f"{summary.minutes:,.1f} minutes of recordings, " if summary.minutes else ""
        line = (
            f"{summary.done + summary.no_text} documents read ({summary.no_text} without text), "
            f"{summary.failed} failed, {summary.pages} pages, {minutes}"
            f"{summary.documents} documents with a new text"
        )
        if self.summaries.problem is not None:
            line += f", {summary.summaries_queued} summaries wait: {self.summaries.problem}"
        elif summary.summaries_queued:
            line += (
                f", {summary.summaries} of {summary.summaries_queued} texts summarised "
                f"({summary.summaries_failed} failed)"
            )
        if summary.tokens_in or summary.tokens_out:
            line += f", {summary.tokens_in + summary.tokens_out} tokens"
        return line

    # check -------------------------------------------------------------------------------------

    async def _check(self) -> None:
        download = await self._model_download()
        with self.job.steps.step(
            "check", unit="bytes" if download else None, total=download or None
        ) as counter:
            async with self.sessionmaker.begin() as session:
                requeued = (await session.execute(_REQUEUE)).rowcount  # type: ignore[attr-defined]
                reapplied = await reapply_results(session)
                waiting = await self._waiting(session, AiTaskKind.OCR)
                recordings = await self._waiting(session, AiTaskKind.TRANSCRIBE)
            if requeued:
                log.warning("%d tasks left running by an earlier run wait again", requeued)
            if reapplied:
                log.info("put %d recognised texts back into documents imported again", reapplied)
            self.summary.documents += reapplied
            self.ocr_waiting = int(waiting.tasks)
            self.recordings_waiting = int(recordings.tasks)
            self.summary.queued = self.progress.queued = self.ocr_waiting + self.recordings_waiting
            choice = self.options.ocr_engine
            needed = int(waiting.vision) > 0 or (choice == "vision" and int(waiting.auto) > 0)
            wanted = choice == "auto" and int(waiting.auto) > 0
            if needed or wanted:
                await self._check_vision(needed)
            tesseract_tasks = int(waiting.tasks) - int(waiting.vision) - int(waiting.auto)
            if tesseract_tasks > 0 or (int(waiting.auto) > 0 and choice != "vision"):
                try:
                    await asyncio.to_thread(self.engines.languages, self.options.languages)
                except self.engines.errors.tesseract_missing as error:
                    raise _Ended(JobStatus.FAILED, describe(error), EXIT_FAILED) from None
            await self._check_text()
            # A stop during the download ends the step as stopped, not failed.
            complete = not self.recordings_waiting or await self._check_model(counter)
        self.pages_waiting = int(waiting.pages)
        if not complete:
            raise _Ended(JobStatus.STOPPED, "stopped on request", EXIT_INTERRUPTED)

    async def _waiting(self, session: AsyncSession, kind: AiTaskKind) -> Any:
        parameters = {
            "kind": kind.value,
            "max_pages": self.options.max_pages,
            "documents": self.options.documents,
            "mails": self.options.mails,
        }
        return (await session.execute(_WAITING, parameters)).one()

    async def _model_download(self) -> int:
        """The bytes the check downloads first (its step counts them): what the transcriber's
        files lack when this run has transcribe tasks, else 0."""
        async with self.sessionmaker() as session:
            only = {"documents": self.options.documents, "mails": self.options.mails}
            recordings = await session.scalar(_RECORDINGS, only)
        if not recordings:
            return 0
        state = await asyncio.to_thread(self.engines.model_state, self.settings.ai_model_dir)
        return 0 if state.ready else state.missing_bytes

    async def _check_model(self, counter: Step) -> bool:
        """Make the transcriber's files complete (D291), downloading what is missing; raises
        _Ended when they cannot be had, and is False after a stop, which keeps what came for
        the next run."""
        directory = self.settings.ai_model_dir
        state = await asyncio.to_thread(self.engines.model_state, directory)
        if state.ready:
            return True
        log.info(
            "the transcriber's model lacks %.1f MB in %s: downloading it",
            state.missing_bytes / 1024**2,
            directory,
        )
        stop = threading.Event()
        relay = asyncio.create_task(self._relay_stop(stop))
        try:
            await asyncio.to_thread(
                self.engines.download_model, directory, progress=counter.advance, stop=stop
            )
        except (self.engines.errors.model_files, OSError) as error:
            raise _Ended(JobStatus.FAILED, self._no_model(error), EXIT_FAILED) from None
        finally:
            relay.cancel()
        if self.job.stop.is_set():
            return False
        state = await asyncio.to_thread(self.engines.model_state, directory)
        if not state.ready:
            missing = f"{state.missing_bytes:,} bytes are still missing"
            raise _Ended(JobStatus.FAILED, self._no_model(missing), EXIT_FAILED)
        return True

    def _no_model(self, reason: BaseException | str) -> str:
        if isinstance(reason, BaseException):
            reason = describe(reason)
        return f"the transcriber's model is not in {self.settings.ai_model_dir}: {reason}"

    async def _relay_stop(self, flag: threading.Event) -> None:
        """Set flag once the run is asked to stop: for work in a thread."""
        await self.job.stop.wait()
        flag.set()

    async def _check_vision(self, needed: bool) -> None:
        """Make the vision service usable or say why not; raises _Ended when tasks need it or
        its model is missing."""
        service = configured_services(self.settings).get("vision")
        if service is not None and self.options.vision_model:
            service = replace(service, model=self.options.vision_model)
        problem = None
        if service is None:
            if not needed:  # without one, everything goes to Tesseract (D182)
                return
            problem = "no vision service is configured (MAILROBBE_AI_VISION_URL)"
        elif not service.model:
            problem = f"no vision model is set for {service.display_url}"
        else:
            problem = refusal(service, self.settings)
        if problem is None:
            assert service is not None
            check = await self._ask(service, needed)
            if check.refused:
                problem = check.refused
            elif check.model_found is False:
                raise _Ended(
                    JobStatus.FAILED,
                    f"{service.display_url} does not offer the model {service.model}",
                    EXIT_FAILED,
                )
            elif not check.reachable:
                problem = f"{service.display_url} does not answer: {check.error or 'no answer'}"
            else:
                self.vision = service
                self.protocol = check.protocol
                self.remote = locality(service.url) == "remote"  # refusal() allowed it
                self.summary.vision = service.display_url
                where = "outside this machine" if self.remote else "local"
                log.info("vision: %s, model %s (%s)", service.display_url, service.model, where)
                return
        if needed:
            raise _Ended(JobStatus.FAILED, f"tasks need the vision model: {problem}", EXIT_FAILED)
        log.warning("everything goes to Tesseract: %s", problem)

    async def _check_text(self) -> None:
        """Make the text service usable for the waiting summaries or say why they wait (D300);
        raises _Ended when its model is missing. One that does not answer is waited for unless
        OCR tasks wait too."""
        if not await self.summaries.count():
            return
        # Waited for when only summaries wait; OCR tasks do not wait for it, the summaries do.
        found = await self._text_service(needed=not self.progress.queued)
        if isinstance(found, str):
            self.summaries.leave(found)
        else:
            self.summaries.use(*found)

    async def _text_service(self, needed: bool) -> tuple[Service, ServiceProtocol] | str:
        """The usable text service with its protocol, or why there is none; raises _Ended when
        its model is missing. needed: one that does not answer is waited for."""
        service = configured_services(self.settings).get("text")
        if service is not None and self.options.text_model:
            service = replace(service, model=self.options.text_model)
        if service is None:
            problem = "no text service is configured (MAILROBBE_AI_TEXT_URL)"
        elif not service.model:
            problem = f"no text model is set for {service.display_url} (MAILROBBE_AI_TEXT_MODEL)"
        else:
            problem = refusal(service, self.settings) or ""
        if not problem:
            assert service is not None
            check = await self._ask(service, needed=needed)
            if check.model_found is False:
                raise _Ended(
                    JobStatus.FAILED,
                    f"{service.display_url} does not offer the model {service.model}",
                    EXIT_FAILED,
                )
            if not check.refused and check.protocol is not None:
                return service, check.protocol
            problem = check.refused or f"{service.display_url}: {check.error or 'no answer'}"
        return problem

    async def _ask(self, service: Service, needed: bool) -> ServiceCheck:
        """The service's check (without the test picture); one tasks need is waited for while
        it does not answer, so that its protocol and models are known before a task is taken."""
        pause = WAIT_FIRST
        while True:
            check = await asyncio.to_thread(self.engines.check, service, self.settings, test=False)
            if check.reachable or check.refused or not needed:
                self._answered()
                return check
            await self._wait(service, check.error or "no answer", pause)
            if self.job.stop.is_set():
                raise _Ended(JobStatus.STOPPED, "stopped on request", EXIT_INTERRUPTED)
            pause = min(pause * 2, WAIT_MAX)

    # ocr ---------------------------------------------------------------------------------------

    async def _ocr(self) -> None:
        if not self.ocr_waiting:
            self.job.steps.skip("ocr")
            return
        self.job.set_phase("ocr")
        ended = None
        with self.job.steps.step("ocr", unit="pages", total=self.pages_waiting) as counter:
            try:
                while not self.job.stop.is_set():
                    task = await self._take()
                    if task is None:
                        break
                    await self._work(task, counter)
            except _Ended as error:  # the step ends stopped or done, not failed
                ended = error
        if ended is not None:
            raise ended
        if self.job.stop.is_set():
            raise _Ended(JobStatus.STOPPED, "stopped on request", EXIT_INTERRUPTED)

    async def _take(self) -> _Task | None:
        """The next waiting task, now running in this run; a task without its document fails."""
        while True:
            async with self.sessionmaker.begin() as session:
                parameters = {
                    "kind": AiTaskKind.OCR.value,
                    "job_id": self.job.job_id,
                    "documents": self.options.documents,
                    "mails": self.options.mails,
                }
                row = (await session.execute(_TAKE, parameters)).first()
                if row is None:
                    return None
                document = (
                    await session.execute(
                        _DOCUMENT,
                        {"sha256": row.target_sha256, "max_pages": self.options.max_pages},
                    )
                ).first()
                if document is not None:
                    partial = Partial.model_validate(row.partial or {})
                    if not partial.pages:
                        partial = await self._continued(session, row.target_sha256, row.engine)
                    return _Task(
                        id=row.id,
                        sha256=row.target_sha256,
                        engine=row.engine,
                        document_id=document.id,
                        kind=document.kind,
                        name=document.name,
                        partial=partial,
                        estimate=max(0, int(document.estimate) - len(partial.pages)),
                    )
                await session.execute(
                    _FAIL, {"id": row.id, "error": "no document has this content any more"}
                )
                self._failed()

    async def _continued(self, session: AsyncSession, sha256: str, engine: str) -> Partial:
        """The pages of an earlier result that read only some, when this task continues it."""
        earlier = (await session.execute(_EARLIER, {"sha256": sha256})).first()
        if earlier is None or earlier.pages_total is None:
            return Partial()
        pages = [OcrPage.model_validate(page) for page in earlier.pages]
        if len(pages) >= earlier.pages_total or engine not in ("auto", earlier.engine):
            return Partial()
        return Partial(pages=pages, pages_total=earlier.pages_total)

    async def _work(self, task: _Task, counter: Step) -> None:
        """One task to its end: done, an attempt, or back to waiting when the run ends."""
        self.progress.current = task.name
        try:
            await self._read_task(task, counter)
        except _Attempt as attempt:
            await self._attempt(task, str(attempt))
        except BaseException:
            async with self.sessionmaker.begin() as session:
                await session.execute(_BACK, {"id": task.id})
            raise
        finally:
            self.progress.current = None
        # The step counted an estimate for the task; what it read is known now.
        if counter.total is not None:
            counter.total = max(counter.done, counter.total - task.estimate + len(task.fresh))

    async def _read_task(self, task: _Task, counter: Step) -> None:
        sources = await self._sources(task)
        try:
            task.data = await asyncio.to_thread(read_attachment, self.settings.mbox_dir, sources)
        except (OSError, AttachmentChanged) as error:
            raise _Attempt(f"unreadable: {describe(error)}") from None
        primary, reread = self._engine_of(task)
        maximum = self.options.max_pages
        # The pass ends at the multiple of max_pages after the first page not read: a stopped
        # pass goes on where it was, one after an incomplete result reads the next pages (D182).
        end = ((self._first_unread(task) - 1) // maximum + 1) * maximum
        while True:
            read = {page.number for page in task.partial.pages}
            first = self._first_unread(task)
            last = end
            if task.partial.pages_total is not None:
                last = min(last, task.partial.pages_total)
            if first > last:
                break  # read to the end of the pass: stored even when a stop arrived
            if self.job.stop.is_set():
                raise _Ended(JobStatus.STOPPED, "stopped on request", EXIT_INTERRUPTED)
            count = min(max(RENDER_BATCH, self._workers(primary)), last - first + 1)
            rendering = await self._render(task, primary, first, count)
            task.partial.pages_total = rendering.pages_total
            pages = [page for page in rendering.pages if page.number not in read]
            if not pages:
                break  # nothing more to render
            await self._read_pages(task, pages, primary, reread, counter)
        await self._finish(task)

    @staticmethod
    def _first_unread(task: _Task) -> int:
        read = {page.number for page in task.partial.pages}
        first = 1
        while first in read:
            first += 1
        return first

    async def _sources(self, task: _Task | _Recording) -> Any:
        async with self.sessionmaker() as session:
            sources = await document_sources(session, [task.document_id])
        if task.document_id not in sources:
            raise _Attempt("unreadable: no attachment carries this document")
        return sources[task.document_id]

    def _engine_of(self, task: _Task) -> tuple[OcrEngine, bool]:
        """The engine reading the task's pages, and whether uncertain pages are read again with
        the vision model (D182)."""
        choice = task.engine if task.engine != "auto" else self.options.ocr_engine
        if choice == "tesseract":
            return "tesseract", False
        if choice == "vision":
            return "vision", False
        if task.kind == "image" and self.vision is not None:
            return "vision", False
        return "tesseract", self.vision is not None

    def _workers(self, engine: OcrEngine) -> int:
        if engine == "vision":
            return max(1, self.options.concurrency)
        return max(1, self.options.tesseract_workers)

    async def _render(self, task: _Task, purpose: OcrEngine, first: int, count: int) -> Rendering:
        try:
            return await asyncio.to_thread(
                self.engines.render,
                task.data,
                "image" if task.kind == "image" else "pdf",
                purpose=purpose,
                first=first,
                count=count,
                timeout=self.settings.attachment_text_timeout,
                memory=int(self.settings.attachment_text_memory),
            )
        except self.engines.errors.render as error:
            raise _Attempt(f"cannot render: {describe(error)}") from None

    async def _read_pages(
        self,
        task: _Task,
        pages: Sequence[RenderedPage],
        engine: OcrEngine,
        reread: bool,
        counter: Step,
    ) -> None:
        """Read these pages, the engine's number at once; each kept and committed as it comes.
        Pages not started when a stop arrives stay unread."""
        limit = asyncio.Semaphore(self._workers(engine))

        async def one(page: RenderedPage) -> OcrPage | None:
            async with limit:
                if self.job.stop.is_set() or self._spent():
                    return None
                return await self._page(task, page, engine, reread)

        running = [asyncio.create_task(one(page)) for page in pages]
        try:
            for next_page in asyncio.as_completed(running):
                found = await next_page
                if found is not None:
                    await self._keep(task, found, counter)
        finally:
            for pending in running:
                pending.cancel()
            await asyncio.gather(*running, return_exceptions=True)
        if self._spent():
            raise self._budget_ended()

    async def _page(
        self, task: _Task, page: RenderedPage, engine: OcrEngine, reread: bool
    ) -> OcrPage:
        if engine == "vision":
            return await self._vision_page(task, page.png, page.number)
        found = await self._tesseract_page(page.png, page.number)
        uncertain = found.uncertain or (
            found.confidence is not None and found.confidence < self.options.uncertain
        )
        if not (reread and uncertain and found.error is None):
            return found
        try:
            again = await self._render(task, "vision", page.number, 1)
        except _Attempt as error:
            log.warning("%s, page %d: kept Tesseract's reading: %s", task.name, page.number, error)
            return found
        if not again.pages:
            return found
        better = await self._vision_page(task, again.pages[0].png, page.number)
        if better.error is not None or not better.text.strip():  # the tokens were spent anyway
            spent = {"tokens_in": better.tokens_in, "tokens_out": better.tokens_out}
            return found.model_copy(update=spent)
        return better

    async def _tesseract_page(self, png: bytes, number: int) -> OcrPage:
        try:
            return await asyncio.to_thread(
                self.engines.tesseract,
                png,
                number,
                languages=self.options.languages,
                uncertain=self.options.uncertain,
                timeout=self.settings.attachment_text_timeout,
            )
        except self.engines.errors.tesseract_missing as error:
            raise _Ended(JobStatus.FAILED, describe(error), EXIT_FAILED) from None

    async def _vision_page(self, task: _Task, png: bytes, number: int) -> OcrPage:
        """A page from the vision model: an invalid answer tried again, a service that does
        not answer waited for (module docstring)."""
        service = self.vision
        assert service is not None
        if self._prompts is None:
            self._prompts = self.engines.prompts()
        errors = self.engines.errors
        attempts = 0
        pause = WAIT_FIRST
        while True:
            if self.job.stop.is_set():
                raise _Ended(JobStatus.STOPPED, "stopped on request", EXIT_INTERRUPTED)
            await self._before_sending(task, png)
            try:
                found = await asyncio.to_thread(
                    self.engines.vision,
                    service,
                    png,
                    number,
                    prompts=self._prompts,
                    protocol=self.protocol,
                    timeout=self.settings.ai_timeout,
                )
            except errors.unreachable as error:
                await self._wait(service, describe(error), pause)
                pause = min(pause * 2, WAIT_MAX)
                continue
            except errors.model_missing as error:
                raise _Ended(JobStatus.FAILED, describe(error), EXIT_FAILED) from None
            except errors.answer as error:
                self._answered()
                attempts += 1
                log.warning("%s, page %d: %s", task.name, number, describe(error))
                if attempts >= AI_TASK_ATTEMPTS:
                    return OcrPage(number=number, engine="vision", error=describe(error))
                continue
            self._answered()
            if self.remote:
                self.remote_tokens += found.tokens_in + found.tokens_out
            return found

    def _spent(self) -> bool:
        """Whether the remote requests used up their token budget (D181)."""
        return self.remote and self.remote_tokens > self.settings.ai_remote_token_budget

    def _budget_ended(self) -> _Ended:
        budget = self.settings.ai_remote_token_budget
        return _Ended(
            JobStatus.STOPPED,
            f"the budget of {budget} tokens for services outside this machine is used up",
            EXIT_FAILED,
        )

    async def _before_sending(self, task: _Task, png: bytes) -> None:
        """A request to a remote service: within the budget, and recorded (D181)."""
        if not self.remote:
            return
        if self._spent():
            raise self._budget_ended()
        assert self.vision is not None
        async with self.sessionmaker.begin() as session:
            await session.execute(
                _SENT,
                {
                    "service_url": self.vision.display_url,
                    "sha256": task.sha256,
                    "bytes": len(png),
                    "job_id": self.job.job_id,
                },
            )

    async def _wait(self, service: Service, reason: str, pause: float) -> None:
        """Wait for a service that did not answer; _Ended after WAIT_LIMIT or on a stop."""
        now = time.monotonic()
        if self.unanswered is None:
            self.unanswered = now
            self.progress.unreachable_since = datetime.now(UTC)
        if now - self.unanswered >= WAIT_LIMIT:
            raise _Ended(
                JobStatus.STOPPED,
                f"{service.display_url} did not answer for {WAIT_LIMIT / 60:.0f} minutes",
                EXIT_FAILED,
            )
        log.warning(
            "waiting for %s (%s), asking again in %.0f s", service.display_url, reason, pause
        )
        try:
            await asyncio.wait_for(self.job.stop.wait(), pause)
        except TimeoutError:
            return

    def _answered(self) -> None:
        self.unanswered = None
        self.progress.unreachable_since = None

    async def _keep(self, task: _Task, page: OcrPage, counter: Step) -> None:
        """One page read: into the task's partial, committed (a stop keeps it)."""
        task.partial.pages = sorted(
            [*(kept for kept in task.partial.pages if kept.number != page.number), page],
            key=lambda kept: kept.number,
        )
        task.fresh.append(page)
        async with self.sessionmaker.begin() as session:
            await session.execute(
                _PARTIAL, {"id": task.id, "partial": task.partial.model_dump_json()}
            )
        counter.advance()
        self.summary.pages += 1
        for figures in (self.summary, self.progress):
            figures.tokens_in += page.tokens_in
            figures.tokens_out += page.tokens_out

    async def _finish(self, task: _Task) -> None:
        """Store the result of the pages read; every page failing is an attempt."""
        pages = task.partial.pages
        if pages and all(page.error is not None for page in pages):
            raise _Attempt(f"every page failed: {pages[0].error}")
        vision = [page for page in pages if page.engine == "vision" and page.error is None]
        service = self.vision if vision else None
        async with self.sessionmaker.begin() as session:
            stored = await store_ocr_result(
                session,
                sha256=task.sha256,
                pages=pages,
                pages_total=task.partial.pages_total,
                model=service.model if service else None,
                service_url=service.display_url if service else None,
                remote=self.remote if service else False,
                prompt_version=self._prompt_version() if service else None,
                options={
                    "engine": task.engine if task.engine != "auto" else self.options.ocr_engine,
                    "languages": self.options.languages,
                    "uncertain": self.options.uncertain,
                    "max_pages": self.options.max_pages,
                },
                seconds=round(sum(page.seconds for page in pages), 3),
                job_id=self.job.job_id,
            )
            await session.execute(_DONE, {"id": task.id, "result_id": stored.result_id})
            await self._calibrate(session, task.fresh)
        self.summary.documents += stored.documents
        body, _ = page_text(pages)
        if body:
            self.summary.done += 1
            self.progress.done += 1
        else:
            self.summary.no_text += 1
            self.progress.no_text += 1
        read = f"{len(pages)} of {task.partial.pages_total} pages"
        failed = sum(page.error is not None for page in pages)
        log.info(
            "%s: %s, %s%s",
            task.name or task.sha256[:12],
            read,
            f"{len(body):,} characters" if body else "no text",
            f", {failed} pages failed" if failed else "",
        )

    def _prompt_version(self) -> int | None:
        version = getattr(self._prompts, "version", None)
        return version if isinstance(version, int) else None

    async def _calibrate(self, session: AsyncSession, pages: Sequence[OcrPage]) -> None:
        """The pages read by this run into the running means per engine and model (D188)."""
        groups: dict[tuple[str, str], list[float]] = {}
        for page in pages:
            if page.error is None and page.seconds > 0:
                model = self.vision.model if page.engine == "vision" and self.vision else ""
                groups.setdefault((page.engine, model), []).append(page.seconds)
        for (engine, model), seconds in groups.items():
            await session.execute(
                _CALIBRATE,
                {"engine": engine, "model": model, "seconds": sum(seconds), "pages": len(seconds)},
            )

    async def _attempt(self, task: _Task | _Recording, reason: str) -> bool:
        """Count a failed attempt of the task; whether the task failed for good."""
        clear = reason.startswith("every page failed")  # the next attempt reads them again
        async with self.sessionmaker.begin() as session:
            status = await session.scalar(
                _ATTEMPT,
                {"id": task.id, "error": reason, "attempts": AI_TASK_ATTEMPTS, "clear": clear},
            )
        log.warning("%s: %s", task.name or task.sha256[:12], reason)
        failed: bool = status == "failed"
        if failed:
            self._failed()
        return failed

    def _failed(self) -> None:
        self.summary.failed += 1
        self.progress.failed += 1

    # transcribe --------------------------------------------------------------------------------

    async def _transcribe(self) -> None:
        if not self.recordings_waiting:
            self.job.steps.skip("transcribe")
            return
        self.job.set_phase("transcribe")
        ended = None
        with self.job.steps.step(
            "transcribe", unit="documents", total=self.recordings_waiting
        ) as counter:
            try:
                transcriber = await self._transcriber()
                while not self.job.stop.is_set():
                    task = await self._take_recording()
                    if task is None:
                        break
                    if await self._hear(task, transcriber):
                        counter.advance()
            except _Ended as error:  # the step ends stopped or done, not failed
                ended = error
        if ended is not None:
            raise ended
        if self.job.stop.is_set():
            raise _Ended(JobStatus.STOPPED, "stopped on request", EXIT_INTERRUPTED)

    async def _transcriber(self) -> Transcribing:
        """Parakeet and Silero VAD, loaded once for the run (about 1.3 GB with four threads)."""
        try:
            return await asyncio.to_thread(
                self.engines.transcriber,
                self.settings.ai_model_dir,
                threads=self.options.transcribe_threads,
            )
        except self.engines.errors.model_files as error:
            raise _Ended(JobStatus.FAILED, self._no_model(error), EXIT_FAILED) from None
        except Exception as error:  # its libraries or ONNX Runtime
            message = f"cannot load the transcriber: {describe(error)}"
            raise _Ended(JobStatus.FAILED, message, EXIT_FAILED) from None

    async def _take_recording(self) -> _Recording | None:
        """The next waiting transcribe task, now running in this run; a task without its
        document fails."""
        while True:
            async with self.sessionmaker.begin() as session:
                parameters = {
                    "kind": AiTaskKind.TRANSCRIBE.value,
                    "job_id": self.job.job_id,
                    "documents": self.options.documents,
                    "mails": self.options.mails,
                }
                row = (await session.execute(_TAKE, parameters)).first()
                if row is None:
                    return None
                document = (
                    await session.execute(_DOCUMENT, {"sha256": row.target_sha256, "max_pages": 1})
                ).first()
                if document is not None:
                    return _Recording(
                        id=row.id,
                        sha256=row.target_sha256,
                        document_id=document.id,
                        name=document.name,
                        partial=TranscriptPartial.model_validate(row.partial or {}),
                    )
                await session.execute(
                    _FAIL, {"id": row.id, "error": "no document has this content any more"}
                )
                self._failed()

    async def _hear(self, task: _Recording, transcriber: Transcribing) -> bool:
        """One recording to its end, or back to waiting when the run ends; whether it ended
        (done, or failed for good) rather than going back to the queue for another attempt."""
        self.progress.current = task.name
        self.progress.position = task.partial.until
        try:
            await self._listen(task, transcriber)
        except _Attempt as attempt:
            return await self._attempt(task, str(attempt))
        except BaseException:
            async with self.sessionmaker.begin() as session:
                await session.execute(_BACK, {"id": task.id})
            raise
        finally:
            self.progress.current = self.progress.position = self.progress.duration = None
        return True

    async def _listen(self, task: _Recording, transcriber: Transcribing) -> None:
        """Decode the recording, read its speech piece by piece from where the task stands,
        each piece's lines kept and committed, and store the transcript."""
        started = time.monotonic()
        sources = await self._sources(task)
        try:
            data = await asyncio.to_thread(read_attachment, self.settings.mbox_dir, sources)
        except (OSError, AttachmentChanged) as error:
            raise _Attempt(f"unreadable: {describe(error)}") from None
        limit = self.options.max_minutes * 60.0
        try:
            sound = await asyncio.to_thread(
                self.engines.decode,
                data,
                timeout=max(self.settings.attachment_text_timeout, 300.0),
                memory=int(self.settings.attachment_text_memory),
                max_seconds=limit,
            )
        except self.engines.errors.decode as error:
            raise _Attempt(f"cannot decode: {describe(error)}") from None
        del data
        partial = task.partial
        decoded = len(sound.samples) / SAMPLE_RATE
        # The decoder may not know the length; what it gave short of the limit is all there is.
        if sound.duration is not None:
            partial.duration = sound.duration
        elif decoded < limit:
            partial.duration = decoded
        self.progress.duration = partial.duration
        begun = partial.until
        if sound.audio:
            uncertain = self.options.transcribe_uncertain
            for piece in await self._model(transcriber.pieces, sound.samples, start=begun):
                if self.job.stop.is_set():
                    raise _Ended(JobStatus.STOPPED, "stopped on request", EXIT_INTERRUPTED)
                lines = await self._model(
                    transcriber.read, sound.samples, piece, uncertain=uncertain
                )
                partial.segments.extend(lines)
                self._reached(partial, piece.end)
                async with self.sessionmaker.begin() as session:
                    await session.execute(
                        _PARTIAL, {"id": task.id, "partial": partial.model_dump_json()}
                    )
        self._reached(partial, max(decoded, partial.until))
        await self._store_transcript(task, sound.audio, time.monotonic() - started, begun)

    async def _model(self, call: Callable[..., Any], *args: Any, **values: Any) -> Any:
        """A call of the transcriber in a thread; what it raises is an attempt of the task."""
        try:
            return await asyncio.to_thread(call, *args, **values)
        except Exception as error:
            raise _Attempt(f"the transcriber failed: {describe(error)}") from None

    def _reached(self, partial: TranscriptPartial, second: float) -> None:
        """The recording in work is read up to second: the task's partial and the figures."""
        if second > partial.until:
            self.progress.minutes += (second - partial.until) / 60
            partial.until = second
        self.progress.position = partial.until

    async def _store_transcript(
        self, task: _Recording, audio: bool, seconds: float, begun: float
    ) -> None:
        """Store what the task read, mark it done and measure the transcriber's speed: seconds
        spent by this run on the seconds of recording it read from begun on."""
        partial = task.partial
        async with self.sessionmaker.begin() as session:
            stored = await store_transcript_result(
                session,
                sha256=task.sha256,
                segments=partial.segments,
                duration=partial.duration,
                transcribed=partial.until,
                audio=audio,
                options={
                    "max_minutes": self.options.max_minutes,
                    "threads": self.options.transcribe_threads,
                    "uncertain": self.options.transcribe_uncertain,
                },
                seconds=round(seconds, 3),
                job_id=self.job.job_id,
            )
            await session.execute(_DONE, {"id": task.id, "result_id": stored.result_id})
            heard = round(partial.until - begun)
            if heard > 0 and seconds > 0:
                await session.execute(
                    _CALIBRATE_MINUTES,
                    {"model": TRANSCRIBE_MODEL, "seconds": seconds, "heard": heard},
                )
        self.summary.documents += stored.documents
        body, _ = transcript_text(partial.segments)
        if body:
            self.summary.done += 1
            self.progress.done += 1
        else:
            self.summary.no_text += 1
            self.progress.no_text += 1
        if not audio:
            found = "no sound"
        elif body:
            found = f"{len(partial.segments)} lines, {len(body):,} characters"
        else:
            found = "no speech"
        length = "" if partial.duration is None else f" of {partial.duration:,.0f}"
        log.info(
            "%s: %s s%s read, %s",
            task.name or task.sha256[:12],
            f"{partial.until:,.0f}",
            length,
            found,
        )

    # summarize ---------------------------------------------------------------------------------

    async def _summarize(self) -> None:
        """The waiting summarize tasks one at a time (ai.summarize.step, D300 to D306)."""
        step = self.summaries
        if step.service is None:  # none waits, or no usable text service (_check_text)
            self.job.steps.skip("summarize")
            return
        self.job.set_phase("summarize")
        ended = None
        with self.job.steps.step("summarize", unit="texts", total=step.waiting) as counter:
            step.begun = True
            try:
                while not self.job.stop.is_set():
                    task = await step.take(counter)
                    if task is None:
                        break
                    await step.work(task, counter)
            except _Ended as error:  # the step ends stopped or done, not failed
                ended = error
        if ended is not None:
            raise ended
        if self.job.stop.is_set():
            raise _Ended(JobStatus.STOPPED, "stopped on request", EXIT_INTERRUPTED)

    async def _answer[T](self, service: Service, call: Callable[[], T]) -> T:
        """What call() gives in a thread once service answers (D184): one that does not answer
        is waited for, a missing model or a stop request ends the run."""
        pause = WAIT_FIRST
        while True:
            if self.job.stop.is_set():
                raise _Ended(JobStatus.STOPPED, "stopped on request", EXIT_INTERRUPTED)
            try:
                found = await asyncio.to_thread(call)
            except services.Unreachable as error:
                await self._wait(service, describe(error), pause)
                pause = min(pause * 2, WAIT_MAX)
                continue
            except services.ModelMissing as error:
                raise _Ended(JobStatus.FAILED, describe(error), EXIT_FAILED) from None
            self._answered()
            return found

    # aliases -----------------------------------------------------------------------------------

    async def _alias_run(self) -> AiRun:
        """A run with --aliases (D321): the check, then the step aliases; no task is taken."""
        self.job.steps.skip("ocr", "transcribe", "summarize")
        try:
            with self.job.steps.step("check"):
                waiting = await self.aliases.read()
                if waiting:
                    self.aliases.use(*await self._local_text_service())
            await self._aliases(waiting)
            code = EXIT_OK
            self.summary.status, self.summary.message = JobStatus.DONE, self._alias_line()
        except _Ended as ended:
            code = ended.exit_code
            self.summary.status = ended.status
            self.summary.message = f"{self._alias_line()}; {ended.message}"
            if ended.exit_code != EXIT_INTERRUPTED:
                log.error("%s", ended.message)
            self.job.steps.skip("aliases")
        self.job.steps.skip("entities", "signals")
        if code == EXIT_INTERRUPTED:
            log.info("stopped: run `mailrobbe ai run --aliases` again to continue")
        self.summary.elapsed_seconds = round(time.monotonic() - self.started, 1)
        return AiRun(self.summary, code)

    async def _local_text_service(self) -> tuple[Service, ServiceProtocol]:
        """The text service of the alias check, which must be on this machine (D322); asked
        only once that is known."""
        service = configured_services(self.settings).get("text")
        if service is not None and locality(service.url) == "remote":
            raise _Ended(
                JobStatus.FAILED,
                f"the alias check sends names and addresses to a text service on this machine "
                f"only, not to {service.display_url}",
                EXIT_FAILED,
            )
        found = await self._text_service(needed=True)
        if isinstance(found, str):
            raise _Ended(
                JobStatus.FAILED, f"the alias check needs a text service: {found}", EXIT_FAILED
            )
        return found

    async def _aliases(self, waiting: int) -> None:
        if not waiting:
            self.job.steps.skip("aliases")
            return
        self.job.set_phase("aliases")
        with self.job.steps.step("aliases", unit="pairs", total=waiting) as counter:
            await self.aliases.work(counter)
        if self.job.stop.is_set():
            raise _Ended(JobStatus.STOPPED, "stopped on request", EXIT_INTERRUPTED)

    def _alias_line(self) -> str:
        """The figures of a run with --aliases in one line, for job.message."""
        summary = self.summary
        line = (
            f"{summary.aliases} of {summary.aliases_queued} pairs of persons checked "
            f"({summary.aliases_same} one person, {summary.aliases_failed} failed)"
        )
        if summary.tokens_in or summary.tokens_out:
            line += f", {summary.tokens_in + summary.tokens_out} tokens"
        return line

    # entities and signals ----------------------------------------------------------------------

    async def _phases(self) -> str | None:
        """The import's entities and signals phases for the new texts; why signals failed."""
        await _scan_entities(self.sessionmaker, max(1, self.settings.import_workers), self.job)
        if self.job.stop.is_set():
            self.job.steps.skip("signals")
            return None
        return await _compute_signals(self.engine, self.settings, self.job)
