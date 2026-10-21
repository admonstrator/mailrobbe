"""refresh_edges (D36) and person.kind (D39).

The generated archive is checked against its manifest: every counter of edge and edge_year, and
the kinds against the list and automated addresses the generator planned. Hand-made mails cover
the counting rules one by one, the writes (only changed rows) and the partial refresh after a
merge or split, which must end with exactly the rows of a full refresh.
"""

import asyncio
import itertools
from collections import defaultdict
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine

from mailrobbe.config import Settings
from mailrobbe.dkim.recheck import recheck
from mailrobbe.enums import DkimStatus
from mailrobbe.graph.edges import AUTOMATED_MIN_SENT, LIST_MIN_SENDERS, EdgeRefresh, refresh_edges
from mailrobbe.importer.model import ParsedMail
from mailrobbe.importer.store import Batch, Store
from tests.conftest import GeneratedArchive
from tests.importer.doubles import FakeVerdict, add_mbox_file, address, make_mail, make_record
from tests.importer.doubles import message as raw_message

pytestmark = pytest.mark.db

Db = AsyncSession | AsyncConnection
Counters = tuple[int, ...]  # a_to_b, b_to_a, cc, pass_a_to_b, pass_b_to_a, pass_cc

_COUNTERS = "e.mails_a_to_b, e.mails_b_to_a, e.mails_cc, e.pass_a_to_b, e.pass_b_to_a, e.pass_cc"
_BY_ADDRESS = """
    SELECT a.canonical_email, b.canonical_email, {columns}
    FROM {table} e JOIN person a ON a.id = e.person_a JOIN person b ON b.id = e.person_b
"""
_files = itertools.count()


def _day(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, 12, tzinfo=UTC)


def _oriented(a: str, b: str, counters: Counters) -> tuple[tuple[str, str], Counters]:
    """The pair keyed by address order instead of person id, its counters turned along."""
    if a < b:
        return (a, b), counters
    ab, ba, cc, pass_ab, pass_ba, pass_cc = counters
    return (b, a), (ba, ab, cc, pass_ba, pass_ab, pass_cc)


async def _rows(db: Db, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    return [tuple(row) for row in await db.execute(text(sql), params)]


async def _edges(db: Db) -> dict[tuple[str, str], Counters]:
    rows = await _rows(db, _BY_ADDRESS.format(columns=_COUNTERS, table="edge"))
    return dict(_oriented(a, b, tuple(counters)) for a, b, *counters in rows)


async def _dates(db: Db) -> dict[tuple[str, str], tuple[datetime | None, datetime | None]]:
    rows = await _rows(db, _BY_ADDRESS.format(columns="e.first_date, e.last_date", table="edge"))
    return {(min(a, b), max(a, b)): (first, last) for a, b, first, last in rows}


async def _years(db: Db) -> dict[tuple[str, str, int], Counters]:
    rows = await _rows(db, _BY_ADDRESS.format(columns=f"e.year, {_COUNTERS}", table="edge_year"))
    years = {}
    for a, b, year, *counters in rows:
        pair, oriented = _oriented(a, b, tuple(counters))
        years[(*pair, year)] = oriented
    return years


async def _kinds(db: Db) -> dict[str, str]:
    sql = "SELECT canonical_email, kind::text FROM person WHERE kind IS NOT NULL"
    return dict(await _rows(db, sql))


async def _store(
    session: AsyncSession, *mails: ParsedMail, status: DkimStatus | None = None
) -> list[int]:
    """Store mails in a new MBOX file; returns their ids in order."""
    file_id = await add_mbox_file(session, f"{next(_files)}.mbox")
    batch = Batch()
    offset = 0
    for index, mail in enumerate(mails):
        record = make_record(offset, raw_message(index))
        batch.add(record, mail, None if status is None else FakeVerdict(status))
        offset += record.byte_length
    await Store().write(session, file_id, batch)
    rows = await _rows(
        session, "SELECT id FROM mail WHERE mbox_file_id = :id ORDER BY byte_offset", id=file_id
    )
    return [mail_id for (mail_id,) in rows]


async def _merge(db: Db, member: str, root: str | None) -> None:
    """Point the person of `member` at the person of `root` (None: split it off again)."""
    await db.execute(
        text(
            "UPDATE person SET merged_into = (SELECT id FROM person WHERE canonical_email = :root) "
            "WHERE canonical_email = :member"
        ),
        {"member": member, "root": root},
    )


async def _ids(db: Db, *emails: str) -> list[int]:
    rows = dict(await _rows(db, "SELECT canonical_email, id FROM person"))
    return [rows[email] for email in emails]


@pytest.fixture
async def connection(graph_copy_url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(graph_copy_url, poolclass=pool.NullPool)
    async with engine.connect() as db:
        yield db
    await engine.dispose()


async def _read_only(url: str) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    async with engine.connect() as db:
        yield db
        await db.rollback()
    await engine.dispose()


@pytest.fixture
async def imported(graph_database_url: str) -> AsyncIterator[AsyncConnection]:
    """A connection to the shared imported archive; must not write."""
    async for db in _read_only(graph_database_url):
        yield db


# The generated archive against its manifest


def _expected(manifest: list[dict[str, Any]]) -> tuple[dict[Any, Counters], dict[Any, Counters]]:
    """edge and edge_year by address, counted straight from the manifest (D36)."""
    edges: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0] * 6)
    years: dict[tuple[str, str, int], list[int]] = defaultdict(lambda: [0] * 6)
    for record in manifest:
        if record["duplicate_of"] is not None:
            continue
        sender = record["sender"].lower()
        direct = {a.lower() for a in (*record["to"], *record["bcc"])}
        copied = {a.lower() for a in record["cc"]} - direct
        passed = record["dkim"]["expected"] == "pass"
        year = datetime.fromisoformat(record["date"]).astimezone(UTC).year
        for recipient in (direct | copied) - {sender}:
            a, b = sorted((sender, recipient))
            index = 2 if recipient in copied else (0 if sender == a else 1)
            for counters in (edges[a, b], years[a, b, year]):
                counters[index] += 1
                counters[index + 3] += passed
    return (
        {key: tuple(value) for key, value in edges.items()},
        {key: tuple(value) for key, value in years.items()},
    )


@pytest.mark.slow
async def test_edges_match_the_manifest(
    imported: AsyncConnection, generated_archive: GeneratedArchive
) -> None:
    manifest = generated_archive.manifest
    edges, years = _expected(manifest)
    assert await _edges(imported) == edges
    assert await _years(imported) == years
    assert any(counters[2] for counters in edges.values())  # Cc
    assert any(counters[3] or counters[4] for counters in edges.values())  # DKIM pass
    dates: dict[tuple[str, str], list[datetime]] = defaultdict(list)
    for record in manifest:
        if record["duplicate_of"] is None:
            sender = record["sender"]
            for recipient in {*record["to"], *record["cc"], *record["bcc"]} - {sender}:
                dates[min(sender, recipient), max(sender, recipient)].append(
                    datetime.fromisoformat(record["date"])
                )
    assert await _dates(imported) == {pair: (min(d), max(d)) for pair, d in dates.items()}


@pytest.mark.slow
async def test_kinds_match_the_manifest(
    imported: AsyncConnection, generated_archive: GeneratedArchive
) -> None:
    lists, automated = set(), set()
    for record in generated_archive.manifest:
        if record["duplicate_of"] is not None:
            continue
        if record["automated"]:
            automated.add(record["sender"])
        elif record["list_id"]:
            lists.update(record["to"])
    kinds = await _kinds(imported)
    assert lists and automated
    assert {email for email, kind in kinds.items() if kind == "list"} == lists
    assert {email for email, kind in kinds.items() if kind == "automated"} == automated


@pytest.mark.slow
async def test_global_stats_hold_the_pairs_and_the_time(imported: AsyncConnection) -> None:
    value = await imported.scalar(text("SELECT value FROM global_stats WHERE key = 'edges'"))
    pairs = await imported.scalar(text("SELECT count(*) FROM edge"))
    assert set(value) == {"pairs", "refreshed_at"}
    assert value["pairs"] == pairs > 0
    assert datetime.fromisoformat(value["refreshed_at"]).utcoffset() is not None


# Counting rules, one mail at a time

ANNA, BERT, CARL = address("anna@a.example"), address("bert@b.example"), address("carl@c.example")
DORA, EMIL = address("dora@d.example"), address("emil@e.example")


async def test_to_before_cc_bcc_as_to_and_no_recipient_pairs(db_session: AsyncSession) -> None:
    await _store(
        db_session,
        # Bert in To and Cc counts once, as To; Carl and Dora are never paired with each other
        make_mail(date_utc=_day(2020), sender=(ANNA,), to=(BERT, CARL), cc=(BERT, DORA)),
        make_mail(date_utc=_day(2021), sender=(BERT,), bcc=(ANNA,)),
        make_mail(date_utc=_day(2021), sender=(CARL,), cc=(ANNA,)),
    )
    await refresh_edges(db_session)
    assert await _edges(db_session) == {
        ("anna@a.example", "bert@b.example"): (1, 1, 0, 0, 0, 0),
        ("anna@a.example", "carl@c.example"): (1, 0, 1, 0, 0, 0),
        ("anna@a.example", "dora@d.example"): (0, 0, 1, 0, 0, 0),
    }
    assert await _years(db_session) == {
        ("anna@a.example", "bert@b.example", 2020): (1, 0, 0, 0, 0, 0),
        ("anna@a.example", "bert@b.example", 2021): (0, 1, 0, 0, 0, 0),
        ("anna@a.example", "carl@c.example", 2020): (1, 0, 0, 0, 0, 0),
        ("anna@a.example", "carl@c.example", 2021): (0, 0, 1, 0, 0, 0),
        ("anna@a.example", "dora@d.example", 2020): (0, 0, 1, 0, 0, 0),
    }


async def test_self_mail_several_senders_and_dkim_pass(db_session: AsyncSession) -> None:
    await _store(db_session, make_mail(sender=(ANNA,), to=(ANNA,)))  # to oneself: no edge
    await _store(
        db_session,
        make_mail(sender=(ANNA, BERT), to=(ANNA, CARL)),  # each sender counts, Anna not to herself
        status=DkimStatus.PASS,
    )
    await refresh_edges(db_session)
    assert await _edges(db_session) == {
        ("anna@a.example", "bert@b.example"): (0, 1, 0, 0, 1, 0),
        ("anna@a.example", "carl@c.example"): (1, 0, 0, 1, 0, 0),
        ("bert@b.example", "carl@c.example"): (1, 0, 0, 1, 0, 0),
    }


async def test_duplicates_and_undated_mails(db_session: AsyncSession) -> None:
    original, duplicate, _ = await _store(
        db_session,
        make_mail(date_utc=_day(2019, 5, 1), sender=(ANNA,), to=(BERT,)),
        make_mail(date_utc=_day(2019, 5, 1), sender=(ANNA,), to=(BERT,)),
        make_mail(sender=(BERT,), to=(ANNA,)),
    )
    await db_session.execute(
        text("UPDATE mail SET is_duplicate_of = :o WHERE id = :d"), {"o": original, "d": duplicate}
    )
    await refresh_edges(db_session)
    assert await _edges(db_session) == {("anna@a.example", "bert@b.example"): (1, 1, 0, 0, 0, 0)}
    assert await _years(db_session) == {
        ("anna@a.example", "bert@b.example", 2019): (1, 0, 0, 0, 0, 0)
    }
    pair = ("anna@a.example", "bert@b.example")  # the undated mail is in edge only
    assert (await _dates(db_session))[pair] == (_day(2019, 5, 1), _day(2019, 5, 1))


async def test_merged_addresses_count_for_their_root(db_session: AsyncSession) -> None:
    anna2, bert2 = address("anna@private.example"), address("bert@private.example")
    await _store(
        db_session,
        make_mail(date_utc=_day(2020), sender=(anna2,), to=(bert2,), cc=(BERT,)),
        make_mail(date_utc=_day(2020), sender=(ANNA,), to=(anna2,)),  # to herself after merging
        make_mail(date_utc=_day(2020), sender=(ANNA, anna2), to=(CARL,)),  # one sender after all
    )
    await _merge(db_session, "anna@private.example", "anna@a.example")
    await _merge(db_session, "bert@private.example", "bert@b.example")
    await refresh_edges(db_session)
    assert await _edges(db_session) == {
        ("anna@a.example", "bert@b.example"): (1, 0, 0, 0, 0, 0),  # To wins over Cc
        ("anna@a.example", "carl@c.example"): (1, 0, 0, 0, 0, 0),
    }


# Writes


async def test_a_refresh_writes_only_what_changed(db_session: AsyncSession) -> None:
    first, second, _ = await _store(
        db_session,
        make_mail(date_utc=_day(2020), sender=(ANNA,), to=(BERT,)),
        make_mail(date_utc=_day(2021), sender=(ANNA,), to=(CARL,)),
        make_mail(date_utc=_day(2021), sender=(DORA,), to=(EMIL,)),
    )
    created = await refresh_edges(db_session)
    assert (created.inserted, created.updated, created.deleted) == (3, 0, 0)
    assert (created.years, created.pairs) == (3, 3)
    again = await refresh_edges(db_session)
    assert (again.changed, again.years, again.kinds, again.pairs) == (0, 0, 0, 3)

    await db_session.execute(
        text("UPDATE mail SET dkim_status = 'pass' WHERE id = :o"), {"o": first}
    )
    await db_session.execute(
        text("UPDATE mail SET is_duplicate_of = :o WHERE id = :d"), {"o": first, "d": second}
    )
    await _store(db_session, make_mail(date_utc=_day(2022), sender=(EMIL,), to=(DORA,)))
    changed = await refresh_edges(db_session)
    # Anna-Bert passes now, Anna-Carl is gone, Dora-Emil got a mail in a new year
    assert (changed.inserted, changed.updated, changed.deleted) == (0, 2, 1)
    assert (changed.years, changed.pairs) == (3, 2)
    assert await _edges(db_session) == {
        ("anna@a.example", "bert@b.example"): (1, 0, 0, 1, 0, 0),
        ("dora@d.example", "emil@e.example"): (1, 1, 0, 0, 0, 0),
    }


@pytest.mark.slow
def test_a_dkim_recheck_refreshes_the_pass_counters(
    graph_copy_url: str, generated_archive: GeneratedArchive
) -> None:
    async def execute(*statements: str) -> dict[tuple[str, str], Counters]:
        engine = create_async_engine(graph_copy_url, poolclass=pool.NullPool)
        async with engine.begin() as db:
            for statement in statements:
                await db.execute(text(statement))
            edges = await _edges(db)
        await engine.dispose()
        return edges

    imported = asyncio.run(execute())
    assert any(counters[3] for counters in imported.values())
    forgotten = asyncio.run(
        execute("UPDATE mail SET dkim_status = NULL", "UPDATE edge SET pass_a_to_b = 0")
    )
    assert forgotten != imported
    settings = Settings(
        database_url=graph_copy_url,
        mbox_dir=generated_archive.mbox_dir,
        dkim_dns_override=generated_archive.dns_override,
    )
    assert recheck(settings, statuses={None}).checked == len(generated_archive.manifest)
    assert asyncio.run(execute()) == imported


# Partial refreshes


async def _snapshot(db: Db) -> tuple[Any, ...]:
    edges = await _rows(db, "SELECT * FROM edge ORDER BY person_a, person_b")
    years = await _rows(db, "SELECT * FROM edge_year ORDER BY person_a, person_b, year")
    kinds = await _rows(db, "SELECT id, kind FROM person ORDER BY id")
    return edges, years, kinds


async def _busiest(db: Db, count: int) -> list[str]:
    rows = await _rows(
        db,
        "SELECT x.canonical_email FROM participation p JOIN person x ON x.id = p.person_id "
        "GROUP BY x.id ORDER BY count(*) DESC, x.id LIMIT :n",
        n=count,
    )
    return [email for (email,) in rows]


async def _assert_full_changes_nothing(db: Db) -> None:
    full = await refresh_edges(db)
    assert (full.changed, full.years, full.kinds) == (0, 0, 0), full


@pytest.mark.slow
async def test_partial_refresh_after_merge_and_split_matches_a_full_one(
    connection: AsyncConnection,
) -> None:
    before = await _snapshot(connection)
    p, q, r, s = await _busiest(connection, 4)
    ids = await _ids(connection, p, q, r, s)
    await _merge(connection, q, p)
    await _merge(connection, s, r)
    partial = await refresh_edges(connection, ids)
    assert partial.deleted > 0 and partial.updated > 0
    merged = await _snapshot(connection)
    assert merged != before
    await _assert_full_changes_nothing(connection)
    await connection.commit()

    await _merge(connection, q, None)
    await _merge(connection, s, None)
    await refresh_edges(connection, ids)
    assert await _snapshot(connection) == before
    await _assert_full_changes_nothing(connection)


@pytest.mark.slow
async def test_a_partial_refresh_of_the_root_alone_drops_its_members_rows(
    connection: AsyncConnection,
) -> None:
    p, q = await _busiest(connection, 2)
    (root,) = await _ids(connection, p)
    await _merge(connection, q, p)
    await refresh_edges(connection, [root, 10**12])  # an unknown id is ignored
    await _assert_full_changes_nothing(connection)


async def test_partial_refresh_leaves_other_pairs_alone(db_session: AsyncSession) -> None:
    await _store(
        db_session,
        make_mail(sender=(ANNA,), to=(BERT,)),
        make_mail(sender=(CARL,), to=(DORA,)),
    )
    await refresh_edges(db_session)
    # wrong on purpose: the partial refresh must not touch Carl and Dora's row
    await db_session.execute(text("UPDATE edge SET mails_cc = 7"))
    await refresh_edges(db_session, await _ids(db_session, "anna@a.example"))
    edges = await _edges(db_session)
    assert edges[("anna@a.example", "bert@b.example")] == (1, 0, 0, 0, 0, 0)
    assert edges[("carl@c.example", "dora@d.example")] == (1, 0, 7, 0, 0, 0)
    result = await refresh_edges(db_session, [])
    assert result == EdgeRefresh(0, 0, 0, 0, 0, 2, result.seconds)


# Kinds (D39)


def _human(n: int) -> Any:
    return address(f"person{n}@corp.example")


async def test_noreply_names_and_programmatic_mails_are_automated(db_session: AsyncSession) -> None:
    await _store(
        db_session,
        make_mail(sender=(address("no-reply@shop.example"),), to=(ANNA,)),
        make_mail(sender=(address("bounces+x7@mail.example"),), to=(ANNA,)),
        make_mail(sender=(address("info@shop.example"),), to=(ANNA,), automated=True),
        make_mail(sender=(address("info@shop.example"),), to=(ANNA,), automated=True),
        make_mail(sender=(address("info@shop.example"),), to=(BERT,)),
        # a List-Id that names none of the recipients: a newsletter, sent in bulk
        make_mail(sender=(address("news@shop.example"),), to=(ANNA,), list_id="news.shop.example"),
        # one of two automated is not more than half
        make_mail(sender=(BERT,), to=(ANNA,), automated=True),
        make_mail(sender=(BERT,), to=(ANNA,)),
    )
    await refresh_edges(db_session)
    assert await _kinds(db_session) == {
        "no-reply@shop.example": "automated",
        "bounces+x7@mail.example": "automated",
        "info@shop.example": "automated",
        "news@shop.example": "automated",
    }


async def test_senders_that_never_converse_are_automated(db_session: AsyncSession) -> None:
    notify, chatty = address("system@tool.example"), address("reports@tool.example")
    mails = [make_mail(sender=(notify,), to=(_human(n),)) for n in range(AUTOMATED_MIN_SENT)]
    mails += [make_mail(sender=(chatty,), to=(ANNA,)) for _ in range(AUTOMATED_MIN_SENT - 1)]
    mails.append(make_mail(sender=(chatty,), to=(ANNA,), in_reply_to="<1@a.example>"))
    mails += [make_mail(sender=(BERT,), to=(ANNA,)) for _ in range(AUTOMATED_MIN_SENT)]
    mails.append(make_mail(sender=(ANNA,), to=(BERT,)))  # Bert received one
    await _store(db_session, *mails)
    await refresh_edges(db_session)
    assert await _kinds(db_session) == {"system@tool.example": "automated"}


async def test_lists_by_list_id_and_by_their_senders(db_session: AsyncSession) -> None:
    team, dl = address("team@lists.example"), address("dl@corp.example")
    small, copied = address("few@corp.example"), address("copied@corp.example")
    mails = [
        make_mail(sender=(ANNA,), to=(team,), list_id="team.lists.example"),
        # Bert reads a list post as a copy: subscribed, still a person
        make_mail(sender=(CARL,), to=(team,), cc=(BERT,), list_id="team.lists.example"),
    ]
    senders = [_human(n) for n in range(LIST_MIN_SENDERS)]
    mails += [make_mail(sender=(sender,), to=(dl,)) for sender in senders]
    mails += [make_mail(sender=(sender,), to=(small,)) for sender in senders[1:]]
    mails += [make_mail(sender=(sender,), to=(BERT,)) for sender in senders]
    # never alone among the recipients: a person who does not write
    mails += [make_mail(sender=(sender,), to=(ANNA,), cc=(copied,)) for sender in senders]
    await _store(db_session, *mails)
    await refresh_edges(db_session)
    assert await _kinds(db_session) == {"team@lists.example": "list", "dl@corp.example": "list"}


async def test_automated_wins_and_merged_persons_have_no_kind(db_session: AsyncSession) -> None:
    noreply = address("noreply@lists.example")
    await _store(
        db_session,
        make_mail(sender=(ANNA,), to=(noreply,), list_id="noreply.lists.example"),
        make_mail(sender=(address("noreply@b.example"),), to=(ANNA,)),
    )
    await refresh_edges(db_session)
    assert await _kinds(db_session) == {
        "noreply@lists.example": "automated",
        "noreply@b.example": "automated",
    }
    await _merge(db_session, "noreply@b.example", "anna@a.example")
    result = await refresh_edges(db_session, await _ids(db_session, "noreply@b.example"))
    # Anna now has a noreply address, and the member lost its kind
    assert result.kinds == 2
    assert await _kinds(db_session) == {
        "noreply@lists.example": "automated",
        "anna@a.example": "automated",
    }
