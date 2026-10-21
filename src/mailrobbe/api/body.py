"""The four views of a mail's body in the detail (D22), pure functions on the message bytes.

text is the part the importer indexes, chosen and decoded by the importer's own functions
(importer.parse.mime_parts, part_text), so the detail shows what the full text index holds, but
up to TEXT_LIMIT characters instead of the index's 50,000, with its segments (quotes.split_text,
D151) for the folded view. html is the first HTML part in the same order, for a sandboxed iframe.
headers and raw show the message as it is.

Messages are parsed with the compat32 policy, as the importer parses them; issues found while
decoding are not reported here (the importer has logged them in import_error).
"""

import email.parser
import email.policy
import re

from mailrobbe.api.schemas import (
    RAW_LIMIT,
    TEXT_LIMIT,
    HeaderField,
    MailHeaders,
    MailRaw,
    MailText,
    TextSegment,
)
from mailrobbe.importer import text
from mailrobbe.importer.model import Issue
from mailrobbe.importer.parse import cut_at_line, mime_parts, part_payload, part_text
from mailrobbe.quotes import split_text

_PARSER = email.parser.BytesParser(policy=email.policy.compat32)
_HEADER_PARSER = email.parser.BytesHeaderParser(policy=email.policy.compat32)
_HEADER_END = re.compile(rb"\r?\n\r?\n")


def mail_text(message: bytes) -> MailText:
    """The body text the full text index is built from, up to TEXT_LIMIT characters."""
    parts = mime_parts(_PARSER.parsebytes(message), [])
    has_html = parts.first("text/html") is not None
    found = parts.first("text/plain", "text/html")
    if found is None:
        return MailText(text="", truncated=False, source="none", has_html=has_html)
    content_type, part = found
    body, truncated = part_text(part, content_type, TEXT_LIMIT, [])
    return MailText(
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
            for segment in split_text(body)
        ],
    )


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
