"""Calendar events (D154, D155): kinds, limits and the figures of the calendar phase, the
contract between the phase, the API and the dashboard."""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Literal, get_args

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe.db.models import GlobalStats

Executor = AsyncSession | AsyncConnection

# calendar_event.kind, the same as schemas.EventKey.
EventKind = Literal["request", "reply", "cancel"]
EVENT_KINDS: tuple[EventKind, ...] = get_args(EventKind)

FIGURES_KEY = "calendar"  # global_stats key of CalendarFigures
DESCRIPTION_LIMIT = 2_000  # characters of calendar_event.description
TEXT_LIMIT = 500  # characters of a summary, a location, a name and the other short values
EVENT_LIMIT = 100  # events kept of one mail (a calendar export can hold thousands)
ATTENDEE_LIMIT = 500  # attendees kept of one event

# The candidate rule (D154): which mails the phase reads. An iCalendar part by its type or name
# among the attachments, inline parts (no name, as Outlook sends them) by the marks of an
# invitation in the subject (after Re:, AW:, WG:, Fwd:) or in the text.
CALENDAR_TYPES = ("text/calendar", "application/ics", "text/x-vcalendar")
CALENDAR_SUFFIXES = (".ics", ".vcs")
SUBJECT_MARKS = (
    *("Einladung", "Aktualisierte Einladung", "Angenommen", "Abgelehnt"),
    *("Mit Vorbehalt angenommen", "Abgesagt", "Invitation", "Updated invitation"),
    *("Accepted", "Declined", "Tentative", "Canceled", "Cancelled"),
)
OUTLOOK_RULE = "*~*~*~*~*~*~*~*~*~*"  # Outlook's line between the time and the text
WHEN_MARKS = ("When", "Wann")  # a line starting "Wann:" together with one starting "Ort:"
WHERE_MARKS = ("Where", "Wo", "Ort")
CALENDAR_MARK = "BEGIN:VCALENDAR"

_REPLIES = frozenset({"REPLY", "COUNTER", "DECLINECOUNTER"})


def event_kind(method: str | None, status: str | None) -> EventKind:
    """The kind of an event (D154) from the METHOD of its calendar and its STATUS, any case."""
    method = (method or "").strip().upper()
    if method == "CANCEL" or (status or "").strip().upper() == "CANCELLED":
        return "cancel"
    if method in _REPLIES:
        return "reply"
    return "request"


@dataclass(frozen=True, slots=True)
class CalendarFigures:
    """What the last calendar phase found (D155)."""

    computed_at: datetime  # when the phase ended
    events: int  # rows of calendar_event
    mails: dict[EventKind, int]  # per kind: mails with an event of that kind; every kind present

    def to_json(self) -> dict[str, Any]:
        return asdict(self) | {"computed_at": self.computed_at.isoformat()}

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "CalendarFigures":
        return cls(
            computed_at=datetime.fromisoformat(value["computed_at"]),
            events=value["events"],
            mails={kind: int(value["mails"].get(kind, 0)) for kind in EVENT_KINDS},
        )


async def read_figures(db: Executor) -> CalendarFigures | None:
    """The figures of the last calendar phase; None when none ran yet."""
    value = await db.scalar(select(GlobalStats.value).where(GlobalStats.key == FIGURES_KEY))
    return None if value is None else CalendarFigures.from_json(value)


async def write_figures(db: Executor, figures: CalendarFigures) -> None:
    """Store the figures of a phase, in the caller's transaction."""
    statement = postgresql.insert(GlobalStats).values(key=FIGURES_KEY, value=figures.to_json())
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[GlobalStats.key],
            set_={"value": statement.excluded.value, "updated_at": func.now()},
        )
    )
