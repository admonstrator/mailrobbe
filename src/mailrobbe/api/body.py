"""The four views of a mail's body in the detail (D22), pure functions on the message bytes.

text is the part the importer indexes, chosen and decoded by the importer's own functions
(importer.parse.mime_parts, part_text), so the detail shows what the full text index holds, but
up to TEXT_LIMIT characters instead of the index's 50,000, with its segments (quotes.split_text,
D151) for the folded view. html is the first HTML part in the same order, for a sandboxed iframe.
headers and raw show the message as it is.

The detail's text view (text_view) adds the standard blocks (D227): the text's paragraphs
(blocks.model.paragraphs) are looked up in paragraph_block and paragraph_override in one query,
and each standard one is cut out of its segment as a folded segment of its own; with_blocks is
that step on its own, pure.

Messages are parsed with the compat32 policy, as the importer parses them; issues found while
decoding are not reported here (the importer has logged them in import_error).
"""

import asyncio
import email.parser
import email.policy
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

import sqlalchemy
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.schemas import (
    RAW_LIMIT,
    TEXT_LIMIT,
    HeaderField,
    MailHeaders,
    MailRaw,
    MailText,
    TextParagraph,
    TextSegment,
)
from mailrobbe.blocks.model import Paragraph, hash_hex, paragraphs
from mailrobbe.importer import text
from mailrobbe.importer.model import Issue
from mailrobbe.importer.parse import cut_at_line, mime_parts, part_payload, part_text
from mailrobbe.quotes import Segment, split_text

_PARSER = email.parser.BytesParser(policy=email.policy.compat32)
_HEADER_PARSER = email.parser.BytesHeaderParser(policy=email.policy.compat32)
_HEADER_END = re.compile(rb"\r?\n\r?\n")
_CONTENT = re.compile(r"[^\s>]")  # a line holding this is counted, as quotes.split_text counts
# What the blocks step and the team know about the paragraphs of a text, in one query.
_KNOWN = sqlalchemy.text("""
    SELECT h.hash, b.standard, b.mails, o.standard AS override
    FROM unnest(CAST(:hashes AS bigint[])) AS h(hash)
    LEFT JOIN paragraph_block b ON b.hash = h.hash
    LEFT JOIN paragraph_override o ON o.hash = h.hash
    WHERE b.hash IS NOT NULL OR o.hash IS NOT NULL
""")


@dataclass(frozen=True, slots=True)
class Known:
    """A paragraph as paragraph_block and paragraph_override know it."""

    standard: bool  # applied by the last blocks step
    mails: int  # paragraph_block.mails; 0 without a row
    override: bool | None  # the team's choice


_UNKNOWN = Known(standard=False, mails=0, override=None)


def mail_text(message: bytes) -> MailText:
    """The body text the full text index is built from, up to TEXT_LIMIT characters."""
    return _read_text(message)[0]


async def text_view(session: AsyncSession, message: bytes) -> MailText:
    """mail_text with the standard blocks cut out and the paragraphs listed (D227)."""
    shown, found = await asyncio.to_thread(_text_and_paragraphs, message)
    return with_blocks(shown, found, await known(session, found))


async def known(session: AsyncSession, found: Collection[Paragraph]) -> dict[int, Known]:
    """What paragraph_block and paragraph_override hold about these paragraphs, by hash."""
    if not found:
        return {}
    rows = await session.execute(_KNOWN, {"hashes": sorted({p.hash for p in found})})
    return {row.hash: Known(bool(row.standard), row.mails or 0, row.override) for row in rows}


def with_blocks(
    shown: MailText, found: Sequence[Paragraph], known: Mapping[int, Known]
) -> MailText:
    """The text with each standard paragraph cut out of its segment as a folded segment of kind
    standard, which takes the blank lines below it; the rest of the segment keeps its kind and
    fold, so the segments still cover the text in order. paragraphs lists all of found."""
    standard = [p for p in found if known.get(p.hash, _UNKNOWN).standard]
    listed = []
    for p in found:
        about = known.get(p.hash, _UNKNOWN)
        listed.append(
            TextParagraph(
                start=p.start,
                end=p.end,
                hash=hash_hex(p.hash),
                standard=about.standard,
                mails=about.mails,
                override=about.override,
            )
        )
    segments = _cut(shown.text, shown.segments, standard)
    return shown.model_copy(update={"segments": segments, "paragraphs": listed})


def _read_text(message: bytes) -> tuple[MailText, list[Segment]]:
    """mail_text and the segments it was built from."""
    parts = mime_parts(_PARSER.parsebytes(message), [])
    has_html = parts.first("text/html") is not None
    found = parts.first("text/plain", "text/html")
    if found is None:
        return MailText(text="", truncated=False, source="none", has_html=has_html), []
    content_type, part = found
    body, truncated = part_text(part, content_type, TEXT_LIMIT, [])
    segments = split_text(body)
    shown = MailText(
        text=body,
        truncated=truncated,
        source="text/plain" if content_type == "text/plain" else "text/html",
        has_html=has_html,
        segments=[
            TextSegment(
                kind=segment.kind,
                start=segment.start,
                end=segment.end,
                lines=segment.lines,
                folded=segment.folded,
            )
            for segment in segments
        ],
    )
    return shown, segments


def _text_and_paragraphs(message: bytes) -> tuple[MailText, list[Paragraph]]:
    shown, segments = _read_text(message)
    return shown, paragraphs(shown.text, segments) if segments else []


def _cut(
    text: str, segments: Sequence[TextSegment], standard: Sequence[Paragraph]
) -> list[TextSegment]:
    """segments with the standard paragraphs (in text order) cut out, as with_blocks says."""
    cut: list[TextSegment] = []
    queue = iter(standard)
    paragraph = next(queue, None)
    for segment in segments:
        position = segment.start
        while paragraph is not None and paragraph.start < segment.end:
            if paragraph.start > position:
                cut.append(_piece(text, segment, position, paragraph.start))
            end = _past_blank_lines(text, paragraph.end, segment.end)
            cut.append(
                TextSegment(
                    kind="standard",
                    start=paragraph.start,
                    end=end,
                    lines=_lines(text, paragraph.start, end),
                    folded=True,
                    block=hash_hex(paragraph.hash),
                )
            )
            position = end
            paragraph = next(queue, None)
        if position < segment.end or position == segment.start:
            cut.append(_piece(text, segment, position, segment.end))
    return cut


def _piece(text: str, segment: TextSegment, start: int, end: int) -> TextSegment:
    """The part of a segment from start to end, of its kind and fold."""
    return segment.model_copy(
        update={"start": start, "end": end, "lines": _lines(text, start, end)}
    )


def _past_blank_lines(text: str, end: int, limit: int) -> int:
    """The offset after the line break at end and the blank lines below it, up to limit."""
    if end >= limit or text[end] != "\n":
        return end
    position = end + 1
    while position < limit:
        newline = text.find("\n", position, limit)
        after = limit if newline == -1 else newline + 1
        if _CONTENT.search(text[position:after]):
            break
        position = after
    return position


def _lines(text: str, start: int, end: int) -> int:
    """Lines of text[start:end] with something besides quote markers on them."""
    return sum(1 for line in text[start:end].split("\n") if _CONTENT.search(line))


def mail_html(message: bytes) -> str | None:
    """The first HTML part in body order, decoded; None when the mail has none."""
    found = mime_parts(_PARSER.parsebytes(message), []).first("text/html")
    if found is None:
        return None
    part = found[1]
    issues: list[Issue] = []
    data = part_payload(part, "text/html part", issues)
    return text.clean(text.decode_bytes(data, part.get_content_charset(), "text/html part", issues))


def mail_headers(message: bytes) -> MailHeaders:
    """Every header field in mail order, unfolded, raw 8-bit bytes and encoded words decoded."""
    match = _HEADER_END.search(message)
    head = message if match is None else message[: match.end()]
    issues: list[Issue] = []
    fields = []
    for name, value in _HEADER_PARSER.parsebytes(head).raw_items():
        where = f"{name} header"
        value = text.decode_words(text.header_text(value, where, issues), where, issues)
        fields.append(HeaderField(name=text.clean(name), value=text.clean(value)))
    return MailHeaders(headers=fields)


def mail_raw(message: bytes) -> MailRaw:
    """The message as UTF-8 text, cut after a line end within RAW_LIMIT bytes."""
    shown = cut_at_line(message, RAW_LIMIT)
    return MailRaw(
        raw=shown.decode("utf-8", "replace"),
        truncated=len(shown) < len(message),
        size=len(message),
    )
