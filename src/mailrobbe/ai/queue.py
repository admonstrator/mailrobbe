"""The AI queue (D186, D295): what someone selected becomes ai_task rows; the run takes them from
here.

Only a selection is queued, never the whole archive. A document can be read by OCR when it has a
SHA-256 (D18) and no text of its own: a scanned PDF, an image, or one an earlier OCR filled
(read again with another engine); the transcriber reads a recording (kind media) with a SHA-256
and no text of its own, or one an earlier transcription filled. Queuing gives each document what
fits it, or only the kind asked for. Each kind and content has at most one open task; queuing it
again raises its priority instead. Higher priorities come first, then the documents carried by
more mails (D70): one document queued from its page (PRIORITY_SINGLE), then what a mail in an
Akte or reviewed relevant carries (PRIORITY_FILED). Images in more than LOGO_MAILS mails are
almost always logos of signatures and are left out of OCR unless chosen one by one or asked for.

Summaries (D300, D308) are queued for mails, by their raw SHA-256 (duplicates share one task),
for documents with a text, by their SHA-256, and for threads of at least THREAD_MIN_MAILS mails,
by the SHA-256 of their mails (THREAD_KEY, D316), with the same priorities. A mail summarised from
its page takes its attachments along (D317): what OCR or the transcriber would read first gets
that task, and every attachment with a text, or waiting for one, a summary unless it has one.
All functions run in the caller's transaction.
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
    THREAD_MIN_MAILS,
    OcrEngineChoice,
)
from mailrobbe.enums import AiTaskKind, AiTaskStatus

WorkList = Literal["scanned", "images", "media"]

# Documents OCR can read (module docstring), as a condition on document d.
OCR_READABLE = (
    "d.sha256 IS NOT NULL AND (d.text_origin = 'ocr' OR (d.text_origin = 'extracted' "
    "AND (d.text_status = 'scanned' OR (d.kind = 'image' AND d.text_status IN "
    "('unsupported', 'empty')))))"
)
# Recordings the transcriber can read (D292, D294), as a condition on document d: audio and
# video with a SHA-256 and no text of their own, or one an earlier transcription filled.
TRANSCRIBABLE = (
    "d.sha256 IS NOT NULL AND d.kind = 'media' AND (d.text_origin = 'transcript' OR "
    "(d.text_origin = 'extracted' AND d.text_status IN ('unsupported', 'empty')))"
)
# The work lists of the AI page (D186): what is still without a valid OCR result, or for media
# without a valid transcript (D295).
_UNREAD = (
    "NOT EXISTS (SELECT 1 FROM ai_result r WHERE r.kind = 'ocr' AND r.state = 'valid' "
    "AND r.target_sha256 = d.sha256)"
)
_UNHEARD = (
    "NOT EXISTS (SELECT 1 FROM ai_result r WHERE r.kind = 'transcribe' AND r.state = 'valid' "
    "AND r.target_sha256 = d.sha256)"
)
WORK_LISTS: dict[WorkList, str] = {
    "scanned": f"d.text_status = 'scanned' AND d.sha256 IS NOT NULL AND {_UNREAD}",
    "images": (
        f"d.kind = 'image' AND d.text_origin = 'extracted' AND d.sha256 IS NOT NULL "
        f"AND d.text_status IN ('unsupported', 'empty') AND d.size_bytes >= {IMAGE_MIN_BYTES} "
        f"AND d.mails <= {LOGO_MAILS} AND {_UNREAD}"
    ),
    "media": f"{TRANSCRIBABLE} AND {_UNHEARD}",
}
_FILED = """
    EXISTS (
        SELECT 1 FROM attachment a JOIN mail m ON m.id = a.mail_id
        WHERE a.document_id = d.id
          AND (EXISTS (SELECT 1 FROM collection_mail c WHERE c.mail_sha256 = m.raw_sha256)
               OR EXISTS (SELECT 1 FROM mail_mark k
                          WHERE k.mail_sha256 = m.raw_sha256 AND k.review = 'relevant')))
"""
# The documents among ids that OCR (when :ocr) or the transcriber (when :transcribe) reads, with
# the kind of task each gets; the two conditions never hold for the same document.
_CANDIDATES = text(f"""
    SELECT d.id, d.sha256, d.kind = 'image' AND d.mails > {LOGO_MAILS} AS logo,
        CASE WHEN {OCR_READABLE} THEN 'ocr' ELSE 'transcribe' END AS kind,
        CASE WHEN :single THEN {PRIORITY_SINGLE}
             WHEN {_FILED} THEN {PRIORITY_FILED} ELSE 0 END AS priority
    FROM document d
    WHERE d.id = ANY(CAST(:ids AS bigint[]))
      AND ((CAST(:ocr AS boolean) AND {OCR_READABLE})
           OR (CAST(:transcribe AS boolean) AND {TRANSCRIBABLE}))
""")
_RAISE = text("""
    UPDATE ai_task SET priority = GREATEST(priority, :priority), engine = :engine
    WHERE kind = CAST(:kind AS ai_task_kind) AND target_sha256 = :sha256
      AND status IN ('waiting', 'running')
    RETURNING id
""")
_INSERT = text("""
    INSERT INTO ai_task (kind, target_sha256, engine, priority, queued_by)
    VALUES (CAST(:kind AS ai_task_kind), :sha256, :engine, :priority, :editor)
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
    """What enqueue did with the documents it was given."""

    queued: int  # new tasks
    raised: int  # already open: priority and engine updated
    unreadable: int  # read by neither (a text of its own, no SHA-256, unknown id)
    logos: int  # images in more than LOGO_MAILS mails, left out


async def enqueue(
    session: AsyncSession,
    document_ids: Sequence[int],
    *,
    kind: AiTaskKind | None = None,
    engine: OcrEngineChoice = "auto",
    editor: str | None = None,
    single: bool = False,
    include_logos: bool = False,
) -> Queued:
    """Queue what fits each of these documents, or only tasks of kind (module docstring);
    single is one document from its page, which also takes a logo. engine is that of the OCR
    tasks; a transcribe task keeps "auto", since there is only the one transcriber (D290)."""
    ids = sorted(set(document_ids))
    selection = {
        "ids": ids,
        "single": single,
        "ocr": kind in (None, AiTaskKind.OCR),
        "transcribe": kind in (None, AiTaskKind.TRANSCRIBE),
    }
    rows = (await session.execute(_CANDIDATES, selection)).all()
    queued = raised = logos = 0
    for row in rows:
        if row.logo and not (single or include_logos):
            logos += 1
            continue
        parameters = {
            "kind": row.kind,
            "sha256": row.sha256,
            "engine": engine if row.kind == AiTaskKind.OCR else "auto",
            "priority": row.priority,
        }
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
# A thread's content (D316), an aggregate over its mails m that are no duplicates: their raw
# SHA-256 sorted and joined by line ends, hashed; a thread that gained a mail is another content.
THREAD_KEY = (
    "encode(sha256(convert_to(string_agg(DISTINCT m.raw_sha256, E'\\n' ORDER BY m.raw_sha256), "
    "'UTF8')), 'hex')"
)
# The threads among :thread_ids with their content, mails and characters (the estimate's input).
_THREADS = f"""
    SELECT m.thread_id, {THREAD_KEY} AS sha256, count(DISTINCT m.raw_sha256) AS mails,
        sum(length(COALESCE(m.subject, '')) + length(COALESCE(m.body_text, ''))) AS characters
    FROM mail m
    WHERE m.thread_id = ANY(CAST(:thread_ids AS bigint[])) AND m.is_duplicate_of IS NULL
    GROUP BY m.thread_id
    HAVING count(DISTINCT m.raw_sha256) >= {THREAD_MIN_MAILS}
"""
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
    WITH threads AS ({_THREADS}),
    chosen AS (
        SELECT * FROM (
            SELECT DISTINCT ON (m.raw_sha256) 'mail' AS target, m.raw_sha256 AS sha256,
                CASE WHEN :single THEN {PRIORITY_SINGLE} WHEN {_FILED_MAIL} THEN {PRIORITY_FILED}
                     ELSE 0 END AS priority,
                length(COALESCE(m.subject, '')) + length(COALESCE(m.body_text, ''))
                    AS characters,
                {_WORDS} < {SUMMARY_MIN_WORDS} AS short, CAST(NULL AS bigint) AS thread_id
            FROM mail m
            WHERE m.id = ANY(CAST(:mail_ids AS bigint[])) AND {SUMMARIZABLE_MAIL}
            ORDER BY m.raw_sha256, priority DESC
        ) mails
        UNION ALL
        SELECT 'document', d.sha256,
            CASE WHEN :single THEN {PRIORITY_SINGLE} WHEN {_FILED} THEN {PRIORITY_FILED}
                 ELSE 0 END,
            length(COALESCE(d.extracted_text, '')), false, NULL
        FROM document d
        WHERE d.id = ANY(CAST(:document_ids AS bigint[]))
          AND ({SUMMARIZABLE_DOCUMENT}
               OR (d.sha256 IS NOT NULL AND d.id = ANY(CAST(:pending AS bigint[]))))
        UNION ALL
        SELECT 'thread', sha256, CASE WHEN :single THEN {PRIORITY_SINGLE} ELSE 0 END,
            characters, false, thread_id
        FROM threads
    )
"""
_SUMMARY_PREVIEW = text(f"""
    {_SUMMARY_CHOSEN}
    SELECT count(*) AS contents, count(*) FILTER (WHERE short) AS short,
        COALESCE(sum(characters), 0) AS characters,
        (SELECT count(*) FROM mail m
         WHERE m.id = ANY(CAST(:mail_ids AS bigint[])) AND {SUMMARIZABLE_MAIL}) AS mails,
        (SELECT count(*) FROM chosen WHERE target = 'document') AS documents,
        (SELECT count(*) FROM threads) AS threads
    FROM chosen
""")
# One open task per kind, target and content (ux_ai_task_open): an open one keeps its place and
# takes the higher priority; xmax = 0 tells a new row from an updated one.
_SUMMARY_INSERT = text(f"""
    {_SUMMARY_CHOSEN}
    INSERT INTO ai_task (kind, target, target_sha256, thread_id, priority, queued_by)
    SELECT 'summarize', target, sha256, thread_id, priority, CAST(:editor AS text) FROM chosen
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
    thread_ids: Sequence[int] = (),
    pending: Sequence[int] = (),
    editor: str | None = None,
    single: bool = False,
    preview: bool = False,
) -> QueuedSummaries:
    """Queue summaries of these mails, documents and threads (D308, D316); single is one element
    from its page, first in the queue. Documents among pending are queued without a text yet:
    their OCR or transcription is queued too and comes first in a run (D317). With preview
    nothing is written."""
    mails, documents, threads = (
        sorted(set(mail_ids)),
        sorted(set(document_ids)),
        sorted(set(thread_ids)),
    )
    parameters = {
        "mail_ids": mails,
        "document_ids": documents,
        "thread_ids": threads,
        "pending": sorted(set(pending)),
        "single": single,
        "editor": editor,
    }
    figures = (await session.execute(_SUMMARY_PREVIEW, parameters)).one()
    given = len(mails) + len(documents) + len(threads)
    unreadable = given - int(figures.mails) - int(figures.documents) - int(figures.threads)
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


# The documents of these mails' own attachments (not an archive's members, D231) for D317: what a
# work list of OCR or transcription would take, whether there is a text to summarise, and whether
# a valid summary exists.
_ATTACHED = text(f"""
    SELECT DISTINCT d.id,
        ({WORK_LISTS["scanned"]}) OR ({WORK_LISTS["images"]}) OR ({WORK_LISTS["media"]})
            AS unread,
        {SUMMARIZABLE_DOCUMENT} AS readable,
        EXISTS (SELECT 1 FROM ai_result r
                WHERE r.kind = 'summarize' AND r.target = 'document'
                  AND r.target_sha256 = d.sha256 AND r.state = 'valid') AS summarized
    FROM attachment a JOIN document d ON d.id = a.document_id
    WHERE a.mail_id = ANY(CAST(:mail_ids AS bigint[])) AND a.container_id IS NULL
""")


@dataclass(frozen=True, slots=True)
class Attached:
    """What enqueue_attachments did for the attachments of some mails."""

    recognized: Queued  # the OCR and transcribe tasks
    summarize: list[int]  # documents to summarise: with a text, or waiting for one, and no summary
    pending: list[int]  # among them those waiting for their text


async def enqueue_attachments(
    session: AsyncSession, mail_ids: Sequence[int], *, editor: str | None = None
) -> Attached:
    """Queue the OCR or transcription of these mails' attachments that a work list would take,
    first in the queue, and name the documents whose summaries go with the mails' (D317)."""
    rows = (await session.execute(_ATTACHED, {"mail_ids": sorted(set(mail_ids))})).all()
    unread = sorted(row.id for row in rows if row.unread)
    recognized = await enqueue(session, unread, editor=editor, single=True)
    summarize = sorted(
        row.id for row in rows if not row.summarized and (row.readable or row.unread)
    )
    return Attached(recognized, summarize, unread)
