"""The signals phase (D132 to D135) on a small archive written in SQL: every rule and its edges,
the persons' figures and silence, the phase's figures, a second run, changed rules, a stop and
an unknown time zone."""

import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mailrobbe import migrate
from mailrobbe.enums import SignalKind
from mailrobbe.signals import phase
from mailrobbe.signals.model import MAIL_KINDS, NEEDS_INTERNAL, SignalRules, read_figures
from mailrobbe.signals.phase import SignalPhaseResult, UnknownTimeZone, compute_signals
from tests.conftest import _temporary_database

pytestmark = pytest.mark.db

RULES = SignalRules(
    internal_domains=("nordwind.example",),
    # A subdomain of an internal domain in the private list: internal wins.
    private_domains=("webpost.example", "mail.nordwind.example"),
    timezone="Europe/Berlin",
    night_from=22,
    night_to=6,
    many_recipients=3,
    forward_prefixes=("Fwd", "Fw", "WG", "TR"),
    themes=(("spenden", "Spendenaffären"), ("gewalt", "Gewalt")),
)

# id, address, merged into, kind
PERSONS = (
    (1, "anna@nordwind.example", None, None),  # internal
    (2, "anna@webpost.example", 1, None),  # private, merged into an internal person
    (3, "bert@mail.nordwind.example", None, None),  # internal, though its domain is private too
    (4, "bert@webpost.example", None, None),  # private, a certain suggestion with 3 (person_b)
    (5, "dora@post.webpost.example", None, None),  # private, suggested with an external person
    (6, "emil@partner.example", None, None),  # external
    (7, "news@nordwind.example", None, "automated"),
    (8, "liste@partner.example", None, "list"),
    (9, "fritz@xwebpost.example", None, None),  # external: no subdomain of webpost.example
    (10, "ida@webpost.example", None, None),  # private, a certain suggestion with 11 (person_a)
    (11, "ida@nordwind.example", None, None),  # internal
    (12, "info@webpost.example", 7, None),  # merged into the automated sender
    (13, "otto@partner.example", None, None),  # falls silent
    (14, "otto@webpost.example", 13, None),
)
SUGGESTIONS = ((3, 4), (10, 11), (5, 6))
# id, kind, key, detail: two term entities of RULES' themes, one of a theme RULES lacks, and a
# place whose detail looks like a theme key
ENTITIES = (
    (1, "term", "spenden:spende", "spenden"),
    (2, "term", "gewalt:angriff", "gewalt"),
    (3, "term", "rassismus:hetze", "rassismus"),
    (4, "place", "köln", "spenden"),
)
DOCUMENT_ENTITIES = (2,)  # mentioned in the text of document 1
WEDNESDAY = "2024-03-13 10:00"  # 11:00 in Berlin


@dataclass(frozen=True)
class Mail:
    id: int
    sender: int
    to: tuple[int, ...] = ()
    cc: tuple[int, ...] = ()
    bcc: tuple[int, ...] = ()
    subject: str = "Angebot"
    date: str | None = WEDNESDAY  # UTC
    automated: bool = False
    duplicate_of: int | None = None
    attachments: tuple[tuple[str, int | None], ...] = ()  # MIME type, document
    entities: tuple[int, ...] = ()  # mentioned in the mail's own text
    signals: frozenset[str] = field(default_factory=frozenset)  # expected under RULES


def mail(id: int, sender: int, *signals: str, **values: Any) -> Mail:
    return Mail(id, sender, signals=frozenset(signals), **values)


PDF, ATTACHED_MAIL = "application/pdf", "Message/RFC822"
MAILS = (
    mail(1, 1, to=(6,), entities=(4,)),
    mail(2, 1, "private", "internal_to_private", to=(5,)),
    mail(3, 5, "private", "private_to_internal", to=(1,)),
    mail(4, 2, "private", "private_alias", to=(6,)),
    mail(5, 6, "private", "private_alias", to=(4,)),
    mail(6, 6, "private", "private_alias", to=(10,)),
    mail(7, 6, "private", to=(5,)),
    mail(8, 1, to=(3,)),
    mail(9, 6, to=(9,)),
    mail(10, 1, "bcc", "private", "private_alias", "internal_to_private", to=(6,), bcc=(2,)),
    mail(11, 6, "many_recipients", to=(1, 3), cc=(11,)),  # exactly the threshold
    mail(12, 6, to=(1, 3), cc=(1,)),  # two addresses, one in To and Cc
    mail(13, 1, "forward", "forward_out", to=(6,), subject="WG: Angebot"),
    mail(14, 1, "forward", to=(3,), subject="AW: Fwd: Angebot"),
    mail(15, 6, "forward", "forward_out", "private", to=(5,), subject="Fwd: Bericht"),
    mail(16, 6, "forward", to=(3,), subject="TR: Bericht"),
    mail(17, 1, to=(6,), subject="Re: Angebot"),
    mail(18, 1, "forward", to=(11,), attachments=((ATTACHED_MAIL, None),)),
    mail(19, 1, to=(6,), attachments=((PDF, None),)),
    # Berlin: summer time from 31 March 2024 01:00 UTC
    mail(20, 1, "night", to=(6,), date="2024-07-10 21:30"),  # 23:30
    mail(21, 1, to=(6,), date="2024-01-10 20:30"),  # 21:30
    mail(22, 1, "night", to=(6,), date="2024-01-14 23:30"),  # Sunday UTC, Monday 00:30
    mail(23, 1, "weekend", to=(6,), date="2024-07-13 10:00"),  # Saturday
    mail(24, 1, "night", "weekend", to=(6,), date="2024-03-30 23:30"),  # Sunday 00:30
    mail(25, 1, "night", to=(6,), date="2024-07-10 03:59"),  # 05:59
    mail(26, 1, to=(6,), date="2024-07-10 04:00"),  # 06:00
    mail(27, 1, "night", to=(6,), date="2024-07-10 20:00"),  # 22:00
    mail(28, 1, to=(6,), date="2024-07-10 19:59"),  # 21:59
    mail(29, 1, to=(6,), date=None),
    # Automated: the word fields only.
    mail(
        30,
        1,
        "term:spenden",
        to=(5,),
        bcc=(2,),
        subject="WG: x",
        automated=True,
        date="2024-07-10 21:30",
        entities=(1,),
    ),
    mail(31, 7, "term:gewalt", to=(2,), attachments=((PDF, 1),)),
    mail(32, 12, to=(5,), date="2024-07-10 21:30"),  # its sender's root is automated
    mail(33, 1, "term:spenden", to=(6,), entities=(1, 3)),
    mail(34, 6, "term:gewalt", to=(1,), attachments=((PDF, 1),)),
    # Duplicates: their signals, but not in the figures.
    mail(35, 1, "private", "internal_to_private", to=(5,), duplicate_of=2),
    mail(36, 6, "term:gewalt", to=(1,), attachments=((PDF, 1),), duplicate_of=34),
    mail(37, 8, "private", to=(5,)),  # sent by a list
    # Otto writes in five months, once from his private alias, then no more.
    mail(38, 13, to=(6,), cc=(8,), date="2024-01-15 10:00"),
    mail(39, 13, to=(6,), cc=(8,), date="2024-02-15 10:00"),
    mail(40, 13, to=(6,), cc=(8,), date="2024-03-15 10:00"),
    mail(41, 13, to=(6,), cc=(8,), date="2024-04-15 10:00"),
    mail(42, 14, "private", to=(6,), cc=(8,), date="2024-05-15 10:00"),
    mail(43, 13, to=(6,), cc=(8,), date="2024-01-15 10:00", duplicate_of=38),
    mail(44, 1, to=(6,), date="2024-12-02 10:00"),  # the archive's last month
)
# Per signal and root person: the mails it sent with it (D135).
SENDERS = {
    "private": {1: 3, 5: 1, 6: 4, 13: 1},
    "internal_to_private": {1: 2},
    "private_to_internal": {5: 1},
    "private_alias": {1: 2, 6: 2},
    "bcc": {1: 1},
    "many_recipients": {6: 1},
    "forward": {1: 3, 6: 2},
    "forward_out": {1: 1, 6: 1},
    "night": {1: 5},
    "weekend": {1: 2},
    "term:spenden": {1: 2},  # mail 30 is automated, its sender is not
    "term:gewalt": {6: 1},
}
SILENT = {13: (5, datetime(2024, 6, 1, tzinfo=UTC))}


Statement = tuple[str, dict[str, Any]]
_PERSON = """
    INSERT INTO person (id, canonical_email, domain, merged_into, kind) OVERRIDING SYSTEM VALUE
    VALUES (:id, :address, :domain, :root, CAST(:kind AS person_kind))"""
_ENTITY = """
    INSERT INTO entity (id, kind, key, label, detail) OVERRIDING SYSTEM VALUE
    VALUES (:id, CAST(:kind AS entity_kind), :key, :key, :detail)"""
_DOCUMENT = """
    INSERT INTO document (id, sha256, mime_type, size_bytes, text_status, extracted_text)
    OVERRIDING SYSTEM VALUE VALUES (1, 'doc', 'application/pdf', 100, 'text', 'Angriff')"""
_MAIL = """
    INSERT INTO mail (id, mbox_file_id, byte_offset, byte_length, raw_sha256, subject, date_utc,
        automated, is_duplicate_of) OVERRIDING SYSTEM VALUE
    VALUES (:id, 1, :offset, 100, :sha, :subject, :date, :automated, :duplicate_of)"""
_PARTICIPATION = """
    INSERT INTO participation (mail_id, person_id, role)
    VALUES (:mail, :person, CAST(:role AS participation_role))"""
_ATTACHMENT = """
    INSERT INTO attachment (mail_id, mime_type, size_bytes, position, document_id)
    VALUES (:mail, :mime_type, 100, :position, :document)"""


def _archive() -> list[Statement]:
    """The statements writing PERSONS, MAILS and the rest."""
    statements: list[Statement] = []

    def add(statement: str, **parameters: Any) -> None:
        statements.append((statement, parameters))

    add("INSERT INTO mbox_file (id, path, size_bytes) VALUES (1, 'a.mbox', 1000000)")
    for person_id, address, root, kind in PERSONS:  # roots come before their aliases
        domain = address.partition("@")[2]
        add(_PERSON, id=person_id, address=address, domain=domain, root=root, kind=kind)
    for a, b in SUGGESTIONS:
        add("INSERT INTO alias_suggestion VALUES (:a, :b, NULL, 'x', 'certain')", a=a, b=b)
    for entity_id, kind, key, detail in ENTITIES:
        add(_ENTITY, id=entity_id, kind=kind, key=key, detail=detail)
    add(_DOCUMENT)
    for entity_id in DOCUMENT_ENTITIES:
        add("INSERT INTO document_entity VALUES (:entity, 1, 1, 0, 0)", entity=entity_id)
    for one in sorted(MAILS, key=lambda one: one.duplicate_of is not None):
        date = None if one.date is None else datetime.fromisoformat(f"{one.date}Z")
        add(
            _MAIL,
            id=one.id,
            offset=one.id * 100,
            sha=f"sha-{one.id}",
            subject=one.subject,
            date=date,
            automated=one.automated,
            duplicate_of=one.duplicate_of,
        )
        roles = [("from", (one.sender,)), ("to", one.to), ("cc", one.cc), ("bcc", one.bcc)]
        for role, persons in roles:
            for person_id in persons:
                add(_PARTICIPATION, mail=one.id, person=person_id, role=role)
        for position, (mime_type, document) in enumerate(one.attachments):
            add(_ATTACHMENT, mail=one.id, mime_type=mime_type, position=position, document=document)
        for entity_id in one.entities:
            add(
                "INSERT INTO mail_entity VALUES (:entity, :mail, 1, 0, 0)",
                entity=entity_id,
                mail=one.id,
            )
    add("ANALYZE")
    return statements


@asynccontextmanager
async def connected(url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


async def execute(url: str, statements: list[Statement]) -> None:
    async with connected(url) as engine, engine.begin() as connection:
        for statement, parameters in statements:
            await connection.execute(text(statement), parameters)


async def rows(url: str, query: str, **parameters: object) -> list[tuple[Any, ...]]:
    async with connected(url) as engine, engine.connect() as connection:
        return [tuple(row) for row in await connection.execute(text(query), parameters)]


class Step:
    """Stands in for the import's jobrun.Step; sets stop after `stop_after` transactions."""

    def __init__(self, stop: asyncio.Event | None = None, stop_after: int = 0) -> None:
        self.total: int | None = None
        self.done = 0
        self.stop = stop
        self.stop_after = stop_after

    def advance(self, count: int = 1) -> None:
        self.done += count
        if self.stop is not None and self.done >= self.stop_after:
            self.stop.set()


async def run(
    url: str,
    rules: SignalRules = RULES,
    *,
    step: Step | None = None,
    stop: asyncio.Event | None = None,
    engine: AsyncEngine | None = None,
) -> SignalPhaseResult:
    """One signals phase over the database at url."""
    if engine is not None:
        return await compute_signals(engine, rules, stop or asyncio.Event(), step or Step())
    async with connected(url) as own:
        return await compute_signals(own, rules, stop or asyncio.Event(), step or Step())


async def mail_signals(url: str) -> dict[int, set[str]]:
    found: dict[int, set[str]] = defaultdict(set)
    for signal, mail_id in await rows(url, "SELECT signal, mail_id FROM mail_signal"):
        found[mail_id].add(signal)
    return dict(found)


async def person_signals(url: str) -> dict[str, dict[int, Any]]:
    found: dict[str, dict[int, Any]] = defaultdict(dict)
    query = "SELECT signal, person_id, mails, since FROM person_signal"
    for signal, person_id, mails, since in await rows(url, query):
        found[signal][person_id] = mails if signal != SignalKind.SILENT else (mails, since)
    return dict(found)


async def everything(url: str) -> tuple[list[tuple[Any, ...]], ...]:
    """Both tables in a fixed order."""
    return (
        await rows(url, 'SELECT * FROM mail_signal ORDER BY signal COLLATE "C", mail_id'),
        await rows(url, 'SELECT * FROM person_signal ORDER BY signal COLLATE "C", person_id'),
    )


def holding(found: dict[int, set[str]], key: str) -> set[int]:
    """The mails of found with signal key."""
    return {mail_id for mail_id, signals in found.items() if key in signals}


def expected_mails(rules: SignalRules = RULES) -> dict[int, set[str]]:
    keys = set(rules.keys)
    found = {one.id: set(one.signals) & keys for one in MAILS}
    return {mail_id: signals for mail_id, signals in found.items() if signals}


@pytest.fixture(scope="module")
def archive_template(database_server_url: str) -> Iterator[str]:
    """The archive of this module, without signals; tests work on copies."""
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        asyncio.run(execute(url, _archive()))
        yield url


@pytest.fixture
def archive_url(database_server_url: str, archive_template: str) -> Iterator[str]:
    template = make_url(archive_template).database
    with _temporary_database(database_server_url, template) as url:
        yield url


async def test_every_rule_holds_for_the_mails_it_names(
    archive_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="mailrobbe")
    step = Step()
    result = await run(archive_url, step=step)
    assert await mail_signals(archive_url) == expected_mails()
    assert not result.stopped and result.forgotten == 0
    assert (step.done, step.total) == (len(RULES.keys) + 1, len(RULES.keys) + 1)
    expected = expected_mails()
    assert result.mails == {
        key: sum(1 for signals in expected.values() if key in signals) for key in RULES.keys
    }
    assert "signal night: 5 mails in " in caplog.text
    assert "signal term:gewalt: 3 mails in " in caplog.text  # a duplicate among them


async def test_senders_and_silent_persons(archive_url: str) -> None:
    await run(archive_url)
    assert await person_signals(archive_url) == {**SENDERS, "silent": SILENT}


async def test_the_figures_count_the_mails_that_are_no_duplicates(archive_url: str) -> None:
    before = datetime.now(UTC)
    result = await run(archive_url)
    async with connected(archive_url) as engine, engine.connect() as connection:
        figures = await read_figures(connection)
    assert figures is not None and figures == result.figures
    assert before <= figures.computed_at <= datetime.now(UTC)
    assert figures.rules == RULES.snapshot()
    originals = [one for one in MAILS if one.duplicate_of is None]
    assert figures.mails == len(originals)
    assert result.figures is not None and list(result.figures.signals) == list(RULES.keys)
    assert figures.signals == {
        key: sum(1 for one in originals if key in one.signals) for key in RULES.keys
    }
    assert list(result.figures.persons) == [*RULES.keys, "silent"]  # JSONB keeps no order
    assert figures.persons == {key: len(SENDERS[key]) for key in RULES.keys} | {"silent": 1}


async def test_a_second_run_gives_the_same_rows(archive_url: str) -> None:
    engine = create_async_engine(archive_url)  # pooled: both runs on the same connection
    try:
        first = await run(archive_url, engine=engine)
        stored = await everything(archive_url)
        second = await run(archive_url, engine=engine)
    finally:
        await engine.dispose()
    assert await everything(archive_url) == stored
    assert first.mails == second.mails
    assert first.figures is not None and second.figures is not None
    assert replace(first.figures, computed_at=second.figures.computed_at) == second.figures


async def test_without_internal_domains_the_internal_signals_go(
    archive_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="mailrobbe")
    await run(archive_url)
    rules = replace(RULES, internal_domains=())
    result = await run(archive_url, rules)
    assert not any(rules.available(key) for key in NEEDS_INTERNAL)
    found = await mail_signals(archive_url)
    assert not {signal for signals in found.values() for signal in signals} & NEEDS_INTERNAL
    assert "signal private_alias: not computed without MAILROBBE_INTERNAL_DOMAINS" in caplog.text
    # nordwind.example is external now, and mail.nordwind.example private.
    assert holding(found, "private") == holding(expected_mails(), "private") | {8, 11, 12, 14, 16}
    assert holding(found, "forward_out") == {14, 15, 16}  # to a private recipient only
    assert result.figures is not None
    assert all(result.figures.signals[key] == 0 for key in NEEDS_INTERNAL)
    assert all(result.figures.persons[key] == 0 for key in NEEDS_INTERNAL)
    persons = await person_signals(archive_url)
    assert not set(persons) & NEEDS_INTERNAL


async def test_a_theme_removed_takes_its_rows_along(archive_url: str) -> None:
    await run(archive_url)
    rules = replace(RULES, themes=RULES.themes[:1])
    result = await run(archive_url, rules)
    assert result.forgotten == 3  # mails 31, 34 and 36
    assert await mail_signals(archive_url) == expected_mails(rules)
    assert "term:gewalt" not in await person_signals(archive_url)
    assert result.figures is not None and "term:gewalt" not in result.figures.signals
    assert "term:gewalt" not in result.figures.persons


async def test_a_stop_keeps_the_signals_replaced_so_far(archive_url: str) -> None:
    await execute(
        archive_url,
        [
            ("INSERT INTO mail_signal VALUES ('private', 1), ('night', 1)", {}),
            ("INSERT INTO person_signal VALUES ('bcc', 9, 7, NULL)", {}),
        ],
    )
    stop = asyncio.Event()
    step = Step(stop, stop_after=1)
    result = await run(archive_url, step=step, stop=stop)
    assert result.stopped and result.figures is None
    assert step.done == 1 and step.total == len(RULES.keys) + 1
    found = await mail_signals(archive_url)
    assert holding(found, "private") == holding(expected_mails(), "private")
    assert {key for signals in found.values() for key in signals} == {"private", "night"}
    assert holding(found, "night") == {1}
    assert await person_signals(archive_url) == {"bcc": {9: 7}}
    async with connected(archive_url) as engine, engine.connect() as connection:
        assert await read_figures(connection) is None

    finished = await run(archive_url)
    assert not finished.stopped
    assert await mail_signals(archive_url) == expected_mails()
    assert await person_signals(archive_url) == {**SENDERS, "silent": SILENT}


async def test_an_unknown_time_zone_fails_before_writing(archive_url: str) -> None:
    await execute(archive_url, [("INSERT INTO mail_signal VALUES ('night', 1)", {})])
    step = Step()
    with pytest.raises(UnknownTimeZone, match="MAILROBBE_TIMEZONE"):
        await run(archive_url, replace(RULES, timezone="Mars/Olympus"), step=step)
    assert await mail_signals(archive_url) == {1: {"night"}}
    assert (step.done, step.total) == (0, None)


async def test_another_time_zone_moves_the_hours(archive_url: str) -> None:
    await run(archive_url, replace(RULES, timezone="UTC"))
    found = await mail_signals(archive_url)
    assert holding(found, "night") == {22, 24, 25, 26}  # 23:30, 03:59 and 04:00 UTC
    assert holding(found, "weekend") == {22, 23, 24}  # mail 22 too: a Sunday in UTC


def test_every_mail_signal_has_a_rule() -> None:
    assert set(phase._RULES) == set(MAIL_KINDS)
