"""`mailrobbe bench` (D51): percentiles, scenarios and output. tests/api/test_bench_run.py runs
it against a real server."""

import random
import socket
import statistics

import pytest

from mailrobbe import bench, cli

FULL = bench.Samples(
    mails=600,
    persons=150,
    mail_id=7,
    next_cursor="abc",
    words=["vertrag", "angebot"],
    neighbours=("dkim", "pass", 9),
    sender_domains=["a.example", "b.example"],
    year=2021,
    top_person=3,
    top_email="anna.berg@a.example",
    contact=4,
    middle_person=80,
    middle_rank=75,
    ego_thresholds={1: 1, 2: 4},
    domains_threshold=2,
    documents=40,
    document_id=12,
    text_document_id=13,
    document_words=["spenden", "quittung"],
)


def test_percentiles_interpolate_between_ranks() -> None:
    assert bench.percentile([42.0], 0.5) == bench.percentile([42.0], 0.95) == 42.0
    assert bench.percentile([5.0, 1.0, 3.0, 2.0, 4.0], 0.5) == 3.0
    assert bench.percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.95) == pytest.approx(4.8)
    values = [random.Random(7).expovariate(1.0) for _ in range(37)]
    assert bench.percentile(values, 0.5) == pytest.approx(statistics.median(values))
    p95 = statistics.quantiles(values, n=20, method="inclusive")[18]
    assert bench.percentile(values, 0.95) == pytest.approx(p95)


def test_every_scenario_has_a_sample_of_a_full_archive() -> None:
    found, skipped = bench.scenarios(FULL)
    names = [scenario.name for scenario in found]
    assert skipped == []
    assert len(names) == len(set(names)) == 53
    paths = {scenario.name: scenario.paths for scenario in found}
    assert paths["mail list, next page"] == ("/api/mails?cursor=abc",)
    assert paths["filter full text word"] == ("/api/mails?q=vertrag", "/api/mails?q=angebot")
    assert paths["filter from:<address>"] == ("/api/mails?q=from%3Aanna.berg%40a.example",)
    assert paths["filter one year"] == ("/api/mails?date_from=2021-01-01&date_to=2021-12-31",)
    assert paths["neighbours in a filtered list"] == ("/api/mails/9/neighbors?dkim=pass",)
    assert paths["mails between top person and contact"] == ("/api/mails?between=3&between=4",)
    assert paths["person search"] == ("/api/persons?q=anna",)
    assert paths["map, ego depth 2"] == ("/api/graph?mode=ego&center=3&depth=2&min_edge=4",)
    assert paths["map, two domains"] == (
        "/api/graph?mode=domains&domain=a.example&domain=b.example&min_edge=2",
    )
    assert paths["documents by size"] == ("/api/documents?sort=size",)
    assert paths["documents, full text word"] == (
        "/api/documents?q=spenden",
        "/api/documents?q=quittung",
    )
    assert paths["documents summary, full text word"] == (
        "/api/documents/summary?q=spenden",
        "/api/documents/summary?q=quittung",
    )
    assert paths["document page"] == ("/api/documents/12",)
    assert paths["document text"] == ("/api/documents/12/text",)
    assert paths["mails of a document, oldest first"] == ("/api/mails?document=12&sort=date_asc",)
    assert paths["mail search through attachments"] == (
        "/api/mails?q=spenden",
        "/api/mails?q=quittung",
    )
    with_export, _ = bench.scenarios(FULL, with_export=True)
    assert with_export[-1].name == "CSV export, every mail"


def test_an_empty_archive_skips_what_needs_a_sample() -> None:
    found, skipped = bench.scenarios(bench.Samples())
    assert [scenario.name for scenario in found] == [
        "stats",
        "mail list, first page",
        "mail list, oldest first",
        "filter dkim=pass",
        "filter dkim=no_key",
        "filter has_attachment",
        "summary, unfiltered",
        "summary, dkim=pass",
        "import status",
        "import summary",
        "import errors",
    ]
    assert "profile, top person" in skipped and "documents, newest first" in skipped
    assert len(found) + len(skipped) == 53


def test_table_rows_mark_slow_and_failed_scenarios() -> None:
    result = bench.Result("filter dkim=pass", ("/api/mails?dkim=pass",), [0.010, 1.2, 0.020])
    result.size = 24_576
    row = result.summary(slow_ms=1000)
    assert (row["p50_ms"], row["max_ms"], row["slow"]) == (20.0, 1200.0, True)
    line = bench.table_row(row)
    assert line.startswith("filter dkim=pass ")
    assert line.endswith("24.0 KiB  SLOW")
    assert bench.table_row(result.summary(slow_ms=5000)).endswith("24.0 KiB")
    result.errors.append("HTTP 500 for /api/mails?dkim=pass: boom")
    assert bench.table_row(result.summary(slow_ms=5000)).endswith("  ERROR")
    assert [bench.format_size(size) for size in (512, 2048, 3 * 1024**2)] == [
        "512 B",
        "2.0 KiB",
        "3.0 MiB",
    ]


def test_an_unreachable_server_is_an_error(capsys: pytest.CaptureFixture[str]) -> None:
    with socket.socket() as unused:
        unused.bind(("127.0.0.1", 0))
        port = unused.getsockname()[1]
    assert cli.main(["bench", "--url", f"http://127.0.0.1:{port}"]) == 1
    assert "cannot reach" in capsys.readouterr().err
    assert cli.main(["bench", "--url", "ftp://example.test"]) == 1
