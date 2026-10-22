"""AI services (milestone 15, D180 to D189): the AI page's status, the check of a service, the
queue, the results, the send log and the run. Endpoints and models are in schemas.py.

Routes: GET /api/ai/status, /api/ai/tasks, /api/ai/results, /api/ai/send-log; POST
/api/ai/services/{capability}/check, /api/ai/tasks, /api/ai/tasks/retry, /api/ai/tasks/cancel,
/api/ai/results/{id}/discard, /api/ai/jobs/{id}/discard, /api/ai/run, /api/ai/run/stop.

The status is polled every 2 s while a run is alive (D48), so it shows the services as the
settings name them without asking them; asking a service and running its real test (a picture
with a known word, D180) is the check, which may take up to MAILROBBE_AI_TIMEOUT and runs in a
thread. The work lists and their estimates (D188) read document rows of the few kinds OCR and
the transcriber read (text status scanned, images, recordings), which their indexes find; an
estimate is the pages times the measured seconds per page of the engine and model
(ai_calibration), else the rule of thumb of AI_RULE_SECONDS, marked estimated. For recordings
(D295) it is their minutes, AI_RULE_MINUTES for one whose length no transcription found yet,
times the transcriber's measured seconds per minute, else AI_RULE_SECONDS_PER_MINUTE; estimated
when a rule of thumb entered. The transcriber's state looks at its files (model_state) and at
its libraries, without loading either.

Queuing (D186, D295) goes through ai.queue, which gives each document what fits it unless the
request names a kind; results are discarded through ai.store, the one place writing ai_result
and the AI texts of documents (D185); a selection from the document list's filters is resolved
by the list's own conditions (documents.document_conditions). The run is
`mailrobbe ai --origin ui run` started as a child process like the dashboard's other runs
(processes.py, D46): it refuses to start while an import, a DKIM run, a key run or another AI run
is alive, and an import refuses while it lives (processes.excluded).

Summaries (milestone 17, D300 to D311) are queued here too, by name (kind summarize): mails by
id or by the mail list's filters (resolved as a bulk change, selection.py), documents by id or
by the document list's filters; a preview counts and estimates without writing (D308), and an
element queued from its page starts `mailrobbe ai run --mail ID` or `--document ID` at once
(D307). Tasks, results and sends name a document or a mail (target, D301); a mail is shown by
the earliest mail of its content. The card of one element is summaries.py.

Every POST takes a JSON body declared as application/json (imports.JSON_BODY); writes take the
editor from X-Mailrobbe-Editor (D54).
"""

import asyncio
import base64
import binascii
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Annotated

import fastapi
from fastapi import APIRouter, Query
from sqlalchemy import (
    ColumnElement,
    Float,
    Integer,
    Text,
    any_,
    case,
    false,
    func,
    literal,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe import jobs
from mailrobbe.ai import queue, services, store
from mailrobbe.ai.audio import parakeet
from mailrobbe.ai.model import (
    CHARS_PER_TOKEN,
    SUMMARY_RULE_SECONDS_PER_KTOKEN,
    SUMMARY_RULE_SECONDS_PER_TASK,
    TRANSCRIBE_MODEL,
    AiOptions,
    Capability,
    ForbiddenService,
    OcrEngine,
    OcrEngineChoice,
    Service,
    ServiceCheck,
    configured_services,
    locality,
    refusal,
    transcribe_threads,
    transcriber_available,
)
from mailrobbe.ai.queue import SUMMARIZABLE_DOCUMENT, WORK_LISTS
from mailrobbe.api import processes
from mailrobbe.api.deps import AppSettings, Editor, Session, api_error
from mailrobbe.api.documents import READABLE, RESULT_FIGURES, document_conditions
from mailrobbe.api.filters import FilterError, internal_domains
from mailrobbe.api.imports import JSON_BODY, NoOptions, Runs, _start, _stop, _valid, ai_job
from mailrobbe.api.schemas import (
    AI_QUEUE_LIMIT,
    AI_RULE_MINUTES,
    AI_RULE_SECONDS,
    AI_RULE_SECONDS_PER_MINUTE,
    AiChanged,
    AiDocumentRef,
    AiEstimate,
    AiJob,
    AiMailRef,
    AiQueued,
    AiQueuedRun,
    AiQueueRequest,
    AiResultItem,
    AiResultPage,
    AiResultParams,
    AiRunRequest,
    AiSendItem,
    AiSendLogPage,
    AiSendLogParams,
    AiServiceInfo,
    AiStatus,
    AiTaskAction,
    AiTaskItem,
    AiTaskPage,
    AiTaskParams,
    AiTextEstimate,
    AiTranscriptionInfo,
    AiWorkList,
    AiWorkListInfo,
    DocumentFilters,
    MailSelection,
)
from mailrobbe.api.selection import resolve_selection
from mailrobbe.config import Settings
from mailrobbe.db.models import AiSendLog, AiTask, Document, Job
from mailrobbe.enums import AiResultState, AiTarget, AiTaskKind, JobKind

router = APIRouter(prefix="/api/ai", tags=["ai"])

ResultId = Annotated[int, fastapi.Path(ge=-(2**63), le=2**63 - 1)]
JobId = Annotated[int, fastapi.Path(ge=-(2**63), le=2**63 - 1)]

# The options of the latest run that the next start from the AI page takes over (D49).
DEFAULT_KEYS = ("ocr_engine", "vision_model", "max_pages", "max_minutes", "text_model")


# Status ----------------------------------------------------------------------------------------


@router.get("/status")
async def ai_status(session: Session, settings: AppSettings) -> AiStatus:
    row = await jobs.latest_job(session, JobKind.AI)
    # A service named by a host is looked up (D181): off the event loop.
    services, defaults = await asyncio.to_thread(_settings_view, settings, row)
    vision = _usable_vision(services)
    seconds = await _calibration(session)
    work_lists = [
        await _work_list(session, key, defaults, vision, seconds) for key in ("scanned", "images")
    ]
    work_lists.append(await _media_list(session, defaults))
    sent = await session.scalar(select(AiSendLog.id).limit(1))
    return AiStatus(
        enabled=True,
        vision=vision,
        tesseract=shutil.which("tesseract") is not None,
        ocr_languages=settings.ai_ocr_languages,
        services=services,
        allow_remote=settings.ai_allow_remote,
        remote_token_budget=settings.ai_remote_token_budget,
        ocr_engine=settings.ai_ocr_engine,
        queue=await queue.task_counts(session),
        work_lists=work_lists,
        remote_used=sent is not None or any(service.locality == "remote" for service in services),
        job=None if row is None else await ai_job(session, settings, row),
        defaults=defaults,
        text=_usable_text(services),
        transcription=await asyncio.to_thread(_transcription, settings),
    )


def _settings_view(settings: Settings, latest: Job | None) -> tuple[list[AiServiceInfo], AiOptions]:
    """The configured services as rows and the defaults of a start (D49); blocking, since a
    service's host may be looked up."""
    return [_service_info(service, settings) for service in _services(settings)], _defaults(
        settings, latest
    )


def _services(settings: Settings) -> list[Service]:
    return list(configured_services(settings).values())


def _service_info(service: Service, settings: Settings) -> AiServiceInfo:
    try:
        where = locality(service.url)
    except ForbiddenService:
        where = None
    return AiServiceInfo(
        capability=service.capability,
        url=service.display_url,
        model=service.model,
        protocol=service.protocol,
        locality=where,
        refused=refusal(service, settings),
        key=bool(service.key),
    )


def _usable_vision(services: Sequence[AiServiceInfo]) -> bool:
    return any(service.capability == "vision" and service.refused is None for service in services)


def _usable_text(services: Sequence[AiServiceInfo]) -> bool:
    """A text service is configured and allowed (D300): "Zusammenfassen" shows."""
    return any(service.capability == "text" and service.refused is None for service in services)


async def text_usable(settings: Settings) -> bool:
    """_usable_text without the other services; asks no service, may look up its host."""
    service = configured_services(settings).get("text")
    if service is None:
        return False
    return await asyncio.to_thread(lambda: refusal(service, settings) is None)


def _defaults(settings: Settings, latest: Job | None) -> AiOptions:
    """The settings' options with the DEFAULT_KEYS of the latest run (D49)."""
    options = AiOptions.from_settings(settings)
    stored = None if latest is None else _valid(AiOptions, latest.options)
    if stored is None:
        return options
    update = {key: getattr(stored, key) for key in DEFAULT_KEYS}
    if not stored.text_model:  # a run before M17 or without a text service: the settings' model
        del update["text_model"]
    return options.model_copy(update=update)


_CALIBRATION = text("""
    SELECT engine, model, seconds_per_unit FROM ai_calibration
    WHERE kind = 'ocr' AND unit = 'page'
""")


async def _calibration(session: AsyncSession) -> dict[tuple[str, str], float]:
    """Measured seconds per page by engine and model (D188)."""
    return {
        (engine, model): float(value)
        for engine, model, value in await session.execute(_CALIBRATION)
    }


def _estimate(
    engine: OcrEngine, model: str, pages: int, seconds: dict[tuple[str, str], float]
) -> AiEstimate:
    model = model if engine == "vision" else ""
    measured = seconds.get((engine, model))
    per_page = AI_RULE_SECONDS[engine] if measured is None else measured
    return AiEstimate(
        engine=engine,
        model=model,
        seconds=pages * per_page,
        estimated=measured is None,
        seconds_per_page=per_page,
    )


def _auto_engine(key: AiWorkList, choice: OcrEngineChoice, vision: bool) -> OcrEngine:
    """The engine a task queued with auto gets for this list (D182)."""
    if choice == "tesseract" or not vision:
        return "tesseract"
    if choice == "vision":
        return "vision"
    return "vision" if key == "images" else "tesseract"


async def _work_list(
    session: AsyncSession,
    key: AiWorkList,
    defaults: AiOptions,
    vision: bool,
    seconds: dict[tuple[str, str], float],
) -> AiWorkListInfo:
    statement = text(f"""
        SELECT count(*) AS documents, COALESCE(sum(d.pages), 0) AS pages,
            count(*) FILTER (WHERE d.pages IS NULL) AS without_pages,
            COALESCE(sum(d.size_bytes), 0) AS bytes,
            COALESCE(sum(LEAST(COALESCE(d.pages, 1), :max_pages)), 0) AS read_pages
        FROM document d WHERE {WORK_LISTS[key]}
    """)
    row = (await session.execute(statement, {"max_pages": defaults.max_pages})).one()
    images = key == "images"
    pages = row.documents if images else int(row.pages)
    read_pages = row.documents if images else int(row.read_pages)
    engines: list[OcrEngine] = ["tesseract", "vision"] if vision else ["tesseract"]
    return AiWorkListInfo(
        key=key,
        documents=row.documents,
        pages=pages,
        without_pages=0 if images else row.without_pages,
        bytes=int(row.bytes),
        estimates=[
            _estimate(engine, defaults.vision_model, read_pages, seconds) for engine in engines
        ],
        engine=_auto_engine(key, defaults.ocr_engine, vision),
    )


_SECONDS_PER_MINUTE = text("""
    SELECT seconds_per_unit FROM ai_calibration
    WHERE kind = 'transcribe' AND engine = 'parakeet' AND model = :model AND unit = 'minute'
""")


async def _media_list(session: AsyncSession, defaults: AiOptions) -> AiWorkListInfo:
    """The work list of recordings (D295) with its one estimate, the transcriber's, for at most
    max_minutes of the defaults per recording."""
    statement = text(f"""
        SELECT count(*) AS documents, COALESCE(sum(d.size_bytes), 0) AS bytes,
            COALESCE(sum(d.duration), 0) AS seconds,
            -- LEAST skips a NULL: an unknown length counts by the rule of thumb instead
            COALESCE(sum(LEAST(d.duration, :max_seconds)) FILTER (WHERE d.duration IS NOT NULL),
                0) AS read_seconds,
            count(*) FILTER (WHERE d.duration IS NULL) AS without_minutes
        FROM document d WHERE {WORK_LISTS["media"]}
    """)
    row = (await session.execute(statement, {"max_seconds": defaults.max_minutes * 60.0})).one()
    measured = await session.scalar(_SECONDS_PER_MINUTE, {"model": TRANSCRIBE_MODEL})
    per_minute = AI_RULE_SECONDS_PER_MINUTE if measured is None else float(measured)
    minutes = float(row.read_seconds) / 60 + AI_RULE_MINUTES * row.without_minutes
    return AiWorkListInfo(
        key="media",
        documents=row.documents,
        pages=0,
        without_pages=0,
        bytes=int(row.bytes),
        estimates=[
            AiEstimate(
                engine="parakeet",
                model=TRANSCRIBE_MODEL,
                seconds=minutes * per_minute,
                estimated=measured is None or row.without_minutes > 0,
                seconds_per_page=0.0,
                seconds_per_minute=per_minute,
            )
        ],
        engine="parakeet",
        minutes=float(row.seconds) / 60,
        without_minutes=row.without_minutes,
    )


def _transcription(settings: Settings) -> AiTranscriptionInfo:
    """The transcriber's libraries and files (D290, D291); blocking, since it looks at files."""
    state = parakeet.model_state(settings.ai_model_dir)
    return AiTranscriptionInfo(
        available=transcriber_available(),
        model=TRANSCRIBE_MODEL,
        ready=state.ready,
        missing_bytes=state.missing_bytes,
        total_bytes=state.total_bytes,
        threads=transcribe_threads(settings),
        max_minutes=settings.ai_transcribe_max_minutes,
    )


# Services --------------------------------------------------------------------------------------


@router.post("/services/{capability}/check", dependencies=JSON_BODY)
async def check(_: NoOptions, capability: Capability, settings: AppSettings) -> ServiceCheck:
    """Ask the service and run its real test (D180); never fails for what the service does."""
    service = configured_services(settings).get(capability)
    if service is None:
        raise api_error(404, "not_found", f"no {capability} service is configured")
    return await asyncio.to_thread(check_service, service, settings)


def check_service(service: Service, settings: Settings) -> ServiceCheck:
    """ai.services.check_service with its test (blocking; tests replace this)."""
    return services.check_service(service, settings, test=True)


# Queue -----------------------------------------------------------------------------------------


@router.post("/tasks", dependencies=JSON_BODY)
async def enqueue(
    request: AiQueueRequest, session: Session, settings: AppSettings, editor: Editor, runs: Runs
) -> AiQueued:
    if request.kind is AiTaskKind.SUMMARIZE:
        return await _enqueue_summaries(request, session, settings, editor, runs)
    if request.mail_ids is not None or request.mail_filters is not None:
        raise api_error(400, "invalid_selection", "mails are queued for summaries only")
    if request.preview:
        raise api_error(400, "invalid_option", "a preview is made for summaries only")
    given = [request.work_list, request.document_ids, request.filters]
    if sum(value is not None for value in given) != 1:
        raise api_error(
            400, "invalid_selection", "give exactly one of work_list, document_ids and filters"
        )
    if request.start and request.document_ids is None:
        raise api_error(400, "invalid_selection", "start needs document_ids")
    ocr = request.kind in (None, AiTaskKind.OCR)
    if ocr and request.engine == "vision" and not await _vision_usable(settings):
        raise api_error(400, "invalid_option", "no usable vision service is configured")
    if request.work_list is not None:
        ids = await queue.work_list_ids(session, request.work_list)
    elif request.filters is not None:
        ids = await readable_ids(session, settings, request.filters, request.kind)
    else:
        ids = list(request.document_ids or [])
    queued = await queue.enqueue(
        session,
        ids,
        kind=request.kind,
        engine=request.engine,
        editor=editor,
        single=request.single,
        include_logos=request.include_logos,
    )
    await session.commit()
    run = None
    if request.start and queued.queued + queued.raised:
        run = await _start_for(session, settings, runs, sorted(set(ids)))
    return AiQueued(
        queued=queued.queued,
        raised=queued.raised,
        unreadable=queued.unreadable,
        logos=queued.logos,
        run=run,
    )


async def _start_for(
    session: AsyncSession,
    settings: Settings,
    runs: Runs,
    document_ids: list[int],
    mail_ids: Sequence[int] = (),
) -> AiQueuedRun:
    """Start a run reading only these documents (D280) and mails (D307), or the whole queue
    without either (D308), with the latest run's options; a live AI run takes them next
    instead, and any other live run leaves them waiting."""
    if await jobs.job_alive(session, JobKind.AI):
        return "running"
    latest = await jobs.latest_job(session, JobKind.AI)
    _, defaults = await asyncio.to_thread(_settings_view, settings, latest)
    arguments = _run_arguments(
        defaults.ocr_engine,
        defaults.vision_model,
        defaults.max_pages,
        defaults.max_minutes,
        defaults.text_model,
    )
    arguments += [f"--document={document_id}" for document_id in document_ids]
    arguments += [f"--mail={mail_id}" for mail_id in mail_ids]
    environment = processes.child_environment(settings)
    try:
        await _start(session, settings, runs, JobKind.AI, arguments, environment)
    except fastapi.HTTPException as error:
        if error.status_code != 409:
            raise
        return "running" if await jobs.job_alive(session, JobKind.AI) else "busy"
    return "started"


async def _vision_usable(settings: Settings) -> bool:
    services = await asyncio.to_thread(
        lambda: [_service_info(service, settings) for service in _services(settings)]
    )
    return _usable_vision(services)


# What the document list's filters queue of each kind (D295), as conditions on document.
_READABLE_BY_KIND = {
    AiTaskKind.OCR: text(
        f"EXISTS (SELECT 1 FROM document d WHERE d.id = document.id AND {queue.OCR_READABLE})"
    ),
    AiTaskKind.TRANSCRIBE: text(
        f"EXISTS (SELECT 1 FROM document d WHERE d.id = document.id AND {queue.TRANSCRIBABLE})"
    ),
}


async def readable_ids(
    session: AsyncSession,
    settings: Settings,
    filters: DocumentFilters,
    kind: AiTaskKind | None = None,
) -> list[int]:
    """The documents of the document list's filters that OCR or the transcriber can read (only
    the one of kind, when given), most mails first; 400 too_many_documents above
    AI_QUEUE_LIMIT."""
    try:
        where = document_conditions(filters, internal_domains(settings.internal_domains))
    except FilterError as error:
        raise api_error(400, "invalid_filter", str(error)) from error
    readable = READABLE if kind is None else _READABLE_BY_KIND.get(kind, false())
    statement = (
        select(Document.id)
        .where(*where, readable)
        .order_by(Document.mails.desc(), Document.id)
        .limit(AI_QUEUE_LIMIT + 1)
    )
    ids = list(await session.scalars(statement))
    if len(ids) > AI_QUEUE_LIMIT:
        raise api_error(
            400,
            "too_many_documents",
            f"the filters match more than {AI_QUEUE_LIMIT} readable documents",
        )
    return ids


# Summaries (D300, D302, D308) ------------------------------------------------------------------

# Documents that can be summarised (ai.queue.SUMMARIZABLE_DOCUMENT), on statements over document.
SUMMARIZABLE = text(
    f"EXISTS (SELECT 1 FROM document d WHERE d.id = document.id AND {SUMMARIZABLE_DOCUMENT})"
)
# Tokens of what a task sends besides the text: subject, date, names and addresses, file names
# and the marks around the material (D302, D306); with the text's characters the estimate's input.
SUMMARY_HEAD_TOKENS = 100
_TEXT_CALIBRATION = text("""
    SELECT seconds_per_unit FROM ai_calibration
    WHERE kind = 'summarize' AND engine = 'text' AND model = :model AND unit = 'ktoken'
""")


async def _enqueue_summaries(
    request: AiQueueRequest,
    session: AsyncSession,
    settings: Settings,
    editor: str | None,
    runs: Runs,
) -> AiQueued:
    """POST /api/ai/tasks with kind summarize (D308): exactly one of mail_ids, mail_filters (as a
    bulk change, at most AI_QUEUE_LIMIT mails), document_ids and the document list's filters;
    with preview nothing is written. start runs the run for these ids at once, or for the whole
    queue after filters (D307)."""
    if request.work_list is not None:
        raise api_error(400, "invalid_option", "a work list is queued for OCR only")
    given = [request.mail_ids, request.mail_filters, request.document_ids, request.filters]
    if sum(value is not None for value in given) != 1:
        raise api_error(
            400,
            "invalid_selection",
            "give exactly one of mail_ids, mail_filters, document_ids and filters",
        )
    latest = await jobs.latest_job(session, JobKind.AI)
    services, defaults = await asyncio.to_thread(_settings_view, settings, latest)
    if not _usable_text(services):
        raise api_error(400, "invalid_option", "no usable text service is configured")
    mail_ids = list(request.mail_ids or [])
    document_ids = list(request.document_ids or [])
    if request.mail_filters is not None:
        selection = MailSelection(filters=request.mail_filters)
        mail_ids = [
            mail.id
            for mail in await resolve_selection(session, settings, selection, AI_QUEUE_LIMIT)
        ]
    elif request.filters is not None:
        document_ids = await summarizable_ids(session, settings, request.filters)
    queued = await queue.enqueue_summaries(
        session,
        mail_ids=mail_ids,
        document_ids=document_ids,
        editor=editor,
        single=request.single,
        preview=request.preview,
    )
    tasks = queued.queued + queued.raised
    estimate = await _text_estimate(session, defaults.text_model, tasks, queued.characters)
    run = None
    if not request.preview:
        await session.commit()
        if request.start and tasks:
            by_ids = request.mail_ids is not None or request.document_ids is not None
            run = await _start_for(
                session,
                settings,
                runs,
                sorted(set(document_ids)) if by_ids else [],
                sorted(set(mail_ids)) if by_ids else [],
            )
    return AiQueued(
        queued=queued.queued,
        raised=queued.raised,
        unreadable=queued.unreadable,
        logos=0,
        run=run,
        short=queued.short,
        estimate=estimate,
    )


async def summarizable_ids(
    session: AsyncSession, settings: Settings, filters: DocumentFilters
) -> list[int]:
    """The documents of the document list's filters that can be summarised (D302), most mails
    first; 400 too_many_documents above AI_QUEUE_LIMIT."""
    try:
        where = document_conditions(filters, internal_domains(settings.internal_domains))
    except FilterError as error:
        raise api_error(400, "invalid_filter", str(error)) from error
    statement = (
        select(Document.id)
        .where(*where, SUMMARIZABLE)
        .order_by(Document.mails.desc(), Document.id)
        .limit(AI_QUEUE_LIMIT + 1)
    )
    ids = list(await session.scalars(statement))
    if len(ids) > AI_QUEUE_LIMIT:
        raise api_error(
            400,
            "too_many_documents",
            f"the filters match more than {AI_QUEUE_LIMIT} documents with a text",
        )
    return ids


async def _text_estimate(
    session: AsyncSession, model: str, tasks: int, characters: int
) -> AiTextEstimate:
    """How long these summaries take (D308): the input's tokens times the measured seconds per
    1,000 tokens of the model, else the rule of thumb per task and per 1,000 tokens."""
    tokens = round(characters / CHARS_PER_TOKEN) + SUMMARY_HEAD_TOKENS * tasks
    measured = await session.scalar(_TEXT_CALIBRATION, {"model": model})
    if measured is None:
        seconds = (
            tasks * SUMMARY_RULE_SECONDS_PER_TASK + tokens / 1000 * SUMMARY_RULE_SECONDS_PER_KTOKEN
        )
    else:
        seconds = tokens / 1000 * float(measured)
    return AiTextEstimate(
        model=model, tasks=tasks, tokens=tokens, seconds=seconds, estimated=measured is None
    )


@router.get("/tasks")
async def tasks(params: Annotated[AiTaskParams, Query()], session: Session) -> AiTaskPage:
    task = AiTask
    where: list[ColumnElement[bool]] = []
    if params.status:
        where.append(task.status.in_(sorted(set(params.status))))
    if params.cursor is not None:
        where.append(task.id < _decode_cursor(params.cursor, "task"))
    # An OCR task keeps its pages, a summary its parts (D303).
    done = func.coalesce(task.partial["pages"], task.partial["parts"])
    pages = func.coalesce(func.jsonb_array_length(done), 0).label("pages_read")
    total = (
        func.coalesce(task.partial["pages_total"].astext, task.partial["parts_total"].astext)
        .cast(Integer)
        .label("pages_total")
    )
    heard = case(
        (
            task.kind == AiTaskKind.TRANSCRIBE,
            func.coalesce(task.partial["until"].astext.cast(Float), 0.0),
        ),
        else_=None,
    ).label("seconds_read")
    found = list(
        await session.execute(
            select(task, pages, total, heard)
            .where(*where)
            .order_by(task.id.desc())
            .limit(params.limit + 1)
        )
    )
    more = len(found) > params.limit
    del found[params.limit :]
    refs = await target_refs(session, [(row[0].target, row[0].target_sha256) for row in found])
    return AiTaskPage(
        items=[
            AiTaskItem(
                id=row.id,
                kind=row.kind,
                document=refs.document(row.target, row.target_sha256),
                engine=row.engine,
                priority=row.priority,
                status=row.status,
                attempts=row.attempts,
                error=row.error,
                queued_by=row.queued_by,
                queued_at=row.queued_at,
                started_at=row.started_at,
                finished_at=row.finished_at,
                pages_read=pages_read,
                pages_total=pages_total,
                result_id=row.result_id,
                target=AiTarget(row.target),
                mail=refs.mail(row.target, row.target_sha256),
                seconds_read=seconds_read,
            )
            for row, pages_read, pages_total, seconds_read in found
        ],
        next_cursor=_encode_cursor("task", found[-1][0].id) if more else None,
    )


@router.post("/tasks/retry", dependencies=JSON_BODY)
async def retry(action: AiTaskAction, session: Session, editor: Editor) -> AiChanged:
    changed = await queue.retry_tasks(session, _task_ids(action), editor=editor)
    await session.commit()
    return AiChanged(changed=changed)


@router.post("/tasks/cancel", dependencies=JSON_BODY)
async def cancel(action: AiTaskAction, session: Session) -> AiChanged:
    changed = await queue.cancel_tasks(session, _task_ids(action))
    await session.commit()
    return AiChanged(changed=changed)


def _task_ids(action: AiTaskAction) -> list[int] | None:
    """The tasks an action names; None for all of them."""
    if action.all == bool(action.ids):
        raise api_error(400, "invalid_selection", "give either ids or all")
    return None if action.all else action.ids


# Results ---------------------------------------------------------------------------------------

# A summary's parts are its pages (RESULT_FIGURES: read, failed), its length the characters;
# its tags and theme hints are counted (D300).
_RESULTS = text(f"""
    SELECT {RESULT_FIGURES}, r.target,
        (SELECT count(*) FROM ai_tag_link l WHERE l.result_id = r.id) AS tags,
        (SELECT count(*) FROM ai_theme_hint h WHERE h.result_id = r.id) AS themes
    FROM ai_result r
    WHERE (CAST(:states AS text[]) IS NULL OR r.state::text = ANY(CAST(:states AS text[])))
      AND (CAST(:job_id AS bigint) IS NULL OR r.job_id = CAST(:job_id AS bigint))
      AND (CAST(:before AS bigint) IS NULL OR r.id < CAST(:before AS bigint))
    ORDER BY r.id DESC LIMIT :limit
""")


@router.get("/results")
async def results(params: Annotated[AiResultParams, Query()], session: Session) -> AiResultPage:
    before = None if params.cursor is None else _decode_cursor(params.cursor, "result")
    found = list(
        await session.execute(
            _RESULTS,
            {
                "states": sorted(set(params.state)) or None,
                "job_id": params.job_id,
                "before": before,
                "limit": params.limit + 1,
            },
        )
    )
    more = len(found) > params.limit
    del found[params.limit :]
    refs = await target_refs(session, [(row.target, row.target_sha256) for row in found])
    return AiResultPage(
        items=[
            AiResultItem(
                id=row.id,
                kind=AiTaskKind(row.kind),
                document=refs.document(row.target, row.target_sha256),
                engine=row.engine,
                model=row.model,
                remote=row.remote,
                pages_read=row.pages_read,
                pages_text=row.pages_text,
                pages_total=row.pages_total,
                uncertain=list(row.uncertain),
                failed=list(row.failed),
                characters=row.characters,
                seconds=row.seconds,
                state=AiResultState(row.state),
                created_at=row.created_at,
                job_id=row.job_id,
                discarded_by=row.discarded_by,
                discarded_at=row.discarded_at,
                target=AiTarget(row.target),
                mail=refs.mail(row.target, row.target_sha256),
                tags=row.tags,
                themes=row.themes,
                duration=row.duration,
                transcribed=row.transcribed,
                segments=row.segments,
                uncertain_segments=row.uncertain_segments,
            )
            for row in found
        ],
        next_cursor=_encode_cursor("result", found[-1].id) if more else None,
    )


@router.post("/results/{result_id}/discard", dependencies=JSON_BODY)
async def discard(_: NoOptions, result_id: ResultId, session: Session, editor: Editor) -> AiChanged:
    """Throw a result away (D185): its documents get the earlier text back, or none."""
    if not await store.discard_result(session, result_id, editor):
        raise api_error(404, "not_found", f"no result {result_id} that is not discarded")
    await session.commit()
    return AiChanged(changed=1)


@router.post("/jobs/{job_id}/discard", dependencies=JSON_BODY)
async def discard_job(_: NoOptions, job_id: JobId, session: Session, editor: Editor) -> AiChanged:
    changed = await store.discard_job_results(session, job_id, editor)
    await session.commit()
    return AiChanged(changed=changed)


# Send log --------------------------------------------------------------------------------------


@router.get("/send-log")
async def send_log(params: Annotated[AiSendLogParams, Query()], session: Session) -> AiSendLogPage:
    sent = AiSendLog
    after = [] if params.cursor is None else [sent.id < _decode_cursor(params.cursor, "sent")]
    found = list(
        await session.scalars(
            select(sent).where(*after).order_by(sent.id.desc()).limit(params.limit + 1)
        )
    )
    more = len(found) > params.limit
    del found[params.limit :]
    refs = await target_refs(session, [(row.target, row.target_sha256) for row in found])
    return AiSendLogPage(
        items=[
            AiSendItem(
                id=row.id,
                sent_at=row.sent_at,
                service_url=row.service_url,
                kind=row.kind,
                document=refs.document(row.target, row.target_sha256),
                bytes=row.bytes,
                job_id=row.job_id,
                target=AiTarget(row.target),
                mail=refs.mail(row.target, row.target_sha256),
            )
            for row in found
        ],
        next_cursor=_encode_cursor("sent", found[-1].id) if more else None,
        total=await session.scalar(select(func.count()).select_from(sent)) or 0,
    )


# Run -------------------------------------------------------------------------------------------


@router.post("/run", status_code=202, dependencies=JSON_BODY)
async def start_run(
    request: AiRunRequest, session: Session, settings: AppSettings, runs: Runs
) -> AiJob:
    """Start `mailrobbe ai run` as the dashboard starts its runs (D46, D187)."""
    latest = await jobs.latest_job(session, JobKind.AI)
    services, defaults = await asyncio.to_thread(_settings_view, settings, latest)
    engine = request.engine or defaults.ocr_engine
    if engine == "vision" and not _usable_vision(services):
        raise api_error(400, "invalid_option", "no usable vision service is configured")
    model = defaults.vision_model if request.vision_model is None else request.vision_model
    if any(not char.isprintable() for char in model):
        raise api_error(400, "invalid_option", "the vision model's name has control characters")
    text_model = defaults.text_model if request.text_model is None else request.text_model
    if any(not char.isprintable() for char in text_model):
        raise api_error(400, "invalid_option", "the text model's name has control characters")
    arguments = _run_arguments(
        engine,
        model,
        request.max_pages or defaults.max_pages,
        request.max_minutes or defaults.max_minutes,
        text_model,
    )
    environment = processes.child_environment(settings)
    job = await _start(session, settings, runs, JobKind.AI, arguments, environment)
    return await ai_job(session, settings, job)


def _run_arguments(
    engine: OcrEngineChoice, model: str, max_pages: int, max_minutes: int, text_model: str = ""
) -> list[str]:
    """The arguments of `mailrobbe ai run` for these options."""
    arguments = [
        "run",
        f"--engine={engine}",
        f"--max-pages={max_pages}",
        f"--max-minutes={max_minutes}",
    ]
    if model.strip():
        arguments.append(f"--vision-model={model.strip()}")
    if text_model.strip():
        arguments.append(f"--text-model={text_model.strip()}")
    return arguments


@router.post("/run/stop", dependencies=JSON_BODY)
async def stop_run(_: NoOptions, session: Session, settings: AppSettings) -> AiJob:
    return await ai_job(session, settings, await _stop(session, JobKind.AI))


# Helpers ---------------------------------------------------------------------------------------


async def document_refs(session: AsyncSession, contents: Sequence[str]) -> dict[str, AiDocumentRef]:
    """The documents of these contents (document.sha256 is unique), by content."""
    if not contents:
        return {}
    found = await session.execute(
        select(
            Document.id,
            Document.name,
            Document.kind,
            Document.pages,
            Document.duration,
            Document.sha256,
        ).where(Document.sha256 == any_(literal(sorted(set(contents)), ARRAY(Text))))
    )
    return {
        row.sha256: AiDocumentRef(
            id=row.id, name=row.name, kind=row.kind, pages=row.pages, duration=row.duration
        )
        for row in found
    }


_MAIL_REFS = text("""
    SELECT DISTINCT ON (raw_sha256) raw_sha256, id, subject, date_utc FROM mail
    WHERE raw_sha256 = ANY(CAST(:contents AS text[]))
    ORDER BY raw_sha256, id
""")


async def mail_refs(session: AsyncSession, contents: Sequence[str]) -> dict[str, AiMailRef]:
    """The earliest mail of each of these contents (mail.raw_sha256, D301), by content."""
    if not contents:
        return {}
    found = await session.execute(_MAIL_REFS, {"contents": sorted(set(contents))})
    return {
        row.raw_sha256: AiMailRef(id=row.id, subject=row.subject, date=row.date_utc)
        for row in found
    }


@dataclass(frozen=True, slots=True)
class TargetRefs:
    """The documents and mails a page of tasks, results or sends names (D301)."""

    documents: dict[str, AiDocumentRef]
    mails: dict[str, AiMailRef]

    def document(self, target: str, content: str) -> AiDocumentRef | None:
        return self.documents.get(content) if target == AiTarget.DOCUMENT else None

    def mail(self, target: str, content: str) -> AiMailRef | None:
        return self.mails.get(content) if target == AiTarget.MAIL else None


async def target_refs(session: AsyncSession, rows: Iterable[tuple[str, str]]) -> TargetRefs:
    """The references of these (target, content) pairs."""
    pairs = list(rows)
    return TargetRefs(
        documents=await document_refs(
            session, [content for target, content in pairs if target == AiTarget.DOCUMENT]
        ),
        mails=await mail_refs(
            session, [content for target, content in pairs if target == AiTarget.MAIL]
        ),
    )


def _encode_cursor(scope: str, row_id: int) -> str:
    return base64.urlsafe_b64encode(f"{scope}:{row_id}".encode()).decode().rstrip("=")


def _decode_cursor(cursor: str, scope: str) -> int:
    """The id of the last row of the previous page; 400 invalid_cursor for anything else."""
    try:
        decoded = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        if not decoded.startswith(f"{scope}:"):
            raise ValueError(decoded)
        return int(decoded.removeprefix(f"{scope}:"))
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise api_error(400, "invalid_cursor", "malformed cursor") from error
