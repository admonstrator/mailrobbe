"""`mailrobbe graph refresh` and `mailrobbe graph export` (D36, D38)."""

import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe.cli import build_parser, main

NS = {"g": "http://graphml.graphdrawing.org/xmlns"}
_EDGES = """
    SELECT person_a, person_b, mails_total, mails_a_to_b, mails_b_to_a, mails_cc, first_date,
        last_date
    FROM edge WHERE mails_total >= :min ORDER BY person_a, person_b
"""
_PERSONS = """
    SELECT id, coalesce(display_name, canonical_email), canonical_email, domain, kind FROM person
"""


def _rows(url: str, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    """Run one statement in its own committed transaction; its rows, if any."""

    async def execute() -> list[tuple[Any, ...]]:
        engine = create_async_engine(url, poolclass=pool.NullPool)
        async with engine.begin() as connection:
            result = await connection.execute(text(sql), params)
            rows = [tuple(row) for row in result] if result.returns_rows else []
        await engine.dispose()
        return rows

    return asyncio.run(execute())


def _graph(document: str) -> ET.Element:
    graph = ET.fromstring(document.encode()).find("g:graph", NS)
    assert graph is not None
    return graph


def _data(element: ET.Element) -> dict[str, str]:
    return {d.attrib["key"]: d.text or "" for d in element.findall("g:data", NS)}


@pytest.fixture
def database(monkeypatch: pytest.MonkeyPatch, graph_copy_url: str) -> str:
    monkeypatch.setenv("MAILROBBE_DATABASE_URL", graph_copy_url)
    return graph_copy_url


def test_options() -> None:
    parser = build_parser()
    args = parser.parse_args(["graph", "export", "out.graphml", "--min-mails", "3", "--force"])
    assert (args.action, args.file, args.min_mails) == ("export", "out.graphml", 3) and args.force
    args = parser.parse_args(["graph", "export", "-"])
    assert (args.file, args.min_mails, args.force) == ("-", 1, False)
    assert parser.parse_args(["graph", "refresh"]).action == "refresh"
    for argv in (["graph"], ["graph", "export"], ["graph", "export", "x", "--min-mails", "0"]):
        with pytest.raises(SystemExit) as exit_info:
            parser.parse_args(argv)
        assert exit_info.value.code == 2


@pytest.mark.db
@pytest.mark.slow
def test_refresh_prints_what_changed(database: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["graph", "refresh"]) == 0  # the import refreshed already
    out = capsys.readouterr().out
    pairs = _rows(database, "SELECT count(*) FROM edge")[0][0]
    assert f"edges:         {pairs} pairs (0 inserted, 0 updated, 0 deleted)" in out
    assert "edge years:    0 rows changed" in out
    assert "person kinds:  0 changed (" in out and "elapsed:" in out

    person = _rows(database, "SELECT min(person_a) FROM edge")[0][0]
    removed = _rows(database, "SELECT count(*) FROM edge WHERE person_a = :p", p=person)[0][0]
    _rows(database, "DELETE FROM edge WHERE person_a = :p", p=person)
    assert main(["graph", "refresh"]) == 0
    assert f"{pairs} pairs ({removed} inserted, 0 updated, 0 deleted)" in capsys.readouterr().out


@pytest.mark.db
@pytest.mark.slow
def test_export_writes_every_edge_and_its_persons(database: str, tmp_path: Path) -> None:
    target = tmp_path / "graph.graphml"
    assert main(["graph", "export", str(target)]) == 0
    graph = _graph(target.read_text(encoding="utf-8"))
    rows = _rows(database, _EDGES, min=1)
    edges = graph.findall("g:edge", NS)
    assert len(edges) == len(rows) > 0
    a, b, total, a_to_b, b_to_a, cc, first, last = rows[0]
    assert (edges[0].attrib["source"], edges[0].attrib["target"]) == (str(a), str(b))
    assert _data(edges[0]) == {
        "weight": str(total),
        "a_to_b": str(a_to_b),
        "b_to_a": str(b_to_a),
        "cc": str(cc),
        "first_date": first.isoformat(),
        "last_date": last.isoformat(),
    }
    weights: dict[int, int] = {}
    for a, b, total, *_ in rows:
        weights[a] = weights.get(a, 0) + total
        weights[b] = weights.get(b, 0) + total
    persons = {row[0]: row for row in _rows(database, _PERSONS)}
    nodes = {int(n.attrib["id"]): _data(n) for n in graph.findall("g:node", NS)}
    assert set(nodes) == set(weights)
    for person_id, data in nodes.items():
        _, label, email, domain, kind = persons[person_id]
        mails = str(weights[person_id])
        expected = {"label": label, "email": email, "domain": domain, "mails": mails}
        assert data == expected | ({"kind": kind} if kind else {})
    assert any("kind" in data for data in nodes.values())


@pytest.mark.db
@pytest.mark.slow
def test_export_with_a_threshold_to_standard_output(
    database: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["graph", "export", "--min-mails", "5", "-"]) == 0
    graph = _graph(capsys.readouterr().out)
    rows = _rows(database, _EDGES, min=5)
    assert 0 < len(graph.findall("g:edge", NS)) == len(rows) < len(_rows(database, _EDGES, min=1))
    ends = {str(person) for a, b, *_ in rows for person in (a, b)}
    assert {n.attrib["id"] for n in graph.findall("g:node", NS)} == ends


@pytest.mark.db
def test_an_existing_file_is_kept_unless_forced(
    database: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    target = tmp_path / "graph.graphml"
    target.write_text("keep", encoding="utf-8")
    assert main(["graph", "export", str(target)]) == 2
    assert "--force" in caplog.text and target.read_text(encoding="utf-8") == "keep"
    assert main(["graph", "export", "--force", str(target)]) == 0
    assert target.read_text(encoding="utf-8").startswith("<?xml")


def test_database_errors_leave_no_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("MAILROBBE_DATABASE_URL", "postgresql+asyncpg://m:m@127.0.0.1:1/m")
    target = tmp_path / "graph.graphml"
    assert main(["graph", "export", str(target)]) == 1
    assert main(["graph", "refresh"]) == 1
    assert "database error" in caplog.text and not target.exists()
    assert main(["graph", "export", str(tmp_path / "missing" / "graph.graphml")]) == 1
    assert "cannot write" in caplog.text
