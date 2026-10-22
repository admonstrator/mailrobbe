"""Which mails a hide rule hides (D221 to D223).

matches() is the one place that turns a rule into SQL: the preview counts its mails, a save and
the step hidden store them (store_rule, one statement per rule). Every criterion the rule names
must hold: the sender's address (the person row of a From participation that has it), a person
(a From participation of any person whose root is the rule person's root, so aliases count, also
those a later merge adds), the sender's domain or a subdomain of it, the List-Id, sent
automatically (D39), and the subject holding or starting with a text in any case, % and _ taken
as written (D204). Each criterion is served by an index (participation by person, ix_mail_list_id,
ix_mail_subject_trgm), except "automatically" alone, which reads every mail.

mail_hidden holds the mails each enabled rule matches; a mail is hidden when a rule matches it
and its content is not kept: in an Akte, with a note, bookmarked or reviewed relevant (D203).
Keeping is decided when a list is asked, so a note or an Akte shows a mail at once.

The unfiltered mail list takes the hidden mails off the archive's figures (D222). global_stats
'hidden' holds the mails an enabled rule matches with their DKIM counts (HiddenFigures), written
in every transaction that changes mail_hidden and again when the archive's figures are newer;
the few kept ones among them are counted when asked (kept_counts).
"""

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    CompoundSelect,
    Select,
    Text,
    and_,
    any_,
    delete,
    exists,
    false,
    func,
    literal,
    or_,
    select,
    union,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe.db.models import (
    CollectionMail,
    GlobalStats,
    HideRule,
    Mail,
    MailHidden,
    MailMark,
    Note,
    Participation,
    Person,
    PersonEmail,
)
from mailrobbe.enums import ParticipationRole, ReviewStatus
from mailrobbe.persons.roots import ROOT

Executor = AsyncSession | AsyncConnection

FIGURES_KEY = "hidden"  # global_stats key of HiddenFigures
UNCHECKED = "unchecked"  # the DKIM key of mails not checked yet, as in global_stats 'dkim'
# Transaction-level advisory lock around writing the figures: the last writer counts after every
# other change to mail_hidden is committed, so the stored figures miss none of them.
_LOCK_KEY = int.from_bytes(b"mrhidden", "big")


class Criteria(Protocol):
    """A rule's criteria as stored: text trimmed, sender, domain and List-Id in lower case, None
    where not given (hide_rule rows, and HideRuleFields once the API cleaned them)."""

    @property
    def sender(self) -> str | None: ...
    @property
    def person_id(self) -> int | None: ...
    @property
    def domain(self) -> str | None: ...
    @property
    def list_id(self) -> str | None: ...
    @property
    def automated(self) -> bool: ...
    @property
    def subject(self) -> str | None: ...
    @property
    def subject_match(self) -> str: ...


def matches(rule: Criteria) -> ColumnElement[bool]:
    """The condition on mail of every criterion the rule names; none named matches nothing."""
    conditions: list[ColumnElement[bool]] = []
    if rule.sender is not None:
        address = union(
            select(PersonEmail.person_id).where(PersonEmail.email == rule.sender),
            select(Person.id).where(Person.canonical_email == rule.sender),
        )
        conditions.append(_sent_by(address))
    if rule.person_id is not None:
        # every person of the root, as the person filter reads them; NULL when the person is gone
        root = select(ROOT).where(Person.id == rule.person_id).scalar_subquery()
        conditions.append(
            _sent_by(select(Person.id).where(or_(Person.id == root, Person.merged_into == root)))
        )
    if rule.domain is not None:
        domain = or_(Person.domain == rule.domain, Person.domain.like("%." + _escaped(rule.domain)))
        conditions.append(_sent_by(select(Person.id).where(domain)))
    if rule.list_id is not None:
        conditions.append(Mail.list_id == rule.list_id)
    if rule.automated:
        conditions.append(Mail.automated.is_(True))
    if rule.subject is not None:
        pattern = _escaped(rule.subject) + "%"
        if rule.subject_match == "contains":
            pattern = "%" + pattern
        conditions.append(Mail.subject.ilike(pattern))
    return and_(*conditions) if conditions else false()


def _sent_by(persons: Select[int] | CompoundSelect[int]) -> ColumnElement[bool]:
    """One of these person rows sent the mail (From)."""
    return exists().where(
        Participation.mail_id == Mail.id,
        Participation.role == ParticipationRole.FROM,
        Participation.person_id.in_(persons),
    )


def _escaped(value: str) -> str:
    """value for a LIKE pattern, its wildcards taken literally; PostgreSQL's escape is \\."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _kept_sources() -> tuple[Select[Any], ...]:
    """The contents in an Akte, with a note, and bookmarked or reviewed relevant (D203)."""
    marked = or_(MailMark.flagged.is_(True), MailMark.review == ReviewStatus.RELEVANT)
    return (
        select(CollectionMail.mail_sha256),
        select(Note.mail_sha256),
        select(MailMark.mail_sha256).where(marked),
    )


def kept() -> ColumnElement[bool]:
    """The mail's content stays visible whatever the rules say (D203)."""
    return or_(*(Mail.raw_sha256.in_(source) for source in _kept_sources()))


def visible() -> ColumnElement[bool]:
    """No enabled rule matches the mail, or it is kept (D222). One NOT EXISTS, which PostgreSQL
    runs as an anti join: index probes of ix_mail_hidden_mail_id along a page of the list, one
    hash of mail_hidden for a count. Written as an OR of "no row" and kept(), it would hash every
    row of mail_hidden for each page, however few mails the page reads."""
    return ~exists().where(MailHidden.mail_id == Mail.id, ~kept())


def shown() -> ColumnElement[bool]:
    """visible() as a column of many mails, as a count reads it: here the OR lets PostgreSQL
    hash mail_hidden once instead of probing it mail by mail."""
    return or_(~exists().where(MailHidden.mail_id == Mail.id), kept())


# Storing a rule's mails ------------------------------------------------------------------------


async def store_rule(session: AsyncSession, rule_id: int) -> HideRule | None:
    """Replace the rule's mail_hidden rows by its matches, none when it is disabled, and set its
    mails and computed_at; the rule, or None when there is none. Locks the rule's row first, so
    a save and the step never compute one rule at the same time. In the caller's transaction."""
    rule = await session.scalar(
        select(HideRule)
        .where(HideRule.id == rule_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if rule is None:
        return None
    if rule.enabled:
        rule.mails = await _replace(session, rule)
    else:
        await session.execute(delete(MailHidden).where(MailHidden.rule_id == rule.id))
        rule.mails = 0
    rule.computed_at = await session.scalar(select(func.now()))
    await session.flush()
    return rule


async def _replace(session: AsyncSession, rule: HideRule) -> int:
    """One statement: the rows of mails the rule no longer matches deleted, those of new matches
    added, so a run that changes nothing writes nothing; the mails it matches."""
    target = select(Mail.id).where(matches(rule)).cte("target")
    gone = (
        delete(MailHidden)
        .where(MailHidden.rule_id == rule.id, ~exists().where(target.c.id == MailHidden.mail_id))
        .returning(MailHidden.mail_id)
        .cte("gone")
    )
    added = (
        postgresql.insert(MailHidden)
        .from_select(["rule_id", "mail_id"], select(literal(rule.id, BigInteger), target.c.id))
        .on_conflict_do_nothing()
        .returning(MailHidden.mail_id)
        .cte("added")
    )
    counted = select(
        select(func.count()).select_from(target).scalar_subquery(),
        select(func.count()).select_from(gone).scalar_subquery(),
        select(func.count()).select_from(added).scalar_subquery(),
    )
    mails, _, _ = (await session.execute(counted)).one()
    return int(mails)


# Figures ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HiddenFigures:
    """The mails an enabled rule matches, kept ones included, when they were last counted."""

    computed_at: datetime
    mails: int
    dkim: dict[str, int]  # by DkimStatus value and UNCHECKED, only those with mails

    def to_json(self) -> dict[str, Any]:
        return asdict(self) | {"computed_at": self.computed_at.isoformat()}

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "HiddenFigures":
        return cls(
            computed_at=datetime.fromisoformat(value["computed_at"]),
            mails=value["mails"],
            dkim=dict(value["dkim"]),
        )


async def read_figures(db: Executor) -> HiddenFigures | None:
    """The stored figures; None before any rule was saved or any step hidden ran."""
    value = await db.scalar(select(GlobalStats.value).where(GlobalStats.key == FIGURES_KEY))
    return None if value is None else HiddenFigures.from_json(value)


async def refresh_figures(db: Executor) -> HiddenFigures:
    """Count and store the figures, in the caller's transaction, which then holds the lock."""
    await db.execute(select(func.pg_advisory_xact_lock(_LOCK_KEY)))
    counts = await _dkim_counts(db, exists().where(MailHidden.mail_id == Mail.id))
    computed_at = await db.scalar(select(func.now()))
    assert computed_at is not None
    figures = HiddenFigures(computed_at, sum(counts.values()), counts)
    statement = postgresql.insert(GlobalStats).values(key=FIGURES_KEY, value=figures.to_json())
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[GlobalStats.key],
            set_={"value": statement.excluded.value, "updated_at": func.now()},
        )
    )
    return figures


async def current_figures(session: AsyncSession, since: datetime) -> HiddenFigures:
    """The stored figures, counted again first when missing or older than since (the archive's
    figures, so that a DKIM recheck reaches them too). Its own short transaction."""
    async with session.begin():
        figures = await read_figures(session)
        if figures is None or figures.computed_at < since:
            figures = await refresh_figures(session)
    return figures


async def kept_counts(db: Executor) -> dict[str, int]:
    """The mails an enabled rule matches that stay visible now (D203), by DKIM key: looked up
    from the kept contents, which the team made by hand, as an array, so that PostgreSQL reads
    their mails from ix_mail_raw_sha256 instead of every mail."""
    contents = func.array(union(*_kept_sources()).scalar_subquery(), type_=ARRAY(Text))
    in_kept = Mail.raw_sha256 == any_(contents)
    return await _dkim_counts(db, in_kept, exists().where(MailHidden.mail_id == Mail.id))


async def _dkim_counts(db: Executor, *where: ColumnElement[bool]) -> dict[str, int]:
    rows = await db.execute(
        select(Mail.dkim_status, func.count()).where(*where).group_by(Mail.dkim_status)
    )
    counts: Counter[str] = Counter()
    for status, count in rows:
        counts[UNCHECKED if status is None else status.value] += count
    return dict(counts)
