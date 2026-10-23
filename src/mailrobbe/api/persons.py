"""Persons: the person list, profiles, contacts, mail counts, alias suggestions, merges and the
merge log (milestone 5, D28 to D33, D160 to D163). Endpoints and models are in schemas.py.

The verdicts of the alias check (D323) stand beside the suggestions: alias_check read through
the roots of its persons, the newest per pair; the view ai lists the open pairs judged one
person, also those no rule suggests. The check itself is an AI run (api/ai.py).

Static paths (/api/persons/suggestions, /api/persons/merge, /api/persons/merges, ...) are
registered before the ones with a person id.

Every id in a path may name an alias; it stands for its root (D28). Figures come from
person_stats, person_year and edge (SPEC 6.3); only the mail counts of a profile's aliases and
of /mail-counts read participation, through its index on person_id.

The lists page by keyset like the mail list (D19, D31): a cursor names the sort key of its
boundary row and is bound to the list it came from (sort order and q, or the person). Ties go by
id in the direction of the sort, so every keyset is one row comparison; the person list by mails
or by latest mail walks ix_person_stats_mails or ix_person_stats_last_date backwards.
"""

import asyncio
import base64
import binascii
import json
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any

import fastapi
from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Integer,
    Select,
    SQLColumnExpression,
    Subquery,
    Text,
    UnaryExpression,
    and_,
    any_,
    case,
    cast,
    distinct,
    false,
    func,
    literal,
    literal_column,
    or_,
    select,
    true,
    tuple_,
    union_all,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from mailrobbe import jobs
from mailrobbe.ai.model import alias_check_service
from mailrobbe.api import paging
from mailrobbe.api.deps import AppSettings, Editor, Session, api_error
from mailrobbe.api.filters import _contains, mail_conditions
from mailrobbe.api.mails import _count_budget, _unless_canceled
from mailrobbe.api.schemas import (
    DISPLAY_NAME_LIMIT,
    SUGGESTION_LIMIT,
    TOP_CONTACTS,
    AliasAddress,
    AliasCandidate,
    AliasCheckInfo,
    AliasCheckState,
    AliasSuggestion,
    CertainMergePlan,
    CertainMergeResult,
    Contact,
    ContactListParams,
    ContactPage,
    DisplayNameCount,
    MailFilters,
    MergeBatchInfo,
    MergeLogEntry,
    MergeLogPage,
    MergeLogParams,
    MergeRequest,
    MergeUndoResult,
    PersonFigures,
    PersonLabelUpdate,
    PersonListParams,
    PersonMailCountParams,
    PersonMailCounts,
    PersonPage,
    PersonProfile,
    PersonRef,
    PersonSort,
    PersonSummary,
    SuggestionCounts,
    SuggestionDismiss,
    SuggestionListParams,
    SuggestionPage,
    YearActivity,
)
from mailrobbe.config import Settings
from mailrobbe.db.models import (
    LAST_DATE_SORT_KEY,
    TIMESTAMPTZ,
    AliasCheck,
    AliasDismissal,
    Edge,
    GlobalStats,
    Mail,
    MergeBatch,
    Participation,
    Person,
    PersonEmail,
    PersonMerge,
    PersonMergeMember,
    PersonStats,
    PersonYear,
    alias_tier_enum,
)
from mailrobbe.db.models import AliasSuggestion as SuggestionRow
from mailrobbe.enums import AliasTier, AliasVerdict, JobKind, ParticipationRole
from mailrobbe.persons.labels import (
    address_labels,
    attach_labels,
    labelled_roots,
    set_label,
    shown_labels,
)
from mailrobbe.persons.merge import (
    MergeError,
    MergePlan,
    MergeUndone,
    UnknownMerge,
    UnknownPerson,
    certain_groups,
    merge_certain,
    merge_persons,
    undo_batch,
    undo_merge,
    unmerge_person,
)
from mailrobbe.persons.merge import dismiss_suggestion as dismiss_pair
from mailrobbe.persons.roots import member_ids, resolve_root
from mailrobbe.persons.suggestions import RULES as SUGGESTION_RULES
from mailrobbe.persons.suggestions import STATS_KEY as SUGGESTIONS_KEY
from mailrobbe.persons.suggestions import SuggestionReason, reason

router = APIRouter(prefix="/api", tags=["persons"])

# person.id is a bigint: a larger number is a validation error, not a database error.
PersonId = Annotated[int, fastapi.Path(ge=-(2**63), le=2**63 - 1)]
RowId = PersonId  # of a merge or a batch of merges, bigints too

_ALIAS = aliased(Person)
_ALIAS_COUNT = (
    select(func.count()).where(_ALIAS.merged_into == Person.id).scalar_subquery().label("aliases")
)
_FIGURES = (
    PersonStats.mails,
    PersonStats.sent,
    PersonStats.received,
    PersonStats.cc_only,
    PersonStats.contacts,
    PersonStats.first_date,
    PersonStats.last_date,
    PersonStats.dkim_pass_ratio,
)
_LAST_DATE: ColumnElement[datetime] = literal_column(LAST_DATE_SORT_KEY, TIMESTAMPTZ)
_NO_DATE = literal_column("'-infinity'::timestamp with time zone", TIMESTAMPTZ)
_NAME_KEY = func.lower(func.coalesce(Person.display_name, Person.canonical_email))
# The duplicates (D16), few and found through their partial index: leaving them out by id spares
# reading every mail of a person.
_DUPLICATES = select(Mail.id).where(Mail.is_duplicate_of.is_not(None))


# Cursors ---------------------------------------------------------------------------------------


def _int(value: Any) -> int:
    if type(value) is not int:
        raise TypeError("not an integer")
    return value


def _text(value: Any) -> str:
    if type(value) is not str:
        raise TypeError("not a string")
    return value


def _flag(value: Any) -> bool:
    if type(value) is not bool:
        raise TypeError("not a boolean")
    return value


def _stamp(value: Any) -> datetime | None:
    if value is None:
        return None
    stamp = datetime.fromisoformat(_text(value))
    if stamp.tzinfo is None:
        raise ValueError("no time zone")
    return stamp


@dataclass(frozen=True, slots=True)
class _Cursor:
    """Just after the boundary row whose sort key is `key` (with before: just before it);
    scope names the list it belongs to."""

    scope: str
    before: bool
    key: tuple[Any, ...]

    def encode(self) -> str:
        key = [value.isoformat() if isinstance(value, datetime) else value for value in self.key]
        raw = json.dumps({"s": self.scope, "b": self.before, "k": key}, separators=(",", ":"))
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")

    def flipped(self) -> "_Cursor":
        return _Cursor(self.scope, not self.before, self.key)

    @classmethod
    def decode(
        cls, token: str | None, scope: str, kinds: Sequence[Callable[[Any], Any]]
    ) -> "_Cursor | None":
        """The cursor in token (None without one); 400 invalid_cursor for a foreign one."""
        if token is None:
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
            found, before, key = data["s"], _flag(data["b"]), data["k"]
            if type(key) is not list or len(key) != len(kinds):
                raise ValueError("wrong sort key")
            values = tuple(kind(value) for kind, value in zip(kinds, key, strict=True))
        except (binascii.Error, ValueError, TypeError, KeyError) as error:
            raise api_error(400, "invalid_cursor", "malformed cursor") from error
        if found != scope:
            raise api_error(400, "invalid_cursor", "cursor for another list, sort order or q")
        return cls(scope, before, values)


def _beyond(
    columns: Sequence[SQLColumnExpression[Any]], values: Sequence[Any], descending: bool
) -> ColumnElement[bool]:
    """Rows after the boundary `values` in the order of columns, descending or ascending."""
    if descending:
        return tuple_(*columns) < tuple_(*values)
    return tuple_(*columns) > tuple_(*values)


def _by(
    columns: Sequence[SQLColumnExpression[Any]], descending: bool
) -> list[UnaryExpression[Any]]:
    return [column.desc() if descending else column.asc() for column in columns]


# Persons -------------------------------------------------------------------------------------


def _figures(row: Any) -> PersonFigures:
    return PersonFigures(
        mails=row.mails,
        sent=row.sent,
        received=row.received,
        cc_only=row.cc_only,
        contacts=row.contacts,
        first_date=row.first_date,
        last_date=row.last_date,
        dkim_pass_ratio=row.dkim_pass_ratio,
    )


async def _summaries(session: AsyncSession, ids: Sequence[int]) -> dict[int, PersonSummary]:
    """These persons as list entries; those without a person_stats row are left out."""
    if not ids:
        return {}
    rows = await session.execute(
        select(Person.id, Person.display_name, Person.canonical_email, Person.domain)
        .add_columns(_ALIAS_COUNT, *_FIGURES)
        .join(PersonStats, PersonStats.person_id == Person.id)
        .where(Person.id == any_(literal(list(ids), ARRAY(BigInteger))))
    )
    return {
        row.id: PersonSummary(
            id=row.id,
            name=row.display_name,
            email=row.canonical_email,
            domain=row.domain,
            aliases=row.aliases,
            figures=_figures(row),
        )
        for row in rows
    }


async def _root(session: AsyncSession, person_id: int) -> int:
    root = await resolve_root(session, person_id)
    if root is None:
        raise api_error(404, "not_found", f"no person with id {person_id}")
    return root


def _person_key(
    sort: PersonSort,
) -> tuple[SQLColumnExpression[Any], SQLColumnExpression[Any], bool]:
    """The sort key before the person id, the column a cursor keeps of it, and whether it
    descends. Recent keeps last_date itself, since its key is -infinity without one."""
    match sort:
        case "mails":
            return PersonStats.mails, PersonStats.mails, True
        case "recent":
            return _LAST_DATE, PersonStats.last_date, True
    return _NAME_KEY, _NAME_KEY, False


def _boundary(sort: PersonSort, value: Any) -> ColumnElement[Any]:
    match sort:
        case "mails":
            return literal(value, Integer)
        case "recent":
            return func.coalesce(literal(value, TIMESTAMPTZ), _NO_DATE)
    return literal(value, Text)


@router.get("/persons")
async def list_persons(
    params: Annotated[PersonListParams, Query()], session: Session, settings: AppSettings
) -> PersonPage:
    q = params.q.strip()
    scope = f"persons/{params.sort}/{q}" + ("/labelled" if params.labelled else "")
    kind = {"mails": _int, "recent": _stamp, "name": _text}[params.sort]
    cursor = _Cursor.decode(params.cursor, scope, (kind, _int))
    key, kept, descending = _person_key(params.sort)
    columns = [key, PersonStats.person_id]
    where = [Person.merged_into.is_(None)]
    if q:
        match = aliased(Person)
        pattern = _contains(q)
        matching = select(func.coalesce(match.merged_into, match.id)).where(
            or_(match.canonical_email.ilike(pattern), match.display_name.ilike(pattern))
        )
        where.append(Person.id.in_(union_all(matching, labelled_roots(pattern))))
    if params.labelled:
        where.append(Person.id.in_(labelled_roots()))
    listed: Select[int, Any] = (
        select(PersonStats.person_id, kept.label("key"))
        .select_from(PersonStats)
        .join(Person, Person.id == PersonStats.person_id)
        .where(*where)
    )
    total: int = (
        await session.scalar(
            select(func.count())
            .select_from(PersonStats)
            .join(Person, Person.id == PersonStats.person_id)
            .where(*where)
        )
    ) or 0
    jumped = None
    if paging.wanted(params.page, params.last):  # D193, from the nearer end of the total
        if cursor is not None:
            raise api_error(400, "invalid_cursor", "a cursor and a page to jump to")

        async def read(offset: int, limit: int, reverse: bool) -> list[Any]:
            ordered = listed.order_by(*_by(columns, descending != reverse))
            return list(await session.execute(ordered.offset(offset).limit(limit)))

        jumped = await paging.jump(
            session, settings, read, total, page=params.page, last=params.last, limit=params.limit
        )
        rows: list[Any] = jumped.rows
    else:
        reverse = cursor is not None and cursor.before
        start = []
        if cursor is not None:
            boundary = [_boundary(params.sort, cursor.key[0]), literal(cursor.key[1], BigInteger)]
            start.append(_beyond(columns, boundary, descending != reverse))
        rows = list(
            await session.execute(
                listed.where(*start)
                .order_by(*_by(columns, descending != reverse))
                .limit(params.limit + 1)
            )
        )
        more = len(rows) > params.limit
        del rows[params.limit :]
        if reverse:
            rows.reverse()
    summaries = await _summaries(session, [row.person_id for row in rows])

    def at(row: Any, before: bool) -> str:
        return _Cursor(scope, before, (row.key, row.person_id)).encode()

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
    page = PersonPage(
        items=[summaries[row.person_id] for row in rows],
        next_cursor=next_cursor,
        prev_cursor=prev_cursor,
        total=total,
        page=jumped.page if jumped is not None else 1 if cursor is None else None,
    )
    await attach_labels(session, page)
    return page


# Alias suggestions -----------------------------------------------------------------------------


def _ordered_suggestions() -> Subquery:
    """Every suggestion whose persons have figures, with `first` the one with more mails (the
    lower id on a tie) and the sort key: both reasons, the mails of first, first, second."""
    stats_a, stats_b = aliased(PersonStats), aliased(PersonStats)
    b_first = stats_b.mails > stats_a.mails
    return (
        select(
            case((b_first, SuggestionRow.person_b), else_=SuggestionRow.person_a).label("first"),
            case((b_first, SuggestionRow.person_a), else_=SuggestionRow.person_b).label("second"),
            SuggestionRow.same_name,
            SuggestionRow.same_local_part,
            SuggestionRow.tier,
            and_(
                SuggestionRow.same_name.is_not(None), SuggestionRow.same_local_part.is_not(None)
            ).label("both"),
            func.greatest(stats_a.mails, stats_b.mails).label("mails"),
        )
        .join(stats_a, stats_a.person_id == SuggestionRow.person_a)
        .join(stats_b, stats_b.person_id == SuggestionRow.person_b)
        .subquery("suggestions")
    )


def _root_pair(
    table: type[AliasCheck] | type[AliasDismissal],
) -> tuple[Select[Any], ColumnElement[int], ColumnElement[int]]:
    """The rows of a table of person pairs with the roots of both (D28), the smaller first:
    (select from the table and both persons, low, high); a pair within one root is left out."""
    a, b = aliased(Person), aliased(Person)
    root_a, root_b = func.coalesce(a.merged_into, a.id), func.coalesce(b.merged_into, b.id)
    joined = (
        select(table)
        .join(a, a.id == table.person_a)
        .join(b, b.id == table.person_b)
        .where(root_a != root_b)
    )
    return joined, func.least(root_a, root_b), func.greatest(root_a, root_b)


def _checks() -> Subquery:
    """The newest check of every pair of roots (D323): alias_check through the roots of its
    persons, like alias_dismissal; a pair within one root is left out."""
    joined, low, high = _root_pair(AliasCheck)
    return (
        joined.with_only_columns(low.label("person_a"), high.label("person_b"), AliasCheck.verdict)
        .distinct(low, high)
        .order_by(low, high, AliasCheck.created_at.desc())
        .subquery("checks")
    )


def _ai_suggestions() -> Subquery:
    """The open pairs the text model judged one person (D323), with the columns of
    _ordered_suggestions: the signs and tier of their suggestion, or none and uncertain for a
    pair only the alias check found. A dismissed pair is left out."""
    checks = _checks()
    joined, low, high = _root_pair(AliasDismissal)
    dismissed = (
        joined.with_only_columns(AliasDismissal.person_a)
        .where(low == checks.c.person_a, high == checks.c.person_b)
        .exists()
    )
    stats_a, stats_b = aliased(PersonStats), aliased(PersonStats)
    b_first = stats_b.mails > stats_a.mails
    return (
        select(
            case((b_first, checks.c.person_b), else_=checks.c.person_a).label("first"),
            case((b_first, checks.c.person_a), else_=checks.c.person_b).label("second"),
            SuggestionRow.same_name,
            SuggestionRow.same_local_part,
            func.coalesce(
                SuggestionRow.tier, literal(AliasTier.UNCERTAIN, type_=alias_tier_enum)
            ).label("tier"),
            func.coalesce(
                and_(
                    SuggestionRow.same_name.is_not(None),
                    SuggestionRow.same_local_part.is_not(None),
                ),
                false(),
            ).label("both"),
            func.greatest(stats_a.mails, stats_b.mails).label("mails"),
        )
        .select_from(checks)
        .join(stats_a, stats_a.person_id == checks.c.person_a)
        .join(stats_b, stats_b.person_id == checks.c.person_b)
        .outerjoin(
            SuggestionRow,
            and_(
                SuggestionRow.person_a == checks.c.person_a,
                SuggestionRow.person_b == checks.c.person_b,
            ),
        )
        .where(checks.c.verdict == AliasVerdict.SAME, ~dismissed)
        .subquery("suggestions")
    )


@router.get("/persons/suggestions")
async def list_suggestions(
    params: Annotated[SuggestionListParams, Query()], session: Session, settings: AppSettings
) -> SuggestionPage:
    scope = "suggestions/ai" if params.ai else f"suggestions/{params.tier}"
    cursor = _Cursor.decode(params.cursor, scope, (_flag, _int, _int, _int))
    ordered = _ordered_suggestions()
    rows = _ai_suggestions() if params.ai else ordered
    columns = [rows.c.both, rows.c.mails, rows.c.first, rows.c.second]
    start = [] if cursor is None else [_beyond(columns, cursor.key, True)]
    tier = [] if params.ai else [rows.c.tier == params.tier]
    found = list(
        await session.execute(
            select(rows).where(*tier, *start).order_by(*_by(columns, True)).limit(params.limit + 1)
        )
    )
    more = len(found) > params.limit
    del found[params.limit :]
    counts = await _tier_counts(session, select(ordered.c.tier).subquery())
    check = await _check_state(session, settings)
    summaries = await _summaries(session, [i for row in found for i in (row.first, row.second)])
    verdicts = await _verdicts(session, [(row.first, row.second) for row in found])
    next_cursor = None
    if more:
        last = found[-1]
        key = (last.both, last.mails, last.first, last.second)
        next_cursor = _Cursor(scope, False, key).encode()
    computed = await session.scalar(
        select(GlobalStats.value).where(GlobalStats.key == SUGGESTIONS_KEY)
    )
    page = SuggestionPage(
        items=[
            AliasSuggestion(
                first=summaries[row.first],
                second=summaries[row.second],
                same_name=row.same_name,
                same_local_part=row.same_local_part,
                tier=row.tier,
                reason=_reason(row.same_name, row.same_local_part, row.tier),
                ai=verdicts.get(_pair(row.first, row.second)),
            )
            for row in found
        ],
        next_cursor=next_cursor,
        total=check.same if params.ai else getattr(counts, params.tier.value),
        counts=counts,
        computed=computed == {"rules": SUGGESTION_RULES},
        check=check,
    )
    await attach_labels(session, page)
    return page


def _reason(
    same_name: str | None, same_local_part: str | None, tier: AliasTier
) -> SuggestionReason:
    """reason of a suggestion, "ai" for a pair only the alias check found (D323)."""
    if same_name is None and same_local_part is None:
        return "ai"
    return reason(same_name, same_local_part, tier)


def _pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


async def _verdicts(
    session: AsyncSession, pairs: Sequence[tuple[int, int]]
) -> dict[tuple[int, int], AliasCheckInfo]:
    """The newest check of each pair of roots (D323), by _pair: alias_check read through the
    persons of these roots, by the indexes of both its persons."""
    roots = {root for pair in pairs for root in pair}
    if not roots:
        return {}
    members = dict(
        (
            await session.execute(
                select(Person.id, func.coalesce(Person.merged_into, Person.id)).where(
                    or_(Person.id.in_(roots), Person.merged_into.in_(roots))
                )
            )
        )
        .tuples()
        .all()
    )
    wanted = {_pair(*pair) for pair in pairs}
    found: dict[tuple[int, int], AliasCheckInfo] = {}
    checks = await session.scalars(
        select(AliasCheck)
        .where(AliasCheck.person_a.in_(members), AliasCheck.person_b.in_(members))
        .order_by(AliasCheck.created_at, AliasCheck.person_a, AliasCheck.person_b)
    )
    for check in checks:
        key = _pair(members[check.person_a], members[check.person_b])
        if key in wanted:  # the newest one stays
            found[key] = AliasCheckInfo(
                verdict=check.verdict,
                reason=check.reason,
                model=check.model,
                checked_at=check.created_at,
            )
    return found


async def _check_state(session: AsyncSession, settings: Settings) -> AliasCheckState:
    """The alias check as the suggestion list shows it (D321 to D323)."""
    running = False
    if await jobs.job_alive(session, JobKind.AI):
        job = await jobs.latest_job(session, JobKind.AI)
        running = job is not None and bool((job.options or {}).get("aliases"))
    return AliasCheckState(
        available=await asyncio.to_thread(lambda: alias_check_service(settings) is not None),
        running=running,
        checked=await session.scalar(select(func.count()).select_from(AliasCheck)) or 0,
        same=await session.scalar(select(func.count()).select_from(_ai_suggestions())) or 0,
    )


async def _tier_counts(session: AsyncSession, tiers: Subquery) -> SuggestionCounts:
    """The suggestions per tier, from a subquery with the tier of each."""
    rows = await session.execute(select(tiers.c.tier, func.count()).group_by(tiers.c.tier))
    found = {tier: count for tier, count in rows}
    return SuggestionCounts(
        certain=found.get(AliasTier.CERTAIN, 0), uncertain=found.get(AliasTier.UNCERTAIN, 0)
    )


@contextmanager
def _user_write() -> Iterator[None]:
    """A merge, undo, unmerge or dismissal (D28, D163); its errors as 404 not_found,
    400 invalid_merge and 409 merge_undone."""
    try:
        yield
    except (UnknownPerson, UnknownMerge) as error:
        raise api_error(404, "not_found", str(error)) from error
    except MergeError as error:
        raise api_error(400, "invalid_merge", str(error)) from error
    except MergeUndone as error:
        raise api_error(409, "merge_undone", str(error)) from error


@router.post("/persons/suggestions/dismiss", status_code=204)
async def dismiss_suggestion(dismiss: SuggestionDismiss, session: Session) -> Response:
    with _user_write():
        await dismiss_pair(session, *dismiss.persons)
    await session.commit()
    return Response(status_code=204)


# Merging ---------------------------------------------------------------------------------------


@router.post("/persons/merge")
async def merge(request: MergeRequest, session: Session, editor: Editor) -> PersonProfile:
    with _user_write():
        root = await merge_persons(session, request.target, request.sources, editor)
    await session.commit()
    return await _profile(session, root)


def _plan(plan: MergePlan) -> CertainMergePlan:
    return CertainMergePlan(
        merges=len(plan.groups),
        persons=sum(len(sources) for _, sources in plan.groups),
        left_out_groups=len(plan.left_out),
        left_out_persons=sum(map(len, plan.left_out)),
    )


@router.get("/persons/merge-certain")
async def certain_merge_plan(session: Session) -> CertainMergePlan:
    return _plan(await certain_groups(session))


@router.post("/persons/merge-certain")
async def merge_every_certain(session: Session, editor: Editor) -> CertainMergeResult:
    done = await merge_certain(session, editor)
    await session.commit()
    return CertainMergeResult(
        batch_id=done.batch_id,
        merges=done.merges,
        persons=done.persons,
        left_out_groups=done.left_out_groups,
        left_out_persons=done.left_out_persons,
    )


@router.get("/persons/merges")
async def merge_log(params: Annotated[MergeLogParams, Query()], session: Session) -> MergeLogPage:
    cursor = _Cursor.decode(params.cursor, "merges", (_int,))
    start = [] if cursor is None else [PersonMerge.id < cursor.key[0]]
    ids = list(
        await session.scalars(
            select(PersonMerge.id)
            .where(*start)
            .order_by(PersonMerge.id.desc())
            .limit(params.limit + 1)
        )
    )
    more = len(ids) > params.limit
    del ids[params.limit :]
    items = await _merge_entries(session, ids)
    batches = {item.batch_id for item in items if item.batch_id is not None}
    rows = await session.execute(
        select(
            MergeBatch.id,
            MergeBatch.created_at,
            MergeBatch.editor,
            func.count(PersonMerge.id),
            func.count(PersonMerge.undone_at),
        )
        .join(PersonMerge, PersonMerge.batch_id == MergeBatch.id)
        .where(MergeBatch.id.in_(batches))
        .group_by(MergeBatch.id)
        .order_by(MergeBatch.id.desc())
    )
    page = MergeLogPage(
        items=items,
        batches=[
            MergeBatchInfo(id=batch, created_at=at, editor=by, merges=merges, undone=undone)
            for batch, at, by, merges, undone in rows
        ],
        next_cursor=_Cursor("merges", False, (ids[-1],)).encode() if more else None,
        total=await session.scalar(select(func.count()).select_from(PersonMerge)) or 0,
    )
    await attach_labels(session, page)
    return page


@router.post("/persons/merges/{merge_id}/undo")
async def undo_one_merge(merge_id: RowId, session: Session, editor: Editor) -> MergeUndoResult:
    with _user_write():
        done = await undo_merge(session, merge_id, editor)
    await session.commit()
    return MergeUndoResult(merges=done.merges, persons=done.persons)


@router.post("/persons/merge-batches/{batch_id}/undo")
async def undo_merge_batch(batch_id: RowId, session: Session, editor: Editor) -> MergeUndoResult:
    with _user_write():
        done = await undo_batch(session, batch_id, editor)
    await session.commit()
    return MergeUndoResult(merges=done.merges, persons=done.persons)


async def _merge_entries(session: AsyncSession, ids: Sequence[int]) -> list[MergeLogEntry]:
    """These logged merges, newest first, with their targets and the persons they moved."""
    if not ids:
        return []
    asked = literal(list(ids), ARRAY(BigInteger))
    merges = await session.execute(
        select(PersonMerge, Person.canonical_email, Person.display_name)
        .join(Person, Person.id == PersonMerge.target)
        .where(PersonMerge.id == any_(asked))
        .order_by(PersonMerge.id.desc())
    )
    moved: dict[int, list[PersonRef]] = {merge_id: [] for merge_id in ids}
    members = await session.execute(
        select(PersonMergeMember.merge_id, Person.id, Person.canonical_email, Person.display_name)
        .join(Person, Person.id == PersonMergeMember.person_id)
        .where(PersonMergeMember.merge_id == any_(asked))
        .order_by(PersonMergeMember.merge_id, Person.id)
    )
    for merge_id, person_id, email, name in members:
        moved[merge_id].append(PersonRef(person_id=person_id, email=email, name=name))
    return [
        MergeLogEntry(
            id=row.id,
            target=PersonRef(person_id=row.target, email=email, name=name),
            moved=moved[row.id],
            batch_id=row.batch_id,
            editor=row.editor,
            created_at=row.created_at,
            undone_at=row.undone_at,
            undone_by=row.undone_by,
        )
        for row, email, name in merges
    ]


@router.post("/persons/{person_id}/unmerge")
async def unmerge(person_id: PersonId, session: Session) -> PersonProfile:
    with _user_write():
        root = await unmerge_person(session, person_id)
    await session.commit()
    return await _profile(session, root)


# Labels ----------------------------------------------------------------------------------------


@router.put("/persons/{person_id}/label")
async def save_label(
    person_id: PersonId, update: PersonLabelUpdate, session: Session, editor: Editor
) -> PersonProfile:
    """The label of the root's own address (D156); all fields blank removes it."""
    root = await _root(session, person_id)
    email = await session.scalar(select(Person.canonical_email).where(Person.id == root))
    assert email is not None, "_root found the person"
    await set_label(session, email, update, editor)
    await session.commit()
    return await _profile(session, root)


# Profile ---------------------------------------------------------------------------------------


@router.get("/persons/{person_id}")
async def person_profile(person_id: PersonId, session: Session) -> PersonProfile:
    return await _profile(session, await _root(session, person_id))


async def _profile(session: AsyncSession, root: int) -> PersonProfile:
    person = (
        await session.execute(
            select(Person.canonical_email, Person.display_name, Person.domain).where(
                Person.id == root
            )
        )
    ).one()
    stats = (
        await session.execute(select(*_FIGURES).where(PersonStats.person_id == root))
    ).one_or_none()
    years = await session.execute(
        select(PersonYear.year, PersonYear.sent, PersonYear.received)
        .where(PersonYear.person_id == root)
        .order_by(PersonYear.year)
    )
    contacts, _ = await _contacts(session, root, TOP_CONTACTS)
    profile = PersonProfile(
        id=root,
        name=person.display_name,
        email=person.canonical_email,
        domain=person.domain,
        aliases=await _aliases(session, root),
        display_names=await _display_names(session, root),
        figures=None if stats is None else _figures(stats),
        years=[
            YearActivity(year=year, sent=sent, received=received) for year, sent, received in years
        ],
        top_contacts=contacts,
        suggestions=await _candidates(session, root),
        suggestion_counts=await _tier_counts(
            session,
            select(SuggestionRow.tier)
            .join(PersonStats, PersonStats.person_id == _other(root))
            .where(or_(SuggestionRow.person_a == root, SuggestionRow.person_b == root))
            .subquery(),
        ),
        merges=await _merges_into(session, root),
        label=(await shown_labels(session, [root])).get(root),
    )
    await attach_labels(session, profile)
    return profile


async def _merges_into(session: AsyncSession, root: int) -> list[MergeLogEntry]:
    """The logged merges not undone that moved one of root's aliases into it, newest first."""
    ids = await session.scalars(
        select(PersonMergeMember.merge_id)
        .join(Person, Person.id == PersonMergeMember.person_id)
        .join(PersonMerge, PersonMerge.id == PersonMergeMember.merge_id)
        .where(Person.merged_into == root, PersonMerge.undone_at.is_(None))
        .distinct()
    )
    return await _merge_entries(session, list(ids))


async def _aliases(session: AsyncSession, root: int) -> list[AliasAddress]:
    """The addresses merged into root, each with its mails that are not duplicates."""
    mails = (
        select(func.count(distinct(Participation.mail_id)))
        .where(Participation.person_id == Person.id, Participation.mail_id.not_in(_DUPLICATES))
        .scalar_subquery()
        .label("mails")
    )
    rows = list(
        await session.execute(
            select(Person.id, Person.canonical_email, Person.display_name, mails)
            .where(Person.merged_into == root)
            .order_by(mails.desc(), Person.id.desc())
        )
    )
    labels = await address_labels(session, [row.canonical_email for row in rows])
    return [
        AliasAddress(
            person_id=person_id, email=email, name=name, mails=count, label=labels.get(email)
        )
        for person_id, email, name, count in rows
    ]


async def _display_names(session: AsyncSession, root: int) -> list[DisplayNameCount]:
    """The names used with any address of root, summed, most used first."""
    names = func.jsonb_each_text(PersonEmail.display_names).table_valued("key", "value")
    mails = func.sum(cast(names.c.value, BigInteger)).label("mails")
    members = select(Person.id).where(or_(Person.id == root, Person.merged_into == root))
    rows = await session.execute(
        select(names.c.key, mails)
        .select_from(PersonEmail)
        .join(names, true())
        .where(PersonEmail.person_id.in_(members))
        .group_by(names.c.key)
        .order_by(mails.desc(), names.c.key)
        .limit(DISPLAY_NAME_LIMIT)
    )
    return [DisplayNameCount(name=name, mails=count) for name, count in rows]


def _other(root: int) -> ColumnElement[int]:
    """The other person of a suggestion with root."""
    return case(
        (SuggestionRow.person_a == root, SuggestionRow.person_b), else_=SuggestionRow.person_a
    )


async def _candidates(session: AsyncSession, root: int) -> list[AliasCandidate]:
    """The open suggestions with root: certain ones first, then the other person with most
    mails first."""
    other = _other(root).label("other")
    rows = list(
        await session.execute(
            select(
                other, SuggestionRow.same_name, SuggestionRow.same_local_part, SuggestionRow.tier
            )
            .join(PersonStats, PersonStats.person_id == other)
            .where(or_(SuggestionRow.person_a == root, SuggestionRow.person_b == root))
            .order_by(
                (SuggestionRow.tier == AliasTier.CERTAIN).desc(),
                PersonStats.mails.desc(),
                other.desc(),
            )
            .limit(SUGGESTION_LIMIT)
        )
    )
    summaries = await _summaries(session, [row.other for row in rows])
    verdicts = await _verdicts(session, [(root, row.other) for row in rows])
    return [
        AliasCandidate(
            person=summaries[row.other],
            same_name=row.same_name,
            same_local_part=row.same_local_part,
            tier=row.tier,
            reason=reason(row.same_name, row.same_local_part, row.tier),
            ai=verdicts.get(_pair(root, row.other)),
        )
        for row in rows
    ]


# Contacts --------------------------------------------------------------------------------------


def _edges(root: int) -> Subquery:
    """The edges of root seen from it: the other person and the mails each way."""
    as_a = select(
        Edge.person_b.label("other"),
        Edge.mails_a_to_b.label("sent"),
        Edge.mails_b_to_a.label("received"),
        Edge.mails_cc.label("cc"),
        Edge.mails_total.label("mails"),
        Edge.first_date,
        Edge.last_date,
    ).where(Edge.person_a == root)
    as_b = select(
        Edge.person_a,
        Edge.mails_b_to_a,
        Edge.mails_a_to_b,
        Edge.mails_cc,
        Edge.mails_total,
        Edge.first_date,
        Edge.last_date,
    ).where(Edge.person_b == root)
    return union_all(as_a, as_b).subquery("contacts")


async def _contacts(
    session: AsyncSession, root: int, limit: int, after: Sequence[int] | None = None
) -> tuple[list[Contact], bool]:
    """The first `limit` contacts of root by mails, then id, after the contact `after`
    (mails, id) when given; and whether more follow."""
    edges = _edges(root)
    columns = [edges.c.mails, edges.c.other]
    start = [] if after is None else [_beyond(columns, after, True)]
    rows = list(
        await session.execute(
            select(edges, Person.canonical_email, Person.display_name, Person.domain)
            .join(Person, Person.id == edges.c.other)
            .where(*start)
            .order_by(*_by(columns, True))
            .limit(limit + 1)
        )
    )
    return [
        Contact(
            person=PersonRef(person_id=row.other, email=row.canonical_email, name=row.display_name),
            domain=row.domain,
            mails=row.mails,
            sent=row.sent,
            received=row.received,
            cc=row.cc,
            first_date=row.first_date,
            last_date=row.last_date,
        )
        for row in rows[:limit]
    ], len(rows) > limit


@router.get("/persons/{person_id}/contacts")
async def list_contacts(
    person_id: PersonId, params: Annotated[ContactListParams, Query()], session: Session
) -> ContactPage:
    root = await _root(session, person_id)
    scope = f"contacts/{root}"
    cursor = _Cursor.decode(params.cursor, scope, (_int, _int))
    contacts, more = await _contacts(
        session, root, params.limit, None if cursor is None else cursor.key
    )
    total = await session.scalar(select(func.count()).select_from(_edges(root)))
    next_cursor = None
    if more:
        last = contacts[-1]
        next_cursor = _Cursor(scope, False, (last.mails, last.person.person_id)).encode()
    page = ContactPage(items=contacts, next_cursor=next_cursor, total=total or 0)
    await attach_labels(session, page)
    return page


# Mail counts -----------------------------------------------------------------------------------


@router.get("/persons/{person_id}/mail-counts")
async def mail_counts(
    person_id: PersonId,
    params: Annotated[PersonMailCountParams, Query()],
    session: Session,
    settings: AppSettings,
) -> PersonMailCounts:
    """The tabs of the person's mail list (D32) as the mail list filters them: person_role,
    between the person and the contact, the year as a date range, without duplicates.

    One pass over the participations of the person's and the contact's addresses gives each mail
    once with the roles both have in it; the mails themselves are read only for the year.
    """
    root = await _root(session, person_id)
    members = await member_ids(session, root)
    contact = [] if params.contact is None else await member_ids(session, params.contact)
    mine, theirs = Participation.person_id.in_(members), Participation.person_id.in_(contact)
    role = Participation.role
    flags = (
        select(
            Participation.mail_id,
            *(
                func.bool_or(and_(mine, role == each)).label(each.value)
                for each in ParticipationRole
            ),
            func.bool_or(and_(theirs, role == ParticipationRole.FROM)).label("contact_sent"),
            func.bool_or(and_(theirs, role != ParticipationRole.FROM)).label("contact_received"),
        )
        .where(Participation.person_id.in_([*members, *contact]))
        .group_by(Participation.mail_id)
        .subquery("flags")
    )
    sent, to, cc, bcc = (flags.c[each.value] for each in ParticipationRole)
    where: list[ColumnElement[bool]] = [flags.c.mail_id.not_in(_DUPLICATES)]
    if params.contact is not None:  # as filters._between: one sent it, the other received it
        where.append(
            or_(
                and_(sent, flags.c.contact_received),
                and_(flags.c.contact_sent, or_(to, cc, bcc)),
            )
        )
    if params.year is not None:
        year = MailFilters(
            date_from=date(params.year, 1, 1),
            date_to=date(params.year, 12, 31) if params.year < date.max.year else None,
        )
        dated = select(Mail.id).where(*mail_conditions(year, (), ()))
        where.append(flags.c.mail_id.in_(dated))
    counts = select(
        func.count(),
        func.count().filter(sent),
        func.count().filter(~sent),
        func.count().filter(and_(cc, ~sent, ~to, ~bcc)),
    ).where(*where)
    await _count_budget(session, settings)
    row = await _unless_canceled(session, counts)
    if row is None:
        return PersonMailCounts(all=None, sent=None, received=None, cc=None)
    return PersonMailCounts(all=row[0], sent=row[1], received=row[2], cc=row[3])
