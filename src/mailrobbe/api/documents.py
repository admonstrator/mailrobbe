"""Attachments and documents (milestone 9, D70 to D76): the document list, its figures, a
document's page and text, and attachment downloads. Endpoints and models are in schemas.py.

Routes: GET /api/documents, /api/documents/summary, /api/documents/metadata-values,
/api/documents/{id}, /api/documents/{id}/text, /api/attachments/{id}/content,
/api/mails/{id}/hits.

The list reads document rows only, apart from the conditions on the mails carrying a document
(date, person, external), which hold when one carrying mail that is no duplicate meets them all:
one EXISTS over attachment and mail with the mail list's own conditions (filters.mail_conditions,
D21, D32). It pages by keyset as the person list does (D19, D31): a cursor names the sort key of
its boundary row and is bound to the sort order; ties go by id in the direction of the sort, so
each sort walks its index (ix_document_first_date, ix_document_mails, ix_document_size_bytes).
With conditions on mails and no search words the walk is bounded as the mail list's
(filters.first_ids): the next WALK_ROWS documents in order, then, when they hold too few matches,
every match sorted; matches cluster (one year's documents, one person's), and PostgreSQL's
estimate assumes they do not. A jump to a page by number (D193, api/paging.py) reads by OFFSET;
without conditions on mails, the test that remains (a carrier that is no duplicate and not
hidden, D222) becomes the list of the few documents failing it (_by_id), so that counting and a
page far into the list read document alone; within the first WALK_ROWS rows it is tested one
document at a time, as the walk does.

A snippet is found in PostgreSQL, so that only its surroundings leave the database: the search
words as typed become one regular expression, any case written out as character classes (the
database's locale may know only ASCII case), which regexp_instr finds in the stored text.

The hits of one mail (D79, D176) say where the words the mail list counts occur, in the places
it searched: the subject, the mail's own text, and per attachment its document's text and file
names, with the list's counts (hits.mail_places). An attachment whose text holds one shows the
snippet of the list, or around another form of a word where none occurs as typed. The browser
marks the words as typed and the words the stems of the query begin, the forms German stemming
finds; with whole words (D173) the words as written alone, and the snippet is found around them.

What a file says about itself (D167) was read by the import's metadata step: the document page
shows every field found, the list filters by the summary's author and program (exact values,
their partial indexes) and counts the most frequent of them; a search within those values
(metadata-values) finds the others. They are not part of q: the full text index is computed
from the text and the file names, and the names and versions of authors and programs are
found as typed rather than as German stems.

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
from itertools import chain
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
    all_,
    any_,
    cast,
    exists,
    false,
    func,
    literal,
    literal_column,
    or_,
    select,
    text,
    true,
    union,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.util import ClauseAdapter

from mailrobbe.api import paging
from mailrobbe.api.deps import AppSettings, Session, api_error
from mailrobbe.api.detail import MailId, mail_senders
from mailrobbe.api.filters import (
    WALK_ROWS,
    FilterError,
    _contains,
    internal_domains,
    mail_conditions,
)
from mailrobbe.api.fulltext import (
    Words,
    full_text_search,
    ts_query,
    word_regex,
    word_regex_python,
)
from mailrobbe.api.hits import mail_places
from mailrobbe.api.mails import (
    _QUERY_CANCELED,
    BY_ID_LIMIT,
    _count_budget,
    _unless_canceled,
)
from mailrobbe.api.persons import _beyond, _by, _Cursor, _int, _stamp
from mailrobbe.api.query import QueryError, parse_query
from mailrobbe.api.schemas import (
    COUNT_LIMIT,
    DOCUMENT_NAMES_LIMIT,
    DOCUMENT_PERSONS_LIMIT,
    METADATA_VALUES_LIMIT,
    SNIPPET_LENGTH,
    AttachmentHit,
    DocumentDetail,
    DocumentFilters,
    DocumentListItem,
    DocumentListParams,
    DocumentMetadata,
    DocumentNameCount,
    DocumentPage,
    DocumentSort,
    DocumentSummary,
    DocumentText,
    MailFilters,
    MailHits,
    MailHitsParams,
    MetadataSummary,
    MetadataValueCount,
    MetadataValueParams,
    MetadataValues,
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
    MailHidden,
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
    filters: DocumentFilters, internal: Sequence[str], *, walk: bool = False, carried: bool = True
) -> list[ColumnElement[bool]]:
    """Every condition of the filters (D74) on document; FilterError for an unusable one.

    The conditions on mails become one test of the carrying mails (_carried); carried False
    leaves it out, for a jump that tests it by the document's id instead (_by_id).
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
    if filters.author:
        where.append(Document.metadata_author.in_(sorted(set(filters.author))))
    if filters.program:
        where.append(Document.metadata_program.in_(sorted(set(filters.program))))
    mail_filters = MailFilters(
        date_from=filters.date_from,
        date_to=filters.date_to,
        person=[] if filters.person is None else [filters.person],
        person_role=filters.person_role,
        external=filters.external,
    )
    on_mail = mail_conditions(mail_filters, (), internal)
    if on_mail and carried:
        where.append(_carried(on_mail, walk=walk))
    return where


def _carried(on_mail: Sequence[ColumnElement[bool]], *, walk: bool = False) -> ColumnElement[bool]:
    """One carrying mail that is no duplicate meets every condition of on_mail: an EXISTS, which
    PostgreSQL may turn into a join over every carrying mail; with walk, a subquery it runs for
    one document at a time instead, for the bounded walk of _first_ids."""
    carrying = (
        Attachment.document_id == Document.id,
        Mail.id == Attachment.mail_id,
        Mail.is_duplicate_of.is_(None),
        *on_mail,
    )
    if not walk:
        return exists().where(*carrying)
    one = select(true()).select_from(Attachment, Mail).where(*carrying).limit(1)
    return func.coalesce(one.scalar_subquery(), false())  # scalar: never hashed in full


def _where(
    filters: DocumentFilters, internal_setting: str, *, walk: bool = False, carried: bool = True
) -> list[ColumnElement[bool]]:
    try:
        internal = internal_domains(internal_setting)
        return document_conditions(filters, internal, walk=walk, carried=carried)
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
    item = select(*_ITEM_COLUMNS, kept.label("key"))
    # With search words the GIN index narrows first: no walk, which would test every text.
    walk = None if params.q.strip() else _where(params, settings.internal_domains, walk=True)

    async def read(
        offset: int, limit: int, reverse: bool, start: Sequence[ColumnElement[bool]] = ()
    ) -> list[Any]:
        """limit rows after the first offset ones beyond start, in list order or reversed."""
        down = descending != reverse
        if not _on_mails(params):
            statement = item.where(*where, *start).order_by(*_by(columns, down))
            return list(await session.execute(statement.offset(offset).limit(limit)))
        ids = await _first_ids(session, where, walk, start, key, down, limit, offset)
        found = await session.execute(
            item.where(Document.id == any_(literal(ids, ARRAY(BigInteger))))
        )
        by_id = {row.id: row for row in found}
        return [by_id[document_id] for document_id in ids]

    jumped = None
    if paging.wanted(params.page, params.last):  # D193
        if cursor is not None:
            raise api_error(400, "invalid_cursor", "a cursor and a page to jump to")
        if not _on_mails(params):  # the where that read and the count below see
            far = (params.page or 1) * params.limit >= WALK_ROWS
            # With search words every match is tested before the sort, near the start too.
            plain = await _by_id(session) if (far or walk is None) and not params.last else None
            if plain is not None:
                where = [*_where(params, settings.internal_domains, carried=False), *plain]
            elif walk is not None:  # one document at a time: no join of every carrying mail
                where = list(walk)
        count = select(func.count()).select_from(Document).where(*where)
        jumped = await paging.jump(
            session, settings, read, count, page=params.page, last=params.last, limit=params.limit
        )
        rows = jumped.rows
    else:
        reverse = cursor is not None and cursor.before
        start = []
        if cursor is not None:
            boundary = [_boundary(params.sort, cursor.key[0]), literal(cursor.key[1], BigInteger)]
            start.append(_beyond(columns, boundary, descending != reverse))
        rows = await read(0, params.limit + 1, reverse, start)
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
    if jumped is not None:
        prev_cursor = at(rows[0], True) if jumped.before and rows else None
        next_cursor = at(rows[-1], False) if jumped.after and rows else None
    elif cursor is None:
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
        page=jumped.page if jumped is not None else 1 if cursor is None else None,
    )
    await attach_labels(session, page)
    return page


def _on_mails(filters: DocumentFilters) -> bool:
    """Conditions on the carrying mails apply beyond the hidden mails (D222)."""
    on_mails = (filters.date_from, filters.date_to, filters.person)
    return filters.external or any(value is not None for value in on_mails)


async def _by_id(session: AsyncSession) -> list[ColumnElement[bool]] | None:
    """The test of the carrying mails a list without conditions on them still has (a carrier
    that is no duplicate and not hidden) as a test of the document's id, as mails._by_id does
    for the mail list: only a document that a duplicate or a hidden mail carries, or none, can
    fail it, so those are tested one by one and the failing ones listed. Counting then reads
    document alone and a page far into the list is a sort of it, where PostgreSQL would join
    every carrying mail. None for more than BY_ID_LIMIT failing documents."""
    touched = union(
        select(Mail.id).where(Mail.is_duplicate_of.is_not(None)), select(MailHidden.mail_id)
    )
    carrying = select(Attachment.document_id).where(Attachment.mail_id.in_(touched))
    # A document whose mails were all deleted (a replaced file, D14) lost its first mail with
    # them (ON DELETE SET NULL) and lasts until finalize deletes it (attachments.documents).
    candidates = (
        select(Document.id)
        .where(or_(Document.id.in_(carrying), Document.first_mail_id.is_(None)))
        .cte("candidates")
        .prefix_with("MATERIALIZED")  # so that the test below runs for them alone
    )
    carried = _carried(mail_conditions(MailFilters(), (), ()), walk=True)
    failing = select(candidates.c.id).where(~ClauseAdapter(candidates).traverse(carried))
    ids = list(await session.scalars(failing.limit(BY_ID_LIMIT + 1)))
    if len(ids) > BY_ID_LIMIT:
        return None
    if not ids:
        return []
    await paging.custom_plans(session)
    return [Document.id != all_(literal(sorted(ids), ARRAY(BigInteger)))]


async def _first_ids(
    session: AsyncSession,
    where: Sequence[ColumnElement[bool]],
    walk: Sequence[ColumnElement[bool]] | None,
    start: Sequence[ColumnElement[bool]],
    key: SQLColumnExpression[Any],
    descending: bool,
    limit: int,
    offset: int = 0,
) -> list[int]:
    """Ids of the first `limit` documents matching where in list order after the first
    `offset` ones: among the next WALK_ROWS documents (tested with walk, the same conditions one
    document at a time), else among every match (filters.first_ids does the same for mails).
    walk None: every match."""
    if walk is not None and offset + limit <= WALK_ROWS:
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
            .offset(offset)
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
    return list(await session.scalars(ordered.offset(offset).limit(limit)))


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


async def _snippets(
    session: AsyncSession,
    pattern: str,
    ids: Sequence[int],
    compiled: re.Pattern[str] | None = None,
) -> dict[int, str]:
    """Per document, the stored text around the first place the pattern matches; compiled is
    the pattern for Python where its syntax differs (whole words)."""
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
    compiled = compiled or re.compile(pattern)
    found = {}
    for document_id, around, offset in rows:
        snippet = snippet_around(around, offset, compiled)
        if snippet is not None:
            found[document_id] = snippet
    return found


# Hits in one mail -----------------------------------------------------------------------------


@router.get("/mails/{mail_id}/hits")
async def mail_hits(
    mail_id: MailId, params: Annotated[MailHitsParams, Query()], session: Session
) -> MailHits:
    try:
        terms = parse_query(params.q)
    except QueryError as error:
        raise api_error(400, "invalid_query", str(error)) from error
    search = full_text_search(terms, params.scope, params.whole_word, body_part=params.body_part)
    counted = () if search is None else search.counted
    # the lexemes of each counted words, in the order its query has them
    queries = [cast(ts_query(words.websearch()), Text) for words, _ in counted]
    found = (await session.execute(select(Mail.id, *queries).where(Mail.id == mail_id))).first()
    if found is None:
        raise api_error(404, "not_found", f"no mail with id {mail_id}")
    if search is None:
        return MailHits(
            words=[], stems=[], in_mail=False, attachments=[], whole_word=params.whole_word
        )
    counts, attached = await mail_places(session, mail_id, search)
    stems = {
        words: [lexeme.replace("''", "'") for lexeme in _LEXEME.findall(text)]
        for (words, _), text in zip(counted, found[1:], strict=True)
    }
    attachments = select(Attachment.id, Attachment.document_id).where(Attachment.mail_id == mail_id)
    documents = {
        attachment: document
        for attachment, document in await session.execute(attachments)
        if document is not None
    }
    texts = [documents[attachment] for attachment, hit in attached.items() if hit.attachment]
    in_texts = [words for words, fields in counted if "attachment" in fields]
    snippets = await _hit_snippets(session, search.whole_word, in_texts, stems, texts)
    return MailHits(
        words=_typed([words for words, _ in counted]),
        stems=[] if search.whole_word else list(dict.fromkeys(chain(*stems.values()))),
        in_mail=counts.subject + counts.body > 0,
        attachments=[
            AttachmentHit(
                attachment_id=attachment,
                in_name=hit.filename > 0,
                in_text=hit.attachment > 0,
                snippet=snippets.get(documents[attachment]) if hit.attachment else None,
            )
            for attachment, hit in sorted(attached.items())
            if hit.filename or hit.attachment
        ],
        whole_word=search.whole_word,
        in_subject=counts.subject > 0,
        in_body=counts.body > 0,
        counts=counts,
    )


def _typed(counted: Sequence[Words]) -> list[str]:
    """The counted words as typed, as search_words reads them from q."""
    return search_words(" ".join(words.websearch() for words in counted))


async def _hit_snippets(
    session: AsyncSession,
    whole_word: bool,
    counted: Sequence[Words],
    stems: dict[Words, list[str]],
    ids: Sequence[int],
) -> dict[int, str]:
    """Per document, the text around the first place one of the counted words occurs (D79):
    as written with whole words (D173), otherwise as typed or as a word one of their stems
    begins, the place the browser marks either way."""
    if whole_word:
        pattern = "|".join(f"(?:{word_regex(words)})" for words in counted)
        python = "|".join(f"(?:{word_regex_python(words).pattern})" for words in counted)
        return await _snippets(session, f"(?i){pattern}", ids, re.compile(python, re.IGNORECASE))
    beginning = list(dict.fromkeys(chain(*(stems[words] for words in counted))))
    pattern = "|".join(filter(None, [literal_pattern(_typed(counted)), stem_pattern(beginning)]))
    return await _snippets(session, pattern, ids)


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
            total=sum(statuses.values()),
            exact=True,
            kinds=kinds,
            text_status=statuses,
            authors=await _metadata_values(session, where, Document.metadata_author),
            programs=await _metadata_values(session, where, Document.metadata_program),
        )
    bounded = select(Document.id).where(*where).limit(COUNT_LIMIT + 1).subquery()
    row = await _unless_canceled(session, select(func.count()).select_from(bounded))
    total = None if row is None else min(row[0], COUNT_LIMIT)
    exact = row is not None and row[0] <= COUNT_LIMIT
    return DocumentSummary(total=total, exact=exact, kinds=None, text_status=None)


@router.get("/documents/metadata-values")
async def metadata_values(
    params: Annotated[MetadataValueParams, Query()], session: Session, settings: AppSettings
) -> MetadataValues:
    where = _where(params, settings.internal_domains)
    column = Document.metadata_author if params.field == "author" else Document.metadata_program
    await _count_budget(session, settings)
    values = await _metadata_values(session, where, column, params.search, params.limit)
    return MetadataValues(values=values)


async def _metadata_values(
    session: AsyncSession,
    where: Sequence[ColumnElement[bool]],
    column: SQLColumnExpression[str | None],
    search: str = "",
    limit: int = METADATA_VALUES_LIMIT,
) -> list[MetadataValueCount] | None:
    """The values of a metadata column among the documents where holds, with their documents,
    most first (ties by value); None when the count budget ran out."""
    count = func.count().label("count")
    statement = select(column, count).where(*where, column.is_not(None))
    if search.strip():
        statement = statement.where(column.ilike(_contains(search.strip())))
    statement = statement.group_by(column).order_by(count.desc(), column.collate("C"))
    rows = await _all_unless_canceled(session, statement.limit(limit))
    if rows is None:
        return None
    return [MetadataValueCount(value=value, documents=documents) for value, documents in rows]


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
    Document.metadata_status,
    Document.metadata_error,
    Document.metadata_fields,
    Document.metadata_author,
    Document.metadata_modified_by,
    Document.metadata_program,
    Document.metadata_device,
    Document.metadata_created,
    Document.metadata_gps,
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
        metadata=_metadata(document),
    )
    await attach_labels(session, detail)
    return detail


def _metadata(document: Any) -> DocumentMetadata:
    fields = document.metadata_fields or {}
    return DocumentMetadata(
        status=document.metadata_status,
        error=document.metadata_error,
        fields=fields,
        summary=_summary(document) if fields else None,
    )


def _summary(row: Any) -> MetadataSummary:
    """The summary columns of a document row (D167) as the API names them."""
    return MetadataSummary(
        author=row.metadata_author,
        modified_by=row.metadata_modified_by,
        software=row.metadata_program,
        device=row.metadata_device,
        created=row.metadata_created,
        gps=row.metadata_gps,
    )


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
