"""Near duplicates in the mail list and the mail detail (D153), read from mail_near."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import BigInteger, any_, func, literal, literal_column, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from mailrobbe.api.schemas import NEAR_LIMIT, RECIPIENT_PREVIEW, NearMail, PersonRef
from mailrobbe.db.models import MAIL_SORT_KEY, Mail, MailNear, Participation, Person
from mailrobbe.enums import ParticipationRole

_ROLES = list(ParticipationRole)  # From, To, Cc, Bcc: the order of the mail list


@dataclass(slots=True)
class NearGroup:
    """A mail's group as MailDetail shows it; group_id None: the mail is in no group."""

    group_id: int | None = None
    mails: list[NearMail] = field(default_factory=list)  # the others, oldest first, NEAR_LIMIT
    size: int = 0  # the whole group, this mail included; 0 without a group


async def near_counts(session: AsyncSession, mail_ids: Sequence[int]) -> dict[int, int]:
    """For the mails of a list page: the other mails of each one's group; mails without one
    are left out."""
    if not mail_ids:
        return {}
    member = aliased(MailNear)
    size = select(func.count()).where(member.group_id == MailNear.group_id).scalar_subquery()
    rows = await session.execute(
        select(MailNear.mail_id, size).where(
            MailNear.mail_id == any_(literal(list(mail_ids), ARRAY(BigInteger))),
            MailNear.group_id.is_not(None),
        )
    )
    return {mail_id: members - 1 for mail_id, members in rows if members > 1}


async def near_group(session: AsyncSession, mail_id: int) -> NearGroup:
    """The group of near duplicates of one mail."""
    group_id = await session.scalar(select(MailNear.group_id).where(MailNear.mail_id == mail_id))
    if group_id is None:
        return NearGroup()
    size = await session.scalar(select(func.count()).where(MailNear.group_id == group_id)) or 0
    if size < 2:  # the others were deleted since the last import
        return NearGroup()
    rows = (
        await session.execute(
            select(Mail.id, Mail.date_utc, Mail.subject, Mail.dkim_status, Mail.is_duplicate_of)
            .join(MailNear, MailNear.mail_id == Mail.id)
            .where(MailNear.group_id == group_id, Mail.id != mail_id)
            .order_by(literal_column(MAIL_SORT_KEY), Mail.id)
            .limit(NEAR_LIMIT)
        )
    ).all()
    people = await _people(session, [row.id for row in rows])
    mails = []
    for row in rows:
        sender, recipients = people.get(row.id, (None, []))
        mails.append(
            NearMail(
                id=row.id,
                date=row.date_utc,
                subject=row.subject,
                sender=sender,
                dkim_status=row.dkim_status,
                recipients=recipients[:RECIPIENT_PREVIEW],
                recipient_count=len(recipients),
                is_duplicate=row.is_duplicate_of is not None,
            )
        )
    return NearGroup(group_id, mails, size)


async def _people(
    session: AsyncSession, mail_ids: list[int]
) -> dict[int, tuple[PersonRef | None, list[PersonRef]]]:
    """The sender and the recipients of each of these mails, in the order of the mail list:
    To, Cc, Bcc, each by name (unnamed last), then address."""
    name = func.coalesce(Participation.display_name, Person.display_name)
    rows = await session.execute(
        select(Participation.mail_id, Participation.role, Person.id, Person.canonical_email, name)
        .join(Person, Person.id == Participation.person_id)
        .where(Participation.mail_id.in_(mail_ids))
    )
    found: defaultdict[int, list[tuple[ParticipationRole, PersonRef]]] = defaultdict(list)
    for mail_id, role, person_id, email, display in rows:
        found[mail_id].append((role, PersonRef(person_id=person_id, email=email, name=display)))
    people = {}
    for mail_id, participants in found.items():
        participants.sort(
            key=lambda each: (
                _ROLES.index(each[0]),
                each[1].name is None,
                (each[1].name or "").casefold(),
                each[1].email,
            )
        )
        senders = [person for role, person in participants if role is ParticipationRole.FROM]
        others = [person for role, person in participants if role is not ParticipationRole.FROM]
        people[mail_id] = (senders[0] if senders else None, others)
    return people
