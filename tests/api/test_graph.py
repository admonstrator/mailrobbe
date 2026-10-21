"""GET /api/graph, /api/graph/size and /api/graph/export.graphml (D37, D38).

Most tests read a hand-made graph in a database of this module: a few persons of two domains
and a star of MAX_GRAPH_NODES + 1 leaves, which is one person too many for a map. The last test
reads the imported archive, whose edge table may be empty or filled.
"""

import asyncio
import xml.etree.ElementTree as ET
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import migrate
from mailrobbe.api.graph import GRAPHML_FILENAME
from mailrobbe.api.schemas import MAX_GRAPH_NODES
from mailrobbe.config import Settings
from mailrobbe.enums import PersonKind
from mailrobbe.graph.graphml import MEDIA_TYPE
from tests.api.conftest import _client
from tests.conftest import _temporary_database
from tests.graph.graph_data import E, P, insert_graph

pytestmark = pytest.mark.db

NS = {"g": "http://graphml.graphdrawing.org/xmlns"}
HUB = 100
LEAVES = range(HUB + 1, HUB + MAX_GRAPH_NODES + 2)
PEOPLE = [
    P(1, name="Anna Keller"),
    P(2),
    P(3, "sued.example", name="Carla Sommer"),
    P(4, kind=PersonKind.LIST),
    P(9, "alt.example", merged_into=1),
    P(HUB, "stern.example"),
    *(P(leaf, "stern.example") for leaf in LEAVES),
]
EDGES = [
    E(1, 2, a_to_b=5, b_to_a=2, cc=1, pass_a_to_b=1),
    E(1, 3, a_to_b=3),
    E(2, 3, b_to_a=2, cc=4),
    E(1, 4, a_to_b=4),
    E(1, 2, a_to_b=2, year=2020),
    E(1, 3, a_to_b=3, year=2021),
    *(E(HUB, leaf, b_to_a=1) for leaf in LEAVES),
]


async def _fill(url: str) -> None:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            await insert_graph(connection, PEOPLE, EDGES)
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def graph_database_url(database_server_url: str) -> Iterator[str]:
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        asyncio.run(_fill(url))
        yield url


@pytest.fixture
async def graph_client(graph_database_url: str, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(database_url=graph_database_url, frontend_dir=tmp_path / "no-frontend")
    async for http in _client(settings):
        yield http


async def _get(client: httpx.AsyncClient, path: str, params: Any) -> Any:
    response = await client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_ego_graph(graph_client: httpx.AsyncClient) -> None:
    graph = await _get(graph_client, "/api/graph", [("center", 9), ("center", 3)])

    assert graph["centers"] == [1, 3]
    assert graph["nodes"][0] == {
        "id": 1,
        "name": "Anna Keller",
        "email": "p1@nord.example",
        "domain": "nord.example",
        "kind": None,
        "mails": 14,
        "contacts": 3,
        "center": True,
    }
    assert [(n["id"], n["kind"], n["center"]) for n in graph["nodes"]] == [
        (1, None, True),
        (2, None, False),
        (3, None, True),
        (4, "list", False),
    ]
    assert graph["edges"] == [
        {"source": 1, "target": 2, "a_to_b": 5, "b_to_a": 2, "cc": 1, "weight": 7},
        {"source": 1, "target": 4, "a_to_b": 4, "b_to_a": 0, "cc": 0, "weight": 4},
        {"source": 1, "target": 3, "a_to_b": 3, "b_to_a": 0, "cc": 0, "weight": 3},
        {"source": 2, "target": 3, "a_to_b": 0, "b_to_a": 2, "cc": 4, "weight": 2},
    ]
    assert graph["mails"] == 16
    # Without the global_stats row of a refresh: the rows of edge, never refreshed.
    assert graph["edge_table"] == {"pairs": len(EDGES) - 2, "refreshed_at": None}


async def test_options(graph_client: httpx.AsyncClient) -> None:
    async def edges(**params: Any) -> list[tuple[int, int, int]]:
        graph = await _get(graph_client, "/api/graph", {"center": 1, **params})
        return [(e["source"], e["target"], e["weight"]) for e in graph["edges"]]

    assert await edges(depth=2, cc="true", hide_lists="true", min_edge=4) == [
        (1, 2, 8),
        (2, 3, 6),
    ]
    assert await edges(dkim_only="true") == [(1, 2, 1)]
    assert await edges(year_from=2021) == [(1, 3, 3)]
    assert await edges(year_to=2020) == [(1, 2, 2)]
    assert await edges(hide=[2, 4], expand=[3]) == [(1, 3, 3)]
    assert await edges(depth=2, min_edge=10) == []
    assert await edges(min_edge=2**40, expand=[2**64], hide=[-(2**64)]) == []


async def test_top_and_domains(graph_client: httpx.AsyncClient) -> None:
    # The hub has the most mails, but no edge to another of the top persons.
    graph = await _get(graph_client, "/api/graph", {"mode": "top", "limit": 3})
    assert [node["id"] for node in graph["nodes"]] == [1, 2]
    assert graph["centers"] == []
    graph = await _get(graph_client, "/api/graph", {"mode": "top", "limit": 2})
    assert graph["nodes"] == []

    params = [("mode", "domains"), ("domain", "sued.example"), ("domain", "nord.example")]
    graph = await _get(graph_client, "/api/graph", params)
    assert [node["id"] for node in graph["nodes"]] == [1, 2, 3]
    assert len(graph["edges"]) == 3


async def test_size_answers_above_the_limit(graph_client: httpx.AsyncClient) -> None:
    size = await _get(graph_client, "/api/graph/size", {"center": HUB})
    assert size == {
        "nodes": MAX_GRAPH_NODES + 2,
        "edges": MAX_GRAPH_NODES + 1,
        "mails": MAX_GRAPH_NODES + 1,
        "too_large": True,
    }
    size = await _get(graph_client, "/api/graph/size", {"center": 1, "cc": "true"})
    assert size == {"nodes": 4, "edges": 4, "mails": 21, "too_large": False}


@pytest.mark.parametrize("path", ["/api/graph", "/api/graph/export.graphml"])
async def test_graph_and_download_refuse_above_the_limit(
    graph_client: httpx.AsyncClient, path: str
) -> None:
    response = await graph_client.get(path, params={"center": HUB})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "graph_too_large"
    assert str(MAX_GRAPH_NODES + 2) in detail["message"]


@pytest.mark.parametrize(
    ("params", "status", "code"),
    [
        ({"mode": "ego"}, 400, "invalid_filter"),
        ({"mode": "domains", "domain": "nord.example"}, 400, "invalid_filter"),
        ({"mode": "top", "year_from": 2021, "year_to": 2020}, 400, "invalid_filter"),
        ({"center": 99_999}, 404, "not_found"),
        ({"center": 2**64}, 404, "not_found"),
        ({"center": 1, "depth": 4}, 422, None),
        ({"mode": "top", "limit": 0}, 422, None),
        ({"mode": "top", "limit": MAX_GRAPH_NODES + 1}, 422, None),
        ({"center": 1, "min_edge": 0}, 422, None),
        ({"mode": "all"}, 422, None),
    ],
)
@pytest.mark.parametrize("path", ["/api/graph", "/api/graph/size", "/api/graph/export.graphml"])
async def test_errors(
    graph_client: httpx.AsyncClient, path: str, params: Any, status: int, code: str | None
) -> None:
    response = await graph_client.get(path, params=params)
    assert response.status_code == status
    if code is not None:
        assert response.json()["detail"]["code"] == code


async def test_graphml_download(graph_client: httpx.AsyncClient) -> None:
    params = {"center": "1", "cc": "true"}
    graph = await _get(graph_client, "/api/graph", params)
    response = await graph_client.get("/api/graph/export.graphml", params=params)

    assert response.status_code == 200
    assert response.headers["content-type"] == MEDIA_TYPE
    assert response.headers["content-disposition"] == f'attachment; filename="{GRAPHML_FILENAME}"'
    root = ET.fromstring(response.content)
    nodes = root.findall("g:graph/g:node", NS)
    edges = root.findall("g:graph/g:edge", NS)
    assert len(nodes) == len(graph["nodes"]) == 4
    assert len(edges) == len(graph["edges"]) == 4

    def data(element: ET.Element) -> dict[str, str]:
        return {d.attrib["key"]: d.text or "" for d in element.findall("g:data", NS)}

    by_id = {node.attrib["id"]: data(node) for node in nodes}
    assert by_id["1"]["label"] == "Anna Keller"
    assert by_id["2"]["label"] == "p2@nord.example"  # no display name
    assert by_id["4"]["kind"] == "list"
    assert by_id["1"]["mails"] == str(graph["nodes"][0]["mails"])
    assert next((e.attrib["source"], e.attrib["target"], data(e)) for e in edges) == (
        "1",
        "2",
        {"weight": "8", "a_to_b": "5", "b_to_a": "2", "cc": "1"},
    )


async def test_exactly_the_limit(graph_client: httpx.AsyncClient) -> None:
    """Two leaves hidden leave MAX_GRAPH_NODES persons, which a map shows; the download is
    streamed in several pieces."""
    params: dict[str, Any] = {"center": HUB, "hide": [LEAVES[0], LEAVES[1]]}
    graph = await _get(graph_client, "/api/graph", params)
    assert (len(graph["nodes"]), len(graph["edges"])) == (MAX_GRAPH_NODES, MAX_GRAPH_NODES - 1)
    response = await graph_client.get("/api/graph/export.graphml", params=params)
    assert response.status_code == 200
    root = ET.fromstring(response.content)
    assert len(root.findall("g:graph/g:node", NS)) == MAX_GRAPH_NODES
    assert len(root.findall("g:graph/g:edge", NS)) == MAX_GRAPH_NODES - 1


async def test_imported_archive(client: httpx.AsyncClient) -> None:
    """The endpoints work on a real import, whether its edge table is filled or not."""
    page = await _get(client, "/api/mails", {"limit": 20})
    person_id = next(item["sender"]["person_id"] for item in page["items"] if item["sender"])

    for params in ({"mode": "top"}, {"center": person_id}, {"center": person_id, "depth": 2}):
        graph = await _get(client, "/api/graph", params)
        size = await _get(client, "/api/graph/size", params)
        ids = [node["id"] for node in graph["nodes"]]
        assert (size["nodes"], size["edges"], size["mails"]) == (
            len(ids),
            len(graph["edges"]),
            graph["mails"],
        )
        assert set(ids) >= {e["source"] for e in graph["edges"]} | {
            e["target"] for e in graph["edges"]
        }
        assert graph["mails"] == sum(edge["weight"] for edge in graph["edges"])
        mails = [node["mails"] for node in graph["nodes"]]
        assert mails == sorted(mails, reverse=True)
        assert graph["edge_table"]["pairs"] >= len(graph["edges"])
        if "center" in params:
            assert graph["centers"] == [person_id]
            assert person_id in ids
        response = await client.get("/api/graph/export.graphml", params=params)
        assert response.status_code == 200
        assert len(ET.fromstring(response.content).findall("g:graph/g:node", NS)) == len(ids)
