"""Attachments and documents (milestone 9, D70 to D76): the document list, its figures, a
document's page and text, and attachment downloads. Endpoints and models are in schemas.py.

Routes: GET /api/documents, /api/documents/summary, /api/documents/{id},
/api/documents/{id}/text, /api/attachments/{id}/content, /api/mails/{id}/hits.

The list reads document rows only, apart from the conditions on the mails carrying a document
(date, person, external), which hold when one carrying mail that is no duplicate meets them all:
one EXISTS over attachment and mail with the mail list's own conditions (filters.mail_conditions,
D21, D32). It pages by keyset as the person list does (D19, D31): a cursor names the sort key of
its boundary row and is bound to the sort order; ties go by id in the direction of the sort, so
each sort walks its index (ix_document_first_date, ix_document_mails, ix_document_size_bytes).
With conditions on mails and no search words the walk is bounded as the mail list's
(filters.first_ids): the next WALK_ROWS documents in order, then, when they hold too few matches,
every match sorted; matches cluster (one year's documents, one person's), and PostgreSQL's
estimate assumes they do not.

A snippet is found in PostgreSQL, so that only its surroundings leave the database: the search
words as typed become one regular expression, any case written out as character classes (the
database's locale may know only ASCII case), which regexp_instr finds in the stored text.

The hits of one mail (D79) say whether its own text matches the mail list's full text words and
which of its attachments do, each with the snippet of the list, or around another form of a
word where none occurs as typed. The browser marks the words as typed and the words the stems of
the query begin, the forms German stemming finds.

Downloads read the bytes from the MBOX file on request (attachments.content, D76) and are never
cached: a download as application/octet-stream with a sandboxing policy, apart from raster
images by their first bytes, which the document page shows in an <img>.
"""

import asyncio
import logging
import re
import urllib.parse
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Annotated, Any

import fastapi
from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Executable,
    Integer,
    Select,
    SQLColumnExpression,
    Text,
    any_,
    cast,
    exists,
    false,
    func,
    literal,
    literal_column,
    select,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.util import ClauseAdapter

from mailrobbe.api.deps import AppSettings, Session, api_error
from mailrobbe.api.detail import MailId, mail_senders
from mailrobbe.api.filters import (
    WALK_ROWS,
    FilterError,
    _contains,
    internal_domains,
    mail_conditions,
    text_query,
    text_search,
)
from mailrobbe.api.mails import _QUERY_CANCELED, _count_budget, _unless_canceled
from mailrobbe.api.persons import _beyond, _by, _Cursor, _int, _stamp
from mailrobbe.api.query import QueryError, parse_query
from mailrobbe.api.schemas import (
    COUNT_LIMIT,
    DOCUMENT_NAMES_LIMIT,
    DOCUMENT_PERSONS_LIMIT,
    SNIPPET_LENGTH,
    AttachmentHit,
    DocumentDetail,
    DocumentFilters,
    DocumentListItem,
    DocumentListParams,
    DocumentNameCount,
    DocumentPage,
    DocumentSort,
    DocumentSummary,
    DocumentText,
    MailFilters,
    MailHits,
    PersonCount,
    PersonRef,
    ThreadMail,
)
from mailrobbe.attachments.content import (
    AttachmentChanged,
    attachment_source,
    document_sources,
    read_attachment,
)
from mailrobbe.db.models import (
    FIRST_DATE_SORT_KEY,
    TEXT_SEARCH_CONFIG,
    TIMESTAMPTZ,
    Attachment,
    Document,
    Mail,
    Participation,
    Person,
)
from mailrobbe.enums import DocumentKind, DocumentTextStatus, ParticipationRole
from mailrobbe.persons.labels import attach_labels
from mailrobbe.persons.roots import ROOT
from mailrobbe.preview.kinds import preview_kind

router = APIRouter(prefix="/api", tags=["documents"])
log = logging.getLogger(__name__)

# document.id and attachment.id are bigints: a larger number is a validation error.
DocumentId = Annotated[int, fastapi.Path(ge=-(2**63), le=2**63 - 1)]
AttachmentId = Annotated[int, fastapi.Path(ge=-(2**63), le=2**63 - 1)]

# The bytes are served as a download; even opened directly, nothing in them runs (D76).
CONTENT_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; sandbox"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",  # the bytes are read for each request and never kept
}
# Raster images by their first bytes keep their type, so an <img> can show them (D76).
_RASTER_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

_FIRST_DATE: ColumnElement[datetime] = literal_column(FIRST_DATE_SORT_KEY, TIMESTAMPTZ)
_NO_DATE = literal_column("'-infinity'::timestamp with time zone", TIMESTAMPTZ)
_TEXT_SEARCH: ColumnElement[Any] = literal_column(f"'{TEXT_SEARCH_CONFIG}'::regconfig")
_RECIPIENTS = (ParticipationRole.TO, ParticipationRole.CC, ParticipationRole.BCC)
_NAMES = Document.names  # every file name, one per line (attachments.documents.NAMES_LIMIT)
_ITEM_COLUMNS = (
    Document.id,
    Document.name,
    _NAMES,
    Document.kind,
    Document.mime_type,
    Document.size_bytes,
    Document.sha256,
    Document.pages,
    Document.text_status,
    Document.mails,
    Document.first_date,
    Document.last_date,
    Document.first_mail_id,
)


# Filters -------------------------------------------------------------------------------------


def document_conditions(
    filters: DocumentFilters, internal: Sequence[str], *, walk: bool = False
) -> list[ColumnElement[bool]]:
    """Every condition of the filters (D74) on document; FilterError for an unusable one.

    The conditions on mails become one EXISTS, which PostgreSQL may turn into a join over every
    carrying mail; with walk, a subquery it runs for one document at a time instead, for the
    bounded walk of _first_ids.
    """
    where: list[ColumnElement[bool]] = []
    if filters.q.strip():
        query = func.websearch_to_tsquery(_TEXT_SEARCH, filters.q)
        where.append(Document.tsv.bool_op("@@")(query))
    if filters.name.strip():
        where.append(_NAMES.ilike(_contains(filters.name.strip())))
    if filters.kind:
        where.append(Document.kind.in_(sorted(set(filters.kind))))
    if filters.text_status:
        where.append(Document.text_status.in_(sorted(set(filters.text_status))))
    if filters.shared:
        where.append(Document.mails >= 2)
    mail_filters = MailFilters(
        date_from=filters.date_from,
        date_to=filters.date_to,
        person=[] if filters.person is None else [filters.person],
        person_role=filters.person_role,
        external=filters.external,
    )
    on_mail = mail_conditions(mail_filters, (), internal)
    if not on_mail:
        return where
    carrying = (  # one carrying mail that is no duplicate meets them all
        Attachment.document_id == Document.id,
        Mail.id == Attachment.mail_id,
        Mail.is_duplicate_of.is_(None),
        *on_mail,
    )
    if not walk:
        where.append(exists().where(*carrying))
        return where
    one = select(true()).select_from(Attachment, Mail).where(*carrying).limit(1)
    where.append(func.coalesce(one.scalar_subquery(), false()))  # scalar: never hashed in full
    return where


def _where(
    filters: DocumentFilters, internal_setting: str, *, walk: bool = False
) -> list[ColumnElement[bool]]:
    try:
        return document_conditions(filters, internal_domains(internal_setting), walk=walk)
    except FilterError as error:
        raise api_error(400, "invalid_filter", str(error)) from error


def _sort_key(
    sort: DocumentSort,
) -> tuple[SQLColumnExpression[Any], SQLColumnExpression[Any], bool, Callable[[Any], Any]]:
    """The sort key before the id, the column a cursor keeps of it, whether it descends, and how
    a cursor's value is read. The first date keeps first_date itself, as its key is -infinity
    without one."""
    match sort:
        case "recent":
            return _FIRST_DATE, Document.first_date, True, _stamp
        case "oldest":
            return _FIRST_DATE, Document.first_date, False, _stamp
        case "mails":
            return Document.mails, Document.mails, True, _int
    return Document.size_bytes, Document.size_bytes, True, _int


def _boundary(sort: DocumentSort, value: Any) -> ColumnElement[Any]:
    match sort:
        case "recent" | "oldest":
            return func.coalesce(literal(value, TIMESTAMPTZ), _NO_DATE)
        case "mails":
            return literal(value, Integer)
    return literal(value, BigInteger)


# List ----------------------------------------------------------------------------------------


@router.get("/documents")
async def list_documents(
    params: Annotated[DocumentListParams, Query()], session: Session, settings: AppSettings
) -> DocumentPage:
    scope = f"documents/{params.sort}"
    key, kept, descending, kind = _sort_key(params.sort)
    cursor = _Cursor.decode(params.cursor, scope, (kind, _int))
    where = _where(params, settings.internal_domains)
    columns = [key, Document.id]
    reverse = cursor is not None and cursor.before
    start = []
    if cursor is not None:
        boundary = [_boundary(params.sort, cursor.key[0]), literal(cursor.key[1], BigInteger)]
        start.append(_beyond(columns, boundary, descending != reverse))
    item = select(*_ITEM_COLUMNS, kept.label("key"))
    if _on_mails(params):
        # With search words the GIN index narrows first: no walk, which would test every text.
        walk = None if params.q.strip() else _where(params, settings.internal_domains, walk=True)
        down = descending != reverse
        ids = await _first_ids(session, where, walk, start, key, down, params.limit + 1)
        found = await session.execute(
            item.where(Document.id == any_(literal(ids, ARRAY(BigInteger))))
        )
        by_id = {row.id: row for row in found}
        rows: list[Any] = [by_id[document_id] for document_id in ids]
    else:
        statement = item.where(*where, *start).order_by(*_by(columns, descending != reverse))
        rows = list(await session.execute(statement.limit(params.limit + 1)))
    more = len(rows) > params.limit
    del rows[params.limit :]
    if reverse:
        rows.reverse()
    senders = await mail_senders(session, [row.first_mail_id for row in rows if row.first_mail_id])
    snippets = await _snippets(
        session, literal_pattern(search_words(params.q)), [row.id for row in rows]
    )

    def at(row: Any, before: bool) -> str:
        return _Cursor(scope, before, (row.key, row.id)).encode()

    # As in the mail list: a prev cursor walks backwards, "more" then means rows before the page.
    prev_cursor = next_cursor = None
    if cursor is None:
        next_cursor = at(rows[-1], False) if more else None
    elif cursor.before:
        prev_cursor = at(rows[0], True) if more else None
        next_cursor = at(rows[-1], False) if rows else cursor.flipped().encode()
    else:
        next_cursor = at(rows[-1], False) if more else None
        prev_cursor = at(rows[0], True) if rows else cursor.flipped().encode()
    page = DocumentPage(
        items=[
            DocumentListItem(
                id=row.id,
                name=row.name,
                names=len(row.names.split("\n")) if row.names else 0,
                kind=row.kind,
                mime_type=row.mime_type,
                size=row.size_bytes,
                sha256=row.sha256,
                pages=row.pages,
                text_status=row.text_status,
                mails=row.mails,
                first_date=row.first_date,
                last_date=row.last_date,
                first_sender=senders.get(row.first_mail_id),
                snippet=snippets.get(row.id),
            )
            for row in rows
        ],
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
    )
    await attach_labels(session, page)
    return page


def _on_mails(filters: DocumentFilters) -> bool:
    """Conditions on the carrying mails apply (the EXISTS of document_conditions)."""
    on_mails = (filters.date_from, filters.date_to, filters.person)
    return filters.external or any(value is not None for value in on_mails)


async def _first_ids(
    session: AsyncSession,
    where: Sequence[ColumnElement[bool]],
    walk: Sequence[ColumnElement[bool]] | None,
    start: Sequence[ColumnElement[bool]],
    key: SQLColumnExpression[Any],
    descending: bool,
    limit: int,
) -> list[int]:
    """Ids of the first `limit` documents matching where in list order: among the next
    WALK_ROWS documents (tested with walk, the same conditions one document at a time), else
    among every match (filters.first_ids does the same for mails). walk None: every match."""
    if walk is not None:
        window = (
            select(*Document.__table__.c, key.label("key"))
            .where(*start)
            .order_by(*_by([key, Document.id], descending))
            .limit(WALK_ROWS)
            .subquery("walk")
        )
        on_window = ClauseAdapter(window).traverse
        walked = (
            select(window.c.id)
            .where(*(on_window(condition) for condition in walk))
            .order_by(*_by([window.c.key, window.c.id], descending))
            .limit(limit)
        )
        found = list(await session.scalars(walked))
        if len(found) == limit:
            return found
    # MATERIALIZED keeps PostgreSQL from turning this back into an unbounded walk.
    matched = (
        select(Document.id, key.label("key"))
        .where(*start, *where)
        .cte("matched")
        .prefix_with("MATERIALIZED")
    )
    ordered = select(matched.c.id).order_by(*_by([matched.c.key, matched.c.id], descending))
    return list(await session.scalars(ordered.limit(limit)))


# Snippets ------------------------------------------------------------------------------------

# websearch_to_tsquery's syntax: "a phrase", -excluded, OR, and plain words.
_TOKEN = re.compile(r'(-?)"([^"]*)"?|(\S+)')
_WORD_EDGES = re.compile(r"^\W+|\W+$")
_SPECIAL = frozenset("\\^$.|?*+()[]{}")  # escaped alike in PostgreSQL's and Python's syntax
_FOLDED = {"a": "aäAÄ", "o": "oöOÖ", "u": "uüUÜ"}  # the German stems fold umlauts
_LEXEME = re.compile(r"'((?:[^']|'')+)'")  # a lexeme in the text of a tsquery
_SNIPPETS = text("""
    SELECT id, substr(extracted_text, greatest(1, at - :before), :span) AS around,
        at - greatest(1, at - :before) AS offset
    FROM (
        SELECT id, extracted_text, regexp_instr(extracted_text, :pattern) AS at
        FROM document
        WHERE id = ANY(CAST(:ids AS bigint[])) AND extracted_text IS NOT NULL
    ) found
    WHERE at > 0
""")


def search_words(q: str) -> list[str]:
    """The words and phrases of a full text query as typed, without excluded ones and OR."""
    words = []
    for match in _TOKEN.finditer(q):
        negated, phrase, word = match.groups()
        if word is None:
            value = "" if negated else " ".join(phrase.split())
        elif word.startswith("-") or word.lower() == "or":
            value = ""
        else:
            value = word
        value = _WORD_EDGES.sub("", value)
        if value and value not in words:
            words.append(value)
    return words


def _char(value: str) -> str:
    """One character in any case, escaped where the syntax needs it."""
    variants = sorted({value, value.lower(), value.upper()} - {""})
    variants = [variant for variant in variants if len(variant) == 1]
    if len(variants) > 1:
        return "[" + "".join(variants) + "]"
    return "\\" + value if value in _SPECIAL else value


def literal_pattern(words: Sequence[str]) -> str:
    """One regular expression for any of the words as typed, in any case, with any whitespace
    between the words of a phrase; valid in PostgreSQL's and in Python's syntax."""

    def word(value: str) -> str:
        return r"\s+".join("".join(_char(c) for c in part) for part in value.split())

    return "|".join(f"(?:{word(value)})" for value in words)


def stem_pattern(stems: Sequence[str]) -> str:
    """One regular expression for any word beginning with one of the German stems of a query
    (D79): umlauts folded to their base letter and ß to ss, as the dictionary stores them, in
    any case; stems under four letters left out, as the browser marks them only as whole words.
    Valid in PostgreSQL's and in Python's syntax, like literal_pattern."""

    def char(value: str) -> str:
        return f"[{_FOLDED[value]}]" if value in _FOLDED else _char(value)

    def stem(value: str) -> str:
        return "(?:[Ss]{2}|ß)".join("".join(char(c) for c in part) for part in value.split("ss"))

    return "|".join(rf"(?:(?<!\w){stem(value)})" for value in stems if len(value) >= 4)


def snippet_around(around: str, offset: int, pattern: re.Pattern[str]) -> str | None:
    """At most SNIPPET_LENGTH characters of around with the match at offset, in whole words
    where it can, whitespace collapsed."""
    match = pattern.search(around, offset) or pattern.search(around)
    if match is None:
        return None
    start = max(0, match.start() - SNIPPET_LENGTH // 4)
    if start > 0:  # begin with a whole word
        space = around.find(" ", start, match.start())
        start = space + 1 if space >= 0 else start
    end = start + SNIPPET_LENGTH
    if end < len(around):  # end with a whole word
        space = around.rfind(" ", match.end(), end)
        end = space if space >= 0 else end
    return " ".join(around[start:end].split())[:SNIPPET_LENGTH] or None


async def _snippets(session: AsyncSession, pattern: str, ids: Sequence[int]) -> dict[int, str]:
    """Per document, the stored text around the first place the pattern matches."""
    if not pattern or not ids:
        return {}
    rows = await session.execute(
        _SNIPPETS,
        {
            "ids": list(ids),
            "pattern": pattern,
            "before": SNIPPET_LENGTH,
            "span": 3 * SNIPPET_LENGTH,
        },
    )
    compiled = re.compile(pattern)
    found = {}
    for document_id, around, offset in rows:
        snippet = snippet_around(around, offset, compiled)
        if snippet is not None:
            found[document_id] = snippet
    return found


# Hits in one mail -----------------------------------------------------------------------------


@router.get("/mails/{mail_id}/hits")
async def mail_hits(mail_id: MailId, session: Session, q: str = "") -> MailHits:
    try:
        terms = parse_query(q)
    except QueryError as error:
        raise api_error(400, "invalid_query", str(error)) from error
    search, query = text_search(terms), text_query(terms)
    own = Mail.tsv.bool_op("@@")(query) if query is not None else false()
    lexemes = cast(query, Text) if query is not None else literal("")
    found = (await session.execute(select(own, lexemes).where(Mail.id == mail_id))).first()
    if found is None:
        raise api_error(404, "not_found", f"no mail with id {mail_id}")
    if query is None:
        return MailHits(words=[], stems=[], in_mail=False, attachments=[])
    names = func.to_tsvector(_TEXT_SEARCH, func.translate(Document.names, "_.-", "   "))
    rows = (
        await session.execute(
            select(
                Attachment.id, Attachment.document_id, names.bool_op("@@")(query).label("in_name")
            )
            .join(Document, Document.id == Attachment.document_id)
            .where(Attachment.mail_id == mail_id, Document.tsv.bool_op("@@")(query))
            .order_by(Attachment.id)
        )
    ).all()
    words = search_words(search)
    stems = list(dict.fromkeys(lexeme.replace("''", "'") for lexeme in _LEXEME.findall(found[1])))
    # the words as typed, else another form of one (the place the browser marks either way)
    pattern = "|".join(filter(None, [literal_pattern(words), stem_pattern(stems)]))
    snippets = await _snippets(session, pattern, [row.document_id for row in rows])
    return MailHits(
        words=words,
        stems=stems,
        in_mail=found[0],
        attachments=[
            AttachmentHit(
                attachment_id=row.id, in_name=row.in_name, snippet=snippets.get(row.document_id)
            )
            for row in rows
        ],
    )


# Summary -------------------------------------------------------------------------------------


@router.get("/documents/summary")
async def summary(
    filters: Annotated[DocumentFilters, Query()], session: Session, settings: AppSettings
) -> DocumentSummary:
    where = _where(filters, settings.internal_domains)
    await _count_budget(session, settings)
    counts = (
        select(Document.kind, Document.text_status, func.count())
        .where(*where)
        .group_by(Document.kind, Document.text_status)
    )
    rows = await _all_unless_canceled(session, counts)
    if rows is not None:
        kinds = dict.fromkeys(DocumentKind, 0)
        statuses = dict.fromkeys(DocumentTextStatus, 0)
        for kind, status, count in rows:
            if kind is not None:
                kinds[kind] += count
            statuses[status] += count
        return DocumentSummary(
            total=sum(statuses.values()), exact=True, kinds=kinds, text_status=statuses
        )
    bounded = select(Document.id).where(*where).limit(COUNT_LIMIT + 1).subquery()
    row = await _unless_canceled(session, select(func.count()).select_from(bounded))
    total = None if row is None else min(row[0], COUNT_LIMIT)
    exact = row is not None and row[0] <= COUNT_LIMIT
    return DocumentSummary(total=total, exact=exact, kinds=None, text_status=None)


async def _all_unless_canceled(session: AsyncSession, statement: Executable) -> list[Any] | None:
    """The statement's rows, or None when the count budget's statement timeout stopped it."""
    try:
        async with session.begin_nested():
            return list(await session.execute(statement))
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) != _QUERY_CANCELED:
            raise
        return None


# One document --------------------------------------------------------------------------------

_DETAIL_COLUMNS = (
    Document.id,
    Document.name,
    Document.mime_type,
    Document.kind,
    Document.size_bytes,
    Document.sha256,
    Document.pages,
    Document.text_status,
    Document.text_error,
    Document.text_truncated,
    Document.extracted_at,
    Document.mails,
    Document.attachments,
    Document.first_date,
    Document.last_date,
    Document.first_mail_id,
)


@router.get("/documents/{document_id}")
async def document_detail(
    document_id: DocumentId, session: Session, settings: AppSettings
) -> DocumentDetail:
    found = await session.execute(select(*_DETAIL_COLUMNS).where(Document.id == document_id))
    document = found.one_or_none()
    source = None
    if document is not None:  # finalize deletes documents without attachments
        source = (await document_sources(session, [document_id])).get(document_id)
    if document is None or source is None:
        raise _not_found(document_id)
    senders, sender_count, recipients, recipient_count = await _persons(session, document_id)
    detail = DocumentDetail(
        id=document.id,
        name=document.name,
        mime_type=document.mime_type,
        kind=document.kind,
        size=document.size_bytes,
        sha256=document.sha256,
        pages=document.pages,
        text_status=document.text_status,
        text_error=document.text_error,
        text_truncated=document.text_truncated,
        extracted_at=document.extracted_at,
        mails=document.mails,
        attachments=document.attachments,
        first_date=document.first_date,
        last_date=document.last_date,
        first_mail=await _first_mail(session, document.first_mail_id),
        names=await _names(session, document_id),
        senders=senders,
        sender_count=sender_count,
        recipients=recipients,
        recipient_count=recipient_count,
        attachment_id=source.attachment_id,
        preview=preview_kind(
            document.kind,
            document.name,
            document.mime_type,
            document.size_bytes,
            hashed=document.sha256 is not None,
            max_size=settings.preview_max_size,
        ),
    )
    await attach_labels(session, detail)
    return detail


@router.get("/documents/{document_id}/text")
async def document_text(document_id: DocumentId, session: Session) -> DocumentText:
    found = await session.execute(
        select(Document.extracted_text, Document.text_truncated, Document.text_status).where(
            Document.id == document_id
        )
    )
    row = found.one_or_none()
    if row is None:
        raise _not_found(document_id)
    return DocumentText(
        text=row.extracted_text or "", truncated=row.text_truncated, text_status=row.text_status
    )


def _not_found(document_id: int) -> fastapi.HTTPException:
    return api_error(404, "not_found", f"no document with id {document_id}")


async def _first_mail(session: AsyncSession, mail_id: int | None) -> ThreadMail | None:
    if mail_id is None:
        return None
    row = (
        await session.execute(
            select(Mail.id, Mail.date_utc, Mail.subject, Mail.dkim_status).where(Mail.id == mail_id)
        )
    ).one_or_none()
    if row is None:
        return None
    senders = await mail_senders(session, [mail_id])
    return ThreadMail(
        id=row.id,
        date=row.date_utc,
        subject=row.subject,
        sender=senders.get(mail_id),
        dkim_status=row.dkim_status,
    )


async def _names(session: AsyncSession, document_id: int) -> list[DocumentNameCount]:
    """The file names it was sent under, with their attachments, most used first."""
    count = func.count().label("count")
    rows = await session.execute(
        select(Attachment.filename, count)
        .where(Attachment.document_id == document_id, Attachment.filename.is_not(None))
        .group_by(Attachment.filename)
        .order_by(count.desc(), Attachment.filename)
        .limit(DOCUMENT_NAMES_LIMIT)
    )
    return [
        DocumentNameCount(name=name, attachments=attachments)
        for name, attachments in rows
        if name is not None  # left out above already
    ]


async def _persons(
    session: AsyncSession, document_id: int
) -> tuple[list[PersonCount], int, list[PersonCount], int]:
    """The root persons who sent and who received the mails carrying it (duplicates not
    counted), each with those mails, most first; and how many there are of each."""
    carried = (
        select(Attachment.mail_id)
        .join(Mail, Mail.id == Attachment.mail_id)
        .where(Attachment.document_id == document_id, Mail.is_duplicate_of.is_(None))
    )
    return await mail_persons(session, carried, DOCUMENT_PERSONS_LIMIT)


async def mail_persons(
    session: AsyncSession, mail_ids: Select[Any], limit: int
) -> tuple[list[PersonCount], int, list[PersonCount], int]:
    """The root persons who sent and who received these mails (a select of mail ids), each
    with those mails, the `limit` with most first; and how many there are of each. The entity
    page counts the same way (api/entities.py)."""
    sent = Participation.role == ParticipationRole.FROM
    root = ROOT.label("root")
    mails = func.count(Participation.mail_id.distinct()).label("mails")
    rows = list(
        await session.execute(
            select(root, sent.label("sent"), mails)
            .join(Person, Person.id == Participation.person_id)
            .where(Participation.mail_id.in_(mail_ids))
            .group_by(root, sent)
            .order_by(mails.desc(), root)
        )
    )
    senders = [row for row in rows if row.sent]
    recipients = [row for row in rows if not row.sent]
    shown = [*senders[:limit], *recipients[:limit]]
    people = {}
    if shown:
        found = await session.execute(
            select(Person.id, Person.canonical_email, Person.display_name).where(
                Person.id.in_({row.root for row in shown})
            )
        )
        people = {
            person_id: PersonRef(person_id=person_id, email=email, name=name)
            for person_id, email, name in found
        }

    def counts(selected: list[Any]) -> list[PersonCount]:
        return [PersonCount(person=people[row.root], mails=row.mails) for row in selected[:limit]]

    return counts(senders), len(senders), counts(recipients), len(recipients)


# Downloads -----------------------------------------------------------------------------------


@router.get("/attachments/{attachment_id}/content")
async def attachment_content(
    attachment_id: AttachmentId, session: Session, settings: AppSettings
) -> Response:
    source = await attachment_source(session, attachment_id)
    if source is None:
        raise api_error(404, "not_found", f"no attachment with id {attachment_id}")
    await session.commit()  # the file may be slow to read; hold no connection meanwhile
    try:
        data = await asyncio.to_thread(read_attachment, settings.mbox_dir, source)
    except OSError as error:
        log.warning("attachment %d: cannot read %s: %s", attachment_id, source.path, error)
        raise api_error(409, "source_missing", f"cannot read {source.path}: {error}") from None
    except AttachmentChanged as error:
        log.warning("attachment %d: %s", attachment_id, error)
        raise api_error(409, "source_changed", str(error)) from None
    name = source.filename or f"attachment-{attachment_id}"
    headers = {**CONTENT_HEADERS, "Content-Disposition": content_disposition(name)}
    return Response(data, media_type=content_type(data), headers=headers)


def content_type(data: bytes) -> str:
    """image/png, image/jpeg, image/gif or image/webp when the first bytes prove it, else
    application/octet-stream."""
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    for signature, media_type in _RASTER_SIGNATURES:
        if data.startswith(signature):
            return media_type
    return "application/octet-stream"


def content_disposition(filename: str) -> str:
    """A download under this file name (RFC 6266): an ASCII fallback, and the name itself as
    UTF-8 (RFC 5987) when it is not plain ASCII."""
    name = "".join(" " if ord(c) < 32 or c in '/\\"' else c for c in filename).strip() or "file"
    fallback = "".join(c if 32 <= ord(c) < 127 else "_" for c in name)
    value = f'attachment; filename="{fallback}"'
    if fallback != name:
        value += f"; filename*=UTF-8''{urllib.parse.quote(name, safe='')}"
    return value
