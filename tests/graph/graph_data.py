"""Hand-made graphs for the excerpt and graph API tests: persons and edge rows with known counters.

Persons get explicit ids and the address p<id>@<domain>; an edge row without a year goes into
edge, one with a year into edge_year. Nothing checks that edge and edge_year agree, so a test can
give them different counters on purpose.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe.db.models import Edge, EdgeYear, Person
from mailrobbe.enums import PersonKind


@dataclass(frozen=True, slots=True)
class P:
    id: int
    domain: str = "nord.example"
    kind: PersonKind | None = None
    merged_into: int | None = None
    name: str | None = None

    @property
    def email(self) -> str:
        return f"p{self.id}@{self.domain}"


@dataclass(frozen=True, slots=True)
class E:
    a: int  # the smaller id
    b: int
    a_to_b: int = 0
    b_to_a: int = 0
    cc: int = 0
    pass_a_to_b: int = 0
    pass_b_to_a: int = 0
    pass_cc: int = 0
    year: int | None = None  # None: a row of edge, else of edge_year


def persons(*ids: int, domain: str = "nord.example") -> list[P]:
    return [P(person_id, domain) for person_id in ids]


async def insert_graph(
    db: AsyncSession | AsyncConnection, people: Iterable[P], edges: Iterable[E] = ()
) -> None:
    people = list(people)
    edges = list(edges)
    # Roots first: merged_into refers to them.
    for batch in (
        [p for p in people if p.merged_into is None],
        [p for p in people if p.merged_into],
    ):
        if batch:
            await db.execute(
                insert(Person),
                [
                    {
                        "id": p.id,
                        "canonical_email": p.email,
                        "display_name": p.name,
                        "domain": p.domain,
                        "merged_into": p.merged_into,
                        "kind": p.kind,
                    }
                    for p in batch
                ],
            )
    for table, rows in (
        (Edge, [e for e in edges if e.year is None]),
        (EdgeYear, [e for e in edges if e.year]),
    ):
        if rows:
            await db.execute(insert(table), [_edge_row(e) for e in rows])


def _edge_row(edge: E) -> dict[str, int]:
    assert edge.a < edge.b, "edge rows order their persons"
    row = {
        "person_a": edge.a,
        "person_b": edge.b,
        "mails_a_to_b": edge.a_to_b,
        "mails_b_to_a": edge.b_to_a,
        "mails_cc": edge.cc,
        "pass_a_to_b": edge.pass_a_to_b,
        "pass_b_to_a": edge.pass_b_to_a,
        "pass_cc": edge.pass_cc,
    }
    if edge.year is not None:
        row["year"] = edge.year
    return row
