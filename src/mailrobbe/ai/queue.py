"""The AI queue (D186): what someone selected becomes ai_task rows; the run takes them from here.

Only a selection is queued, never the whole archive. A document can be read by OCR when it has a
SHA-256 (D18) and no text of its own: a scanned PDF, an image, or one an earlier OCR filled
(read again with another engine). Each kind and content has at most one open task; queuing it
again raises its priority instead. Higher priorities come first, then the documents carried by
more mails (D70): one document queued from its page (PRIORITY_SINGLE), then what a mail in an
Akte or reviewed relevant carries (PRIORITY_FILED). Images in more than LOGO_MAILS mails are
almost always logos of signatures and are left out unless chosen one by one or asked for.

Summaries (D300, D308) are queued for mails, by their raw SHA-256 (duplicates share one task),
and for documents with a text, by their SHA-256, with the same priorities. All functions run in
the caller's transaction.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.ai.model import (
    IMAGE_MIN_BYTES,
    LOGO_MAILS,
    PRIORITY_FILED,
    PRIORITY_SINGLE,
    SUMMARY_MIN_WORDS,
    OcrEngineChoice,
)
from mailrobbe.enums import AiTaskKind, AiTaskStatus

WorkList = Literal["scanned", "images"]

# Documents OCR can read (module docstring), as a condition on document d.
OCR_READABLE = (
    "d.sha256 IS NOT NULL AND (d.text_origin = 'ocr' OR (d.text_origin = 'extracted' "
    "AND (d.text_status = 'scanned' OR (d.kind = 'image' AND d.text_status IN "
    "('unsupported', 'empty')))))"
)
# The work lists of the AI page (D186): what is still without a valid OCR result.
_UNREAD = (
    "NOT EXISTS (SELECT 1 FROM ai_result r WHERE r.kind = 'ocr' AND r.state = 'valid' "
    "AND r.target_sha256 = d.sha256)"
)
WORK_LISTS: dict[WorkList, str] = {
    "scanned": f"d.text_status = 'scanned' AND d.sha256 IS NOT NULL AND {_UNREAD}",
    "images": (
        f"d.kind = 'image' AND d.text_origin = 'extracted' AND d.sha256 IS NOT NULL "
        f"AND d.text_status IN ('unsupported', 'empty') AND d.size_bytes >= {IMAGE_MIN_BYTES} "
        f"AND d.mails <= {LOGO_MAILS} AND {_UNREAD}"
    ),
}
_FILED = """
    EXISTS (
        SELECT 1 FROM attachment a JOIN mail m ON m.id = a.mail_id
        WHERE a.document_id = d.id
          AND (EXISTS (SELECT 1 FROM collection_mail c WHERE c.mail_sha256 = m.raw_sha256)
               OR EXISTS (SELECT 1 FROM mail_mark k
                          WHERE k.mail_sha256 = m.raw_sha256 AND k.review = 'relevant')))
"""
_CANDIDATES = text(f"""
    SELECT d.id, d.sha256, d.kind = 'image' AND d.mails > {LOGO_MAILS} AS logo,
        CASE WHEN :single THEN {PRIORITY_SINGLE}
             WHEN {_FILED} THEN {PRIORITY_FILED} ELSE 0 END AS priority
    FROM document d
    WHERE d.id = ANY(CAST(:ids AS bigint[])) AND {OCR_READABLE}
""")
_RAISE = text("""
    UPDATE ai_task SET priority = GREATEST(priority, :priority), engine = :engine
    WHERE kind = 'ocr' AND target_sha256 = :sha256 AND status IN ('waiting', 'running')
    RETURNING id
""")
_INSERT = text("""
    INSERT INTO ai_task (kind, target_sha256, engine, priority, queued_by)
    VALUES ('ocr', :sha256, :engine, :priority, :editor)
""")
_RETRY = text("""
    UPDATE ai_task t SET status = 'waiting', attempts = 0, error = NULL, finished_at = NULL,
        queued_by = CAST(:editor AS text), queued_at = now()
    WHERE t.status IN ('failed', 'cancelled')
      AND (CAST(:ids AS bigint[]) IS NULL OR t.id = ANY(CAST(:ids AS bigint[])))
      AND (CAST(:kind AS text) IS NULL OR t.kind = CAST(:kind AS ai_task_kind))
      AND NOT EXISTS (SELECT 1 FROM ai_task o
                      WHERE o.kind = t.kind AND o.target = t.target
                        AND o.target_sha256 = t.target_sha256
                        AND o.status IN ('waiting', 'running'))
""")
_CANCEL = text("""
    UPDATE ai_task SET status = 'cancelled', finished_at = now()
    WHERE status = 'waiting'
      AND (CAST(:ids AS bigint[]) IS NULL OR id = ANY(CAST(:ids AS bigint[])))
      AND (CAST(:kind AS text) IS NULL OR kind = CAST(:kind AS ai_task_kind))
""")
_COUNTS = text("""
    SELECT kind::text, status::text, count(*) FROM ai_task GROUP BY kind, status
""")


@dataclass(frozen=True, slots=True)
class Queued:
    """What enqueue_ocr did with the documents it was given."""

    queued: int  # new tasks
    raised: int  # already open: priority and engine updated
    unreadable: int  # not readable by OCR (a text of its own, no SHA-256, unknown id)
    logos: int  # images in more than LOGO_MAILS mails, left out


async def enqueue_ocr(
    session: AsyncSession,
    document_ids: Sequence[int],
    *,
    engine: OcrEngineChoice = "auto",
    editor: str | None = None,
    single: bool = False,
    include_logos: bool = False,
) -> Queued:
    """Queue OCR for these documents (module docstring); single is one document from its page,
    which also takes a logo."""
    ids = sorted(set(document_ids))
    rows = (await session.execute(_CANDIDATES, {"ids": ids, "single": single})).all()
    queued = raised = logos = 0
    for row in rows:
        if row.logo and not (single or include_logos):
            logos += 1
            continue
        parameters = {"sha256": row.sha256, "engine": engine, "priority": row.priority}
        if (await session.execute(_RAISE, parameters)).first() is not None:
            raised += 1
            continue
        await session.execute(_INSERT, {**parameters, "editor": editor})
        queued += 1
    return Queued(queued, raised, len(ids) - len(rows), logos)


async def work_list_ids(session: AsyncSession, work_list: WorkList) -> list[int]:
    """The documents of a work list of the AI page, most mails first."""
    statement = text(
        f"SELECT d.id FROM document d WHERE {WORK_LISTS[work_list]} ORDER BY d.mails DESC, d.id"
    )
    return list((await session.execute(statement)).scalars())


async def retry_tasks(
    session: AsyncSession,
    task_ids: Sequence[int] | None = None,
    *,
    kind: AiTaskKind | None = None,
    editor: str | None = None,
) -> int:
    """Put failed or cancelled tasks back on the queue (all of them when task_ids is None);
    one whose content has an open task already stays as it is. How many."""
    parameters = {
        "ids": None if task_ids is None else list(task_ids),
        "kind": None if kind is None else kind.value,
        "editor": editor,
    }
    result = await session.execute(_RETRY, parameters)
    return int(result.rowcount)  # type: ignore[attr-defined]


async def cancel_tasks(
    session: AsyncSession, task_ids: Sequence[int] | None = None, *, kind: AiTaskKind | None = None
) -> int:
    """Take waiting tasks off the queue (all of them when task_ids is None); how many. A running
    task ends with its run (stop the run first)."""
    parameters = {
        "ids": None if task_ids is None else list(task_ids),
        "kind": None if kind is None else kind.value,
    }
    result = await session.execute(_CANCEL, parameters)
    return int(result.rowcount)  # type: ignore[attr-defined]


async def task_counts(session: AsyncSession) -> dict[AiTaskKind, dict[AiTaskStatus, int]]:
    """Tasks per kind and status; every kind and status present."""
    counts = {kind: dict.fromkeys(AiTaskStatus, 0) for kind in AiTaskKind}
    for kind, status, count in (await session.execute(_COUNTS)).all():
        counts[AiTaskKind(kind)][AiTaskStatus(status)] = int(count)
    return counts


# Summaries (D300, D308) -----------------------------------------------------------------------

# What can be summarised (D302): a mail with a subject or a text, a document with a SHA-256 and a
# text of any origin.
SUMMARIZABLE_MAIL = "(COALESCE(m.subject, '') <> '' OR COALESCE(m.body_text, '') <> '')"
SUMMARIZABLE_DOCUMENT = "(d.sha256 IS NOT NULL AND COALESCE(d.extracted_text, '') <> '')"
# Words of a mail's whole text: an estimate of "short" before the run splits off quotes (D302).
_WORDS = (
    "COALESCE(array_length(regexp_split_to_array(btrim(COALESCE(m.body_text, '')), "
    r"'\s+'), 1), 0)"
)
_FILED_MAIL = """
    (EXISTS (SELECT 1 FROM collection_mail c WHERE c.mail_sha256 = m.raw_sha256)
     OR EXISTS (SELECT 1 FROM mail_mark k
                WHERE k.mail_sha256 = m.raw_sha256 AND k.review = 'relevant'))
"""
_SUMMARY_CHOSEN = f"""
    WITH chosen AS (
        SELECT * FROM (
            SELECT DISTINCT ON (m.raw_sha256) 'mail' AS target, m.raw_sha256 AS sha256,
                CASE WHEN :single THEN {PRIORITY_SINGLE} WHEN {_FILED_MAIL} THEN {PRIORITY_FILED}
                     ELSE 0 END AS priority,
                length(COALESCE(m.subject, '')) + length(COALESCE(m.body_text, ''))
                    AS characters,
                {_WORDS} < {SUMMARY_MIN_WORDS} AS short
            FROM mail m
            WHERE m.id = ANY(CAST(:mail_ids AS bigint[])) AND {SUMMARIZABLE_MAIL}
            ORDER BY m.raw_sha256, priority DESC
        ) mails
        UNION ALL
        SELECT 'document', d.sha256,
            CASE WHEN :single THEN {PRIORITY_SINGLE} WHEN {_FILED} THEN {PRIORITY_FILED}
                 ELSE 0 END,
            length(d.extracted_text), false
        FROM document d
        WHERE d.id = ANY(CAST(:document_ids AS bigint[])) AND {SUMMARIZABLE_DOCUMENT}
    )
"""
_SUMMARY_PREVIEW = text(f"""
    {_SUMMARY_CHOSEN}
    SELECT count(*) AS contents, count(*) FILTER (WHERE short) AS short,
        COALESCE(sum(characters), 0) AS characters,
        (SELECT count(*) FROM mail m
         WHERE m.id = ANY(CAST(:mail_ids AS bigint[])) AND {SUMMARIZABLE_MAIL}) AS mails,
        (SELECT count(*) FROM document d
         WHERE d.id = ANY(CAST(:document_ids AS bigint[])) AND {SUMMARIZABLE_DOCUMENT})
            AS documents
    FROM chosen
""")
# One open task per kind, target and content (ux_ai_task_open): an open one keeps its place and
# takes the higher priority; xmax = 0 tells a new row from an updated one.
_SUMMARY_INSERT = text(f"""
    {_SUMMARY_CHOSEN}
    INSERT INTO ai_task (kind, target, target_sha256, priority, queued_by)
    SELECT 'summarize', target, sha256, priority, CAST(:editor AS text) FROM chosen
    ON CONFLICT (kind, target, target_sha256) WHERE status IN ('waiting', 'running')
    DO UPDATE SET priority = GREATEST(ai_task.priority, EXCLUDED.priority)
    RETURNING (xmax = 0) AS inserted
""")


@dataclass(frozen=True, slots=True)
class QueuedSummaries:
    """What enqueue_summaries did, or with preview would do."""

    queued: int  # new tasks (with preview: the contents a queuing would take)
    raised: int  # already open: priority raised (0 with preview)
    unreadable: int  # nothing to summarise, or an unknown id (D302)
    short: int  # contents of mails whose whole text has fewer than SUMMARY_MIN_WORDS words
    characters: int  # of the texts queued or raised: the estimate's input (D308)


async def enqueue_summaries(
    session: AsyncSession,
    *,
    mail_ids: Sequence[int] = (),
    document_ids: Sequence[int] = (),
    editor: str | None = None,
    single: bool = False,
    preview: bool = False,
) -> QueuedSummaries:
    """Queue summaries of these mails and documents (D308); single is one element from its page,
    first in the queue. With preview nothing is written."""
    mails, documents = sorted(set(mail_ids)), sorted(set(document_ids))
    parameters = {"mail_ids": mails, "document_ids": documents, "single": single, "editor": editor}
    figures = (await session.execute(_SUMMARY_PREVIEW, parameters)).one()
    given = len(mails) + len(documents)
    unreadable = given - int(figures.mails) - int(figures.documents)
    queued, raised = int(figures.contents), 0
    if not preview:
        inserted = list((await session.execute(_SUMMARY_INSERT, parameters)).scalars())
        queued = sum(1 for new in inserted if new)
        raised = len(inserted) - queued
    return QueuedSummaries(
        queued=queued,
        raised=raised,
        unreadable=unreadable,
        short=int(figures.short),
        characters=int(figures.characters),
    )
