"""GraphML for Gephi (D5, D38): one format for the excerpt download and the full export.

The graph is undirected; Gephi takes the node attribute "label" as the label and the edge
attribute "weight" as the weight. Node ids are person ids. Edge dates are only written when
known, which is the case for the full export from the edge table; the team's label of a person
(D157) only when it has one, and its name is then the label.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from xml.sax.saxutils import escape, quoteattr

MEDIA_TYPE = "application/graphml+xml"

# (id, for, type): the attribute keys, in the order they appear in every node and edge.
_NODE_KEYS = (
    ("label", "string"),
    ("email", "string"),
    ("domain", "string"),
    ("kind", "string"),
    ("mails", "int"),
    ("label_name", "string"),
    ("label_role", "string"),
)
_EDGE_KEYS = (
    ("weight", "int"),
    ("a_to_b", "int"),
    ("b_to_a", "int"),
    ("cc", "int"),
    ("first_date", "string"),
    ("last_date", "string"),
)
# Characters XML 1.0 cannot carry, even escaped; display names may contain them.
_INVALID_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


@dataclass(frozen=True, slots=True)
class GraphmlNode:
    id: int  # person id
    label: str  # the label's name, else the display name, else the address
    email: str
    domain: str
    kind: str | None  # person.kind
    mails: int
    label_name: str | None = None  # the team's label (D157)
    label_role: str | None = None


@dataclass(frozen=True, slots=True)
class GraphmlEdge:
    source: int
    target: int
    weight: int
    a_to_b: int
    b_to_a: int
    cc: int
    first_date: datetime | None = None
    last_date: datetime | None = None


def graphml_chunks(
    nodes: Iterable[GraphmlNode], edges: Iterable[GraphmlEdge], graph_id: str = "mailrobbe"
) -> Iterator[str]:
    """The document in pieces of one element each, for streaming; every edge's ends must be
    among the nodes."""
    yield '<?xml version="1.0" encoding="UTF-8"?>\n'
    yield '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">\n'
    for target, keys in (("node", _NODE_KEYS), ("edge", _EDGE_KEYS)):
        for key, kind in keys:
            yield f'  <key id="{key}" for="{target}" attr.name="{key}" attr.type="{kind}"/>\n'
    yield f'  <graph id={_attr(graph_id)} edgedefault="undirected">\n'
    for node in nodes:
        attributes = (
            node.label,
            node.email,
            node.domain,
            node.kind,
            node.mails,
            node.label_name,
            node.label_role,
        )
        yield f'    <node id="{node.id}">{_data(_NODE_KEYS, attributes)}</node>\n'
    for edge in edges:
        values = (
            edge.weight,
            edge.a_to_b,
            edge.b_to_a,
            edge.cc,
            None if edge.first_date is None else edge.first_date.isoformat(),
            None if edge.last_date is None else edge.last_date.isoformat(),
        )
        yield (
            f'    <edge source="{edge.source}" target="{edge.target}">'
            f"{_data(_EDGE_KEYS, values)}</edge>\n"
        )
    yield "  </graph>\n</graphml>\n"


def _data(keys: tuple[tuple[str, str], ...], values: Iterable[str | int | None]) -> str:
    return "".join(
        f'<data key="{key}">{_text(value)}</data>'
        for (key, _), value in zip(keys, values, strict=True)
        if value is not None
    )


def _text(value: str | int) -> str:
    return escape(_INVALID_XML.sub("", str(value)))


def _attr(value: str) -> str:
    return quoteattr(_INVALID_XML.sub("", value))
