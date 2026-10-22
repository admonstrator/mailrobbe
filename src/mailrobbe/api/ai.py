"""AI services (milestone 15, D180 to D189): the AI page's status, the check of a service, the
queue, the results, the send log and the run. Endpoints and models are in schemas.py.

Routes: GET /api/ai/status, /api/ai/tasks, /api/ai/results, /api/ai/send-log; POST
/api/ai/services/{capability}/check, /api/ai/tasks, /api/ai/tasks/retry, /api/ai/tasks/cancel,
/api/ai/results/{id}/discard, /api/ai/jobs/{id}/discard, /api/ai/run, /api/ai/run/stop.

The status is polled every 2 s while a run is alive (D48), so it shows the services as the
settings name them without asking them; asking a service and running its real test (a picture
with a known word, D180) is the check, which may take up to MAILROBBE_AI_TIMEOUT and runs in a
thread. The work lists and their estimates (D188) read document rows of the few kinds OCR reads
(text status scanned, or images), which their indexes find; an estimate is the pages times the
measured seconds per page of the engine and model (ai_calibration), else the rule of thumb of
AI_RULE_SECONDS, marked estimated.

Queuing (D186) goes through ai.queue, results are discarded through ai.store, the one place
writing ai_result and the AI texts of documents (D185); a selection from the document list's
filters is resolved by the list's own conditions (documents.document_conditions). The run is
`mailrobbe ai --origin ui run` started as a child process like the dashboard's other runs
(processes.py, D46): it refuses to start while an import, a DKIM run, a key run or another AI run
is alive, and an import refuses while it lives (processes.excluded).

Every POST takes a JSON body declared as application/json (imports.JSON_BODY); writes take the
editor from X-Mailrobbe-Editor (D54).
"""

import asyncio
import base64
import binascii
import importlib
import shutil
from collections.abc import Sequence
from typing import Annotated

import fastapi
from fastapi import APIRouter, Query
from sqlalchemy import ColumnElement, Integer, Text, any_, func, literal, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe import jobs
from mailrobbe.ai import queue, store
from mailrobbe.ai.model import (
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
)
from mailrobbe.ai.queue import WORK_LISTS
from mailrobbe.api import processes
from mailrobbe.api.deps import AppSettings, Editor, Session, api_error
from mailrobbe.api.documents import READABLE, RESULT_FIGURES, document_conditions
from mailrobbe.api.filters import FilterError, internal_domains
from mailrobbe.api.imports import JSON_BODY, NoOptions, Runs, _start, _stop, _valid, ai_job
from mailrobbe.api.schemas import (
    AI_QUEUE_LIMIT,
    AI_RULE_SECONDS,
    AiChanged,
    AiDocumentRef,
    AiEstimate,
    AiJob,
    AiQueued,
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
    AiWorkList,
    AiWorkListInfo,
    DocumentFilters,
)
from mailrobbe.config import Settings
from mailrobbe.db.models import AiSendLog, AiTask, Document, Job
from mailrobbe.enums import AiResultState, AiTaskKind, JobKind

router = APIRouter(prefix="/api/ai", tags=["ai"])

ResultId = Annotated[int, fastapi.Path(ge=-(2**63), le=2**63 - 1)]
JobId = Annotated[int, fastapi.Path(ge=-(2**63), le=2**63 - 1)]

# The options of the latest run that the next start from the AI page takes over (D49).
DEFAULT_KEYS = ("ocr_engine", "vision_model", "max_pages")


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


def _defaults(settings: Settings, latest: Job | None) -> AiOptions:
    """The settings' options with the DEFAULT_KEYS of the latest run (D49)."""
    options = AiOptions.from_settings(settings)
    stored = None if latest is None else _valid(AiOptions, latest.options)
    if stored is None:
        return options
    return options.model_copy(update={key: getattr(stored, key) for key in DEFAULT_KEYS})


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
    services = importlib.import_module("mailrobbe.ai.services")
    found: ServiceCheck = services.check_service(service, settings, test=True)
    return found


# Queue -----------------------------------------------------------------------------------------


@router.post("/tasks", dependencies=JSON_BODY)
async def enqueue(
    request: AiQueueRequest, session: Session, settings: AppSettings, editor: Editor
) -> AiQueued:
    given = [request.work_list, request.document_ids, request.filters]
    if sum(value is not None for value in given) != 1:
        raise api_error(
            400, "invalid_selection", "give exactly one of work_list, document_ids and filters"
        )
    if request.engine == "vision" and not await _vision_usable(settings):
        raise api_error(400, "invalid_option", "no usable vision service is configured")
    if request.work_list is not None:
        ids = await queue.work_list_ids(session, request.work_list)
    elif request.filters is not None:
        ids = await readable_ids(session, settings, request.filters)
    else:
        ids = list(request.document_ids or [])
    queued = await queue.enqueue_ocr(
        session,
        ids,
        engine=request.engine,
        editor=editor,
        single=request.single,
        include_logos=request.include_logos,
    )
    await session.commit()
    return AiQueued(
        queued=queued.queued, raised=queued.raised, unreadable=queued.unreadable, logos=queued.logos
    )


async def _vision_usable(settings: Settings) -> bool:
    services = await asyncio.to_thread(
        lambda: [_service_info(service, settings) for service in _services(settings)]
    )
    return _usable_vision(services)


async def readable_ids(
    session: AsyncSession, settings: Settings, filters: DocumentFilters
) -> list[int]:
    """The documents of the document list's filters that OCR can read, most mails first; 400
    too_many_documents above AI_QUEUE_LIMIT."""
    try:
        where = document_conditions(filters, internal_domains(settings.internal_domains))
    except FilterError as error:
        raise api_error(400, "invalid_filter", str(error)) from error
    statement = (
        select(Document.id)
        .where(*where, READABLE)
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


@router.get("/tasks")
async def tasks(params: Annotated[AiTaskParams, Query()], session: Session) -> AiTaskPage:
    task = AiTask
    where: list[ColumnElement[bool]] = []
    if params.status:
        where.append(task.status.in_(sorted(set(params.status))))
    if params.cursor is not None:
        where.append(task.id < _decode_cursor(params.cursor, "task"))
    pages = func.coalesce(func.jsonb_array_length(task.partial["pages"]), 0).label("pages_read")
    total = task.partial["pages_total"].astext.cast(Integer).label("pages_total")
    found = list(
        await session.execute(
            select(task, pages, total)
            .where(*where)
            .order_by(task.id.desc())
            .limit(params.limit + 1)
        )
    )
    more = len(found) > params.limit
    del found[params.limit :]
    documents = await document_refs(session, [row[0].target_sha256 for row in found])
    return AiTaskPage(
        items=[
            AiTaskItem(
                id=row.id,
                kind=row.kind,
                document=documents.get(row.target_sha256),
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
            )
            for row, pages_read, pages_total in found
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

_RESULTS = text(f"""
    SELECT {RESULT_FIGURES} FROM ai_result r
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
    documents = await document_refs(session, [row.target_sha256 for row in found])
    return AiResultPage(
        items=[
            AiResultItem(
                id=row.id,
                kind=AiTaskKind(row.kind),
                document=documents.get(row.target_sha256),
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
    documents = await document_refs(session, [row.target_sha256 for row in found])
    return AiSendLogPage(
        items=[
            AiSendItem(
                id=row.id,
                sent_at=row.sent_at,
                service_url=row.service_url,
                kind=row.kind,
                document=documents.get(row.target_sha256),
                bytes=row.bytes,
                job_id=row.job_id,
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
    arguments = [
        "run",
        f"--engine={engine}",
        f"--max-pages={request.max_pages or defaults.max_pages}",
    ]
    if model.strip():
        arguments.append(f"--vision-model={model.strip()}")
    environment = processes.child_environment(settings)
    job = await _start(session, settings, runs, JobKind.AI, arguments, environment)
    return await ai_job(session, settings, job)


@router.post("/run/stop", dependencies=JSON_BODY)
async def stop_run(_: NoOptions, session: Session, settings: AppSettings) -> AiJob:
    return await ai_job(session, settings, await _stop(session, JobKind.AI))


# Helpers ---------------------------------------------------------------------------------------


async def document_refs(session: AsyncSession, contents: Sequence[str]) -> dict[str, AiDocumentRef]:
    """The documents of these contents (document.sha256 is unique), by content."""
    if not contents:
        return {}
    found = await session.execute(
        select(Document.id, Document.name, Document.kind, Document.pages, Document.sha256).where(
            Document.sha256 == any_(literal(sorted(set(contents)), ARRAY(Text)))
        )
    )
    return {
        row.sha256: AiDocumentRef(id=row.id, name=row.name, kind=row.kind, pages=row.pages)
        for row in found
    }


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
