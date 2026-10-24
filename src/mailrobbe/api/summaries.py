"""The summary of one mail, document or thread (milestone 17, D307, D316): GET /api/ai/summary,
what the card "KI-Zusammenfassung" shows. Models are in schemas.py (AiSummaryView).

A summary is the valid ai_result of kind summarize for the element's content: a mail by its
raw_sha256, a document by its sha256 (D301). The card asks again every 3 s while a task is open,
so the view is a handful of indexed queries: the element by id, its summary (ux_ai_result_valid),
its open task (ux_ai_task_open), the latest failed task (ix_ai_task_status reads the failed ones
only), a mail's attachments' summaries (ix_attachment_mail_id), then the tags with the mails each
describes (api/ai_tags.tag_counts) and the theme hints of all these summaries at once. Nothing is
read from the MBOX file (D302); everything shown is machine made (D311), which the card says with
model and date.

A thread (D316) is found by its thread_id: its content now (ai.queue.THREAD_KEY over
ix_mail_thread_id), its valid summary by ix_ai_result_thread_id, stale when that read other
mails. A mail counts its attachments' open tasks of any kind (D317), a thread its mails'
(D346), and while the element or its attachments have one and an AI run lives, the view carries
that run, whose steps are the card's progress (D318).
"""

from collections import defaultdict
from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe import jobs
from mailrobbe.ai.model import THREAD_MIN_MAILS
from mailrobbe.ai.queue import SUMMARIZABLE_DOCUMENT, SUMMARIZABLE_MAIL, THREAD_KEY
from mailrobbe.api.ai import text_usable
from mailrobbe.api.ai_tags import tag_counts
from mailrobbe.api.deps import AppSettings, Session, api_error
from mailrobbe.api.imports import ai_job
from mailrobbe.api.schemas import (
    AiAttachmentSummary,
    AiSummaryParams,
    AiSummaryResult,
    AiSummaryTask,
    AiSummaryTheme,
    AiSummaryView,
    AiTagCount,
)
from mailrobbe.enums import AiTarget, AiTaskStatus, JobKind, TextOrigin
from mailrobbe.themes import load_themes

router = APIRouter(prefix="/api/ai", tags=["ai"])

BIGINT = range(-(2**63), 2**63)
ORIGINS = frozenset(origin.value for origin in TextOrigin)

_MAIL = text(f"""
    SELECT m.raw_sha256 AS sha256, {SUMMARIZABLE_MAIL} AS summarizable FROM mail m WHERE m.id = :id
""")
_DOCUMENT = text(f"""
    SELECT d.sha256, {SUMMARIZABLE_DOCUMENT} AS summarizable FROM document d WHERE d.id = :id
""")
_THREAD = text(f"""
    SELECT {THREAD_KEY} AS sha256,
        count(DISTINCT m.raw_sha256) >= {THREAD_MIN_MAILS} AS summarizable
    FROM mail m WHERE m.thread_id = :id AND m.is_duplicate_of IS NULL
    HAVING count(*) > 0
""")
# A summary's parts are its pages (ai.model.SummaryPart); its options say whether the text was
# short and which text of a document it read.
_FIELDS = """
    r.id, r.target, r.body, r.options, jsonb_array_length(r.pages) AS parts_read, r.pages_total,
    r.model, r.remote, r.prompt_version, r.created_at
"""
_RESULT = text(f"""
    SELECT {_FIELDS}, r.target_sha256 FROM ai_result r
    WHERE r.kind = 'summarize' AND r.target = :target AND r.target_sha256 = :sha256
      AND r.state = 'valid'
""")
# A thread keeps one valid summary (ai.store), whatever mails it read.
_THREAD_RESULT = text(f"""
    SELECT {_FIELDS}, r.target_sha256 FROM ai_result r
    WHERE r.thread_id = :thread_id AND r.kind = 'summarize' AND r.target = 'thread'
      AND r.state = 'valid'
""")
_TASK = text("""
    SELECT id, status::text AS status,
        CASE WHEN jsonb_typeof(partial -> 'parts') = 'array'
             THEN jsonb_array_length(partial -> 'parts') ELSE 0 END AS parts_done,
        CASE WHEN jsonb_typeof(partial -> 'parts_total') = 'number'
             THEN (partial ->> 'parts_total')::int END AS parts_total,
        queued_at, started_at
    FROM ai_task
    WHERE kind = 'summarize' AND target = :target AND target_sha256 = :sha256
      AND status IN ('waiting', 'running')
""")
# The latest failed task, unless a summary was made after it (kept, replaced or discarded since).
_FAILED = text("""
    SELECT t.error FROM ai_task t
    WHERE t.status = 'failed' AND t.kind = 'summarize' AND t.target = :target
      AND t.target_sha256 = :sha256
      AND NOT EXISTS (
          SELECT 1 FROM ai_result r
          WHERE r.target_sha256 = t.target_sha256 AND r.kind = 'summarize'
            AND r.target = t.target AND r.created_at >= COALESCE(t.finished_at, t.queued_at))
    ORDER BY t.id DESC LIMIT 1
""")
# The summaries of a mail's attachments' documents, in the order of the attachments.
_ATTACHMENTS = text(f"""
    SELECT * FROM (
        SELECT DISTINCT ON (d.id) a.id AS attachment_id, d.id AS document_id, d.name, {_FIELDS}
        FROM attachment a
        JOIN document d ON d.id = a.document_id
        JOIN ai_result r ON r.kind = 'summarize' AND r.target = 'document'
            AND r.target_sha256 = d.sha256 AND r.state = 'valid'
        WHERE a.mail_id = :mail_id
        ORDER BY d.id, a.id
    ) found
    ORDER BY attachment_id
""")
_PREPARING = text("""
    SELECT count(DISTINCT t.id) FROM attachment a
    JOIN document d ON d.id = a.document_id
    JOIN ai_task t ON t.target = 'document' AND t.target_sha256 = d.sha256
        AND t.status IN ('waiting', 'running')
    WHERE a.mail_id = :mail_id AND a.container_id IS NULL
""")
# A thread's too (D346): its mails' attachments are read and summarised first.
_THREAD_PREPARING = text("""
    SELECT count(DISTINCT t.id) FROM mail m
    JOIN attachment a ON a.mail_id = m.id AND a.container_id IS NULL
    JOIN document d ON d.id = a.document_id
    JOIN ai_task t ON t.target = 'document' AND t.target_sha256 = d.sha256
        AND t.status IN ('waiting', 'running')
    WHERE m.thread_id = :thread_id AND m.is_duplicate_of IS NULL
""")
_LINKS = text("""
    SELECT l.result_id, l.tag_id FROM ai_tag_link l
    WHERE l.result_id = ANY(CAST(:result_ids AS bigint[]))
""")
_THEMES = text("""
    SELECT result_id, theme, quote, position FROM ai_theme_hint
    WHERE result_id = ANY(CAST(:result_ids AS bigint[]))
    ORDER BY result_id, id
""")


@router.get("/summary")
async def summary(
    params: Annotated[AiSummaryParams, Query()], session: Session, settings: AppSettings
) -> AiSummaryView:
    given = {AiTarget.MAIL: params.mail, AiTarget.DOCUMENT: params.document}
    given[AiTarget.THREAD] = params.thread
    chosen = [(target, value) for target, value in given.items() if value is not None]
    if len(chosen) != 1:
        raise api_error(400, "invalid_selection", "give exactly one of mail, document and thread")
    ((target, element_id),) = chosen
    element = None
    if element_id in BIGINT:
        statement = {AiTarget.MAIL: _MAIL, AiTarget.DOCUMENT: _DOCUMENT, AiTarget.THREAD: _THREAD}
        element = (await session.execute(statement[target], {"id": element_id})).first()
    if element is None:
        raise api_error(404, "not_found", f"no {target} with id {element_id}")

    found = task = failed = None
    if element.sha256 is not None:  # a document above the hash limit has none (D18)
        keys = {"target": target.value, "sha256": element.sha256}
        if target is AiTarget.THREAD:
            found = (await session.execute(_THREAD_RESULT, {"thread_id": element_id})).first()
        else:
            found = (await session.execute(_RESULT, keys)).first()
        task = (await session.execute(_TASK, keys)).first()
        if task is None:
            failure = (await session.execute(_FAILED, keys)).first()
            failed = None if failure is None else failure.error or "failed"
    attached: list[Row[Any]] = []
    preparing = 0
    if target is AiTarget.MAIL:
        attached = list(await session.execute(_ATTACHMENTS, {"mail_id": element_id}))
        preparing = int(await session.scalar(_PREPARING, {"mail_id": element_id}) or 0)
    elif target is AiTarget.THREAD:
        preparing = int(await session.scalar(_THREAD_PREPARING, {"thread_id": element_id}) or 0)
    run = None
    if task is not None or preparing:
        latest = await jobs.latest_job(session, JobKind.AI)
        run = None if latest is None else await ai_job(session, settings, latest)
        run = run if run is not None and run.alive else None

    result_ids = [row.id for row in [found, *attached] if row is not None]
    tags = await _tags(session, result_ids)
    themes = await _themes(session, result_ids)
    return AiSummaryView(
        available=await text_usable(settings),
        summarizable=element.summarizable,
        result=None if found is None else _result(found, tags, themes),
        task=None
        if task is None
        else AiSummaryTask(
            id=task.id,
            status=AiTaskStatus(task.status),
            parts_done=task.parts_done,
            parts_total=task.parts_total,
            queued_at=task.queued_at,
            started_at=task.started_at,
        ),
        failed=failed,
        attachments=[
            AiAttachmentSummary(
                document_id=row.document_id, name=row.name, result=_result(row, tags, themes)
            )
            for row in attached
        ],
        preparing=preparing,
        stale=found is not None and found.target_sha256 != element.sha256,
        run=run,
    )


def _result(
    row: Row[Any],
    tags: dict[int, list[AiTagCount]],
    themes: dict[int, list[AiSummaryTheme]],
) -> AiSummaryResult:
    options: dict[str, Any] = row.options if isinstance(row.options, dict) else {}
    origin = str(options.get("origin"))
    return AiSummaryResult(
        id=row.id,
        target=AiTarget(row.target),
        summary=row.body,
        short=bool(options.get("short", False)),
        tags=tags.get(row.id, []),
        themes=themes.get(row.id, []),
        parts_read=row.parts_read,
        parts_total=row.parts_read if row.pages_total is None else row.pages_total,
        origin=TextOrigin(origin) if origin in ORIGINS else None,
        model=row.model,
        remote=row.remote,
        prompt_version=row.prompt_version,
        created_at=row.created_at,
    )


async def _tags(session: AsyncSession, result_ids: Sequence[int]) -> dict[int, list[AiTagCount]]:
    """The tags of each summary, by its label, with the mails each describes (tag_counts, D309)."""
    found: dict[int, list[AiTagCount]] = defaultdict(list)
    if not result_ids:
        return found
    links = (await session.execute(_LINKS, {"result_ids": list(result_ids)})).all()
    counts = {tag.id: tag for tag in await tag_counts(session, [row.tag_id for row in links])}
    for row in links:
        found[row.result_id].append(counts[row.tag_id])
    for tags in found.values():
        tags.sort(key=lambda tag: (tag.label.lower(), tag.id))
    return found


async def _themes(
    session: AsyncSession, result_ids: Sequence[int]
) -> dict[int, list[AiSummaryTheme]]:
    """The theme hints of each summary in the order of themes.toml, each theme's quotes as they
    stand in the text (one in the head first); a theme no longer in the file shows its key."""
    order = {theme.key: (index, theme.name) for index, theme in enumerate(load_themes())}
    found: dict[int, list[AiSummaryTheme]] = defaultdict(list)
    if not result_ids:
        return found
    for row in await session.execute(_THEMES, {"result_ids": list(result_ids)}):
        _, label = order.get(row.theme, (len(order), row.theme))
        found[row.result_id].append(
            AiSummaryTheme(theme=row.theme, label=label, quote=row.quote, position=row.position)
        )
    for hints in found.values():
        hints.sort(
            key=lambda hint: (
                order.get(hint.theme, (len(order), hint.theme)),
                -1 if hint.position is None else hint.position,
            )
        )
    return found
