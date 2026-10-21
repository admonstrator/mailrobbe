"""Calendar events (D155): of a mail in its detail, of the mails of a list page, and of a
person: GET /api/persons/{id}/events."""

from collections.abc import Sequence

from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.deps import Session
from mailrobbe.api.persons import PersonId
from mailrobbe.api.schemas import CalendarEventInfo, EventKey, PersonEvents

router = APIRouter(prefix="/api", tags=["events"])


async def event_kinds(session: AsyncSession, mail_ids: Sequence[int]) -> dict[int, EventKey]:
    """For the mails of a list page: the kind of each one's first event; mails without one are
    left out."""
    return {}  # milestone 14: calendar invitations


async def mail_events(session: AsyncSession, mail_id: int) -> list[CalendarEventInfo]:
    """The events of one mail in mail order, with their attendees and persons."""
    return []  # milestone 14: calendar invitations


@router.get("/persons/{person_id}/events")
async def person_events(person_id: PersonId, session: Session) -> PersonEvents:
    """The events the person (its root and aliases) organised or was invited to."""
    return PersonEvents(items=[], total=0)  # milestone 14: calendar invitations
