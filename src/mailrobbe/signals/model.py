"""What a signal is, and what its rules read (D130 to D135): the contract between the signals
phase, the API and the export.

Keys: the SignalKind values of mails (MAIL_KINDS, in display order) and "term:<theme key>" for
each research theme of themes.toml whose word field a mail mentions; silent belongs to persons
only. SignalRules gathers what the rules read; its snapshot is stored with the figures of every
signals phase (SignalFigures in global_stats 'signals'), so the overview can tell when the rules
changed since. Time zones are applied in PostgreSQL (timezone(zone, date_utc)), which knows them
whether or not the server's Python has time zone data.

Address classes (D131): internal when the domain is one of the internal domains or a subdomain
of one; otherwise private when it is one of the private domains or a subdomain of one;
otherwise external.
"""

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal, cast

from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe.api.schemas import SignalGroup
from mailrobbe.config import Settings
from mailrobbe.db.models import GlobalStats, Mail
from mailrobbe.enums import SignalKind
from mailrobbe.themes import load_signal_lists, load_themes
from mailrobbe.timeline.buckets import axis
from mailrobbe.timeline.marks import SILENT_WINDOW, silent_from

Executor = AsyncSession | AsyncConnection
AddressClass = Literal["internal", "private", "external"]

TERM_PREFIX = "term:"
# The signals of a mail, in the order the screens list them; term signals follow them.
MAIL_KINDS: tuple[SignalKind, ...] = tuple(kind for kind in SignalKind if kind != "silent")
# Signals that compare with the owner's domains: without MAILROBBE_INTERNAL_DOMAINS no mail
# has them (D131).
NEEDS_INTERNAL = frozenset(
    {SignalKind.INTERNAL_TO_PRIVATE, SignalKind.PRIVATE_TO_INTERNAL, SignalKind.PRIVATE_ALIAS}
)
GROUPS: dict[SignalKind, SignalGroup] = {
    SignalKind.PRIVATE: "addresses",
    SignalKind.INTERNAL_TO_PRIVATE: "addresses",
    SignalKind.PRIVATE_TO_INTERNAL: "addresses",
    SignalKind.PRIVATE_ALIAS: "addresses",
    SignalKind.BCC: "recipients",
    SignalKind.MANY_RECIPIENTS: "recipients",
    SignalKind.FORWARD: "recipients",
    SignalKind.FORWARD_OUT: "recipients",
    SignalKind.NIGHT: "time",
    SignalKind.WEEKEND: "time",
    SignalKind.SILENT: "persons",
}
# German names for the CSV and the export; the web UI has its own (features/signals/labels.ts).
LABELS: dict[SignalKind, str] = {
    SignalKind.PRIVATE: "Private Adresse",
    SignalKind.INTERNAL_TO_PRIVATE: "Von intern an privat",
    SignalKind.PRIVATE_TO_INTERNAL: "Von privat an intern",
    SignalKind.PRIVATE_ALIAS: "Private Zweitadresse",
    SignalKind.BCC: "Blindkopie (Bcc)",
    SignalKind.MANY_RECIPIENTS: "Viele Empfänger",
    SignalKind.FORWARD: "Weiterleitung",
    SignalKind.FORWARD_OUT: "Weiterleitung nach außen",
    SignalKind.NIGHT: "Nachts",
    SignalKind.WEEKEND: "Wochenende",
    SignalKind.SILENT: "Verstummt",
}
# Reply prefixes a forward prefix may stand behind ("AW: WG: ..."), any case.
REPLY_PREFIXES = ("Re", "AW", "Antw", "SV", "RIF", "RES", "Odp")
FORWARD_MIME_TYPE = "message/rfc822"  # an attached mail makes a forward too (D132)


def term_signal(theme_key: str) -> str:
    """The signal of a theme's word field: "term:<theme key>"."""
    return TERM_PREFIX + theme_key


def signal_theme(key: str) -> str | None:
    """The theme key of a term signal; None for any other key."""
    return key.removeprefix(TERM_PREFIX) if key.startswith(TERM_PREFIX) else None


def signal_group(key: str) -> SignalGroup:
    """The group a signal is listed in; term signals are "wording"."""
    return "wording" if key.startswith(TERM_PREFIX) else GROUPS[SignalKind(key)]


def signal_keys() -> tuple[str, ...]:
    """Every signal of a mail as the filter knows them, whatever the settings: MAIL_KINDS, then
    the word field of each theme of themes.toml."""
    return (*MAIL_KINDS, *(term_signal(theme.key) for theme in load_themes()))


def domain_list(setting: str) -> tuple[str, ...]:
    """Domains from a setting such as MAILROBBE_INTERNAL_DOMAINS: comma-separated, any case."""
    return tuple(
        dict.fromkeys(domain for part in setting.split(",") if (domain := part.strip().lower()))
    )


@dataclass(frozen=True, slots=True)
class SignalRules:
    """Everything the rules read (D131 to D133), as the signals phase applies them."""

    internal_domains: tuple[str, ...]  # MAILROBBE_INTERNAL_DOMAINS, lowercase
    private_domains: tuple[str, ...]  # [signals] private_domains, then MAILROBBE_PRIVATE_DOMAINS
    timezone: str  # MAILROBBE_TIMEZONE
    night_from: int  # hours, local time
    night_to: int
    many_recipients: int
    forward_prefixes: tuple[str, ...]  # as written in themes.toml
    themes: tuple[tuple[str, str], ...]  # (key, name) of each research theme, in file order

    @property
    def keys(self) -> tuple[str, ...]:
        """Every signal of a mail, in display order: MAIL_KINDS, then the themes' word fields."""
        return (*MAIL_KINDS, *(term_signal(key) for key, _ in self.themes))

    def knows(self, key: str) -> bool:
        """Whether key names a signal of a mail under these rules."""
        return key in self.keys

    def available(self, key: str) -> bool:
        """Whether the phase computes this signal: known, and not one needing internal domains
        while there are none."""
        return self.knows(key) and not (key in NEEDS_INTERNAL and not self.internal_domains)

    def theme_name(self, key: str) -> str | None:
        """The theme's name of a term signal; None for any other key or an unknown theme."""
        theme = signal_theme(key)
        return next((name for key_, name in self.themes if key_ == theme), None)

    def label(self, key: str) -> str:
        """The German name of a signal, "Wortfeld <theme name>" for a term signal."""
        if key.startswith(TERM_PREFIX):
            return f"Wortfeld {self.theme_name(key) or signal_theme(key)}"
        return LABELS[SignalKind(key)]

    @property
    def night_hours(self) -> tuple[int, ...]:
        """The local hours (0 to 23) that are night: from night_from up to before night_to."""
        start, end = self.night_from, self.night_to
        if start < end:
            return tuple(range(start, end))
        return (*range(end), *range(start, 24))

    def snapshot(self) -> dict[str, Any]:
        """The rules as JSON (tuples as lists), stored with the figures of a phase and compared
        with the current rules (SignalOverview.outdated)."""
        return cast(dict[str, Any], json.loads(json.dumps(asdict(self))))


def rules(settings: Settings) -> SignalRules:
    """The rules as configured now: the settings, the table [signals] and the themes."""
    lists = load_signal_lists()
    return SignalRules(
        internal_domains=domain_list(settings.internal_domains),
        private_domains=tuple(
            dict.fromkeys((*lists.private_domains, *domain_list(settings.private_domains)))
        ),
        timezone=settings.timezone,
        night_from=lists.night_from,
        night_to=lists.night_to,
        many_recipients=lists.many_recipients,
        forward_prefixes=lists.forward_prefixes,
        themes=tuple((theme.key, theme.name) for theme in load_themes()),
    )


def in_domains(domain: str, domains: Iterable[str]) -> bool:
    """The domain is one of domains or a subdomain of one (any case)."""
    domain = domain.lower()
    return any(domain == entry or domain.endswith("." + entry) for entry in domains)


def address_class(domain: str, rules: SignalRules) -> AddressClass:
    """internal, private or external (D131); internal wins over private."""
    if in_domains(domain, rules.internal_domains):
        return "internal"
    if in_domains(domain, rules.private_domains):
        return "private"
    return "external"


def forward_pattern(prefixes: Iterable[str]) -> str:
    """The regular expression of a forwarded mail's subject (D132), the same in Python's re
    and in PostgreSQL (~*), matched in any case: from the start, list tags in brackets and
    reply or forward prefixes, then a forward prefix with its colon; a counter such as "AW[2]:"
    is allowed. Group 1 is that forward prefix as written."""
    forward = "|".join(sorted(prefixes, key=len, reverse=True))
    any_prefix = "|".join(sorted((*REPLY_PREFIXES, *prefixes), key=len, reverse=True))
    counter = r"(?:\[[0-9]+\])?"
    chain = rf"(?:(?:\[[^]]*\]|(?:{any_prefix}){counter}\s*:)\s*)*"
    return rf"^\s*{chain}({forward}){counter}\s*:"


def forward_prefix(subject: str | None, prefixes: Iterable[str]) -> str | None:
    """The forward prefix the subject carries, as written ("WG"); None when it has none."""
    if not subject:
        return None
    match = re.match(forward_pattern(prefixes), subject, re.IGNORECASE)
    return None if match is None else match.group(1)


# Silence of a person (D134) --------------------------------------------------------------------


async def archive_months(db: Executor) -> tuple[date, date] | None:
    """The first days (UTC) of the archive's first and last month: of its earliest dated mail
    and of its end, the latest date not after today (D91); None without a dated mail."""
    tomorrow = datetime.combine(datetime.now(UTC).date() + timedelta(days=1), time(), tzinfo=UTC)
    first, last = (
        await db.execute(
            select(
                func.min(Mail.date_utc), func.max(Mail.date_utc).filter(Mail.date_utc < tomorrow)
            )
        )
    ).one()
    if first is None or last is None:
        return None
    return _month(first), _month(last)


def _month(moment: datetime) -> date:
    return moment.astimezone(UTC).date().replace(day=1)


def silence(months: Mapping[date, int], first: date, end: date) -> tuple[date, int] | None:
    """The month a person's silence began and its mails in the window before (D134, the rule
    of timeline.marks.silent_from), from its mails per month (the first day of each month,
    UTC) between the archive's first month and the month of its end; None when not silent.
    Months outside that span are not counted."""
    starts = axis(first, end, "month")
    counts = [months.get(start, 0) for start in starts]
    index = silent_from(counts, "month", len(counts) - 1)
    if index is None:
        return None
    return starts[index], sum(counts[max(0, index - SILENT_WINDOW["month"]) : index])


# Figures of a phase (global_stats 'signals') ---------------------------------------------------

FIGURES_KEY = "signals"


@dataclass(frozen=True, slots=True)
class SignalFigures:
    """What the last signals phase found, and under which rules (D135)."""

    computed_at: datetime  # when the phase ended
    rules: dict[str, Any]  # SignalRules.snapshot() of the rules it applied
    mails: int  # mails that are no duplicates, the base of every share
    signals: dict[str, int]  # per signal: such mails with it; every key of those rules present
    persons: dict[str, int]  # per signal: root persons who sent one; silent: persons silent

    def to_json(self) -> dict[str, Any]:
        return asdict(self) | {"computed_at": self.computed_at.isoformat()}

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "SignalFigures":
        return cls(
            computed_at=datetime.fromisoformat(value["computed_at"]),
            rules=value["rules"],
            mails=value["mails"],
            signals=value["signals"],
            persons=value["persons"],
        )


async def read_figures(db: Executor) -> "SignalFigures | None":
    """The figures of the last signals phase; None when none ran yet."""
    value = await db.scalar(select(GlobalStats.value).where(GlobalStats.key == FIGURES_KEY))
    return None if value is None else SignalFigures.from_json(value)


async def write_figures(db: Executor, figures: SignalFigures) -> None:
    """Store the figures of a phase, in the caller's transaction."""
    statement = postgresql.insert(GlobalStats).values(key=FIGURES_KEY, value=figures.to_json())
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[GlobalStats.key],
            set_={"value": statement.excluded.value, "updated_at": func.now()},
        )
    )


async def known_timezone(db: Executor, timezone: str) -> bool:
    """Whether PostgreSQL knows the time zone (pg_timezone_names, abbreviations aside)."""
    found = await db.scalar(
        text("SELECT EXISTS (SELECT 1 FROM pg_timezone_names WHERE name = :name)"),
        {"name": timezone},
    )
    return bool(found)
