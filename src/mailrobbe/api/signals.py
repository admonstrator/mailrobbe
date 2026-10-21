"""Signals (milestone 12, D130 to D139): the overview, the facets of the mail list, the signals of
one mail and of one person. Endpoints and models are in schemas.py; the mail list's signal filter
(D136) is in filters.py. The rules are in signals.model, which this module only reads.

Routes: GET /api/signals, /api/mails/signals, /api/mails/{id}/signals,
/api/persons/{id}/signals. Registered before the detail router, so that /api/mails/signals is
not taken for a mail id.

The figures of the overview and of unfiltered facets are those of the last signals phase
(global_stats 'signals', person_signal); filtered facets are counted over mail_signal as the
entity facets are (D87). A mail's reasons explain its stored rows under the current rules, from
its own participants, subject, date, attachments and mentions; a person's signals are counted on
request over the mails its addresses sent, so merges count at once (D134, D137).
"""

from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import (
    Executable,
    and_,
    any_,
    distinct,
    func,
    literal_column,
    or_,
    select,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe import aggregates
from mailrobbe.api.deps import AppSettings, Session, api_error
from mailrobbe.api.detail import MailId
from mailrobbe.api.documents import _all_unless_canceled
from mailrobbe.api.entities import FACET_FALLBACK, _ids, _ref
from mailrobbe.api.filters import resolve_contents
from mailrobbe.api.mails import _count_budget, _terms, _where
from mailrobbe.api.persons import _DUPLICATES, PersonId
from mailrobbe.api.schemas import (
    FACET_MAILS,
    SIGNAL_DOMAINS,
    SIGNAL_SENDERS,
    SILENT_LISTED,
    DomainCount,
    EntityRef,
    MailFilters,
    MailSignals,
    PersonCount,
    PersonRef,
    PersonSignalCount,
    PersonSignals,
    SignalFacets,
    SignalInfo,
    SignalOverview,
    SignalReason,
    SignalSettings,
    SilentPerson,
)
from mailrobbe.db.models import (
    AliasSuggestion,
    Attachment,
    Entity,
    Mail,
    MailSignal,
    Participation,
    Person,
    PersonSignal,
)
from mailrobbe.entities.mentions import mentions
from mailrobbe.enums import EntityKind, ParticipationRole, SignalKind
from mailrobbe.persons.labels import attach_labels
from mailrobbe.persons.roots import ROOT, member_ids, resolve_root
from mailrobbe.signals.model import (
    FORWARD_MIME_TYPE,
    AddressClass,
    SignalRules,
    address_class,
    archive_months,
    forward_prefix,
    in_domains,
    known_timezone,
    read_figures,
    rules,
    signal_group,
    signal_theme,
    silence,
)

router = APIRouter(prefix="/api", tags=["signals"])

_ROLE_ORDER = {role: index for index, role in enumerate(ParticipationRole)}
_NAME = func.coalesce(Participation.display_name, Person.display_name)  # as used in that mail
_PERSON_COLUMNS = (Person.id, Person.canonical_email, Person.display_name)


def _person(row: Any) -> PersonRef:
    """A root person with its own display name."""
    return PersonRef(person_id=row.id, email=row.canonical_email, name=row.display_name)


# Overview ------------------------------------------------------------------------------------


@router.get("/signals")
async def signal_overview(session: Session, settings: AppSettings) -> SignalOverview:
    signal_rules = rules(settings)
    figures = await read_figures(session)
    mail_counts = {} if figures is None else figures.signals
    person_counts = {} if figures is None else figures.persons
    senders = await _senders(session, signal_rules.keys)
    sender_domains = []
    if not signal_rules.internal_domains:
        # The list in global_stats, most mails first; read beyond SIGNAL_DOMAINS, as private
        # providers among them are left out.
        sender_domains = [
            DomainCount(domain=domain, mails=count)
            for domain, count in await aggregates.read_sender_domains(session)
            if not in_domains(domain, signal_rules.private_domains)
        ][:SIGNAL_DOMAINS]
    overview = SignalOverview(
        signals=[
            SignalInfo(
                key=key,
                group=signal_group(key),
                theme=signal_rules.theme_name(key),
                available=signal_rules.available(key),
                mails=mail_counts.get(key, 0),
                persons=person_counts.get(key, 0),
                senders=senders.get(key, []),
            )
            for key in signal_rules.keys
        ],
        settings=SignalSettings(
            internal_domains=list(signal_rules.internal_domains),
            private_domains=len(signal_rules.private_domains),
            timezone=signal_rules.timezone,
            timezone_known=await known_timezone(session, signal_rules.timezone),
            night_from=signal_rules.night_from,
            night_to=signal_rules.night_to,
            many_recipients=signal_rules.many_recipients,
            forward_prefixes=list(signal_rules.forward_prefixes),
        ),
        computed_at=None if figures is None else figures.computed_at,
        outdated=figures is not None and figures.rules != signal_rules.snapshot(),
        mails=0 if figures is None else figures.mails,
        silent=await _silent(session),
        silent_count=person_counts.get(SignalKind.SILENT, 0),
        sender_domains=sender_domains,
    )
    await attach_labels(session, overview)
    return overview


async def _senders(session: AsyncSession, keys: Sequence[str]) -> dict[str, list[PersonCount]]:
    """Per signal the root persons who sent most mails with it at the last phase, each read
    backwards from ix_person_signal_mails; persons merged since are left out."""
    tops = [
        select(PersonSignal.signal, PersonSignal.mails, *_PERSON_COLUMNS)
        .join(Person, Person.id == PersonSignal.person_id)
        .where(PersonSignal.signal == key, Person.merged_into.is_(None))
        .order_by(PersonSignal.mails.desc(), PersonSignal.person_id.desc())
        .limit(SIGNAL_SENDERS)
        .subquery()
        for key in keys
    ]
    rows = await session.execute(union_all(*(select(top) for top in tops)))
    found: dict[str, list[PersonCount]] = {}
    for row in sorted(rows, key=lambda row: (-row.mails, -row.id)):
        found.setdefault(row.signal, []).append(PersonCount(person=_person(row), mails=row.mails))
    return found


async def _silent(session: AsyncSession) -> list[SilentPerson]:
    """The persons fallen silent at the last phase, most mails before their silence first."""
    rows = await session.execute(
        select(PersonSignal.mails, PersonSignal.since, *_PERSON_COLUMNS)
        .join(Person, Person.id == PersonSignal.person_id)
        .where(PersonSignal.signal == SignalKind.SILENT, Person.merged_into.is_(None))
        .order_by(PersonSignal.mails.desc(), PersonSignal.person_id.desc())
        .limit(SILENT_LISTED)
    )
    return [SilentPerson(person=_person(row), since=row.since, mails=row.mails) for row in rows]


# Facets --------------------------------------------------------------------------------------


@router.get("/mails/signals")
async def signal_facets(
    filters: Annotated[MailFilters, Query()], session: Session, settings: AppSettings
) -> SignalFacets:
    keys = rules(settings).keys
    where = _where(filters, _terms(filters.q), settings)
    if not where:
        figures = await read_figures(session)
        stored = {} if figures is None else figures.signals
        return SignalFacets(signals=_in_order(keys, stored), mails=None, sampled=False)
    where = await resolve_contents(session, where)
    await _count_budget(session, settings)
    ids: list[int] | None = None
    for size in (FACET_MAILS, FACET_FALLBACK):
        if ids is None:
            matched = select(Mail.id).where(*where).limit(size + 1)
            found = await _all_unless_canceled(session, matched)
            ids = None if found is None else [row.id for row in found]
        if ids is None:
            continue
        sample = ids[:size]
        counted = await _all_unless_canceled(session, _signal_counts(sample))
        if counted is not None:
            signals = _in_order(keys, {row.signal: row.mails for row in counted})
            return SignalFacets(signals=signals, mails=len(sample), sampled=len(ids) > size)
    return SignalFacets(signals={}, mails=None, sampled=False)


def _signal_counts(mail_ids: Sequence[int]) -> Executable:
    """Per signal the mails among mail_ids with it (ix_mail_signal_mail_id); a mail has a signal
    once, so its rows count mails."""
    return (
        select(MailSignal.signal, func.count().label("mails"))
        .where(MailSignal.mail_id == any_(_ids(mail_ids)))
        .group_by(MailSignal.signal)
    )


def _in_order(keys: Sequence[str], counts: dict[str, int]) -> dict[str, int]:
    """The counts of these keys that are above 0, in the order of keys."""
    return {key: counts[key] for key in keys if counts.get(key, 0) > 0}


# One mail ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Participant:
    role: ParticipationRole
    person: PersonRef  # the address, with the display name used in this mail
    address: AddressClass
    root: int


@dataclass(frozen=True, slots=True)
class _Facts:
    """What the reasons of one mail read, each only when one of its signals needs it."""

    participants: list[_Participant]  # by role, then person id
    aliases: set[int]  # roots of private participants that have an internal address too
    prefix: str | None  # the subject's forward prefix
    attached: str | None  # the file name of the first attached mail
    local_time: str | None
    terms: dict[str, list[EntityRef]]  # by theme key


@router.get("/mails/{mail_id}/signals")
async def mail_signals(mail_id: MailId, session: Session, settings: AppSettings) -> MailSignals:
    found = await session.execute(select(Mail.subject, Mail.date_utc).where(Mail.id == mail_id))
    mail = found.one_or_none()
    if mail is None:
        raise api_error(404, "not_found", f"no mail with id {mail_id}")
    signal_rules = rules(settings)
    stored = set(
        await session.scalars(select(MailSignal.signal).where(MailSignal.mail_id == mail_id))
    )
    keys = [key for key in signal_rules.keys if key in stored]
    reasons = []
    if keys:
        participants = await _participants(session, mail_id, signal_rules)
        aliases: set[int] = set()
        if SignalKind.PRIVATE_ALIAS in stored:
            private = {p.root for p in participants if p.address == "private"}
            aliases = await _alias_roots(session, private, signal_rules)
        forwarded = bool(stored & {SignalKind.FORWARD, SignalKind.FORWARD_OUT})
        timed = bool(stored & {SignalKind.NIGHT, SignalKind.WEEKEND})
        facts = _Facts(
            participants=participants,
            aliases=aliases,
            prefix=forward_prefix(mail.subject, signal_rules.forward_prefixes),
            attached=await _attached_mail(session, mail_id) if forwarded else None,
            local_time=(
                await _local_time(session, mail_id, mail.date_utc, signal_rules.timezone)
                if timed and mail.date_utc is not None
                else None
            ),
            terms=await _terms_found(session, mail_id, keys),
        )
        reasons = [_reason(key, signal_rules, facts) for key in keys]
    figures = await read_figures(session)
    signals = MailSignals(
        signals=reasons,
        timezone=signal_rules.timezone,
        computed_at=None if figures is None else figures.computed_at,
    )
    await attach_labels(session, signals)
    return signals


def _reason(key: str, signal_rules: SignalRules, facts: _Facts) -> SignalReason:
    """What makes the signal hold for the mail (D132)."""
    senders = [p for p in facts.participants if p.role is ParticipationRole.FROM]
    recipients = [p for p in facts.participants if p.role is not ParticipationRole.FROM]

    def of(found: Iterable[_Participant], *classes: AddressClass) -> list[_Participant]:
        return [p for p in found if p.address in classes]

    concerned: list[_Participant] = []
    match key:
        case SignalKind.PRIVATE:
            concerned = of(facts.participants, "private")
        case SignalKind.INTERNAL_TO_PRIVATE:
            concerned = [*of(senders, "internal"), *of(recipients, "private")]
        case SignalKind.PRIVATE_TO_INTERNAL:
            concerned = [*of(senders, "private"), *of(recipients, "internal")]
        case SignalKind.PRIVATE_ALIAS:
            concerned = [p for p in of(facts.participants, "private") if p.root in facts.aliases]
        case SignalKind.BCC:
            concerned = [p for p in recipients if p.role is ParticipationRole.BCC]
        case SignalKind.FORWARD_OUT:
            # with internal domains, from an internal sender every recipient outside counts
            inside = bool(signal_rules.internal_domains) and bool(of(senders, "internal"))
            concerned = (
                of(recipients, "private", "external") if inside else of(recipients, "private")
            )
    persons: dict[int, PersonRef] = {}  # each person once, as in its first role
    for p in concerned:
        persons.setdefault(p.person.person_id, p.person)
    forward = key in (SignalKind.FORWARD, SignalKind.FORWARD_OUT)
    theme = signal_theme(key)
    return SignalReason(
        key=key,
        group=signal_group(key),
        theme=signal_rules.theme_name(key),
        persons=list(persons.values()),
        local_time=facts.local_time if key in (SignalKind.NIGHT, SignalKind.WEEKEND) else None,
        recipients=(
            len({p.person.person_id for p in recipients})
            if key == SignalKind.MANY_RECIPIENTS
            else None
        ),
        forward_prefix=facts.prefix if forward else None,
        forwarded_mail=facts.attached if forward else None,
        terms=[] if theme is None else facts.terms.get(theme, []),
    )


async def _participants(
    session: AsyncSession, mail_id: int, signal_rules: SignalRules
) -> list[_Participant]:
    """The mail's participants by role (From, To, Cc, Bcc), then person id, with the class of
    their address (D131) and their root person."""
    rows = await session.execute(
        select(
            Participation.role,
            Person.id,
            Person.canonical_email,
            _NAME.label("name"),
            Person.domain,
            ROOT.label("root"),
        )
        .join(Person, Person.id == Participation.person_id)
        .where(Participation.mail_id == mail_id)
    )
    participants = [
        _Participant(
            role=row.role,
            person=PersonRef(person_id=row.id, email=row.canonical_email, name=row.name),
            address=address_class(row.domain, signal_rules),
            root=row.root,
        )
        for row in rows
    ]
    return sorted(participants, key=lambda p: (_ROLE_ORDER[p.role], p.person.person_id))


async def _alias_roots(
    session: AsyncSession, roots: Collection[int], signal_rules: SignalRules
) -> set[int]:
    """Of these root persons, those with an internal address too: one of their own, or one of
    a person they form an open alias suggestion with (D30, D132)."""
    if not roots:
        return set()
    asked = _ids(sorted(roots))
    pairs = await session.execute(
        select(AliasSuggestion.person_a, AliasSuggestion.person_b).where(
            or_(AliasSuggestion.person_a == any_(asked), AliasSuggestion.person_b == any_(asked))
        )
    )
    partners = {root: {root} for root in roots}
    for person_a, person_b in pairs:
        for one, other in ((person_a, person_b), (person_b, person_a)):
            if one in partners:
                partners[one].add(other)
    everyone = _ids(sorted(set().union(*partners.values())))
    members = await session.execute(
        select(ROOT, Person.domain).where(
            or_(Person.id == any_(everyone), Person.merged_into == any_(everyone))
        )
    )
    internal = {
        root for root, domain in members if address_class(domain, signal_rules) == "internal"
    }
    return {root for root, others in partners.items() if others & internal}


async def _attached_mail(session: AsyncSession, mail_id: int) -> str | None:
    """The file name of the mail's first attached mail, "" when unnamed; None without one."""
    found = await session.execute(
        select(Attachment.filename)
        .where(Attachment.mail_id == mail_id, Attachment.mime_type == FORWARD_MIME_TYPE)
        .order_by(Attachment.position, Attachment.id)
        .limit(1)
    )
    row = found.one_or_none()
    return None if row is None else row.filename or ""


async def _local_time(
    session: AsyncSession, mail_id: int, date_utc: datetime, zone: str
) -> str | None:
    """The mail's date in the time zone as ISO 8601 with the zone's offset at that moment, as
    PostgreSQL converts it (D133); None for a zone it does not know."""
    if not await known_timezone(session, zone):
        return None
    wall: datetime | None = await session.scalar(
        select(func.timezone(zone, Mail.date_utc)).where(Mail.id == mail_id)
    )
    if wall is None:
        return None
    offset = wall - date_utc.astimezone(UTC).replace(tzinfo=None)
    return wall.replace(tzinfo=timezone(offset)).isoformat()


async def _terms_found(
    session: AsyncSession, mail_id: int, keys: Sequence[str]
) -> dict[str, list[EntityRef]]:
    """Per theme of these term signals, its terms mentioned in the mail or in its attachments,
    by label in code point order, then id."""
    themes = [theme for key in keys if (theme := signal_theme(key)) is not None]
    if not themes:
        return {}
    mention = mentions()
    rows = await session.execute(
        select(Entity.id, Entity.kind, Entity.label, Entity.detail)
        .distinct()
        .join_from(mention, Entity, Entity.id == mention.c.entity_id)
        .where(
            mention.c.mail_id == mail_id,
            Entity.kind == EntityKind.TERM,
            Entity.detail.in_(themes),
        )
    )
    found: dict[str, list[EntityRef]] = {}
    for row in sorted(rows, key=lambda row: (row.label, row.id)):
        found.setdefault(row.detail, []).append(_ref(row))
    return found


# One person ----------------------------------------------------------------------------------


@router.get("/persons/{person_id}/signals")
async def person_signals(
    person_id: PersonId, session: Session, settings: AppSettings
) -> PersonSignals:
    root = await resolve_root(session, person_id)
    if root is None:
        raise api_error(404, "not_found", f"no person with id {person_id}")
    members = await member_ids(session, root)
    signal_rules = rules(settings)
    figures = await read_figures(session)
    # The mails its addresses sent that are no duplicates (ix_participation_person_id_role),
    # and the signals of those mails (ix_mail_signal_mail_id).
    sent_by = and_(
        Participation.person_id == any_(_ids(members)),
        Participation.role == ParticipationRole.FROM,
        Participation.mail_id.not_in(_DUPLICATES),
    )
    mails = func.count(distinct(Participation.mail_id))
    sent = await session.scalar(select(mails).where(sent_by))
    counted = {
        signal: count
        for signal, count in await session.execute(
            select(MailSignal.signal, mails)
            .join(MailSignal, MailSignal.mail_id == Participation.mail_id)
            .where(sent_by)
            .group_by(MailSignal.signal)
        )
    }
    silent = await _silence(session, root, members)

    def share(key: str) -> float | None:
        if figures is None or not figures.mails or key not in figures.signals:
            return None
        return figures.signals[key] / figures.mails

    return PersonSignals(
        sent=sent or 0,
        signals=[
            PersonSignalCount(
                key=key,
                group=signal_group(key),
                theme=signal_rules.theme_name(key),
                mails=counted[key],
                archive_share=share(key),
            )
            for key in signal_rules.keys
            if counted.get(key, 0) > 0
        ],
        silent_since=None if silent is None else datetime.combine(silent[0], time(), tzinfo=UTC),
        silent_mails=None if silent is None else silent[1],
    )


async def _silence(
    session: AsyncSession, root: int, members: Sequence[int]
) -> tuple[date, int] | None:
    """The month a person fell silent and its mails in the window before (D134), over its
    dated mails in any role that are no duplicates per UTC month; None when it did not, or for
    a list or an automated sender."""
    if await session.scalar(select(Person.kind).where(Person.id == root)) is not None:
        return None
    span = await archive_months(session)
    if span is None:
        return None
    # literal constants: as parameters, PostgreSQL would not see GROUP BY's expression as the
    # selected one
    utc = func.timezone(literal_column("'UTC'"), Mail.date_utc)
    month = func.date_trunc(literal_column("'month'"), utc)
    rows = await session.execute(
        select(month.label("month"), func.count(distinct(Mail.id)).label("mails"))
        .select_from(Participation)
        .join(Mail, Mail.id == Participation.mail_id)
        .where(
            Participation.person_id == any_(_ids(members)),
            Mail.is_duplicate_of.is_(None),
            Mail.date_utc.is_not(None),
        )
        .group_by(month)
    )
    return silence({row.month.date(): row.mails for row in rows}, *span)
