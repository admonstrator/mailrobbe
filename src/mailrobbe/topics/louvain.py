"""Louvain modularity grouping of a weighted graph (Blondel et al. 2008), deterministic (D145).

Nodes are numbered 0 to n - 1, and that is the order they are visited in (the clusters number
their candidate terms by rank). Every node starts in a community of its own. A pass visits each
node, takes it out of its community and puts it into the community among its neighbours' and its
own that raises the modularity most, ties going to the smaller community number; passes repeat
until one moves no node or raises the modularity by no more than MIN_GAIN. Then the communities
become the nodes of a new graph, numbered by their first node, with the links inside a community
as its loop and the links between two communities summed, and the same runs on it. A level that
does not raise the modularity by more than MIN_GAIN is not taken, and the grouping ends.

The links are sorted before anything is summed, so every sum is taken in the same order and the
same graph gives the same communities whatever order its links come in.
"""

from collections.abc import Iterable
from dataclasses import dataclass

MIN_GAIN = 1e-7  # modularity a pass or a level must add to go on
_TIE = 1e-12  # gains closer than this are equal (sums of floats)

Link = tuple[int, int, float]  # two different nodes and the link's weight (> 0)


@dataclass(frozen=True, slots=True)
class _Graph:
    size: int
    links: list[Link]  # i < j, sorted
    loops: list[float]  # weight inside each node (the links inside a community it stands for)
    adjacent: list[list[tuple[int, float]]]  # per node its neighbours (j, weight), sorted by j
    degree: list[float]  # its links' weights plus twice its loop
    total: float  # twice the weight of every link and loop: the sum of the degrees

    @classmethod
    def build(cls, size: int, links: list[Link], loops: list[float]) -> "_Graph":
        adjacent: list[list[tuple[int, float]]] = [[] for _ in range(size)]
        for i, j, weight in links:
            adjacent[i].append((j, weight))
            adjacent[j].append((i, weight))
        for neighbours in adjacent:
            neighbours.sort()
        degree = [
            sum(weight for _, weight in neighbours) + 2 * loop
            for neighbours, loop in zip(adjacent, loops, strict=True)
        ]
        return cls(size, links, loops, adjacent, degree, sum(degree))

    def modularity(self, community: list[int]) -> float:
        inside: dict[int, float] = {}
        degrees: dict[int, float] = {}
        for node, loop in enumerate(self.loops):
            inside[community[node]] = inside.get(community[node], 0.0) + loop
            degrees[community[node]] = degrees.get(community[node], 0.0) + self.degree[node]
        for i, j, weight in self.links:
            if community[i] == community[j]:
                inside[community[i]] += weight
        half = self.total / 2
        return sum(inside[c] / half - (degrees[c] / self.total) ** 2 for c in sorted(inside))

    def moved(self) -> list[int]:
        """The communities of one level: passes of moves until none raises the modularity."""
        community = list(range(self.size))
        degrees = list(self.degree)  # of each community
        quality = self.modularity(community)
        while True:
            moves = 0
            for node in range(self.size):
                own, degree = community[node], self.degree[node]
                degrees[own] -= degree
                weights: dict[int, float] = {own: 0.0}
                for neighbour, weight in self.adjacent[node]:
                    other = community[neighbour]
                    weights[other] = weights.get(other, 0.0) + weight
                # The gain of joining c, times half the total: its links to c, less what c's
                # degree makes expected.
                best, gain = own, None
                for other in sorted(weights):
                    found = weights[other] - degrees[other] * degree / self.total
                    if gain is None or found > gain + _TIE:
                        best, gain = other, found
                degrees[best] += degree
                if best != own:
                    community[node] = best
                    moves += 1
            before, quality = quality, self.modularity(community)
            if not moves or quality - before <= MIN_GAIN:
                return community

    def merged(self, community: list[int], size: int) -> "_Graph":
        """The graph of the communities (numbered 0 to size - 1)."""
        loops = [0.0] * size
        for node, loop in enumerate(self.loops):
            loops[community[node]] += loop
        between: dict[tuple[int, int], float] = {}
        for i, j, weight in self.links:
            a, b = community[i], community[j]
            if a == b:
                loops[a] += weight
            else:
                pair = (a, b) if a < b else (b, a)
                between[pair] = between.get(pair, 0.0) + weight
        links = [(a, b, weight) for (a, b), weight in sorted(between.items())]
        return _Graph.build(size, links, loops)


def louvain(size: int, links: Iterable[Link]) -> list[int]:
    """The community of each of the nodes 0 to size - 1, numbered from 0 in the order of their
    first node. links: each pair of different nodes at most once, in any order and direction;
    a node without links stays alone."""
    canonical = sorted((i, j, weight) if i < j else (j, i, weight) for i, j, weight in links)
    graph = _Graph.build(size, canonical, [0.0] * size)
    membership = list(range(size))  # each node's node in the current graph
    if not graph.total:
        return membership
    quality = graph.modularity(list(range(size)))
    while True:
        community = graph.moved()
        numbers: dict[int, int] = {}
        for label in community:
            numbers.setdefault(label, len(numbers))
        community = [numbers[label] for label in community]
        level = graph.modularity(community)
        if len(numbers) == graph.size or level - quality <= MIN_GAIN:
            return membership
        membership = [community[node] for node in membership]
        graph, quality = graph.merged(community, len(numbers)), level
