"""The timeline: the mail list's matching mails over time, split into series, with marks, and
the first mention per person (milestone 11, D90 to D95). Models are in schemas.py.

Routes: GET /api/timeline, /api/timeline/first-mentions.

The conditions are the mail list's (mails._where, then filters.resolve_contents, as its summary
does), so every filter of MailFilters holds here as it does there. PostgreSQL counts the
matching mails per UTC day, the undated ones in the same statement; timeline.buckets lays out
the axis and sums the days into weeks and months, timeline.marks finds the marks. A person
series reads only the participations of the chosen persons' addresses
(ix_participation_person_id_role), a thread series the thread's mails (ix_mail_thread_id), a
term series the mails of the filters and its search string. All series of a request are
counted in one statement, so they are there or missing together. The top persons of the
unfiltered archive come from person_stats; with conditions they are counted over the matches.

Every statement after the filters runs under the count budget of the mail list
(MAILROBBE_API_COUNT_TIMEOUT, mails._count_budget) in a savepoint of its own: one that runs out
of time leaves its part None or empty and sets timed_out, and the rest is still answered.
Without the total's days the axis is laid out over the series' days.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Date,
    Executable,
    Integer,
    any_,
    cast,
    func,
    literal,
    literal_column,
    or_,
    select,
    union_all,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from mailrobbe.api.deps import AppSettings, Session, api_error
from mailrobbe.api.documents import _all_unless_canceled
from mailrobbe.api.filters import internal_domains, mail_conditions, resolve_contents
from mailrobbe.api.mails import _count_budget, _terms, _unless_canceled, _where
from mailrobbe.api.query import QueryError, parse_query
from mailrobbe.api.schemas import (
    FirstMention,
    FirstMentionParams,
    FirstMentions,
    MailFilters,
    PersonRef,
    Timeline,
    TimelineBucket,
    TimelineParams,
    TimelineSeries,
)
from mailrobbe.config import Settings
from mailrobbe.db.models import Mail, Participation, Person, PersonStats
from mailrobbe.enums import ParticipationRole
from mailrobbe.persons.labels import attach_labels
from mailrobbe.persons.roots import ROOT
from mailrobbe.timeline import buckets, marks

router = APIRouter(prefix="/api", tags=["timeline"])

# The mail's UTC day; the zone is SQL text, so that SELECT and GROUP BY are the same expression.
_DAY: ColumnElement[date] = cast(func.timezone(literal_column("'UTC'"), Mail.date_utc), Date)
_DATED = Mail.date_utc.is_not(None)

Conditions = Sequence[ColumnElement[bool]]


@dataclass
class _Series:
    """A series before it is laid onto the axis: its matching dated mails per UTC day."""

    key: str
    label: str | None
    person: PersonRef | None = None
    thread_id: int | None = None
    term: str | None = None
    days: dict[date, int] = field(default_factory=dict)


def _ids(values: Sequence[int]) -> ColumnElement[list[int]]:
    return literal(list(values), ARRAY(BigInteger))


@router.get("/timeline")
async def timeline(
    params: Annotated[TimelineParams, Query()], session: Session, settings: AppSettings
) -> Timeline:
    where = _where(params, _terms(params.q), settings)
    searches = _searches(params.term, settings) if params.split == "term" else []
    where = await resolve_contents(session, where)
    await _count_budget(session, settings)
    # The archive's end (D91): its latest date not after today, one probe of ix_mail_date_utc.
    tomorrow = datetime.combine(datetime.now(UTC).date() + timedelta(days=1), time(), tzinfo=UTC)
    latest = await _unless_canceled(
        session, select(func.max(Mail.date_utc)).where(Mail.date_utc < tomorrow)
    )
    archive_end = None if latest is None or latest[0] is None else latest[0].astimezone(UTC).date()
    rows = await _all_unless_canceled(
        session, select(_DAY, func.count()).where(*where).group_by(_DAY)
    )
    total = undated = None
    if rows is not None:
        total = _Series("all", None, days={day: count for day, count in rows if day is not None})
        undated = sum(count for day, count in rows if day is None)
    series = await _split(session, params, where, searches)

    known = (
        set(total.days) if total is not None else {d for each in series or () for d in each.days}
    )
    bucket: TimelineBucket = params.bucket or "month"
    coarsened, starts = False, []
    if known:
        first = params.date_from or min(known)
        last = params.date_to or max(max(known), archive_end or date.min)
        bucket, coarsened = buckets.choose(first, last, params.bucket)
        starts = buckets.axis(first, last, bucket)
    # The end of the days a series can show (D93): the archive's end, or date_to before it.
    end_day = None if archive_end is None else min(archive_end, params.date_to or archive_end)
    end = -1 if end_day is None else buckets.position(starts, end_day)
    low = buckets.covered(starts, bucket, params.date_from, end_day)

    def laid_out(each: _Series) -> TimelineSeries:
        counts = buckets.sum_days(each.days, starts, bucket)
        silent = marks.silent_from(counts, bucket, end)
        return TimelineSeries(
            key=each.key,
            label=each.label,
            person=each.person,
            thread_id=each.thread_id,
            term=each.term,
            counts=counts,
            total=sum(counts),
            outliers=marks.outliers(counts, bucket, low),
            silent_from=None if silent is None else starts[silent],
        )

    response = Timeline(
        bucket=bucket,
        coarsened=coarsened,
        starts=starts,
        total=None if total is None else laid_out(total),
        series=[laid_out(each) for each in series or ()],
        undated=undated,
        archive_end=archive_end,
        timed_out=latest is None or total is None or series is None,
    )
    await attach_labels(session, response)
    for each in response.series:  # a person's legend shows the name the team gave it (D157)
        if each.person is not None and each.person.label is not None and each.person.label.name:
            each.label = each.person.label.name
    return response


def _searches(
    strings: Sequence[str], settings: Settings
) -> list[tuple[str, list[ColumnElement[bool]]]]:
    """Each search string of a term split with its conditions (400 invalid_query naming it)."""
    internal = internal_domains(settings.internal_domains)
    found = []
    for string in strings:
        try:
            terms = parse_query(string)
        except QueryError as error:
            raise api_error(400, "invalid_query", f'term "{string}": {error}') from error
        found.append((string, mail_conditions(MailFilters(), terms, internal)))
    return found


async def _split(
    session: AsyncSession,
    params: TimelineParams,
    where: Conditions,
    searches: Sequence[tuple[str, Conditions]],
) -> list[_Series] | None:
    """The series of the split in order (D92); None when out of time."""
    match params.split:
        case "person":
            return await _person_series(session, params, where)
        case "thread":
            return await _thread_series(session, params, where)
        case "term":
            series = {
                index: _Series(f"term:{index}", string, term=string)
                for index, (string, _) in enumerate(searches)
            }
            branches = [
                select(literal(index, Integer), _DAY, func.count())
                .where(*where, *conditions, _DATED)
                .group_by(_DAY)
                for index, (_, conditions) in enumerate(searches)
            ]
            return await _counted(session, union_all(*branches), series) if branches else []
    return []


async def _counted(
    session: AsyncSession, statement: Executable, series: dict[int, _Series]
) -> list[_Series] | None:
    """The series in order with their days from statement's rows (key, day, count)."""
    rows = await _all_unless_canceled(session, statement)
    if rows is None:
        return None
    for key, day, count in rows:
        series[key].days[day] = count
    return list(series.values())


async def _person_series(
    session: AsyncSession, params: TimelineParams, where: Conditions
) -> list[_Series] | None:
    """Root persons labelled with their name, else their address; each counts the mails of all
    its addresses, read through the participation index of those addresses only."""
    chosen = await _all_unless_canceled(session, _chosen_persons(params, where))
    if chosen is None:
        return None
    if params.split_id:  # rows (given id, root, email, name): in the order given, roots once
        found = {given: tuple(row) for given, *row in chosen}
        chosen = list(dict.fromkeys(found[given] for given in params.split_id if given in found))
    series = {
        root: _Series(
            f"person:{root}",
            name or email,
            person=PersonRef(person_id=root, email=email, name=name),
        )
        for root, email, name in chosen
    }
    if not series:
        return []
    roots = _ids(list(series))
    members = await _all_unless_canceled(
        session,
        select(Person.id).where(or_(Person.id == any_(roots), Person.merged_into == any_(roots))),
    )
    if members is None:
        return None
    # Each mail once per root, however many of its addresses take part, in whichever roles.
    links = (
        select(ROOT.label("root"), Participation.mail_id)
        .distinct()
        .join(Person, Person.id == Participation.person_id)
        .where(Participation.person_id == any_(_ids([member for (member,) in members])))
        .subquery("links")
    )
    statement = (
        select(links.c.root, _DAY, func.count())
        .join_from(links, Mail, Mail.id == links.c.mail_id)
        .where(*where, _DATED)
        .group_by(links.c.root, _DAY)
    )
    return await _counted(session, statement, series)


def _chosen_persons(params: TimelineParams, where: Conditions) -> Executable:
    """The root persons of a person split (D92). With split_id: (given id, root id, address,
    name) of each given person that exists. Else (root id, address, name) of the `series` roots
    with the most matching mails in any role, lists and automated senders (D39) left out, ties
    by the higher id: from person_stats without any condition, else counted over the matches."""
    root = aliased(Person, name="root")
    if params.split_id:
        return (
            select(Person.id, root.id, root.canonical_email, root.display_name)
            .join(root, root.id == ROOT)
            .where(Person.id == any_(_ids(params.split_id)))
        )
    columns = (root.id, root.canonical_email, root.display_name)
    if not where:
        return (
            select(*columns)
            .join(PersonStats, PersonStats.person_id == root.id)
            .where(root.kind.is_(None), PersonStats.mails > 0)
            .order_by(PersonStats.mails.desc(), PersonStats.person_id.desc())
            .limit(params.series)
        )
    matched = select(Mail.id).where(*where).cte("matched")
    links = (
        select(ROOT.label("root"), Participation.mail_id)
        .distinct()
        .join(Person, Person.id == Participation.person_id)
        .join(matched, matched.c.id == Participation.mail_id)
        .subquery("links")
    )
    return (
        select(*columns)
        .join(links, links.c.root == root.id)
        .where(root.kind.is_(None))
        .group_by(root.id)
        .order_by(func.count().desc(), root.id.desc())
        .limit(params.series)
    )


async def _thread_series(
    session: AsyncSession, params: TimelineParams, where: Conditions
) -> list[_Series] | None:
    """Threads labelled with the subject of their first mail, whose id is the thread's (D17)."""
    if params.split_id:  # the given threads that exist, in the order given
        statement = select(Mail.id, Mail.subject).where(
            Mail.id == any_(_ids(params.split_id)), Mail.thread_id == Mail.id
        )
    else:  # the `series` threads with the most matching mails, ties by the higher id
        top = (
            select(Mail.thread_id.label("id"), func.count().label("mails"))
            .where(*where, Mail.thread_id.is_not(None))
            .group_by(Mail.thread_id)
            .order_by(func.count().desc(), Mail.thread_id.desc())
            .limit(params.series)
            .subquery("top")
        )
        first = aliased(Mail, name="first")
        statement = (
            select(top.c.id, first.subject)
            .outerjoin(first, first.id == top.c.id)
            .order_by(top.c.mails.desc(), top.c.id.desc())
        )
    chosen = await _all_unless_canceled(session, statement)
    if chosen is None:
        return None
    subjects = dict(chosen)
    threads = params.split_id if params.split_id else list(subjects)
    series = {
        thread: _Series(f"thread:{thread}", subjects[thread], thread_id=thread)
        for thread in threads
        if thread in subjects
    }
    if not series:
        return []
    counts = (
        select(Mail.thread_id, _DAY, func.count())
        .where(*where, _DATED, Mail.thread_id == any_(_ids(list(series))))
        .group_by(Mail.thread_id, _DAY)
    )
    return await _counted(session, counts, series)


# First mentions --------------------------------------------------------------------------------


@router.get("/timeline/first-mentions")
async def first_mentions(
    params: Annotated[FirstMentionParams, Query()], session: Session, settings: AppSettings
) -> FirstMentions:
    where = await resolve_contents(session, _where(params, _terms(params.q), settings))
    await _count_budget(session, settings)
    rows = await _all_unless_canceled(session, _first_mentions(params, where))
    if rows is None:
        return FirstMentions(items=[], persons=None, timed_out=True)
    items = [
        FirstMention(
            person=PersonRef(person_id=row.id, email=row.canonical_email, name=row.display_name),
            kind=row.kind,
            role=row.role,
            date=row.date_utc,
            mail_id=row.mail_id,
            subject=row.subject,
            mails=row.mails,
        )
        for row in rows
    ]
    found = FirstMentions(items=items, persons=rows[0].persons if rows else 0, timed_out=False)
    await attach_labels(session, found)
    return found


def _first_mentions(params: FirstMentionParams, where: Conditions) -> Executable:
    """D94 in one statement: each root's matching mails once with its best role in each (From,
    To, Cc, Bcc: the enum's order), the earliest dated one per root with the number of all,
    then the first `limit` of them by date, mail and person, and how many there are."""
    matched = select(Mail.id, Mail.date_utc).where(*where).cte("matched")
    per_mail = (
        select(
            ROOT.label("root"),
            Participation.mail_id,
            matched.c.date_utc,
            func.min(Participation.role).label("role"),
        )
        .join(Person, Person.id == Participation.person_id)
        .join(matched, matched.c.id == Participation.mail_id)
        .group_by(ROOT, Participation.mail_id, matched.c.date_utc)
    )
    if params.role == "sent":
        per_mail = per_mail.where(Participation.role == ParticipationRole.FROM)
    mails = per_mail.subquery("per_mail")
    firsts = (
        select(
            mails.c.root,
            mails.c.mail_id,
            mails.c.date_utc,
            mails.c.role,
            func.count().over(partition_by=mails.c.root).label("mails"),
        )
        .ext(postgresql.distinct_on(mails.c.root))
        .order_by(mails.c.root, mails.c.date_utc.asc().nulls_last(), mails.c.mail_id)
        .subquery("firsts")
    )
    root = aliased(Person, name="root")
    subject = select(Mail.subject).where(Mail.id == firsts.c.mail_id).scalar_subquery()
    statement = (
        select(
            root.id,
            root.canonical_email,
            root.display_name,
            root.kind,
            firsts.c.role,
            firsts.c.date_utc,
            firsts.c.mail_id,
            subject.label("subject"),
            firsts.c.mails,
            func.count().over().label("persons"),
        )
        .join_from(firsts, root, root.id == firsts.c.root)
        .where(firsts.c.date_utc.is_not(None))
        .order_by(firsts.c.date_utc, firsts.c.mail_id, root.id)
        .limit(params.limit)
    )
    return statement if params.lists else statement.where(root.kind.is_(None))
