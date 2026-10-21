"""MailFilters and the terms of q as SQL conditions on mail, the list order and keyset cursors.

The list, its summary, the neighbours of a mail and the CSV export all build on these, so they
agree on which mails match and in which order (D19 to D21). Conditions are plain columns of mail
or EXISTS subqueries correlated to it: participants through participation and person (both
indexed for this), flags through mail_note, documents through attachment. The full text words
match the mail's own text or the text of one of its attachments' documents (D73): both GIN
indexes give mail ids, which PostgreSQL ORs as bitmaps (full_text); first_ids's walk tests the
mails it passes one by one instead, as it did for the mail's own text alone.

The order is MAIL_SORT_KEY (mails without a date as the oldest), then id; ix_mail_sort serves it
in both directions, and keyset conditions compare the same pair. A cursor names the boundary
mail by date_utc and id; a missing date stays NULL in the cursor and becomes -infinity in SQL.

first_ids finds the first mails of a filtered list. PostgreSQL alone would pick either walking
ix_mail_sort until enough mails match, or collecting every match and sorting it, by an estimate
that assumes matches are spread evenly over the order. Matches cluster (an old project's name,
one person's mails), and a walk past most of the archive takes a second at 400,000 mails. So the
walk is bounded to WALK_ROWS mails, and when that is not enough every match is collected. Date
bounds and a single DKIM status narrow the walk itself (see _ranges).
"""

import base64
import binascii
import json
import weakref
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import (
    BigInteger,
    BinaryExpression,
    ColumnElement,
    Select,
    UnaryExpression,
    and_,
    any_,
    exists,
    false,
    func,
    literal,
    literal_column,
    or_,
    select,
    true,
    tuple_,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute, aliased
from sqlalchemy.sql.util import ClauseAdapter

from mailrobbe.api.query import parse_day
from mailrobbe.api.schemas import MailFilters, PersonRole, QueryTerm, SortOrder
from mailrobbe.db.models import (
    MAIL_SORT_KEY,
    TEXT_SEARCH_CONFIG,
    TIMESTAMPTZ,
    Attachment,
    Document,
    Mail,
    MailNote,
    Participation,
    Person,
)
from mailrobbe.enums import DkimStatus, ParticipationRole

_sort_key: ColumnElement[datetime] = literal_column(MAIL_SORT_KEY, TIMESTAMPTZ)
_NO_DATE = literal_column("'-infinity'::timestamp with time zone", TIMESTAMPTZ)
_TEXT_SEARCH: ColumnElement[Any] = literal_column(f"'{TEXT_SEARCH_CONFIG}'::regconfig")
# The table column itself, so that _ranges recognises conditions on it.
_DKIM_STATUS: ColumnElement[DkimStatus | None] = Mail.__table__.c.dkim_status
_SENDER = (ParticipationRole.FROM,)
_RECIPIENTS = (ParticipationRole.TO, ParticipationRole.CC, ParticipationRole.BCC)
# Mails of the order a filtered page looks at before collecting all matches instead: a filter
# matching one mail in 100 fills a page of 50 within them.
WALK_ROWS = 5000
# Conditions with a form of their own for the walk (full_text): the walk passes them mail by
# mail. Keyed by the condition object, gone with it.
_WALK_FORMS: "weakref.WeakKeyDictionary[ColumnElement[bool], ColumnElement[bool]]" = (
    weakref.WeakKeyDictionary()
)


class FilterError(ValueError):
    """A filter parameter that cannot be used (400 invalid_filter)."""


class CursorError(ValueError):
    """A cursor this API did not issue, or one for another sort order (400 invalid_cursor)."""


def internal_domains(setting: str) -> list[str]:
    """The owner's domains from MAILROBBE_INTERNAL_DOMAINS: comma-separated, any case."""
    return [domain for part in setting.split(",") if (domain := part.strip().lower())]


def mail_conditions(
    filters: MailFilters, terms: Sequence[QueryTerm], internal: Sequence[str]
) -> list[ColumnElement[bool]]:
    """Every condition of the filters and of q's terms; a mail matches when all hold."""
    where = [condition for term in terms for condition in _term(term)]
    query = text_query(terms)
    if query is not None:
        where.append(full_text(query))
    if filters.dkim:
        where.append(_dkim(filters.dkim))
    if filters.sender_domain:
        domains = sorted({domain.strip().lower() for domain in filters.sender_domain})
        where.append(_takes_part(_SENDER, Person.domain.in_(domains)))
    if filters.date_from:
        where.append(_sort_key >= _midnight(filters.date_from))
    if filters.date_to:
        where += _before(filters.date_to + timedelta(days=1))
    if filters.has_attachment:
        where.append(Mail.has_attachments.is_(True))
    if filters.in_thread:
        where.append(Mail.thread_id.is_not(None))
    if filters.hide_duplicates:
        where.append(Mail.is_duplicate_of.is_(None))
    if filters.flagged:
        where.append(exists().where(MailNote.mail_id == Mail.id, MailNote.flagged.is_(True)))
    if filters.mbox_file is not None:
        where.append(Mail.mbox_file_id == filters.mbox_file)
    where += [_takes_part(None, _person(person_id)) for person_id in filters.person]
    if filters.person_role is not None:
        where += _person_role(filters.person, filters.person_role)
    if filters.between:
        where.append(_between(filters.between))
    if filters.external:
        where.append(_external(internal))
    if filters.document is not None:
        where.append(_carries(filters.document))
    return where


def text_query(terms: Sequence[QueryTerm]) -> ColumnElement[Any] | None:
    """The tsquery of q's full text words; None without any."""
    words = [_phrase(term) for term in terms if term.key == "text"]
    if not words:
        return None
    return func.websearch_to_tsquery(_TEXT_SEARCH, " ".join(words))


def full_text(query: ColumnElement[Any]) -> ColumnElement[bool]:
    """D73: the mail's own text matches, or the text of one of its attachments' documents.

    For a set of mails (counts, CSV, all matches of a rare word) each side uses its GIN index:
    the mails' own ids and those of the matching documents' mails (one array, computed once) are
    ORed as bitmaps. A UNION of the two id sets would make PostgreSQL join it back to mail, and
    an EXISTS in the OR would make it scan every mail. first_ids's walk takes the second form,
    which looks at one mail's attachments at a time and so never collects every matching
    document of a common word.
    """
    own = Mail.tsv.bool_op("@@")(query)
    documents = (
        select(Attachment.mail_id)
        .join(Document, Document.id == Attachment.document_id)
        .where(Document.tsv.bool_op("@@")(query))
    )
    found = or_(own, Mail.id == any_(func.array(documents.scalar_subquery())))
    attached = (
        select(true())
        .select_from(Attachment)
        .join(Document, Document.id == Attachment.document_id)
        .where(Attachment.mail_id == Mail.id, Document.tsv.bool_op("@@")(query))
        .limit(1)
        .scalar_subquery()  # correlated and scalar: run per mail, never hashed in full
    )
    # has_attachments is true exactly for mails with attachment rows (importer.model)
    _WALK_FORMS[found] = or_(own, and_(Mail.has_attachments, func.coalesce(attached, false())))
    return found


def _carries(document_id: int) -> ColumnElement[bool]:
    """One of the mail's attachments is this document (D75)."""
    return exists().where(Attachment.mail_id == Mail.id, Attachment.document_id == document_id)


def _term(term: QueryTerm) -> list[ColumnElement[bool]]:
    value = term.value
    match term.key:
        case "from" | "to" | "cc":
            pattern = _contains(value)
            person = or_(Person.canonical_email.ilike(pattern), Person.display_name.ilike(pattern))
            return [_takes_part((ParticipationRole(term.key),), person)]
        case "domain":
            domain = value.lower().lstrip("@")
            return [_takes_part(None, _in_domains(Person.domain, [domain]))]
        case "subject":
            return [Mail.subject.ilike(_contains(value))]
        case "has":
            return [Mail.has_attachments.is_(True)]
        case "dkim":
            return [_dkim([value])]
        case "after":
            return [_sort_key >= _midnight(_day(value))]
        case "before":
            return _before(_day(value))
        case "message_id":
            return [Mail.message_id == value]
    return []  # text: one tsquery for all words, built by the caller


def _phrase(term: QueryTerm) -> str:
    """A text term for websearch_to_tsquery: quoted tokens stay phrases."""
    return f'"{term.value}"' if '"' in term.raw else term.value


def _contains(value: str) -> str:
    """An ILIKE pattern for value anywhere; PostgreSQL's default LIKE escape is backslash."""
    return "%" + _escape_like(value) + "%"


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _day(value: str) -> date:
    day = parse_day(value)
    assert day is not None, "parse_query accepts only valid days"
    return day


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=UTC)


def _before(day: date) -> list[ColumnElement[bool]]:
    """Mails dated before the start of day (UTC); mails without a date (-infinity) never match."""
    return [_sort_key < _midnight(day), _sort_key > _NO_DATE]


def _dkim(keys: Sequence[str]) -> ColumnElement[bool]:
    """Any of these statuses; unchecked is NULL. Without unchecked, or with it alone, this is a
    comparison of the column (_ranges); PostgreSQL reads IN with one value as equality."""
    statuses = sorted({DkimStatus(key) for key in keys if key != "unchecked"})
    conditions = [_DKIM_STATUS.in_(statuses)] if statuses else []
    if "unchecked" in keys:
        conditions.append(_DKIM_STATUS.is_(None))
    return conditions[0] if len(conditions) == 1 else or_(false(), *conditions)


def _takes_part(
    roles: Sequence[ParticipationRole] | None, person: ColumnElement[bool]
) -> ColumnElement[bool]:
    """A person matching `person` takes part in the mail in one of roles (None: any role)."""
    condition = exists().where(
        Participation.mail_id == Mail.id, Person.id == Participation.person_id, person
    )
    if roles is not None:
        condition = condition.where(Participation.role.in_(roles))
    return condition


def _person(person_id: int) -> ColumnElement[bool]:
    """The person and the addresses merged into it (milestone 5 sets merged_into)."""
    return or_(Person.id == person_id, Person.merged_into == person_id)


def _in_domains(column: QueryableAttribute[str], domains: Sequence[str]) -> ColumnElement[bool]:
    """The domain in column is one of domains or a subdomain of one."""
    return or_(
        false(),
        *(or_(column == domain, column.like("%." + _escape_like(domain))) for domain in domains),
    )


def _person_role(persons: Sequence[int], role: PersonRole) -> list[ColumnElement[bool]]:
    """D32: sent = the person (any of its addresses) is From; received = it is To, Cc or Bcc and
    not From; cc = it is Cc and neither From, To nor Bcc."""
    if len(persons) != 1:
        raise FilterError(f"person_role needs exactly one person id, not {len(persons)}")
    person = _person(persons[0])
    match role:
        case "sent":
            return [_takes_part(_SENDER, person)]
        case "received":
            return [_takes_part(_RECIPIENTS, person), ~_takes_part(_SENDER, person)]
    others = (ParticipationRole.FROM, ParticipationRole.TO, ParticipationRole.BCC)
    return [_takes_part((ParticipationRole.CC,), person), ~_takes_part(others, person)]


def _between(persons: Sequence[int]) -> ColumnElement[bool]:
    """One of the two persons sent the mail, the other received it (To, Cc or Bcc)."""
    if len(persons) != 2:
        raise FilterError(f"between takes exactly two person ids, not {len(persons)}")
    first, second = (_person(person_id) for person_id in persons)
    return or_(
        and_(_takes_part(_SENDER, first), _takes_part(_RECIPIENTS, second)),
        and_(_takes_part(_SENDER, second), _takes_part(_RECIPIENTS, first)),
    )


def _external(internal: Sequence[str]) -> ColumnElement[bool]:
    """D21: an internal sender and an external recipient, or the other way round.

    One EXISTS over sender and recipient pairs, which PostgreSQL can check mail by mail along
    the list order; an OR of EXISTS would make it collect all participations first.
    """
    if not internal:
        raise FilterError("external needs MAILROBBE_INTERNAL_DOMAINS")
    sender_link, sender = aliased(Participation), aliased(Person)
    recipient_link, recipient = aliased(Participation), aliased(Person)
    return exists().where(
        sender_link.mail_id == Mail.id,
        sender_link.role == ParticipationRole.FROM,
        sender.id == sender_link.person_id,
        recipient_link.mail_id == Mail.id,
        recipient_link.role.in_(_RECIPIENTS),
        recipient.id == recipient_link.person_id,
        _in_domains(sender.domain, internal) != _in_domains(recipient.domain, internal),
    )


# Order and keyset ----------------------------------------------------------------------------


def _descending(sort: SortOrder, reverse: bool) -> bool:
    return (sort == "date_desc") != reverse


def order(sort: SortOrder, reverse: bool = False) -> list[UnaryExpression[Any]]:
    """ORDER BY for the list in this sort order; reverse walks it from the other end."""
    if _descending(sort, reverse):
        return [_sort_key.desc(), Mail.id.desc()]
    return [_sort_key.asc(), Mail.id.asc()]


def beyond(
    sort: SortOrder, date_utc: datetime | None, mail_id: int, reverse: bool = False
) -> ColumnElement[bool]:
    """Mails after the mail (date_utc, mail_id) in the list order; before it with reverse."""
    date_key = func.coalesce(literal(date_utc, TIMESTAMPTZ), _NO_DATE)
    boundary = tuple_(date_key, literal(mail_id, BigInteger))
    if _descending(sort, reverse):
        return tuple_(_sort_key, Mail.id) < boundary
    return tuple_(_sort_key, Mail.id) > boundary


async def first_ids(
    session: AsyncSession,
    where: Sequence[ColumnElement[bool]],
    sort: SortOrder,
    limit: int,
    *,
    after: tuple[datetime | None, int] | None = None,
    reverse: bool = False,
) -> list[int]:
    """Ids of the first `limit` matching mails in list order (from its end with reverse),
    after the mail `after` (date_utc, id) when given."""
    start = [] if after is None else [beyond(sort, *after, reverse=reverse)]
    if not where:
        plain = select(Mail.id).where(*start).order_by(*order(sort, reverse)).limit(limit)
        return list(await session.scalars(plain))
    # The walk: the next WALK_ROWS mails in order within the ranges, the other conditions moved
    # onto them. Its LIMIT lets PostgreSQL test participants mail by mail (a nested loop semi
    # join) instead of hashing every participation of, say, the owner's domain first. Unused
    # columns of the window are dropped by PostgreSQL.
    ranges = [condition for condition in where if _ranges(condition)]
    window = (
        select(*Mail.__table__.c, _sort_key.label("key"))
        .where(*start, *ranges)
        .order_by(*order(sort, reverse))
        .limit(WALK_ROWS)
        .subquery("walk")
    )
    on_window = ClauseAdapter(window).traverse
    rest = [
        on_window(_WALK_FORMS.get(condition, condition))
        for condition in where
        if not _ranges(condition)
    ]
    walked = list(await session.scalars(_ordered(window, sort, reverse, limit).where(*rest)))
    if len(walked) == limit:
        return walked
    # Too few matches near the start: collect every match, then sort. MATERIALIZED keeps
    # PostgreSQL from turning this back into an unbounded walk.
    matched = (
        select(Mail.id, _sort_key.label("key"))
        .where(*start, *where)
        .cte("matched")
        .prefix_with("MATERIALIZED")
    )
    return list(await session.scalars(_ordered(matched, sort, reverse, limit)))


def _ranges(condition: ColumnElement[bool]) -> bool:
    """A condition the walk's window takes: a date bound, a range of the order (ix_mail_sort)
    that the walk starts at, or one DKIM status, a range of an index on (dkim_status, sort
    key, id) where one exists. Without such an index PostgreSQL filters the window instead."""
    return isinstance(condition, BinaryExpression) and (
        condition.left is _sort_key or condition.left is _DKIM_STATUS
    )


def _ordered(rows: Any, sort: SortOrder, reverse: bool, limit: int) -> Select[int]:
    """The first ids of rows (with columns id and key) in list order."""
    key, mail_id = rows.c.key, rows.c.id
    by = [key.desc(), mail_id.desc()] if _descending(sort, reverse) else [key.asc(), mail_id.asc()]
    return select(mail_id).order_by(*by).limit(limit)


@dataclass(frozen=True, slots=True)
class Cursor:
    """A position in the list: just after (or with before, just before) the boundary mail."""

    sort: SortOrder
    before: bool  # prev_cursor: the page that ends before the boundary mail
    date_utc: datetime | None  # of the boundary mail; None sorts as the oldest
    mail_id: int

    def encode(self) -> str:
        data = {
            "s": self.sort,
            "b": self.before,
            "d": None if self.date_utc is None else self.date_utc.isoformat(),
            "i": self.mail_id,
        }
        raw = json.dumps(data, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    def flipped(self) -> "Cursor":
        """The same position, looking the other way."""
        return Cursor(self.sort, not self.before, self.date_utc, self.mail_id)

    @classmethod
    def decode(cls, token: str, sort: SortOrder) -> "Cursor":
        try:
            data = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
            stamp, mail_id, before = data["d"], data["i"], data["b"]
            date_utc = None if stamp is None else datetime.fromisoformat(stamp)
        except (binascii.Error, ValueError, TypeError, KeyError) as error:
            raise CursorError("malformed cursor") from error
        if not (type(mail_id) is int and type(before) is bool):
            raise CursorError("malformed cursor")
        if date_utc is not None and date_utc.tzinfo is None:
            raise CursorError("malformed cursor")
        if data.get("s") != sort:
            raise CursorError(f"cursor for another sort order than {sort}")
        return cls(sort, before, date_utc, mail_id)
