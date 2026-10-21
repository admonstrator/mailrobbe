"""The map excerpt (D37) on small hand-made graphs: every rule of GraphParams pinned."""

from typing import Any

import pytest
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.schemas import MAX_GRAPH_NODES, Graph, GraphNode, GraphParams
from mailrobbe.db.models import GlobalStats
from mailrobbe.enums import PersonKind
from mailrobbe.graph import excerpt
from tests.graph.graph_data import E, P, insert_graph, persons

pytestmark = pytest.mark.db


def _params(**params: Any) -> GraphParams:
    return GraphParams.model_validate(params)


async def _graph(db: AsyncSession, **params: Any) -> Graph:
    return await excerpt.build_graph(db, _params(**params))


def _ids(graph: Graph) -> list[int]:
    return [node.id for node in graph.nodes]


def _nodes(graph: Graph) -> dict[int, GraphNode]:
    return {node.id: node for node in graph.nodes}


def _weights(graph: Graph) -> dict[tuple[int, int], int]:
    return {(edge.source, edge.target): edge.weight for edge in graph.edges}


async def test_depth_steps_away_from_the_center(db_session: AsyncSession) -> None:
    chain = [E(n, n + 1, a_to_b=1) for n in range(1, 5)]
    await insert_graph(db_session, persons(1, 2, 3, 4, 5), chain)

    for depth, expected in ((1, {1, 2}), (2, {1, 2, 3}), (3, {1, 2, 3, 4})):
        graph = await _graph(db_session, center=[1], depth=depth)
        assert set(_ids(graph)) == expected
    assert graph.centers == [1]
    assert [node.id for node in graph.nodes if node.center] == [1]


async def test_threshold_cuts_traversal_and_edges(db_session: AsyncSession) -> None:
    edges = [E(1, 2, a_to_b=5), E(2, 3, a_to_b=1), E(3, 4, b_to_a=5), E(1, 3, a_to_b=1, b_to_a=1)]
    await insert_graph(db_session, persons(1, 2, 3, 4), edges)

    graph = await _graph(db_session, center=[1], depth=3, min_edge=2)
    assert set(_ids(graph)) == {1, 2, 3, 4}
    assert _weights(graph) == {(1, 2): 5, (3, 4): 5, (1, 3): 2}  # 2-3 is too light to show

    graph = await _graph(db_session, center=[1], depth=3, min_edge=3)
    assert set(_ids(graph)) == {1, 2}  # 1-3 and 2-3 are too light to follow
    assert _weights(graph) == {(1, 2): 5}


async def test_every_counted_edge_between_nodes_is_shown_in_order(db_session: AsyncSession) -> None:
    edges = [E(1, 2, a_to_b=3), E(1, 3, a_to_b=3), E(2, 3, b_to_a=7), E(3, 4, a_to_b=9)]
    await insert_graph(db_session, persons(1, 2, 3, 4), edges)

    graph = await _graph(db_session, center=[1])

    # 2-3 is no step from the center, but both ends are shown; 3-4 leads outside.
    assert [(e.source, e.target, e.weight) for e in graph.edges] == [
        (2, 3, 7),
        (1, 2, 3),
        (1, 3, 3),
    ]
    assert graph.mails == 13
    # Most mails first, counting every counted edge (3: 3 + 7 + 9).
    assert [(node.id, node.mails) for node in graph.nodes] == [(3, 19), (2, 10), (1, 6)]


async def test_node_figures_cover_all_counted_edges(db_session: AsyncSession) -> None:
    people = [P(1, name="Anna Keller"), P(2, "sued.example"), P(3), P(4)]
    edges = [E(1, 2, a_to_b=4, b_to_a=1), E(1, 3, a_to_b=1), E(2, 4, b_to_a=2)]
    await insert_graph(db_session, people, edges)

    graph = await _graph(db_session, center=[1], min_edge=3)

    nodes = _nodes(graph)
    assert set(nodes) == {1, 2}
    assert nodes[1].model_dump() == {
        "id": 1,
        "name": "Anna Keller",
        "email": "p1@nord.example",
        "domain": "nord.example",
        "kind": None,
        "mails": 6,  # 1-3 is below the threshold but counted
        "contacts": 2,
        "center": True,
    }
    assert (nodes[2].mails, nodes[2].contacts, nodes[2].center) == (7, 2, False)
    assert graph.mails == 5


async def test_cc_counts_towards_the_weight_only_on_request(db_session: AsyncSession) -> None:
    edges = [E(1, 2, cc=4), E(1, 3, a_to_b=2, cc=3)]
    await insert_graph(db_session, persons(1, 2, 3), edges)

    graph = await _graph(db_session, center=[1])
    assert set(_ids(graph)) == {1, 3}  # a pair of Cc only has weight 0 and does not exist
    (edge,) = graph.edges
    assert (edge.a_to_b, edge.b_to_a, edge.cc, edge.weight) == (2, 0, 3, 2)
    assert (_nodes(graph)[1].mails, _nodes(graph)[1].contacts) == (2, 1)

    graph = await _graph(db_session, center=[1], cc=True)
    assert set(_ids(graph)) == {1, 2, 3}
    assert _weights(graph) == {(1, 3): 5, (1, 2): 4}
    assert (_nodes(graph)[1].mails, _nodes(graph)[1].contacts) == (9, 2)


async def test_dkim_only_counts_the_passed_mails(db_session: AsyncSession) -> None:
    edges = [
        E(1, 2, a_to_b=5, b_to_a=1, pass_a_to_b=2, pass_b_to_a=1),
        E(1, 3, a_to_b=3),
        E(1, 4, cc=2, pass_cc=1),
    ]
    await insert_graph(db_session, persons(1, 2, 3, 4), edges)

    graph = await _graph(db_session, center=[1], dkim_only=True)
    assert set(_ids(graph)) == {1, 2}
    (edge,) = graph.edges
    assert (edge.a_to_b, edge.b_to_a, edge.cc, edge.weight) == (2, 1, 0, 3)

    graph = await _graph(db_session, center=[1], dkim_only=True, cc=True)
    assert _weights(graph) == {(1, 2): 3, (1, 4): 1}
    assert {(e.target, e.cc) for e in graph.edges} == {(2, 0), (4, 1)}


async def test_years_sum_edge_year_over_the_range(db_session: AsyncSession) -> None:
    edges = [
        # edge holds the totals, including undated mails (4 of 1-2)
        E(1, 2, a_to_b=9, b_to_a=1),
        E(1, 3, a_to_b=4),
        E(2, 3, a_to_b=1),
        E(1, 4, cc=2),
        E(1, 2, a_to_b=3, year=2018),
        E(1, 2, a_to_b=2, b_to_a=1, year=2019),
        E(1, 3, a_to_b=4, year=2020),
        E(2, 3, a_to_b=1, year=2018),
        E(1, 4, cc=2, year=2019),
    ]
    await insert_graph(db_session, persons(1, 2, 3, 4), edges)

    async def weights(**years: int) -> dict[tuple[int, int], int]:
        return _weights(await _graph(db_session, center=[1], depth=2, **years))

    assert await weights() == {(1, 2): 10, (1, 3): 4, (2, 3): 1}
    assert await weights(year_from=2019, year_to=2019) == {(1, 2): 3}
    assert await weights(year_from=2019) == {(1, 3): 4, (1, 2): 3}
    assert await weights(year_to=2018) == {(1, 2): 3, (2, 3): 1}
    assert await weights(year_from=2018, year_to=2020) == {(1, 2): 6, (1, 3): 4, (2, 3): 1}
    assert await weights(year_from=2021) == {}

    graph = await _graph(db_session, center=[1], year_from=2019, year_to=2019, cc=True)
    (edge,) = [e for e in graph.edges if e.target == 2]
    assert (edge.a_to_b, edge.b_to_a, edge.cc, edge.weight) == (2, 1, 0, 3)
    assert _weights(graph) == {(1, 2): 3, (1, 4): 2}
    assert (_nodes(graph)[1].mails, _nodes(graph)[1].contacts) == (5, 2)


async def test_hide_leaves_out_persons_and_their_edges(db_session: AsyncSession) -> None:
    people = [*persons(1, 2, 3, 4), P(9, "alt.example", merged_into=2)]
    edges = [E(1, 2, a_to_b=5), E(2, 3, a_to_b=5), E(1, 4, a_to_b=1)]
    await insert_graph(db_session, people, edges)

    graph = await _graph(db_session, center=[1], depth=2, hide=[9, 999])  # 9 is an alias of 2
    assert set(_ids(graph)) == {1, 4}
    assert (_nodes(graph)[1].mails, _nodes(graph)[1].contacts) == (1, 1)

    graph = await _graph(db_session, center=[1], depth=2, hide=[1])  # never a center
    assert set(_ids(graph)) == {1, 2, 3, 4}


async def test_hide_lists_leaves_out_lists_and_automated_senders(db_session: AsyncSession) -> None:
    people = [P(1), P(2, kind=PersonKind.LIST), P(3, "shop.example", PersonKind.AUTOMATED), P(4)]
    edges = [E(1, 2, a_to_b=5), E(1, 3, b_to_a=5), E(1, 4, a_to_b=2), E(2, 4, a_to_b=3)]
    await insert_graph(db_session, people, edges)

    graph = await _graph(db_session, center=[1])
    assert set(_ids(graph)) == {1, 2, 3, 4}
    assert _nodes(graph)[3].kind is PersonKind.AUTOMATED
    assert (_nodes(graph)[1].mails, _nodes(graph)[1].contacts) == (12, 3)

    graph = await _graph(db_session, center=[1], hide_lists=True)
    assert set(_ids(graph)) == {1, 4}
    assert (_nodes(graph)[4].mails, _nodes(graph)[4].contacts) == (2, 1)

    # A list as center stays, with its edges; the automated sender is still left out.
    graph = await _graph(db_session, center=[2], hide_lists=True)
    assert set(_ids(graph)) == {1, 2, 4}
    assert _nodes(graph)[2].kind is PersonKind.LIST
    assert _weights(graph) == {(1, 2): 5, (2, 4): 3, (1, 4): 2}
    assert (_nodes(graph)[1].mails, _nodes(graph)[1].contacts) == (7, 2)


async def test_expand_adds_persons_and_their_neighbours(db_session: AsyncSession) -> None:
    people = [*persons(1, 2, 3, 4, 5, 6), P(7, kind=PersonKind.LIST), P(8, merged_into=3)]
    edges = [
        E(1, 2, a_to_b=5),
        E(2, 3, a_to_b=5),
        E(3, 4, a_to_b=5),
        E(3, 5, a_to_b=1),
        E(3, 7, a_to_b=5),
    ]
    await insert_graph(db_session, people, edges)

    graph = await _graph(db_session, center=[1], expand=[8])  # 8 is an alias of 3
    assert set(_ids(graph)) == {1, 2, 3, 4, 5, 7}
    graph = await _graph(db_session, center=[1], expand=[3], min_edge=2)
    assert set(_ids(graph)) == {1, 2, 3, 4, 7}
    graph = await _graph(db_session, center=[1], expand=[3], hide_lists=True)
    assert set(_ids(graph)) == {1, 2, 3, 4, 5}
    # An expanded person stays without edges; left-out and unknown persons are not added.
    graph = await _graph(db_session, center=[1], expand=[6, 7, 999], hide_lists=True)
    assert set(_ids(graph)) == {1, 2, 6}
    assert _nodes(graph)[6].mails == 0


async def test_merged_centers_resolve_to_their_roots(db_session: AsyncSession) -> None:
    people = [*persons(1, 2, 3), P(9, "alt.example", merged_into=1)]
    await insert_graph(db_session, people, [E(1, 2, a_to_b=3), E(2, 3, a_to_b=3)])

    graph = await _graph(db_session, center=[9, 1, 2])
    assert graph.centers == [1, 2]
    assert set(_ids(graph)) == {1, 2, 3}
    assert {node.id for node in graph.nodes if node.center} == {1, 2}
    assert (await _graph(db_session, center=[2, 9])).centers == [2, 1]
    # Centers only belong to the ego mode.
    assert (await _graph(db_session, mode="top", center=[1, 999])).centers == []


async def test_top_takes_the_persons_with_the_most_mails(db_session: AsyncSession) -> None:
    edges = [E(1, 2, a_to_b=10), E(1, 3, a_to_b=6), E(4, 5, a_to_b=4), E(5, 6, b_to_a=4)]
    await insert_graph(db_session, persons(1, 2, 3, 4, 5, 6), edges)

    # Top 4 by mails: 1 (16), 2 (10), 5 (8), 3 (6); 5 has edges only to persons outside.
    graph = await _graph(db_session, mode="top", limit=4)
    assert _ids(graph) == [1, 2, 3]
    assert graph.centers == []
    # Top 5 takes 4 before 6 (4 mails each), which links 5.
    graph = await _graph(db_session, mode="top", limit=5)
    assert _ids(graph) == [1, 2, 5, 3, 4]
    assert _weights(graph) == {(1, 2): 10, (1, 3): 6, (4, 5): 4}
    graph = await _graph(db_session, mode="top", limit=5, min_edge=5)
    assert _ids(graph) == [1, 2, 3]
    # The ranking is over the counted graph: hidden persons and their edges are gone.
    graph = await _graph(db_session, mode="top", limit=3, hide=[1])
    assert _ids(graph) == [5, 4, 6]
    # Expanded persons and their neighbours may link a ranked person.
    graph = await _graph(db_session, mode="top", limit=4, expand=[4])
    assert _ids(graph) == [1, 2, 5, 3, 4]


async def test_domains_face_each_other(db_session: AsyncSession) -> None:
    people = [
        P(1),
        P(2),
        P(3, "sued.example"),
        P(4, "mail.sued.example"),
        P(5, "west.example"),
        P(6),
        P(7, "sued.example"),
        P(8, "notsued.example"),
    ]
    edges = [
        E(1, 3, a_to_b=2),
        E(2, 4, b_to_a=5),
        E(1, 2, a_to_b=7),  # one side, between shown persons
        E(1, 5, a_to_b=9),  # to a third domain
        E(6, 7, a_to_b=1),
        E(1, 8, a_to_b=5),
    ]
    await insert_graph(db_session, people, edges)

    graph = await _graph(
        db_session, mode="domains", domain=["nord.example", " Sued.Example"], min_edge=2
    )
    assert _ids(graph) == [1, 2, 4, 3]
    assert _weights(graph) == {(1, 2): 7, (2, 4): 5, (1, 3): 2}
    assert _nodes(graph)[1].mails == 23
    graph = await _graph(db_session, mode="domains", domain=["sued.example", "nord.example"])
    assert set(_ids(graph)) == {1, 2, 3, 4, 6, 7}
    graph = await _graph(db_session, mode="domains", domain=["nord.example", "none.example"])
    assert graph.nodes == []


@pytest.mark.parametrize(
    "params",
    [
        {"mode": "ego"},
        {"mode": "domains", "domain": ["a.example"]},
        {"mode": "domains", "domain": ["a.example", "A.example"]},
        {"mode": "domains", "domain": ["a.example", "b.example", "c.example"]},
        {"mode": "domains", "domain": ["a.example", " "]},
        {"mode": "top", "year_from": 2020, "year_to": 2019},
    ],
)
async def test_parameters_without_an_excerpt(db_session: AsyncSession, params: Any) -> None:
    with pytest.raises(excerpt.ExcerptError):
        await _graph(db_session, **params)
    with pytest.raises(excerpt.ExcerptError):
        await excerpt.graph_size(db_session, _params(**params))


async def test_unknown_center(db_session: AsyncSession) -> None:
    await insert_graph(db_session, persons(1))
    with pytest.raises(excerpt.UnknownCenter, match="999"):
        await _graph(db_session, center=[1, 999])


async def test_more_nodes_than_the_limit(db_session: AsyncSession) -> None:
    leaves = range(2, MAX_GRAPH_NODES + 3)
    await insert_graph(db_session, persons(1, *leaves), [E(1, leaf, a_to_b=1) for leaf in leaves])

    with pytest.raises(excerpt.GraphTooLarge) as raised:
        await _graph(db_session, center=[1])
    assert raised.value.nodes == MAX_GRAPH_NODES + 2
    assert str(MAX_GRAPH_NODES + 2) in str(raised.value)
    size = await excerpt.graph_size(db_session, _params(center=[1]))
    assert size.model_dump() == {
        "nodes": MAX_GRAPH_NODES + 2,
        "edges": MAX_GRAPH_NODES + 1,
        "mails": MAX_GRAPH_NODES + 1,
        "too_large": True,
    }
    # Around a leaf the excerpt is small.
    assert len((await _graph(db_session, center=[2])).nodes) == 2


async def test_size_counts_what_the_graph_shows(db_session: AsyncSession) -> None:
    edges = [E(1, 2, a_to_b=3, cc=1), E(1, 3, a_to_b=1), E(2, 3, b_to_a=2), E(3, 4, a_to_b=4)]
    await insert_graph(db_session, persons(1, 2, 3, 4), edges)

    for params in (
        _params(center=[1], min_edge=2),
        _params(center=[1], depth=2, cc=True),
        _params(mode="top", limit=2),
    ):
        graph = await excerpt.build_graph(db_session, params)
        size = await excerpt.graph_size(db_session, params)
        assert (size.nodes, size.edges, size.mails) == (
            len(graph.nodes),
            len(graph.edges),
            graph.mails,
        )
        assert not size.too_large


async def test_edge_table_from_global_stats(db_session: AsyncSession) -> None:
    await insert_graph(db_session, persons(1, 2, 3), [E(1, 2, a_to_b=1), E(2, 3, a_to_b=1)])
    table = await excerpt.edge_table(db_session)
    assert (table.pairs, table.refreshed_at) == (2, None)

    refreshed = {"pairs": 7, "refreshed_at": "2026-10-21T08:15:00+00:00"}
    await db_session.execute(insert(GlobalStats).values(key=excerpt.EDGES_KEY, value=refreshed))
    table = await excerpt.edge_table(db_session)
    assert table.pairs == 7
    assert table.refreshed_at is not None
    assert table.refreshed_at.isoformat() == "2026-10-21T08:15:00+00:00"
    assert (await _graph(db_session, center=[1])).edge_table == table
