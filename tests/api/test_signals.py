"""The signal API (D136, D137): the overview, the facets of the mail list, the signals of one
mail and of one person, and the mail list's signal filter in the list, its summary, the CSV and
the timeline.

The archive is the imported one with the signals of tests/api/conftest.py (SIGNAL_ROWS), as the
signals phase would store them. Expected results come from SQL on mail_signal, person_signal
and global_stats written apart from api/signals.py and api/filters.py; the reasons of a mail are
checked against its participants and the address classes of signals.model. WALK_ROWS is lowered
in some tests, so that the bounded walk runs out and every match is collected.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from mailrobbe.api import documents, filters
from mailrobbe.api import signals as signal_api
from mailrobbe.api.schemas import SIGNAL_DOMAINS, SIGNAL_SENDERS
from mailrobbe.config import Settings
from mailrobbe.enums import ParticipationRole
from mailrobbe.signals.model import (
    NEEDS_INTERNAL,
    SignalFigures,
    SignalRules,
    address_class,
    forward_prefix,
    in_domains,
    rules,
    signal_group,
)
from tests.api.conftest import (
    SIGNAL_COMPUTED_AT,
    SIGNAL_FREEMAIL,
    SIGNAL_INTERNAL,
    _client,
    api_settings,
)
from tests.api.test_mails import Params, export, get, ids, listed, page_ids, pages, rows
from tests.conftest import GeneratedArchive

pytestmark = pytest.mark.db

HAS = "id IN (SELECT mail_id FROM mail_signal WHERE signal = '{}')"
ROOT = "coalesce(p.merged_into, p.id)"
BAD_ZONE = "Mars/Olympus"


def settings_of(url: str, archive: GeneratedArchive, tmp_path: Path, **update: Any) -> Settings:
    settings = api_settings(url, archive, tmp_path / "no-frontend")
    return settings.model_copy(update=update)


async def owner_settings(url: str, archive: GeneratedArchive, tmp_path: Path) -> Settings:
    """The settings of the fixture's classes: its internal domain and the freemail domains."""
    internal = (await rows(url, SIGNAL_INTERNAL))[0].domain
    private = await rows(
        url, "SELECT DISTINCT domain FROM person WHERE domain ~ :f ORDER BY 1", f=SIGNAL_FREEMAIL
    )
    assert private
    return settings_of(
        url,
        archive,
        tmp_path,
        internal_domains=internal.upper(),
        private_domains=", ".join(row.domain for row in private),
    )


async def overview_with(settings: Settings) -> Any:
    async for client in _client(settings):
        return await get(client, "/api/signals")


async def figures(url: str) -> SignalFigures:
    found = await rows(url, "SELECT value FROM global_stats WHERE key = 'signals'")
    return SignalFigures.from_json(found[0].value)


async def stored(url: str, mail_id: int) -> set[str]:
    found = await rows(url, "SELECT signal FROM mail_signal WHERE mail_id = :m", m=mail_id)
    return {row.signal for row in found}


def person(row: Any) -> dict[str, Any]:
    return {
        "person_id": row.id,
        "email": row.canonical_email,
        "name": row.display_name,
        "label": None,
    }


# Overview ------------------------------------------------------------------------------------


async def test_the_overview_lists_every_signal_with_the_last_figures(
    signal_client: httpx.AsyncClient,
    signal_database_url: str,
    generated_archive: GeneratedArchive,
    tmp_path: Path,
) -> None:
    url = signal_database_url
    defaults = rules(settings_of(url, generated_archive, tmp_path))
    stored_figures = await figures(url)
    overview = await get(signal_client, "/api/signals")

    assert [info["key"] for info in overview["signals"]] == list(defaults.keys)
    by_key = {info["key"]: info for info in overview["signals"]}
    for key, info in by_key.items():
        assert info["group"] == signal_group(key)
        assert info["theme"] == defaults.theme_name(key)
        assert info["available"] is (key not in NEEDS_INTERNAL)
        assert info["mails"] == stored_figures.signals[key]
        assert info["persons"] == stored_figures.persons.get(key, 0)
    assert by_key["term:verschleierung"]["theme"] == "Verschleierung"
    assert by_key["term:verschleierung"]["group"] == "wording"
    assert by_key["night"]["group"] == "time"

    # the senders: root persons only, most mails first, then the higher id
    senders = await rows(
        url,
        "SELECT ps.signal, ps.mails, p.id, p.canonical_email, p.display_name, p.merged_into"
        " FROM person_signal ps JOIN person p ON p.id = ps.person_id"
        " WHERE ps.signal <> 'silent' ORDER BY ps.signal, ps.mails DESC, ps.person_id DESC",
    )
    for key, info in by_key.items():
        expected = [
            {"person": person(row), "mails": row.mails}
            for row in senders
            if row.signal == key and row.merged_into is None
        ][:SIGNAL_SENDERS]
        assert info["senders"] == expected, key
    merged = next(row for row in senders if row.signal == "night")
    assert merged.merged_into is not None  # the busiest sender at night, merged since
    assert merged.id not in {s["person"]["person_id"] for s in by_key["night"]["senders"]}

    silent = await rows(
        url,
        "SELECT ps.mails, ps.since, p.id, p.canonical_email, p.display_name FROM person_signal ps"
        " JOIN person p ON p.id = ps.person_id WHERE ps.signal = 'silent'"
        " AND p.merged_into IS NULL ORDER BY ps.mails DESC, ps.person_id DESC",
    )
    assert len(silent) == 4
    assert overview["silent"] == [
        {
            "person": person(row),
            "since": row.since.isoformat().replace("+00:00", "Z"),
            "mails": row.mails,
        }
        for row in silent
    ]
    assert overview["silent_count"] == stored_figures.persons["silent"] == 5

    originals = await rows(url, "SELECT count(*) AS n FROM mail WHERE is_duplicate_of IS NULL")
    assert overview["mails"] == stored_figures.mails == originals[0].n
    assert datetime.fromisoformat(overview["computed_at"]) == datetime.fromisoformat(
        SIGNAL_COMPUTED_AT
    )
    assert overview["outdated"] is False
    assert overview["settings"] == {
        "internal_domains": [],
        "private_domains": len(defaults.private_domains),
        "timezone": "Europe/Berlin",
        "timezone_known": True,
        "night_from": defaults.night_from,
        "night_to": defaults.night_to,
        "many_recipients": defaults.many_recipients,
        "forward_prefixes": list(defaults.forward_prefixes),
    }

    # without internal domains: the sender domains of global_stats as a help
    domains = await rows(
        url,
        "SELECT d.value ->> 'domain' AS domain, (d.value ->> 'mails')::int AS mails"
        " FROM global_stats g, jsonb_array_elements(g.value) WITH ORDINALITY AS d"
        " WHERE g.key = 'sender_domains' ORDER BY d.ordinality",
    )
    assert overview["sender_domains"] == [
        {"domain": row.domain, "mails": row.mails} for row in domains[:SIGNAL_DOMAINS]
    ]


async def test_the_overview_follows_the_settings(
    signal_database_url: str,
    generated_archive: GeneratedArchive,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = signal_database_url
    owner = await owner_settings(url, generated_archive, tmp_path)
    overview = await overview_with(owner)
    assert all(info["available"] for info in overview["signals"])
    assert overview["outdated"] is True  # the phase ran without internal domains
    assert overview["sender_domains"] == []
    assert overview["settings"]["internal_domains"] == [owner.internal_domains.lower()]
    assert overview["settings"]["private_domains"] == len(rules(owner).private_domains)

    # private providers are no help for setting the internal domains
    private = settings_of(url, generated_archive, tmp_path, private_domains=owner.private_domains)
    overview = await overview_with(private)
    shown = [entry["domain"] for entry in overview["sender_domains"]]
    assert shown and overview["outdated"] is True
    domains = await rows(
        url, "SELECT DISTINCT domain FROM person WHERE domain ~ :f", f=SIGNAL_FREEMAIL
    )
    assert not set(shown) & {row.domain for row in domains}
    assert all(not in_domains(domain, rules(private).private_domains) for domain in shown)

    zone = await overview_with(settings_of(url, generated_archive, tmp_path, timezone=BAD_ZONE))
    assert zone["settings"]["timezone"] == BAD_ZONE
    assert zone["settings"]["timezone_known"] is False
    assert zone["outdated"] is True

    monkeypatch.setattr(signal_api, "SIGNAL_SENDERS", 1)
    monkeypatch.setattr(signal_api, "SILENT_LISTED", 2)
    short = await overview_with(settings_of(url, generated_archive, tmp_path))
    assert all(len(info["senders"]) <= 1 for info in short["signals"])
    assert len(short["silent"]) == 2 and short["silent_count"] == 5


async def test_before_any_signals_phase(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    for table in ("mail_signal", "person_signal"):
        await rows(mutable_database_url, f"DELETE FROM {table}")
    await rows(mutable_database_url, "DELETE FROM global_stats WHERE key = 'signals'")
    overview = await get(mutable_client, "/api/signals")
    assert (overview["computed_at"], overview["outdated"], overview["mails"]) == (None, False, 0)
    assert (overview["silent"], overview["silent_count"]) == ([], 0)
    assert all(
        (info["mails"], info["persons"], info["senders"]) == (0, 0, [])
        for info in overview["signals"]
    )
    facets = await get(mutable_client, "/api/mails/signals")
    assert facets == {"signals": {}, "mails": None, "sampled": False}
    mail_id = (await ids(mutable_database_url))[0]
    assert (await get(mutable_client, f"/api/mails/{mail_id}/signals"))["computed_at"] is None
    sender = await rows(
        mutable_database_url, "SELECT person_id FROM participation WHERE role = 'from' LIMIT 1"
    )
    found = await get(mutable_client, f"/api/persons/{sender[0].person_id}/signals")
    assert found["signals"] == [] and found["sent"] > 0


# Facets --------------------------------------------------------------------------------------


async def test_facets_without_filters_are_the_last_figures(
    signal_client: httpx.AsyncClient,
    signal_database_url: str,
    generated_archive: GeneratedArchive,
    tmp_path: Path,
) -> None:
    keys = rules(settings_of(signal_database_url, generated_archive, tmp_path)).keys
    counts = (await figures(signal_database_url)).signals
    facets = await get(signal_client, "/api/mails/signals", [("q", " ")])
    assert (facets["mails"], facets["sampled"]) == (None, False)
    expected = {key: counts[key] for key in keys if counts[key] > 0}
    assert facets["signals"] == expected
    assert list(facets["signals"]) == list(expected)
    assert "term:gewalt" not in facets["signals"]  # no mail mentions its word field


FACET_CASES: dict[str, tuple[Params, str]] = {
    "dkim": ([("dkim", "pass")], "dkim_status = 'pass'"),
    "originals": ([("hide_duplicates", "true")], "is_duplicate_of IS NULL"),
    "signal": ([("signal", "bcc")], HAS.format("bcc")),
    "word": ([("q", "Angebot")], "tsv @@ websearch_to_tsquery('german', 'Angebot')"),
    "nothing": ([("signal", "term:gewalt")], "false"),
}


@pytest.mark.parametrize("case", list(FACET_CASES))
async def test_facets_count_the_mails_of_a_filter(
    signal_client: httpx.AsyncClient,
    signal_database_url: str,
    generated_archive: GeneratedArchive,
    tmp_path: Path,
    case: str,
) -> None:
    params, where = FACET_CASES[case]
    if case == "word":  # D73: or through an attachment's document
        where += (
            " OR id IN (SELECT a.mail_id FROM attachment a JOIN document d"
            " ON d.id = a.document_id WHERE d.tsv @@ websearch_to_tsquery('german', 'Angebot'))"
        )
    keys = rules(settings_of(signal_database_url, generated_archive, tmp_path)).keys
    matched = await ids(signal_database_url, where)
    counted = await rows(
        signal_database_url,
        f"SELECT signal, count(*) AS n FROM mail_signal WHERE mail_id IN"
        f" (SELECT id FROM mail WHERE {where}) GROUP BY signal",
    )
    counts = {row.signal: row.n for row in counted}
    facets = await get(signal_client, "/api/mails/signals", params)
    assert (facets["mails"], facets["sampled"]) == (len(matched), False)
    assert facets["signals"] == counts
    assert list(facets["signals"]) == [key for key in keys if key in counts]


async def test_facets_of_a_large_filter_count_a_sample(
    signal_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(signal_api, "FACET_MAILS", 50)
    facets = await get(signal_client, "/api/mails/signals", [("hide_duplicates", "true")])
    assert (facets["mails"], facets["sampled"]) == (50, True)
    assert facets["signals"] and all(0 < count <= 50 for count in facets["signals"].values())


async def test_facets_fall_back_to_a_smaller_sample(
    signal_client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    run = documents._all_unless_canceled

    async def first_canceled(*args: Any) -> Any:
        calls.append(1)
        return None if len(calls) == 2 else await run(*args)  # the counting of FACET_MAILS

    monkeypatch.setattr(signal_api, "_all_unless_canceled", first_canceled)
    monkeypatch.setattr(signal_api, "FACET_FALLBACK", 20)
    facets = await get(signal_client, "/api/mails/signals", [("hide_duplicates", "true")])
    assert (facets["mails"], facets["sampled"]) == (20, True)
    assert len(calls) == 3

    async def canceled(*_: Any) -> None:
        return None

    monkeypatch.setattr(signal_api, "_all_unless_canceled", canceled)
    facets = await get(signal_client, "/api/mails/signals", [("hide_duplicates", "true")])
    assert facets == {"signals": {}, "mails": None, "sampled": False}


# One mail ------------------------------------------------------------------------------------


async def participants(url: str, mail_id: int, signal_rules: SignalRules) -> list[Any]:
    """The mail's participants by role, then person id, with their address class and root."""
    found = await rows(
        url,
        "SELECT pa.role::text AS role, p.id, p.canonical_email,"
        f" coalesce(pa.display_name, p.display_name) AS name, p.domain, {ROOT} AS root"
        " FROM participation pa JOIN person p ON p.id = pa.person_id WHERE pa.mail_id = :m",
        m=mail_id,
    )
    order = list(ParticipationRole)
    found.sort(key=lambda row: (order.index(ParticipationRole(row.role)), row.id))
    return [(row, address_class(row.domain, signal_rules)) for row in found]


async def alias_roots(url: str, signal_rules: SignalRules) -> set[int]:
    """Root persons with an internal address of their own or of an open suggestion's partner."""
    found = await rows(
        url,
        f"SELECT {ROOT} AS root, p.domain FROM person p UNION ALL"
        f" SELECT s.person_a, p.domain FROM alias_suggestion s JOIN person p"
        f" ON {ROOT} = s.person_b UNION ALL"
        f" SELECT s.person_b, p.domain FROM alias_suggestion s JOIN person p"
        f" ON {ROOT} = s.person_a",
    )
    return {row.root for row in found if address_class(row.domain, signal_rules) == "internal"}


def expected_persons(
    key: str, found: list[Any], aliases: set[int], signal_rules: SignalRules
) -> list[dict[str, Any]]:
    """D132's participants of a signal, each person once, in role order."""
    senders = [(row, kind) for row, kind in found if row.role == "from"]
    recipients = [(row, kind) for row, kind in found if row.role != "from"]
    match key:
        case "private":
            chosen = [row for row, kind in found if kind == "private"]
        case "internal_to_private":
            chosen = [row for row, kind in senders if kind == "internal"]
            chosen += [row for row, kind in recipients if kind == "private"]
        case "private_to_internal":
            chosen = [row for row, kind in senders if kind == "private"]
            chosen += [row for row, kind in recipients if kind == "internal"]
        case "private_alias":
            chosen = [row for row, kind in found if kind == "private" and row.root in aliases]
        case "bcc":
            chosen = [row for row, _ in recipients if row.role == "bcc"]
        case "forward_out":
            inside = signal_rules.internal_domains and any(k == "internal" for _, k in senders)
            outside = ("private", "external") if inside else ("private",)
            chosen = [row for row, kind in recipients if kind in outside]
        case _:
            chosen = []
    once: dict[int, Any] = {}
    for row in chosen:
        once.setdefault(row.id, row)
    return [
        {"person_id": row.id, "email": row.canonical_email, "name": row.name, "label": None}
        for row in once.values()
    ]


async def test_the_reasons_name_what_makes_each_signal_hold(
    signal_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    url = signal_database_url
    owner = await owner_settings(url, generated_archive, tmp_path)
    signal_rules = rules(owner)
    aliases = await alias_roots(url, signal_rules)
    # up to four mails of each signal, the lowest ids
    sample = await rows(
        url,
        "SELECT DISTINCT mail_id FROM (SELECT mail_id, row_number() OVER"
        " (PARTITION BY signal ORDER BY mail_id) AS n FROM mail_signal) x WHERE n <= 4",
    )
    kinds: set[str] = set()
    named: set[str] = set()  # the signals with a person in their reason
    async for client in _client(owner):
        for mail_id in sorted(row.mail_id for row in sample):
            found = await get(client, f"/api/mails/{mail_id}/signals")
            assert found["timezone"] == "Europe/Berlin"
            assert datetime.fromisoformat(found["computed_at"]) == datetime.fromisoformat(
                SIGNAL_COMPUTED_AT
            )
            signals = await stored(url, mail_id)
            keys = [key for key in signal_rules.keys if key in signals]
            assert [reason["key"] for reason in found["signals"]] == keys
            people = await participants(url, mail_id, signal_rules)
            recipients = {row.id for row, _ in people if row.role != "from"}
            for reason in found["signals"]:
                key = reason["key"]
                kinds.add(key)
                assert reason["group"] == signal_group(key)
                assert reason["theme"] == signal_rules.theme_name(key)
                assert reason["persons"] == expected_persons(key, people, aliases, signal_rules)
                if reason["persons"]:
                    named.add(key)
                assert reason["recipients"] == (
                    len(recipients) if key == "many_recipients" else None
                )
                if key not in ("night", "weekend"):
                    assert reason["local_time"] is None
                if key not in ("forward", "forward_out"):
                    assert (reason["forward_prefix"], reason["forwarded_mail"]) == (None, None)
                if not key.startswith("term:"):
                    assert reason["terms"] == []
    every = await rows(url, "SELECT DISTINCT signal FROM mail_signal")
    assert kinds == {row.signal for row in every}
    assert {"private_alias", "internal_to_private", "forward_out", "many_recipients"} <= kinds
    assert {"private", "private_alias", "bcc", "forward_out"} <= named


async def test_the_reasons_of_forwards_times_and_word_fields(
    signal_client: httpx.AsyncClient, signal_database_url: str
) -> None:
    url = signal_database_url
    prefixes = rules(Settings()).forward_prefixes
    originals = await rows(
        url, "SELECT id, subject FROM mail WHERE is_duplicate_of IS NULL ORDER BY id LIMIT 5"
    )
    _, _, prefixed, named, unnamed = originals  # k=3, 4, 5 of SIGNAL_ROWS
    assert prefixed.subject.startswith("AW: WG: ")
    for mail, prefix, attached in [
        (prefixed, "WG", None),
        (named, forward_prefix(named.subject, prefixes), "Weitergeleitet.eml"),  # the first
        (unnamed, forward_prefix(unnamed.subject, prefixes), ""),
    ]:
        found = await get(signal_client, f"/api/mails/{mail.id}/signals")
        forwards = [r for r in found["signals"] if r["key"] in ("forward", "forward_out")]
        assert forwards
        assert all(
            (r["forward_prefix"], r["forwarded_mail"]) == (prefix, attached) for r in forwards
        )

    for moment, local in [
        (datetime(2021, 7, 3, 21, 30, tzinfo=UTC), "2021-07-03T23:30:00+02:00"),  # summer time
        (datetime(2021, 1, 9, 22, 15, tzinfo=UTC), "2021-01-09T23:15:00+01:00"),
    ]:
        mail_id = (await ids(url, "date_utc = :d", d=moment))[0]
        found = await get(signal_client, f"/api/mails/{mail_id}/signals")
        timed = {r["key"]: r["local_time"] for r in found["signals"] if r["local_time"]}
        assert timed == {"night": local, "weekend": local}

    terms = await rows(
        url,
        "SELECT id, label FROM entity WHERE key IN"
        " ('verschleierung:unter uns', 'verschleierung:diskretion') ORDER BY label COLLATE \"C\"",
    )
    both = await ids(
        url,
        "id IN (SELECT mail_id FROM mail_entity m JOIN entity e"
        " ON e.id = m.entity_id WHERE e.key = 'verschleierung:unter uns')",
    )
    through = await ids(
        url,
        "id IN (SELECT a.mail_id FROM attachment a JOIN document_entity d"
        " ON d.document_id = a.document_id JOIN entity e ON e.id = d.entity_id"
        " WHERE e.key = 'verschleierung:diskretion') AND " + f"id <> {both[0]}",
    )
    refs = [
        {"id": row.id, "kind": "term", "label": row.label, "detail": "verschleierung"}
        for row in terms
    ]
    assert [row.label for row in terms] == ["Diskretion", "unter uns"]
    for mail_id, expected in [(both[0], refs), *((mail_id, refs[:1]) for mail_id in through)]:
        found = await get(signal_client, f"/api/mails/{mail_id}/signals")
        worded = [r for r in found["signals"] if r["key"] == "term:verschleierung"]
        assert len(worded) == 1 and worded[0]["terms"] == expected
        assert (worded[0]["theme"], worded[0]["group"]) == ("Verschleierung", "wording")

    donations = await rows(
        url,
        "SELECT x.mail_id, array_agg(DISTINCT e.label) AS labels FROM (SELECT entity_id, mail_id"
        " FROM mail_entity UNION ALL SELECT d.entity_id, a.mail_id FROM document_entity d"
        " JOIN attachment a ON a.document_id = d.document_id) x JOIN entity e"
        " ON e.id = x.entity_id WHERE e.kind = 'term' AND e.detail = 'spenden'"
        " GROUP BY x.mail_id ORDER BY x.mail_id LIMIT 3",
    )
    assert donations
    for row in donations:
        found = await get(signal_client, f"/api/mails/{row.mail_id}/signals")
        donation = next(r for r in found["signals"] if r["key"] == "term:spenden")
        assert [t["label"] for t in donation["terms"]] == sorted(row.labels)


async def test_a_mail_without_signals_and_an_unknown_mail(
    signal_client: httpx.AsyncClient, signal_database_url: str
) -> None:
    quiet = await ids(signal_database_url, "id NOT IN (SELECT mail_id FROM mail_signal)")
    assert quiet
    found = await get(signal_client, f"/api/mails/{quiet[0]}/signals")
    assert found["signals"] == [] and found["timezone"] == "Europe/Berlin"
    error = await get(signal_client, "/api/mails/987654321/signals", status=404)
    assert error["detail"]["code"] == "not_found"
    await get(signal_client, f"/api/mails/{2**63}/signals", status=422)


async def test_an_unknown_time_zone_gives_no_local_time(
    signal_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    mail_id = (await ids(signal_database_url, HAS.format("night")))[0]
    async for client in _client(
        settings_of(signal_database_url, generated_archive, tmp_path, timezone=BAD_ZONE)
    ):
        found = await get(client, f"/api/mails/{mail_id}/signals")
    assert found["timezone"] == BAD_ZONE
    night = [r for r in found["signals"] if r["key"] == "night"]
    assert night and night[0]["local_time"] is None


# One person ----------------------------------------------------------------------------------

SENT = (
    "SELECT {select} FROM participation pa JOIN person p ON p.id = pa.person_id"
    " JOIN mail ON mail.id = pa.mail_id AND mail.is_duplicate_of IS NULL {join}"
    f" WHERE pa.role = 'from' AND {ROOT} = ANY(:roots) {{group}}"
)


async def sent_signals(url: str, roots: list[int]) -> tuple[int, dict[str, int]]:
    """The mails these roots' addresses sent that are no duplicates, and per signal."""
    sent = await rows(
        url, SENT.format(select="count(DISTINCT mail.id) AS n", join="", group=""), roots=roots
    )
    counted = await rows(
        url,
        SENT.format(
            select="ms.signal, count(DISTINCT mail.id) AS n",
            join="JOIN mail_signal ms ON ms.mail_id = mail.id",
            group="GROUP BY ms.signal",
        ),
        roots=roots,
    )
    return sent[0].n, {row.signal: row.n for row in counted}


async def test_person_signals_count_the_sent_mails_of_the_root(
    signal_client: httpx.AsyncClient,
    signal_database_url: str,
    generated_archive: GeneratedArchive,
    tmp_path: Path,
) -> None:
    url = signal_database_url
    signal_rules = rules(settings_of(url, generated_archive, tmp_path))
    archive = await figures(url)
    # a root with an alias (merged since the phase), and the busiest sender
    roots = await rows(
        url,
        "SELECT merged_into AS id, min(id) AS alias FROM person WHERE merged_into IS NOT NULL"
        " GROUP BY merged_into ORDER BY count(*) DESC, merged_into LIMIT 1",
    )
    busiest = await rows(
        url,
        "SELECT person_id AS id FROM participation WHERE role = 'from'"
        " GROUP BY person_id ORDER BY count(*) DESC, person_id LIMIT 1",
    )
    for root in [roots[0].id, busiest[0].id]:
        sent, counted = await sent_signals(url, [root])
        found = await get(signal_client, f"/api/persons/{root}/signals")
        assert found["sent"] == sent > 0
        assert found["signals"] == [
            {
                "key": key,
                "group": signal_group(key),
                "theme": signal_rules.theme_name(key),
                "mails": counted[key],
                "archive_share": archive.signals[key] / archive.mails,
            }
            for key in signal_rules.keys
            if key in counted
        ]
    assert await get(signal_client, f"/api/persons/{roots[0].alias}/signals") == await get(
        signal_client, f"/api/persons/{roots[0].id}/signals"
    )
    error = await get(signal_client, "/api/persons/987654321/signals", status=404)
    assert error["detail"]["code"] == "not_found"


async def test_a_merge_counts_at_once(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    url = mutable_database_url
    await rows(url, "DELETE FROM mail_signal")
    await rows(
        url,
        "INSERT INTO mail_signal (signal, mail_id) SELECT 'weekend', id FROM mail WHERE id % 3 = 0"
        " UNION ALL SELECT 'bcc', mail_id FROM participation WHERE role = 'bcc' GROUP BY mail_id",
    )
    pair = await rows(
        url,
        "SELECT person_id AS id FROM participation WHERE role = 'from'"
        " GROUP BY person_id ORDER BY count(*) DESC, person_id LIMIT 2",
    )
    first, second = (row.id for row in pair)
    before = await get(mutable_client, f"/api/persons/{first}/signals")
    assert before["sent"] == (await sent_signals(url, [first]))[0]
    response = await mutable_client.post(
        "/api/persons/merge", json={"target": first, "sources": [second]}
    )
    assert response.status_code == 200, response.text
    sent, counted = await sent_signals(url, [first])
    after = await get(mutable_client, f"/api/persons/{second}/signals")  # the alias: its root
    assert after["sent"] == sent > before["sent"]
    assert {entry["key"]: entry["mails"] for entry in after["signals"]} == counted


async def test_silence_is_reckoned_on_request(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    """A human with mails in four months before the last five of the archive and none since is
    silent from the first of those five; as a list it is not."""
    url = mutable_database_url
    # the archive's end: its latest date before tomorrow (UTC)
    until = "(date_trunc('day', now() AT TIME ZONE 'UTC') + interval '1 day') AT TIME ZONE 'UTC'"
    end = await rows(
        url,
        "SELECT date_trunc('month', max(date_utc) AT TIME ZONE 'UTC') AS month FROM mail"
        f" WHERE date_utc < {until}",
    )
    month = end[0].month
    latest = f"(SELECT id FROM mail WHERE date_utc < {until} ORDER BY date_utc DESC LIMIT 1)"
    chosen = await rows(
        url,
        "SELECT p.id FROM person p JOIN participation pa ON pa.person_id = p.id"
        " JOIN mail ON mail.id = pa.mail_id AND mail.is_duplicate_of IS NULL"
        " WHERE p.merged_into IS NULL AND p.kind IS NULL"
        " AND NOT EXISTS (SELECT 1 FROM person q WHERE q.merged_into = p.id) AND p.id NOT IN"
        f" (SELECT person_id FROM participation WHERE mail_id = {latest})"
        " GROUP BY p.id HAVING count(DISTINCT mail.id) >= 8 ORDER BY p.id LIMIT 1",
    )
    person_id = chosen[0].id
    await rows(
        url,
        "UPDATE mail SET date_utc = (CAST(:m AS timestamp)"
        " - make_interval(months => CAST(8 - n % 4 AS int))"
        " + interval '10 days 12 hours') AT TIME ZONE 'UTC' FROM (SELECT mail_id,"
        " row_number() OVER (ORDER BY mail_id) AS n FROM participation WHERE person_id = :p"
        " GROUP BY mail_id) x WHERE mail.id = x.mail_id",
        m=month,
        p=person_id,
    )
    mails = await rows(
        url,
        "SELECT count(DISTINCT mail.id) AS n FROM participation pa JOIN mail ON mail.id ="
        " pa.mail_id WHERE pa.person_id = :p AND mail.is_duplicate_of IS NULL",
        p=person_id,
    )
    found = await get(mutable_client, f"/api/persons/{person_id}/signals")
    since = datetime(month.year, month.month, 1, tzinfo=UTC)
    since = since.replace(year=since.year - (since.month <= 4), month=(since.month - 5) % 12 + 1)
    assert datetime.fromisoformat(found["silent_since"]) == since
    assert found["silent_mails"] == mails[0].n >= 8

    active = await rows(url, f"SELECT person_id FROM participation WHERE mail_id = {latest}")
    found = await get(mutable_client, f"/api/persons/{active[0].person_id}/signals")
    assert (found["silent_since"], found["silent_mails"]) == (None, None)

    await rows(url, "UPDATE person SET kind = 'list' WHERE id = :p", p=person_id)
    found = await get(mutable_client, f"/api/persons/{person_id}/signals")
    assert (found["silent_since"], found["silent_mails"]) == (None, None)


# The signal filter (D136) --------------------------------------------------------------------


CASES: dict[str, tuple[Params, str]] = {
    "common": ([("signal", "private")], HAS.format("private")),
    "rare": ([("signal", "bcc")], HAS.format("bcc")),
    "two-signals": (
        [("signal", "private"), ("signal", "many_recipients")],
        f"{HAS.format('private')} AND {HAS.format('many_recipients')}",
    ),
    "same-signal-twice": ([("signal", "weekend"), ("signal", "weekend")], HAS.format("weekend")),
    "word-field": ([("signal", "term:spenden")], HAS.format("term:spenden")),
    # needs internal domains, which these settings lack: it matches what the phase stored
    "not-available": ([("signal", "private_alias")], HAS.format("private_alias")),
    "nothing-stored": ([("signal", "term:gewalt")], "false"),
    "signal-and-date": (
        [("signal", "private"), ("date_from", "2020-01-01")],
        f"{HAS.format('private')} AND date_utc >= '2020-01-01'",
    ),
    "signal-and-dkim": (
        [("signal", "night"), ("dkim", "pass")],
        f"{HAS.format('night')} AND dkim_status = 'pass'",
    ),
    "signal-without-duplicates": (
        [("signal", "private"), ("hide_duplicates", "true")],
        f"{HAS.format('private')} AND is_duplicate_of IS NULL",
    ),
}


@pytest.fixture
def walk_rows(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(filters, "WALK_ROWS", request.param)
    return int(request.param)


WALKS = pytest.mark.parametrize(
    "walk_rows", [filters.WALK_ROWS, 7], ids=["default", "short-walk"], indirect=True
)


@WALKS
@pytest.mark.parametrize("sort", ["date_desc", "date_asc"])
@pytest.mark.parametrize("case", list(CASES))
async def test_the_signal_filter_selects_what_sql_selects(
    signal_client: httpx.AsyncClient,
    signal_database_url: str,
    walk_rows: int,
    sort: str,
    case: str,
) -> None:
    params, where = CASES[case]
    expected = await ids(signal_database_url, where, sort)
    assert expected or where == "false", case
    assert await listed(signal_client, [*params, ("sort", sort)]) == expected
    summary = await get(signal_client, "/api/mails/summary", params)
    assert (summary["total"], summary["exact"]) == (len(expected), True)


async def test_a_common_signal_fills_its_pages_by_walking(
    signal_client: httpx.AsyncClient, signal_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The walk form finds the matches itself: only the last, short page collects them."""
    calls: list[int] = []
    collected = filters._collected

    async def counted(*args: Any, **kwargs: Any) -> list[int]:
        calls.append(1)
        return await collected(*args, **kwargs)

    monkeypatch.setattr(filters, "_collected", counted)
    params, where = CASES["common"]
    expected = await ids(signal_database_url, where)
    found = await pages(signal_client, params, 10)
    assert [mail_id for page in found for mail_id in page_ids(page)] == expected
    assert len(found) > 2 and calls == [1]


async def test_the_csv_and_the_timeline_take_the_signal_filter(
    signal_client: httpx.AsyncClient, signal_database_url: str
) -> None:
    params, where = CASES["two-signals"]
    exported = await export(signal_client, [*params, ("sort", "date_asc")])
    assert [int(row[0]) for row in exported] == await ids(signal_database_url, where, "date_asc")
    timeline = await get(signal_client, "/api/timeline", params)
    dated = await ids(signal_database_url, f"{where} AND date_utc IS NOT NULL")
    assert timeline["total"]["total"] == len(dated) > 0


@pytest.mark.parametrize("key", ["bogus", "silent", "term:nope", "Private"])
async def test_an_unknown_signal_is_an_invalid_filter(
    signal_client: httpx.AsyncClient, key: str
) -> None:
    for path in (
        "/api/mails",
        "/api/mails/summary",
        "/api/mails/export.csv",
        "/api/mails/signals",
        "/api/mails/facets",
        "/api/timeline",
    ):
        error = await get(signal_client, path, [("signal", "private"), ("signal", key)], 400)
        assert error["detail"]["code"] == "invalid_filter", path
        assert key in error["detail"]["message"]
