"""The run's step summarize (D300 to D311): the waiting summarize tasks one at a time, for ai.run.

    take    the next waiting task, highest priority first, then the oldest (FOR UPDATE SKIP
            LOCKED), within the run's restriction to some documents or mails (ai.run._ONLY); what
            the model reads comes from ai.summarize.inputs. A task whose content is gone or has
            nothing to read fails
    ask     a short text (D302): one request with the short prompt, tags and theme hints only. A
            text that fits the context (ai.summarize.parts): one request without an instruction.
            A longer one (D303): one request per part with the part prompt, each part kept in
            ai_task.partial and committed, so a stop continues at the next part; then one with
            the combine prompt over the parts' summaries and tags for the summary and the tags of
            the whole, while the theme hints are the parts'
    check   each answer through ai.summarize.answer, the quotes looked for in the text of that
            request and their positions mapped back to the stored text
    store   ai.store.store_summary_result, the task done, ai_calibration kept (kind summarize,
            engine text, the model: seconds per 1,000 tokens of the material read, counted from
            its characters as the estimate of D308 counts them)

The system prompt and the answer schema are made once per run (D305). A request goes out through
the run (_Run._answer: a service that does not answer is waited for, a missing model or a stop
request ends the run); one to a service outside this machine is logged in ai_send_log first and
counted against the run's token budget (D181). An answer cut at its length, an HTTP error or an
answer not read by the schema is an attempt of the task (D184): it waits again with its parts and
fails after AI_TASK_ATTEMPTS attempts. A context too small for parts of MIN_PART_CHARS fails the
task at once.
"""

import logging
import math
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel
from sqlalchemy import text

from mailrobbe.ai.model import (
    AI_TASK_ATTEMPTS,
    CHARS_PER_TOKEN,
    SUMMARY_MAX_PARTS,
    Protocol,
    Service,
    Summary,
    SummaryPart,
    ThemeHint,
    locality,
)
from mailrobbe.ai.prompts import SummaryPrompts, load_prompts
from mailrobbe.ai.services import AnswerError, ChatAnswer, chat_text, cut_at_length
from mailrobbe.ai.store import store_summary_result
from mailrobbe.ai.summarize.answer import (
    Answer,
    Checked,
    answer_schema,
    check_answer,
    check_tags,
    limit_hints,
    read_answer,
)
from mailrobbe.ai.summarize.inputs import SummaryInput, document_input, mail_input
from mailrobbe.ai.summarize.parts import MIN_PART_CHARS, Part, answer_tokens, cut, part_chars
from mailrobbe.ai.summarize.prompt import (
    fill,
    load_vocabulary,
    material,
    system_prompt,
    user_message,
)
from mailrobbe.enums import AiTarget
from mailrobbe.jobrun import Step, describe
from mailrobbe.themes import Theme

if TYPE_CHECKING:
    from mailrobbe.ai.run import _Run

log = logging.getLogger(__name__)

# {only} is the run's restriction to some documents or mails (ai.run._ONLY).
_COUNT = """
    SELECT count(*) FROM ai_task t
    WHERE t.kind = 'summarize' AND t.status = 'waiting' AND {only}
"""
_TAKE = """
    UPDATE ai_task t SET status = 'running', job_id = :job_id, started_at = now()
    WHERE t.id = (
        SELECT w.id FROM ai_task w
        WHERE w.kind = 'summarize' AND w.status = 'waiting' AND {only}
        ORDER BY w.priority DESC, w.id
        LIMIT 1 FOR UPDATE OF w SKIP LOCKED)
    RETURNING t.id, t.target, t.target_sha256, t.partial
"""
_PARTIAL = text("UPDATE ai_task SET partial = CAST(:partial AS jsonb) WHERE id = :id")
_BACK = text("UPDATE ai_task SET status = 'waiting' WHERE id = :id")
_DONE = text("""
    UPDATE ai_task SET status = 'done', result_id = :result_id, partial = '{}'::jsonb,
        error = NULL, finished_at = now()
    WHERE id = :id
""")
# An attempt keeps the parts summarised: the next one continues after them.
_ATTEMPT = text("""
    UPDATE ai_task SET attempts = attempts + 1, error = :error,
        status = CASE WHEN attempts + 1 >= :attempts THEN CAST('failed' AS ai_task_status)
                      ELSE CAST('waiting' AS ai_task_status) END,
        finished_at = CASE WHEN attempts + 1 >= :attempts THEN now() END
    WHERE id = :id
    RETURNING status::text
""")
_FAIL = text("""
    UPDATE ai_task SET status = 'failed', error = :error, finished_at = now() WHERE id = :id
""")
# A running mean of the seconds per 1,000 tokens (D188, D308), weighted by the tokens: samples
# counts them, not the tasks.
_CALIBRATE = text("""
    INSERT INTO ai_calibration (kind, engine, model, unit, seconds_per_unit, samples)
    VALUES ('summarize', 'text', :model, 'ktoken',
        1000 * CAST(:seconds AS float8) / CAST(:tokens AS integer), :tokens)
    ON CONFLICT (kind, engine, model) DO UPDATE SET
        seconds_per_unit = (ai_calibration.seconds_per_unit * ai_calibration.samples
            + 1000 * CAST(:seconds AS float8))
            / (ai_calibration.samples + CAST(:tokens AS integer)),
        samples = ai_calibration.samples + CAST(:tokens AS integer), unit = 'ktoken',
        updated_at = now()
""")
_SENT = text("""
    INSERT INTO ai_send_log (service_url, kind, target, target_sha256, bytes, job_id)
    VALUES (:service_url, 'summarize', :target, :sha256, :bytes, :job_id)
""")


class SummaryPartial(BaseModel):
    """ai_task.partial of a summarize task: the parts of a long text summarised so far (D303),
    kept across a stop and an attempt as OCR keeps its pages (D187)."""

    parts: list[SummaryPart] = []
    parts_total: int | None = None
    characters: int | None = None  # of the text cut: another text (a new OCR) starts afresh
    size: int | None = None  # characters per part: a continued task cuts as before
    tags: list[list[str]] = []  # each part's tags, for the combining request
    themes: list[ThemeHint] = []  # the parts' checked hints, positions in the stored text
    dropped_themes: int = 0


@dataclass(slots=True)
class SummaryTask:
    """The task in work, with what the model reads."""

    id: int
    source: SummaryInput
    partial: SummaryPartial

    @property
    def name(self) -> str:
        return self.source.name or self.source.sha256[:12]


@dataclass(frozen=True, slots=True)
class _Reply:
    answer: Answer
    seconds: float
    tokens_in: int
    tokens_out: int


class _Attempt(Exception):
    """The task failed this attempt (English reason): it waits again, or fails after the last."""


class _Unusable(Exception):
    """The task cannot be done (English reason): it fails now."""


class SummarizeStep:
    """The step summarize of one run: the text service it uses, the tasks it may take, and the
    work on them (module docstring). ai.run checks the service and runs the step's loop."""

    def __init__(self, run: "_Run", only: str) -> None:
        self.run = run
        self._count = text(_COUNT.replace("{only}", only.format(task="t")))
        self._take = text(_TAKE.replace("{only}", only.format(task="w")))
        self.waiting = 0  # tasks waiting when the run checked
        self.service: Service | None = None  # usable: checked, allowed, its model offered
        self.protocol: Protocol | None = None
        self.remote = False
        self.problem: str | None = None  # why the tasks are left waiting
        self.begun = False  # the step ran, and its status is its own
        self._prompts: SummaryPrompts | None = None
        self._system = ""
        self._schema: dict[str, Any] = {}
        self._themes: tuple[Theme, ...] = ()

    async def count(self) -> int:
        """The summarize tasks waiting that this run may take."""
        async with self.run.sessionmaker() as session:
            found = await session.scalar(self._count, self._only())
        self.waiting = self.run.summary.summaries_queued = int(found or 0)
        return self.waiting

    def use(self, service: Service, protocol: Protocol) -> None:
        """The checked text service: the tasks are taken."""
        self.service, self.protocol = service, protocol
        self.remote = locality(service.url) == "remote"  # refusal() allowed it
        self.run.summary.text = service.display_url
        where = "outside this machine" if self.remote else "local"
        log.info("text: %s, model %s (%s)", service.display_url, service.model, where)

    def leave(self, problem: str) -> None:
        """No usable text service: the tasks wait for a run that has one."""
        self.problem = problem
        log.warning("%d summaries wait: %s", self.waiting, problem)

    def _only(self) -> dict[str, Any]:
        return {"documents": self.run.options.documents, "mails": self.run.options.mails}

    # take ----------------------------------------------------------------------------------------

    async def take(self, counter: Step) -> SummaryTask | None:
        """The next waiting task, now running in this run; one with nothing to read fails."""
        while True:
            async with self.run.sessionmaker.begin() as session:
                parameters = {"job_id": self.run.job.job_id, **self._only()}
                row = (await session.execute(self._take, parameters)).first()
                if row is None:
                    return None
                read = mail_input if row.target == AiTarget.MAIL else document_input
                source = await read(session, row.target_sha256)
                problem = _unreadable(row.target, source)
                if source is not None and problem is None:
                    partial = SummaryPartial.model_validate(row.partial or {})
                    return SummaryTask(row.id, source, partial)
                await session.execute(_FAIL, {"id": row.id, "error": problem})
            log.warning("%s %s: %s", row.target, row.target_sha256[:12], problem)
            self._failed(counter)

    # work ----------------------------------------------------------------------------------------

    async def work(self, task: SummaryTask, counter: Step) -> None:
        """One task to its end: done, an attempt, failed, or back to waiting with its parts when
        the run ends."""
        run = self.run
        run.progress.current = task.source.name or None
        try:
            summary, last = await self._summarize(task)
            await self._store(task, summary, last, counter)
        except _Attempt as attempt:
            await self._attempt(task, str(attempt), counter)
        except _Unusable as unusable:
            await self._fail(task, str(unusable), counter)
        except BaseException:
            async with run.sessionmaker.begin() as session:
                await session.execute(_BACK, {"id": task.id})
            raise
        finally:
            run.progress.current = None

    async def _summarize(self, task: SummaryTask) -> tuple[Summary, _Reply | None]:
        """The task's summary, and the combining request that is in none of its parts."""
        if self._prompts is None:
            await self._prepare()
        assert self._prompts is not None
        source = task.source
        if source.short:
            reply = await self._ask(task, self._prompts.short, source.text)
            checked = self._check(reply.answer, source, source.text, 0)
            return self._whole(source, replace(checked, summary=""), reply), None
        instruction = fill(self._prompts.part, number=SUMMARY_MAX_PARTS, total=SUMMARY_MAX_PARTS)
        overhead = len(user_message(instruction, material(source.head, ""))) + len("\n\n")
        size = part_chars(self.run.options.context_tokens, len(self._system) + overhead)
        if len(source.text) <= size:
            reply = await self._ask(task, "", source.text)
            checked = self._check(reply.answer, source, source.text, 0)
            return self._whole(source, checked, reply), None
        partial = task.partial
        if partial.size is None or partial.characters != len(source.text):
            partial = task.partial = SummaryPartial(characters=len(source.text), size=size)
        if partial.size is None or partial.size < MIN_PART_CHARS:
            raise _Unusable(
                f"a context of {self.run.options.context_tokens} tokens leaves {size} characters "
                f"for a part of the text, fewer than {MIN_PART_CHARS}: raise "
                "MAILROBBE_AI_CONTEXT_TOKENS to the context the model was loaded with"
            )
        return await self._parts(task, cut(source.text, partial.size))

    def _whole(self, source: SummaryInput, checked: Checked, reply: _Reply) -> Summary:
        """The summary of a text read in one request."""
        part = SummaryPart(
            number=1,
            characters=len(source.text),
            summary=checked.summary,
            seconds=reply.seconds,
            tokens_in=reply.tokens_in,
            tokens_out=reply.tokens_out,
        )
        return Summary(
            summary=checked.summary,
            tags=checked.tags,
            themes=checked.themes,
            parts=[part],
            parts_total=1,
            short=source.short,
            dropped_tags=checked.dropped_tags,
            dropped_themes=checked.dropped_themes,
            words=source.words,
            origin=source.origin,
        )

    async def _parts(self, task: SummaryTask, parts: list[Part]) -> tuple[Summary, _Reply]:
        """A long text: its parts one request each, kept as they come, then the combining
        request (module docstring)."""
        assert self._prompts is not None
        partial = task.partial
        partial.parts_total = len(parts)
        reading = parts[:SUMMARY_MAX_PARTS]
        for part in reading[len(partial.parts) :]:
            instruction = fill(self._prompts.part, number=part.number, total=len(parts))
            reply = await self._ask(task, instruction, part.text)
            checked = self._check(reply.answer, task.source, part.text, part.start)
            partial.parts.append(
                SummaryPart(
                    number=part.number,
                    characters=len(part.text),
                    summary=checked.summary,
                    seconds=reply.seconds,
                    tokens_in=reply.tokens_in,
                    tokens_out=reply.tokens_out,
                )
            )
            partial.tags.append(checked.tags)
            partial.themes.extend(checked.themes)
            partial.dropped_themes += checked.dropped_themes
            async with self.run.sessionmaker.begin() as session:
                await session.execute(
                    _PARTIAL, {"id": task.id, "partial": partial.model_dump_json()}
                )
        instruction = fill(self._prompts.combine, total=len(partial.parts))
        reply = await self._ask(task, instruction, _combined(partial))
        tags, dropped_tags = check_tags(reply.answer.tags)
        themes, beyond = limit_hints(partial.themes)
        summary = Summary(
            summary=reply.answer.summary,
            tags=tags,
            themes=themes,
            parts=partial.parts,
            parts_total=len(parts),
            dropped_tags=dropped_tags + reply.answer.malformed_tags,
            dropped_themes=partial.dropped_themes + beyond,
            words=sum(len(part.text.split()) for part in reading),
            origin=task.source.origin,
        )
        return summary, reply

    async def _prepare(self) -> None:
        """The prompts, the system prompt and the answer schema of this run (D305)."""
        self._prompts = load_prompts().summarize
        async with self.run.sessionmaker() as session:
            vocabulary = await load_vocabulary(session)
        self._themes = vocabulary.themes
        self._system = system_prompt(self._prompts, vocabulary)
        self._schema = answer_schema([theme.key for theme in vocabulary.themes])

    async def _ask(self, task: SummaryTask, instruction: str, body: str) -> _Reply:
        """One request with the instruction and this text as material; _Attempt for an answer
        that is no valid one (module docstring)."""
        service, protocol, run = self.service, self.protocol, self.run
        assert service is not None and protocol is not None
        user = user_message(instruction, material(task.source.head, body))
        max_tokens = answer_tokens(run.options.context_tokens, len(self._system) + len(user))
        if self.remote:
            await self._before_sending(task, user)

        def request() -> tuple[ChatAnswer, float]:
            started = time.monotonic()
            found = chat_text(
                service,
                protocol,
                system=self._system,
                user=user,
                schema=self._schema,
                max_tokens=max_tokens,
                timeout=run.settings.ai_timeout,
                context_tokens=run.options.context_tokens,
            )
            return found, round(time.monotonic() - started, 3)

        try:
            found, seconds = await run._answer(service, request)
        except AnswerError as error:
            raise _Attempt(describe(error)) from None
        for figures in (run.summary, run.progress):
            figures.tokens_in += found.tokens_in
            figures.tokens_out += found.tokens_out
        if self.remote:
            run.remote_tokens += found.tokens_in + found.tokens_out
        if found.finish == "length":
            raise _Attempt(f"the answer was {cut_at_length(found, max_tokens)}")
        try:
            answer = read_answer(found.text)
        except AnswerError as error:
            raise _Attempt(str(error)) from None
        return _Reply(answer, seconds, found.tokens_in, found.tokens_out)

    async def _before_sending(self, task: SummaryTask, user: str) -> None:
        """A request to a remote service: within the budget, and recorded (D181)."""
        run = self.run
        if run.remote_tokens > run.settings.ai_remote_token_budget:
            raise run._budget_ended()
        assert self.service is not None
        async with run.sessionmaker.begin() as session:
            await session.execute(
                _SENT,
                {
                    "service_url": self.service.display_url,
                    "target": task.source.target.value,
                    "sha256": task.source.sha256,
                    "bytes": len(self._system.encode()) + len(user.encode()),
                    "job_id": run.job.job_id,
                },
            )

    def _check(self, answer: Answer, source: SummaryInput, body: str, start: int) -> Checked:
        """The answer checked against body, which starts at start in the source's text; the
        hints' positions mapped to the stored text."""
        checked = check_answer(answer, text=body, head="\n".join(source.head), themes=self._themes)
        themes = [
            hint
            if hint.position is None
            else hint.model_copy(update={"position": source.stored(start + hint.position)})
            for hint in checked.themes
        ]
        return replace(checked, themes=themes)

    # end of a task -----------------------------------------------------------------------------

    async def _store(
        self, task: SummaryTask, summary: Summary, last: _Reply | None, counter: Step
    ) -> None:
        """The summary stored, the task done, the speed measured (module docstring)."""
        run, service = self.run, self.service
        assert service is not None and self._prompts is not None
        seconds = sum(part.seconds for part in summary.parts)
        tokens_in = sum(part.tokens_in for part in summary.parts)
        tokens_out = sum(part.tokens_out for part in summary.parts)
        if last is not None:
            seconds, tokens_in = seconds + last.seconds, tokens_in + last.tokens_in
            tokens_out += last.tokens_out
        read = len("\n".join(task.source.head)) + sum(part.characters for part in summary.parts)
        async with run.sessionmaker.begin() as session:
            result_id = await store_summary_result(
                session,
                target=task.source.target,
                sha256=task.source.sha256,
                summary=summary,
                model=service.model,
                service_url=service.display_url,
                remote=self.remote,
                prompt_version=self._prompts.version,
                options={"context_tokens": run.options.context_tokens},
                seconds=round(seconds, 3),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                job_id=run.job.job_id,
            )
            await session.execute(_DONE, {"id": task.id, "result_id": result_id})
            tokens = math.ceil(read / CHARS_PER_TOKEN)
            if seconds > 0 and tokens > 0:
                await session.execute(
                    _CALIBRATE, {"model": service.model, "seconds": seconds, "tokens": tokens}
                )
        run.summary.summaries += 1
        run.progress.summaries += 1
        counter.advance()
        if summary.short:
            read_as = "short"
        else:
            read_as = f"{len(summary.parts)} of {summary.parts_total} parts"
        log.info(
            "%s: %s, %d tags, %d theme hints",
            task.name,
            read_as,
            len(summary.tags),
            len(summary.themes),
        )

    async def _attempt(self, task: SummaryTask, reason: str, counter: Step) -> None:
        async with self.run.sessionmaker.begin() as session:
            status = await session.scalar(
                _ATTEMPT, {"id": task.id, "error": reason, "attempts": AI_TASK_ATTEMPTS}
            )
        log.warning("%s: %s", task.name, reason)
        if status == "failed":
            self._failed(counter)

    async def _fail(self, task: SummaryTask, reason: str, counter: Step) -> None:
        async with self.run.sessionmaker.begin() as session:
            await session.execute(_FAIL, {"id": task.id, "error": reason})
        log.warning("%s: %s", task.name, reason)
        self._failed(counter)

    def _failed(self, counter: Step) -> None:
        self.run.summary.summaries_failed += 1
        counter.advance()


def _unreadable(target: str, source: SummaryInput | None) -> str | None:
    """Why a task's content cannot be summarised (D302), or None."""
    if source is None:
        return f"no {target} has this content any more"
    if target == AiTarget.DOCUMENT and not source.text.strip():
        return "the document has no text"
    if target == AiTarget.MAIL and not source.text.strip() and not source.name:
        return "the mail has neither a subject nor a text of its own"
    return None


def _combined(partial: SummaryPartial) -> str:
    """The material of the combining request: each part's summary with its tags."""
    blocks = []
    for part, tags in zip(partial.parts, partial.tags, strict=True):
        lines = [f"Teil {part.number}:", part.summary or "(ohne Zusammenfassung)"]
        if tags:
            lines.append(f"Schlagwörter: {', '.join(tags)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
