"""The one place writing ai_result and the AI texts of documents (D185, D294).

ai_result is the source, named by the content's SHA-256; document.extracted_text is the copy the
full text search, the hit marks, the entities and the signals read. A recognised text only fills
a document without a text of its own (a scanned PDF, an image) or replaces an earlier OCR text;
a transcript only fills a recording without a text of its own or replaces an earlier transcript;
an empty one never overwrites anything. A transcript also gives every document of its content
the recording's length (document.duration), whatever it holds. Every change of a text sets
extracted_at, so the next entities phase scans the document again (D84). All functions run in
the caller's transaction.

A summary (D300, D301) is the result of kind summarize of a mail (by its raw SHA-256) or a
document: its text is the summary, its pages the parts read, and its AI tags (ai_tag, one row per
model.tag_key, shown by the spelling it was first given, D305) and theme hints (ai_theme_hint,
D304) hang on it, so they leave every view with it. It never touches a document.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.ai.model import (
    TRANSCRIBE_MODEL,
    OcrPage,
    Summary,
    TranscriptSegment,
    page_text,
    result_engine,
    tag_key,
    transcript_text,
)
from mailrobbe.db.models import DOCUMENT_TEXT_LIMIT
from mailrobbe.enums import AiTarget, AiTaskKind

# A document d the text of result r may go into: none of its own, or one from an earlier result
# of the same kind; an OCR text into any such document, a transcript into a recording only.
_FILLABLE = """
    d.sha256 = r.target_sha256
    AND CASE r.kind
        WHEN 'ocr' THEN d.text_origin = 'ocr' OR (d.text_origin = 'extracted'
            AND d.text_status IN ('scanned', 'unsupported', 'empty'))
        WHEN 'transcribe' THEN d.kind = 'media' AND (d.text_origin = 'transcript'
            OR (d.text_origin = 'extracted' AND d.text_status IN ('unsupported', 'empty')))
        ELSE false END
"""
_REPLACE = text("""
    UPDATE ai_result SET state = 'replaced'
    WHERE kind = CAST(:kind AS ai_task_kind) AND target_sha256 = :sha256 AND state = 'valid'
""")
_INSERT = text("""
    INSERT INTO ai_result (kind, target_sha256, engine, model, service_url, remote,
        prompt_version, options, body, pages, pages_total, duration, transcribed, tokens_in,
        tokens_out, seconds, job_id)
    VALUES (CAST(:kind AS ai_task_kind), :sha256, :engine, :model, :service_url, :remote,
        :prompt_version, CAST(:options AS jsonb), :body, CAST(:pages AS jsonb), :pages_total,
        :duration, :transcribed, :tokens_in, :tokens_out, :seconds, :job_id)
    RETURNING id
""")
_APPLY = text(f"""
    UPDATE document d SET extracted_text = r.body,
        text_truncated = length(r.body) >= {DOCUMENT_TEXT_LIMIT},
        text_status = 'text', text_error = NULL,
        text_origin = CASE r.kind WHEN 'transcribe' THEN CAST('transcript' AS text_origin)
                                  ELSE CAST('ocr' AS text_origin) END,
        ai_result_id = r.id, pages = COALESCE(r.pages_total, d.pages),
        duration = COALESCE(r.duration, d.duration), extracted_at = now()
    FROM ai_result r
    WHERE r.id = :result_id AND {_FILLABLE}
""")
# The recording's length on every document of its content (D293), when it is known.
_DURATION = text("""
    UPDATE document SET duration = CAST(:duration AS float8)
    WHERE sha256 = :sha256 AND CAST(:duration AS float8) IS NOT NULL
""")
# Back to what the import found: a PDF is a scan again, any other file has no text extraction.
_RESTORE = text("""
    UPDATE document SET extracted_text = NULL, text_truncated = false,
        text_status = CASE WHEN kind = 'pdf' THEN CAST('scanned' AS document_text_status)
                           ELSE CAST('unsupported' AS document_text_status) END,
        text_origin = 'extracted', ai_result_id = NULL, extracted_at = now()
    WHERE ai_result_id = :result_id
""")
_RESULT = text("""
    SELECT kind::text AS kind, target, target_sha256, state::text AS state FROM ai_result
    WHERE id = :result_id FOR UPDATE
""")
_DISCARD = text("""
    UPDATE ai_result SET state = 'discarded', discarded_by = :editor, discarded_at = now()
    WHERE id = :result_id
""")
# The newest replaced result with a text, which takes the discarded one's place; any summary,
# since a short one has tags and hints without a text (D302).
_PREDECESSOR = text("""
    SELECT id FROM ai_result
    WHERE kind = CAST(:kind AS ai_task_kind) AND target = :target AND target_sha256 = :sha256
      AND state = 'replaced' AND (body <> '' OR kind = 'summarize')
    ORDER BY id DESC LIMIT 1
""")
_REVIVE = text("UPDATE ai_result SET state = 'valid' WHERE id = :result_id")
_JOB_RESULTS = text("""
    SELECT id FROM ai_result WHERE job_id = :job_id AND state = 'valid' ORDER BY id
""")
# Documents made again after a new import whose content has a valid OCR result or transcript
# with a text.
_UNAPPLIED = text(f"""
    SELECT r.id
    FROM ai_result r
    WHERE r.kind IN ('ocr', 'transcribe') AND r.state = 'valid' AND r.body <> ''
      AND EXISTS (SELECT 1 FROM document d WHERE d.text_origin = 'extracted' AND {_FILLABLE})
    ORDER BY r.id
""")
# Their lengths too, also of transcripts without a text (nobody speaks).
_LENGTHS = text("""
    UPDATE document d SET duration = r.duration
    FROM ai_result r
    WHERE r.kind = 'transcribe' AND r.state = 'valid' AND r.duration IS NOT NULL
      AND d.sha256 = r.target_sha256 AND d.duration IS NULL
""")


@dataclass(frozen=True, slots=True)
class StoredResult:
    result_id: int
    documents: int  # documents that took its text: 0 for an empty text or a document with one


async def store_ocr_result(
    session: AsyncSession,
    *,
    sha256: str,
    pages: Sequence[OcrPage],
    pages_total: int | None,
    model: str | None,
    service_url: str | None,
    remote: bool,
    prompt_version: int | None,
    options: dict[str, Any],
    seconds: float,
    job_id: int | None,
) -> StoredResult:
    """Record an OCR result as the valid one for this content and put its text into the
    documents it may fill (module docstring). An empty text is recorded, but changes no document:
    "no text found" is an outcome, not an error (D184)."""
    body, _ = page_text(pages)
    await session.execute(_REPLACE, {"kind": AiTaskKind.OCR.value, "sha256": sha256})
    result_id = await session.scalar(
        _INSERT,
        {
            "kind": AiTaskKind.OCR.value,
            "sha256": sha256,
            "engine": result_engine(pages),
            "model": model,
            "service_url": service_url,
            "remote": remote,
            "prompt_version": prompt_version,
            "options": json.dumps(options),
            "body": body,
            "pages": json.dumps([page.model_dump(mode="json") for page in pages]),
            "pages_total": pages_total,
            "duration": None,
            "transcribed": None,
            "tokens_in": sum(page.tokens_in for page in pages),
            "tokens_out": sum(page.tokens_out for page in pages),
            "seconds": seconds,
            "job_id": job_id,
        },
    )
    assert result_id is not None
    documents = 0
    if body:
        documents = await _apply(session, int(result_id))
    return StoredResult(int(result_id), documents)


async def store_transcript_result(
    session: AsyncSession,
    *,
    sha256: str,
    segments: Sequence[TranscriptSegment],
    duration: float | None,
    transcribed: float,
    audio: bool,
    options: dict[str, Any],
    seconds: float,
    job_id: int | None,
) -> StoredResult:
    """Record a transcript as the valid one for this content (D294): its lines in time order as
    pages, the recording's length (None: not known) and the seconds of it read; its text into
    the recordings it may fill and the length into every document of the content. An empty
    transcript (nobody speaks, or audio False: the file has no sound) is recorded, but changes
    no text."""
    body, _ = transcript_text(segments)
    lines = sorted(segments, key=lambda segment: segment.start)
    await session.execute(_REPLACE, {"kind": AiTaskKind.TRANSCRIBE.value, "sha256": sha256})
    result_id = await session.scalar(
        _INSERT,
        {
            "kind": AiTaskKind.TRANSCRIBE.value,
            "sha256": sha256,
            "engine": "parakeet",
            "model": TRANSCRIBE_MODEL,
            "service_url": None,
            "remote": False,
            "prompt_version": None,
            "options": json.dumps({**options, "audio": audio}),
            "body": body,
            "pages": json.dumps([segment.model_dump(mode="json") for segment in lines]),
            "pages_total": None,
            "duration": duration,
            "transcribed": transcribed,
            "tokens_in": 0,
            "tokens_out": 0,
            "seconds": seconds,
            "job_id": job_id,
        },
    )
    assert result_id is not None
    await session.execute(_DURATION, {"sha256": sha256, "duration": duration})
    documents = 0
    if body:
        documents = await _apply(session, int(result_id))
    return StoredResult(int(result_id), documents)


async def _apply(session: AsyncSession, result_id: int) -> int:
    result = await session.execute(_APPLY, {"result_id": result_id})
    return int(result.rowcount)  # type: ignore[attr-defined]


async def discard_result(session: AsyncSession, result_id: int, editor: str | None) -> bool:
    """Throw a result away (D185); False when there is none or it was discarded before.

    The documents holding its text get the newest earlier result with a text of the same kind
    and content back, or lose the AI text and return to what the import found. A summary touches
    no document: the newest one it replaced is valid again, a short one without a text too.
    """
    row = (await session.execute(_RESULT, {"result_id": result_id})).first()
    if row is None or row.state == "discarded":
        return False
    summary = row.kind == AiTaskKind.SUMMARIZE  # touches no document (module docstring)
    await session.execute(_DISCARD, {"result_id": result_id, "editor": editor})
    if not summary:
        await session.execute(_RESTORE, {"result_id": result_id})
    if row.state == "valid":
        previous = await session.scalar(
            _PREDECESSOR, {"kind": row.kind, "target": row.target, "sha256": row.target_sha256}
        )
        if previous is not None:
            await session.execute(_REVIVE, {"result_id": previous})
            if not summary:
                await _apply(session, int(previous))
    return True


async def discard_job_results(session: AsyncSession, job_id: int, editor: str | None) -> int:
    """Throw away every valid result of one run; how many."""
    ids = list((await session.execute(_JOB_RESULTS, {"job_id": job_id})).scalars())
    for result_id in ids:
        await discard_result(session, result_id, editor)
    return len(ids)


async def reapply_results(session: AsyncSession) -> int:
    """Put valid OCR texts and transcripts into documents an import made again for the same
    content (D185, D294), and the lengths of recordings; how many documents took a text."""
    documents = 0
    for result_id in list((await session.execute(_UNAPPLIED)).scalars()):
        documents += await _apply(session, result_id)
    await session.execute(_LENGTHS)
    return documents


# Summaries (D300 to D305) -----------------------------------------------------------------------

_REPLACE_SUMMARY = text("""
    UPDATE ai_result SET state = 'replaced'
    WHERE kind = 'summarize' AND target = :target AND target_sha256 = :sha256 AND state = 'valid'
""")
_INSERT_SUMMARY = text("""
    INSERT INTO ai_result (kind, target, target_sha256, engine, model, service_url, remote,
        prompt_version, options, body, pages, pages_total, tokens_in, tokens_out, seconds, job_id)
    VALUES ('summarize', :target, :sha256, 'text', :model, :service_url, :remote, :prompt_version,
        CAST(:options AS jsonb), :body, CAST(:pages AS jsonb), :pages_total, :tokens_in,
        :tokens_out, :seconds, :job_id)
    RETURNING id
""")
# A new key keeps the spelling it is given now, a known one its first (D305).
_TAGS = text("""
    INSERT INTO ai_tag (key, label)
    SELECT * FROM unnest(CAST(:keys AS text[]), CAST(:labels AS text[]))
    ON CONFLICT (key) DO NOTHING
""")
_LINKS = text("""
    INSERT INTO ai_tag_link (result_id, tag_id)
    SELECT :result_id, id FROM ai_tag WHERE key = ANY(CAST(:keys AS text[]))
""")
_HINTS = text("""
    INSERT INTO ai_theme_hint (result_id, theme, quote, position)
    SELECT :result_id, * FROM unnest(CAST(:themes AS text[]), CAST(:quotes AS text[]),
        CAST(:positions AS integer[]))
""")


async def store_summary_result(
    session: AsyncSession,
    *,
    target: AiTarget,
    sha256: str,
    summary: Summary,
    model: str,
    service_url: str,
    remote: bool,
    prompt_version: int,
    options: dict[str, Any],
    seconds: float,
    tokens_in: int,
    tokens_out: int,
    job_id: int | None,
) -> int:
    """Record a summary as the valid one of this target and content, replacing the one before,
    with its AI tags and theme hints (module docstring); its id. options gets the summary's
    short, words, origin, dropped_tags and dropped_themes."""
    parameters = {"target": target.value, "sha256": sha256}
    await session.execute(_REPLACE_SUMMARY, parameters)
    figures = summary.model_dump(
        include={"short", "words", "origin", "dropped_tags", "dropped_themes"}
    )
    result_id = await session.scalar(
        _INSERT_SUMMARY,
        {
            **parameters,
            "model": model,
            "service_url": service_url,
            "remote": remote,
            "prompt_version": prompt_version,
            "options": json.dumps({**options, **figures}),
            "body": summary.summary,
            "pages": json.dumps([part.model_dump(mode="json") for part in summary.parts]),
            "pages_total": summary.parts_total,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "seconds": seconds,
            "job_id": job_id,
        },
    )
    assert result_id is not None
    if summary.tags:
        keys = [tag_key(label) for label in summary.tags]
        await session.execute(_TAGS, {"keys": keys, "labels": summary.tags})
        await session.execute(_LINKS, {"result_id": result_id, "keys": keys})
    if summary.themes:
        await session.execute(
            _HINTS,
            {
                "result_id": result_id,
                "themes": [hint.theme for hint in summary.themes],
                "quotes": [hint.quote for hint in summary.themes],
                "positions": [hint.position for hint in summary.themes],
            },
        )
    return int(result_id)
