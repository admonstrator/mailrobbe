"""The signals phase of an import (D135): every rule of D132 to D134 applied to every mail and
person in the database again; nothing is read from the MBOX files.

    zone        a time zone PostgreSQL does not know fails the phase before anything is written
                (D133, UnknownTimeZone)
    addresses   every person (address) once into the temporary table signal_person: its root,
                the root's kind, its class (D131: the domain equal to or a subdomain of an
                internal domain, else of a private one, else external) and whether it is a
                private address of a person with an internal one (merged or an alias
                suggestion sharing a main name, D160: private_alias); the mails of automated
                senders (mail.automated or a sender whose root is of kind automated) into
                signal_automated. Both are analysed, since autovacuum never looks at temporary
                tables.
    mails       rows of signals the rules no longer know deleted; then per signal of the rules,
                in display order, one transaction: its rows of mail_signal deleted and, when
                the signal is available, inserted again by one INSERT ... SELECT over
                participation, mail and attachment (term signals: the entity mentions of
                entities.mentions), each a hash join or aggregate linear in mails and
                participations. Mails of automated senders get the term signals only;
                duplicates get theirs like every mail.
    persons     one transaction: person_signal replaced by the mails each root person that is
                no list and no automated sender sent with each signal (no duplicates), and the
                persons fallen silent (D134: their mails per UTC month, streamed and grouped
                per person, under signals.model.silence); then the figures in global_stats
                'signals' (model.SignalFigures).

A stop (D46) ends the phase between two signals: the signals replaced so far stay, the figures
are not written, and the next import does everything again. The step counts the phase's
transactions (a signal each, then the persons), so a stop shows as stopped; the database
activity (D111) is its sign of life.
"""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from mailrobbe.enums import SignalKind
from mailrobbe.signals.model import (
    FORWARD_MIME_TYPE,
    SignalFigures,
    SignalRules,
    archive_months,
    forward_pattern,
    known_timezone,
    signal_theme,
    silence,
    write_figures,
)

log = logging.getLogger(__name__)

_TABLES = ("signal_person", "signal_automated")
# A domain d.domain in the list :{name}, or a subdomain of one (model.in_domains).
_IN_LIST = """EXISTS (
    SELECT 1 FROM unnest(CAST(:{name} AS text[])) AS l(entry)
    WHERE d.domain = l.entry OR right(d.domain, length(l.entry) + 1) = '.' || l.entry)"""
_ADDRESSES = (
    *(f"DROP TABLE IF EXISTS {table}" for table in _TABLES),
    """CREATE TEMP TABLE signal_person (
        id bigint PRIMARY KEY, root bigint NOT NULL, kind person_kind, class text NOT NULL,
        alias boolean NOT NULL DEFAULT false)""",
    # Each distinct domain is classified once: there are far fewer than addresses.
    f"""WITH domains AS (SELECT DISTINCT domain FROM person),
    classes AS (
        SELECT d.domain, CASE WHEN {_IN_LIST.format(name="internal")} THEN 'internal'
            WHEN {_IN_LIST.format(name="private")} THEN 'private' ELSE 'external' END AS class
        FROM domains d
    )
    INSERT INTO signal_person (id, root, kind, class)
    SELECT p.id, r.id, r.kind, c.class
    FROM person p JOIN person r ON r.id = coalesce(p.merged_into, p.id)
    JOIN classes c ON c.domain = p.domain""",
    # Private addresses of a root that has an internal address too, or that shares a main name in
    # an alias suggestion with a root that has one, certain or not (D132, D160).
    """WITH internal AS (SELECT DISTINCT root FROM signal_person WHERE class = 'internal'),
    pairs AS (
        SELECT a.root AS one, b.root AS other FROM alias_suggestion s
        JOIN signal_person a ON a.id = s.person_a JOIN signal_person b ON b.id = s.person_b
        WHERE s.same_name IS NOT NULL
    ),
    linked AS (
        SELECT root FROM internal
        UNION SELECT p.one FROM pairs p JOIN internal i ON i.root = p.other
        UNION SELECT p.other FROM pairs p JOIN internal i ON i.root = p.one
    )
    UPDATE signal_person a SET alias = true FROM linked l
    WHERE a.root = l.root AND a.class = 'private'""",
    "CREATE TEMP TABLE signal_automated (mail_id bigint PRIMARY KEY)",
    """INSERT INTO signal_automated
    SELECT id FROM mail WHERE automated
    UNION
    SELECT p.mail_id FROM participation p JOIN signal_person a ON a.id = p.person_id
    WHERE p.role = 'from' AND a.kind = 'automated'""",
    "ANALYZE signal_person",
    "ANALYZE signal_automated",
)

# The mails of each signal of D132 but the term signals, as distinct mail_id.
_FORWARDS = """
    SELECT id AS mail_id FROM mail WHERE subject ~* :forward
    UNION SELECT mail_id FROM attachment WHERE lower(mime_type) = :attached_mail"""
_SENT = """
    SELECT DISTINCT s.mail_id
    FROM participation s JOIN signal_person a ON a.id = s.person_id
    JOIN participation r ON r.mail_id = s.mail_id AND r.role <> 'from'
    JOIN signal_person b ON b.id = r.person_id
    WHERE s.role = 'from' AND a.class = '{sender}' AND b.class = '{recipient}'"""
_RULES: dict[SignalKind, str] = {
    SignalKind.PRIVATE: """
        SELECT DISTINCT p.mail_id FROM participation p
        JOIN signal_person a ON a.id = p.person_id WHERE a.class = 'private'""",
    SignalKind.INTERNAL_TO_PRIVATE: _SENT.format(sender="internal", recipient="private"),
    SignalKind.PRIVATE_TO_INTERNAL: _SENT.format(sender="private", recipient="internal"),
    SignalKind.PRIVATE_ALIAS: """
        SELECT DISTINCT p.mail_id FROM participation p
        JOIN signal_person a ON a.id = p.person_id WHERE a.alias""",
    SignalKind.BCC: "SELECT DISTINCT mail_id FROM participation WHERE role = 'bcc'",
    SignalKind.MANY_RECIPIENTS: """
        SELECT mail_id FROM (
            SELECT DISTINCT mail_id, person_id FROM participation WHERE role <> 'from'
        ) r GROUP BY mail_id HAVING count(*) >= :many""",
    SignalKind.FORWARD: _FORWARDS,
    # A private recipient, or an internal sender and a recipient who is not internal; without
    # internal domains no sender is internal.
    SignalKind.FORWARD_OUT: f"""
        SELECT f.mail_id FROM ({_FORWARDS}) f
        JOIN participation p ON p.mail_id = f.mail_id
        JOIN signal_person a ON a.id = p.person_id
        GROUP BY f.mail_id
        HAVING bool_or(p.role <> 'from' AND a.class = 'private')
            OR (bool_or(p.role = 'from' AND a.class = 'internal')
                AND bool_or(p.role <> 'from' AND a.class <> 'internal'))""",
    SignalKind.NIGHT: """
        SELECT id AS mail_id FROM mail
        WHERE CAST(extract(hour FROM timezone(:zone, date_utc)) AS integer)
            = ANY(CAST(:hours AS integer[]))""",
    SignalKind.WEEKEND: """
        SELECT id AS mail_id FROM mail
        WHERE extract(isodow FROM timezone(:zone, date_utc)) IN (6, 7)""",
}
_INSERT = """
    INSERT INTO mail_signal (signal, mail_id)
    SELECT CAST(:signal AS text), x.mail_id FROM ({rule}) x
    WHERE NOT EXISTS (SELECT 1 FROM signal_automated a WHERE a.mail_id = x.mail_id)"""
_INSERTS = {kind: text(_INSERT.format(rule=rule)) for kind, rule in _RULES.items()}
# A term of the theme's word field mentioned in the mail or one of its attachments (D132): the
# two parts of entities.mentions, each joined to the term entities, so that the primary keys of
# mail_entity and document_entity apply; joined to the union as one relation, PostgreSQL scans
# every mention in a document once per term. Automated mails get these too.
_TERMS = text("""
    INSERT INTO mail_signal (signal, mail_id)
    SELECT CAST(:signal AS text), x.mail_id FROM (
        SELECT m.mail_id FROM entity e JOIN mail_entity m ON m.entity_id = e.id
        WHERE e.kind = 'term' AND e.detail = :theme
        UNION
        SELECT a.mail_id FROM entity e JOIN document_entity d ON d.entity_id = e.id
        JOIN attachment a ON a.document_id = d.document_id
        WHERE e.kind = 'term' AND e.detail = :theme
    ) x
""")
_FORGET = text("DELETE FROM mail_signal WHERE signal = :signal")
_FORGET_UNKNOWN = text("DELETE FROM mail_signal WHERE signal <> ALL(CAST(:keys AS text[]))")

# The mails each root person that is no list and no automated sender sent with each signal,
# its own and its aliases' (D135), duplicates left out.
_SENDERS = text("""
    INSERT INTO person_signal (signal, person_id, mails)
    SELECT x.signal, x.root, count(*) FROM (
        SELECT DISTINCT s.signal, a.root, s.mail_id
        FROM mail_signal s JOIN mail m ON m.id = s.mail_id
        JOIN participation p ON p.mail_id = s.mail_id
        JOIN signal_person a ON a.id = p.person_id
        WHERE m.is_duplicate_of IS NULL AND p.role = 'from' AND a.kind IS NULL
    ) x GROUP BY x.signal, x.root
""")
# Their dated mails in any role per UTC month (D134), ordered by person.
_MONTHS = text("""
    SELECT x.root, x.month, count(*) FROM (
        SELECT DISTINCT a.root, p.mail_id,
            CAST(date_trunc('month', timezone('UTC', m.date_utc)) AS date) AS month
        FROM participation p JOIN signal_person a ON a.id = p.person_id
        JOIN mail m ON m.id = p.mail_id
        WHERE a.kind IS NULL AND m.is_duplicate_of IS NULL AND m.date_utc IS NOT NULL
    ) x GROUP BY x.root, x.month ORDER BY x.root, x.month
""").execution_options(yield_per=10_000)
_SILENT = text(f"""
    INSERT INTO person_signal (signal, person_id, mails, since)
    SELECT '{SignalKind.SILENT.value}', u.person_id, u.mails, u.since
    FROM unnest(CAST(:persons AS bigint[]), CAST(:mails AS integer[]),
        CAST(:since AS timestamptz[])) AS u(person_id, mails, since)
""")
_ORIGINALS = text("SELECT count(*) FROM mail WHERE is_duplicate_of IS NULL")
_MAIL_COUNTS = text("""
    SELECT s.signal, count(*) FROM mail_signal s JOIN mail m ON m.id = s.mail_id
    WHERE m.is_duplicate_of IS NULL GROUP BY s.signal
""")
_PERSON_COUNTS = text("SELECT signal, count(*) FROM person_signal GROUP BY signal")


class UnknownTimeZone(Exception):
    """MAILROBBE_TIMEZONE names a zone PostgreSQL does not know (D133)."""


class Progress(Protocol):
    """The import's step (jobrun.Step without a unit): the phase sets its total to the number
    of its transactions and counts each one done."""

    total: int | None

    def advance(self, count: int = 1) -> None: ...


@dataclass(slots=True)
class SignalPhaseResult:
    """What one compute_signals did, for its log lines and the tests."""

    mails: dict[str, int] = field(default_factory=dict)  # per signal replaced: rows written
    forgotten: int = 0  # rows of signals the rules no longer know, deleted
    seconds: float = 0.0
    stopped: bool = False
    figures: SignalFigures | None = None  # None after a stop


async def compute_signals(
    engine: AsyncEngine, rules: SignalRules, stop: asyncio.Event, step: Progress
) -> SignalPhaseResult:
    """Compute every signal under rules until done or `stop` is set (module docstring); raises
    UnknownTimeZone before writing anything when PostgreSQL does not know rules.timezone."""
    started = time.monotonic()
    result = SignalPhaseResult()
    async with engine.connect() as connection:
        if not await known_timezone(connection, rules.timezone):
            raise UnknownTimeZone(
                f"PostgreSQL does not know the time zone {rules.timezone!r}: set "
                "MAILROBBE_TIMEZONE to a name of pg_timezone_names, such as Europe/Berlin"
            )
        step.total = len(rules.keys) + 1
        parameters = {
            "internal": list(rules.internal_domains),
            "private": list(rules.private_domains),
            "forward": forward_pattern(rules.forward_prefixes),
            "attached_mail": FORWARD_MIME_TYPE,
            "many": rules.many_recipients,
            "zone": rules.timezone,
            "hours": list(rules.night_hours),
        }
        for statement in _ADDRESSES:
            await connection.execute(text(statement), parameters)
        forgotten = await connection.execute(_FORGET_UNKNOWN, {"keys": list(rules.keys)})
        result.forgotten = cast(CursorResult[Any], forgotten).rowcount
        await connection.commit()
        for key in rules.keys:
            if stop.is_set():
                break
            await _replace(connection, rules, key, parameters, result)
            step.advance()
        result.stopped = stop.is_set()
        if not result.stopped:
            await connection.execute(text("ANALYZE mail_signal"))
            await connection.commit()
            result.figures = await _persons(connection, rules)
            step.advance()
        for table in _TABLES:
            await connection.execute(text(f"DROP TABLE {table}"))
        await connection.commit()
    result.seconds = time.monotonic() - started
    _log_result(result)
    return result


async def _replace(
    connection: AsyncConnection,
    rules: SignalRules,
    key: str,
    parameters: Mapping[str, object],
    result: SignalPhaseResult,
) -> None:
    """One transaction: the rows of signal key deleted and, when available, inserted again."""
    started = time.monotonic()
    await connection.execute(_FORGET, {"signal": key})
    if not rules.available(key):
        await connection.commit()
        log.info("signal %s: not computed without MAILROBBE_INTERNAL_DOMAINS", key)
        return
    theme = signal_theme(key)
    statement = _INSERTS[SignalKind(key)] if theme is None else _TERMS
    inserted = await connection.execute(statement, {**parameters, "signal": key, "theme": theme})
    await connection.commit()
    rows = cast(CursorResult[Any], inserted).rowcount
    result.mails[key] = rows
    log.info("signal %s: %d mails in %.2f s", key, rows, time.monotonic() - started)


async def _persons(connection: AsyncConnection, rules: SignalRules) -> SignalFigures:
    """One transaction: person_signal replaced, then the figures of the phase."""
    started = time.monotonic()
    await connection.execute(text("DELETE FROM person_signal"))
    senders = cast(CursorResult[Any], await connection.execute(_SENDERS)).rowcount
    silent = await _silent(connection)
    if silent:
        persons, mails, since = zip(*silent, strict=True)
        await connection.execute(
            _SILENT, {"persons": list(persons), "mails": list(mails), "since": list(since)}
        )
    await connection.execute(text("ANALYZE person_signal"))
    signals = dict.fromkeys(rules.keys, 0)
    signals.update((key, count) for key, count in await connection.execute(_MAIL_COUNTS))
    persons_by_key = dict.fromkeys((*rules.keys, SignalKind.SILENT.value), 0)
    persons_by_key.update((key, count) for key, count in await connection.execute(_PERSON_COUNTS))
    figures = SignalFigures(
        computed_at=datetime.now(UTC),
        rules=rules.snapshot(),
        mails=await connection.scalar(_ORIGINALS) or 0,
        signals=signals,
        persons=persons_by_key,
    )
    await write_figures(connection, figures)
    await connection.commit()
    log.info(
        "signals: %d rows of senders and %d persons silent in person_signal, %.2f s",
        senders,
        len(silent),
        time.monotonic() - started,
    )
    return figures


async def _silent(connection: AsyncConnection) -> list[tuple[int, int, datetime]]:
    """The persons fallen silent (D134): person, the window's mails, the first silent month."""
    span = await archive_months(connection)
    if span is None:
        return []
    first, end = span
    found = []
    async for person, months in _monthly(connection):
        quiet = silence(months, first, end)
        if quiet is not None:
            since, mails = quiet
            found.append((person, mails, datetime(since.year, since.month, 1, tzinfo=UTC)))
    return found


async def _monthly(connection: AsyncConnection) -> AsyncIterator[tuple[int, dict[date, int]]]:
    """Each person's mails per month (_MONTHS), one person at a time."""
    person: int | None = None
    months: dict[date, int] = {}
    async for partition in (await connection.stream(_MONTHS)).partitions():
        for root, month, mails in partition:
            if root != person:
                if person is not None:
                    yield person, months
                person, months = root, {}
            months[month] = mails
    if person is not None:
        yield person, months


def _log_result(result: SignalPhaseResult) -> None:
    forgotten = (
        f", {result.forgotten} rows of signals no longer configured deleted"
        if result.forgotten
        else ""
    )
    log.info(
        "signals: %s%d signals replaced in %.1f s%s",
        "stopped; " if result.stopped else "",
        len(result.mails),
        result.seconds,
        forgotten,
    )
