import random

import pytest

from mailrobbe.topics.louvain import Link, _Graph, louvain


def clique(nodes: list[int], weight: float = 1.0) -> list[Link]:
    return [(a, b, weight) for index, a in enumerate(nodes) for b in nodes[index + 1 :]]


def ring_of_cliques(cliques: int, size: int) -> list[Link]:
    """Cliques of consecutive nodes, each linked to the next by one link, the last to the first."""
    links = []
    for number in range(cliques):
        first = number * size
        links += clique(list(range(first, first + size)))
        links.append((first + size - 1, (first + size) % (cliques * size), 1.0))
    return links


def shuffled(links: list[Link], seed: int) -> list[Link]:
    """The same links in another order, some of them the other way round."""
    rng = random.Random(seed)
    turned = [(j, i, weight) if rng.random() < 0.5 else (i, j, weight) for i, j, weight in links]
    rng.shuffle(turned)
    return turned


# Two cliques of four, interleaved, with one weak link between them.
TWO_GROUPS = [*clique([0, 2, 4, 6]), *clique([1, 3, 5, 7], 0.8), (6, 7, 0.2)]


def test_two_obvious_groups_are_found_and_numbered_by_their_first_node() -> None:
    assert louvain(8, TWO_GROUPS) == [0, 1, 0, 1, 0, 1, 0, 1]


@pytest.mark.parametrize(
    ("size", "links"),
    [
        (8, TWO_GROUPS),
        (4, [(0, 1, 1.0), (1, 2, 1.0), (2, 3, 1.0), (3, 0, 1.0)]),  # ties everywhere
        (24, ring_of_cliques(6, 4)),
        (90, ring_of_cliques(30, 3)),
    ],
)
def test_the_same_graph_gives_the_same_communities(size: int, links: list[Link]) -> None:
    found = louvain(size, links)
    assert louvain(size, links) == found
    for seed in range(5):
        assert louvain(size, shuffled(links, seed)) == found


def test_ties_go_to_the_smaller_community() -> None:
    # A square: every node is as close to one neighbour as to the other.
    assert louvain(4, [(0, 1, 1.0), (1, 2, 1.0), (2, 3, 1.0), (3, 0, 1.0)]) == [0, 0, 1, 1]


def test_nodes_without_links_stay_alone() -> None:
    assert louvain(5, []) == [0, 1, 2, 3, 4]
    assert louvain(5, [(1, 3, 1.0), (3, 4, 1.0), (1, 4, 1.0)]) == [0, 1, 2, 1, 1]


def test_cliques_in_a_ring_are_communities() -> None:
    assert louvain(24, ring_of_cliques(6, 4)) == [node // 4 for node in range(24)]


def test_the_aggregation_merges_communities_while_modularity_grows() -> None:
    # 30 triangles in a ring: the first level finds the triangles, the next joins neighbours,
    # which raises the modularity (the resolution limit of modularity).
    links = ring_of_cliques(30, 3)
    graph = _Graph.build(90, sorted(links), [0.0] * 90)
    first_level = graph.moved()
    assert len(set(first_level)) == 30
    triangles = [node // 3 for node in range(90)]
    found = louvain(90, links)
    assert found == [node // 6 for node in range(90)]
    assert graph.modularity(found) > graph.modularity(triangles)


def test_modularity() -> None:
    # Two cliques of four without links between them: each has half the weight and half the
    # degrees, 2 * (1/2 - 1/4).
    links = sorted([*clique([0, 1, 2, 3]), *clique([4, 5, 6, 7])])
    graph = _Graph.build(8, links, [0.0] * 8)
    assert graph.modularity([0, 0, 0, 0, 1, 1, 1, 1]) == pytest.approx(0.5)
    assert graph.modularity(list(range(8))) == pytest.approx(-8 * (3 / 24) ** 2)


def test_a_merged_graph_keeps_the_modularity_of_its_communities() -> None:
    links = sorted(ring_of_cliques(6, 4))
    graph = _Graph.build(24, links, [0.0] * 24)
    community = [node // 8 for node in range(24)]
    merged = graph.merged(community, 3)
    assert merged.size == 3
    assert merged.total == pytest.approx(graph.total)
    assert merged.modularity([0, 1, 2]) == pytest.approx(graph.modularity(community))
    assert merged.modularity([0, 0, 1]) == pytest.approx(
        graph.modularity([node // 16 for node in range(24)])
    )
