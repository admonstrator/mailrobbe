"""The excerpt of the relationship map that /api/graph shows (D37).

GraphParams defines the counted graph and the modes. Everything is read from edge, or from
edge_year for a year range, never from mails, in a few set-based queries: one per step of the
ego mode, one for the neighbours of expanded persons, one for the edges between the chosen
persons and one for their figures. Those follow the primary key and ix_edge_person_b
(ix_edge_year_person_b), so they cost what the excerpt touches, not what the archive holds; only
the top mode ranks every person, in one aggregate over the counted graph. A step returns just
the persons not reached before, so even an excerpt far above MAX_GRAPH_NODES is counted in a
few passes over the edge table.

The functions run in the caller's transaction and only read.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe.api.schemas import (
    MAX_GRAPH_NODES,
    EdgeTable,
    Graph,
    GraphEdge,
    GraphNode,
    GraphParams,
    GraphSize,
)
from mailrobbe.db.models import GlobalStats, Person

Executor = AsyncSession | AsyncConnection

EDGES_KEY = "edges"  # global_stats row of refresh_edges: {"pairs": int, "refreshed_at": str}

_COUNTERS = ("a_to_b", "b_to_a", "cc")
_YEARS = (0, 32_767)  # bounds of edge_year.year (smallint) for an open end of the range
_IDS = range(-(2**63), 2**63)  # bigint: anything else is no person id
_MAX_WEIGHT = 2**31 - 1  # no edge is heavier, so a larger min_edge means the same
# Conditions on the pairs of edge and edge_year; the arrays are bound per query.
_TOUCHING = "(person_a = ANY(:persons) OR person_b = ANY(:persons))"
_BETWEEN = "person_a = ANY(:nodes) AND person_b = ANY(:nodes)"
_ACROSS = (
    "(person_a = ANY(:left) AND person_b = ANY(:right)"
    " OR person_a = ANY(:right) AND person_b = ANY(:left))"
)
# Both ends of every edge e, as rows of ends.person.
_ENDS = "CROSS JOIN LATERAL (VALUES (e.person_a), (e.person_b)) AS ends(person)"


class ExcerptError(ValueError):
    """Parameters that describe no excerpt (400 invalid_filter)."""


class UnknownCenter(LookupError):
    """A center id that is no person (404 not_found)."""

    def __init__(self, person_id: int) -> None:
        super().__init__(f"no person with id {person_id}")
        self.person_id = person_id


class GraphTooLarge(Exception):
    """The excerpt has more nodes than a map shows (400 graph_too_large)."""

    def __init__(self, nodes: int) -> None:
        super().__init__(
            f"the excerpt has {nodes} persons, more than the limit of {MAX_GRAPH_NODES};"
            " raise the threshold or narrow the excerpt"
        )
        self.nodes = nodes


@dataclass(frozen=True, slots=True)
class _Counting:
    """The counted graph of one set of parameters, as SQL over edge or edge_year."""

    prefix: str  # counter columns: mails_* or, for DKIM-valid mails only, pass_*
    cc: bool  # Cc in the weight
    yearly: bool  # summed from edge_year
    values: dict[str, Any]  # bind values shared by every query: hidden, years, min_edge

    @classmethod
    def of(cls, params: GraphParams, hidden: list[int]) -> "_Counting":
        return cls(
            prefix="pass" if params.dkim_only else "mails",
            cc=params.cc,
            yearly=params.year_from is not None or params.year_to is not None,
            values={
                "hidden": hidden,
                "year_from": _YEARS[0] if params.year_from is None else params.year_from,
                "year_to": _YEARS[1] if params.year_to is None else params.year_to,
                "min_edge": min(params.min_edge, _MAX_WEIGHT),
            },
        )

    def edges(self, pairs: str) -> str:
        """A query of the counted edges among the pairs matching the condition pairs: columns
        person_a, person_b, a_to_b, b_to_a, cc and weight, which is above zero."""
        table, where = self._rows(pairs)
        if self.yearly:
            counters = ", ".join(f"sum({self.prefix}_{name}) AS {name}" for name in _COUNTERS)
            source = (
                f"SELECT person_a, person_b, {counters} FROM {table} WHERE {where}"
                " GROUP BY person_a, person_b"
            )
        else:
            counters = ", ".join(f"{self.prefix}_{name} AS {name}" for name in _COUNTERS)
            source = f"SELECT person_a, person_b, {counters} FROM {table} WHERE {where}"
        weight = self._weight("")
        return f"SELECT c.*, {weight} AS weight FROM ({source}) AS c WHERE {weight} > 0"

    def ranking(self) -> str:
        """A query of person and mails, one row per end of the edge or edge_year rows: summed
        per person, they give the mails of everyone in the counted graph. Sums per pair are not
        needed first, as a pair of weight 0 adds nothing, which spares an aggregate over all
        pairs of a year range."""
        table, where = self._rows("TRUE")
        weight = self._weight(self.prefix + "_")
        return (
            f"SELECT person_a AS person, sum({weight}) AS mails FROM {table} WHERE {where}"
            f" GROUP BY person_a UNION ALL"
            f" SELECT person_b, sum({weight}) FROM {table} WHERE {where} GROUP BY person_b"
        )

    def _rows(self, pairs: str) -> tuple[str, str]:
        """The table and the condition of the rows counted for the pairs matching pairs."""
        where = [pairs]
        if self.values["hidden"]:  # <> ALL over a bound array is a hash lookup
            where.append("person_a <> ALL(:hidden) AND person_b <> ALL(:hidden)")
        if self.yearly:
            where.append("year BETWEEN :year_from AND :year_to")
        return "edge_year" if self.yearly else "edge", " AND ".join(where)

    def _weight(self, prefix: str) -> str:
        names = _COUNTERS if self.cc else _COUNTERS[:2]
        return " + ".join(prefix + name for name in names)


@dataclass(frozen=True, slots=True)
class _Excerpt:
    nodes: set[int]
    centers: list[int]  # root persons in the given order
    counting: _Counting


async def build_graph(db: Executor, params: GraphParams) -> Graph:
    """The excerpt with its nodes, edges and figures; GraphTooLarge above MAX_GRAPH_NODES."""
    excerpt = await _excerpt(db, params)
    if len(excerpt.nodes) > MAX_GRAPH_NODES:
        raise GraphTooLarge(len(excerpt.nodes))
    nodes = sorted(excerpt.nodes)
    values = {**excerpt.counting.values, "nodes": nodes, "persons": nodes}
    shown = excerpt.counting.edges(_BETWEEN)
    edges = [
        GraphEdge(source=a, target=b, a_to_b=a_to_b, b_to_a=b_to_a, cc=cc, weight=weight)
        for a, b, a_to_b, b_to_a, cc, weight in await db.execute(
            text(f"""
                SELECT e.person_a, e.person_b, e.a_to_b, e.b_to_a, e.cc, e.weight
                FROM ({shown}) AS e WHERE e.weight >= :min_edge
                ORDER BY e.weight DESC, e.person_a, e.person_b
            """),
            values,
        )
    ]
    # A node's figures cover all its counted edges, shown or not.
    counted = excerpt.counting.edges(_TOUCHING)
    rows = await db.execute(
        text(f"""
            SELECT p.id, p.display_name, p.canonical_email, p.domain, p.kind,
                coalesce(f.mails, 0), coalesce(f.contacts, 0)
            FROM person p LEFT JOIN (
                SELECT ends.person, sum(e.weight) AS mails, count(*) AS contacts
                FROM ({counted}) AS e {_ENDS}
                WHERE ends.person = ANY(:persons)
                GROUP BY ends.person
            ) AS f ON f.person = p.id
            WHERE p.id = ANY(:nodes)
        """),
        values,
    )
    centers = set(excerpt.centers)
    shown_nodes = [
        GraphNode(
            id=person_id,
            name=name,
            email=email,
            domain=domain,
            kind=kind,
            mails=mails,
            contacts=contacts,
            center=person_id in centers,
        )
        for person_id, name, email, domain, kind, mails, contacts in rows
    ]
    shown_nodes.sort(key=lambda node: (-node.mails, node.id))
    return Graph(
        nodes=shown_nodes,
        edges=edges,
        mails=sum(edge.weight for edge in edges),
        centers=excerpt.centers,
        edge_table=await edge_table(db),
    )


async def graph_size(db: Executor, params: GraphParams) -> GraphSize:
    """The counts build_graph would show, for any excerpt however large."""
    excerpt = await _excerpt(db, params)
    shown = excerpt.counting.edges(_BETWEEN)
    edges, mails = (
        await db.execute(
            text(
                f"SELECT count(*), coalesce(sum(e.weight), 0) FROM ({shown}) AS e"
                " WHERE e.weight >= :min_edge"
            ),
            {**excerpt.counting.values, "nodes": sorted(excerpt.nodes)},
        )
    ).one()
    nodes = len(excerpt.nodes)
    return GraphSize(nodes=nodes, edges=edges, mails=mails, too_large=nodes > MAX_GRAPH_NODES)


async def edge_table(db: Executor) -> EdgeTable:
    """Size and age of the edge table, from the row refresh_edges writes into global_stats."""
    value = await db.scalar(select(GlobalStats.value).where(GlobalStats.key == EDGES_KEY))
    if value is None:
        return EdgeTable(
            pairs=await db.scalar(text("SELECT count(*) FROM edge")) or 0, refreshed_at=None
        )
    return EdgeTable(pairs=value["pairs"], refreshed_at=value.get("refreshed_at"))


async def _excerpt(db: Executor, params: GraphParams) -> _Excerpt:
    """The excerpt's persons; ExcerptError or UnknownCenter for parameters that name none."""
    if (
        params.year_from is not None
        and params.year_to is not None
        and params.year_from > params.year_to
    ):
        raise ExcerptError(f"year_from {params.year_from} is after year_to {params.year_to}")
    domains = list(dict.fromkeys(domain.strip().lower().lstrip("@") for domain in params.domain))
    if params.mode == "domains" and (len(domains) != 2 or not all(domains)):
        raise ExcerptError("the domains mode takes exactly two different domains")
    if params.mode == "ego" and not params.center:
        raise ExcerptError("the ego mode needs at least one center")

    asked = params.center if params.mode == "ego" else []
    roots = await _roots(db, [*asked, *params.expand, *params.hide])
    for person_id in asked:
        if person_id not in roots:
            raise UnknownCenter(person_id)
    centers = list(dict.fromkeys(roots[person_id] for person_id in asked))
    hidden = {roots[person_id] for person_id in params.hide if person_id in roots}
    if params.hide_lists:
        hidden.update(await db.scalars(select(Person.id).where(Person.kind.is_not(None))))
    hidden.difference_update(centers)
    counting = _Counting.of(params, sorted(hidden))

    ranked: list[int] = []
    match params.mode:
        case "ego":
            nodes = await _ego(db, counting, centers, params.depth)
        case "top":
            ranked = await _top(db, counting, params.limit)
            nodes = set(ranked)
        case "domains":
            nodes = await _across(db, counting, domains[0], domains[1])

    expanded = {roots[person_id] for person_id in params.expand if person_id in roots} - hidden
    if expanded:
        nodes |= expanded | await _neighbours(db, counting, expanded, nodes | expanded)
    if ranked:
        # Everyone else came in over a shown edge or stays anyway (centers, expanded persons).
        linked = await _linked(db, counting, ranked, nodes)
        nodes.difference_update(set(ranked) - linked - expanded)
    return _Excerpt(nodes, centers, counting)


async def _roots(db: Executor, person_ids: list[int]) -> dict[int, int]:
    """The root person of each of these ids that is a person."""
    ids = [person_id for person_id in person_ids if person_id in _IDS]
    if not ids:
        return {}
    rows = await db.execute(
        text("SELECT id, coalesce(merged_into, id) FROM person WHERE id = ANY(:ids)"),
        {"ids": ids},
    )
    return {person_id: root for person_id, root in rows}


async def _neighbours(
    db: Executor, counting: _Counting, persons: set[int], known: set[int]
) -> set[int]:
    """Persons outside known with an edge of at least min_edge to one of persons."""
    rows = await db.scalars(
        text(f"""
            SELECT DISTINCT ends.person FROM ({counting.edges(_TOUCHING)}) AS e {_ENDS}
            WHERE e.weight >= :min_edge AND ends.person <> ALL(:known)
        """),
        {**counting.values, "persons": sorted(persons), "known": sorted(known)},
    )
    return set(rows)


async def _ego(db: Executor, counting: _Counting, centers: list[int], depth: int) -> set[int]:
    """The centers and everyone up to depth steps away over edges of at least min_edge."""
    reached = set(centers)
    frontier = set(centers)
    for _ in range(depth):
        if not frontier:
            break
        frontier = await _neighbours(db, counting, frontier, reached)
        reached |= frontier
    return reached


async def _top(db: Executor, counting: _Counting, limit: int) -> list[int]:
    """The limit persons with the most mails over the counted graph, ties by id."""
    rows = await db.scalars(
        text(f"""
            SELECT r.person FROM ({counting.ranking()}) AS r GROUP BY r.person
            HAVING sum(r.mails) > 0 ORDER BY sum(r.mails) DESC, r.person LIMIT :limit
        """),
        {**counting.values, "limit": limit},
    )
    return list(rows)


async def _across(db: Executor, counting: _Counting, left: str, right: str) -> set[int]:
    """The persons of either domain with an edge of at least min_edge to the other one."""
    left_side, right_side = await _domain(db, left), await _domain(db, right)
    if not left_side or not right_side:
        return set()
    rows = await db.scalars(
        text(f"""
            SELECT DISTINCT ends.person FROM ({counting.edges(_ACROSS)}) AS e {_ENDS}
            WHERE e.weight >= :min_edge
        """),
        {**counting.values, "left": left_side, "right": right_side},
    )
    return set(rows)


async def _domain(db: Executor, domain: str) -> list[int]:
    """The root persons of the domain and its subdomains."""
    in_domain = or_(Person.domain == domain, Person.domain.endswith("." + domain, autoescape=True))
    return list(await db.scalars(select(Person.id).where(Person.merged_into.is_(None), in_domain)))


async def _linked(
    db: Executor, counting: _Counting, persons: list[int], nodes: set[int]
) -> set[int]:
    """Those of persons with an edge of at least min_edge to another of the nodes."""
    rows = await db.scalars(
        text(f"""
            SELECT DISTINCT ends.person FROM ({counting.edges(_BETWEEN)}) AS e {_ENDS}
            WHERE e.weight >= :min_edge AND ends.person = ANY(:persons)
        """),
        {**counting.values, "persons": persons, "nodes": sorted(nodes)},
    )
    return set(rows)
