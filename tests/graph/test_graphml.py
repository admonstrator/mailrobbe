"""GraphML documents parse as XML and carry every attribute Gephi needs."""

import xml.etree.ElementTree as ET
from datetime import UTC, datetime

from mailrobbe.graph.graphml import GraphmlEdge, GraphmlNode, graphml_chunks

NS = {"g": "http://graphml.graphdrawing.org/xmlns"}


def _parse(nodes: list[GraphmlNode], edges: list[GraphmlEdge]) -> ET.Element:
    return ET.fromstring("".join(graphml_chunks(nodes, edges)).encode())


def _data(element: ET.Element) -> dict[str, str]:
    return {d.attrib["key"]: d.text or "" for d in element.findall("g:data", NS)}


def test_nodes_edges_and_keys() -> None:
    nodes = [
        GraphmlNode(1, "Anna Keller", "anna@nordlicht.example", "nordlicht.example", None, 12),
        GraphmlNode(2, "news@shop.example", "news@shop.example", "shop.example", "automated", 3),
    ]
    first = datetime(2019, 3, 1, 8, 30, tzinfo=UTC)
    edges = [GraphmlEdge(1, 2, 5, 3, 1, 1, first, None)]
    root = _parse(nodes, edges)

    keys = {
        (k.attrib["id"], k.attrib["for"], k.attrib["attr.type"]) for k in root.findall("g:key", NS)
    }
    assert ("label", "node", "string") in keys
    assert ("weight", "edge", "int") in keys
    graph = root.find("g:graph", NS)
    assert graph is not None
    assert graph.attrib["edgedefault"] == "undirected"
    parsed = {n.attrib["id"]: _data(n) for n in graph.findall("g:node", NS)}
    assert parsed["1"] == {
        "label": "Anna Keller",
        "email": "anna@nordlicht.example",
        "domain": "nordlicht.example",
        "mails": "12",
    }
    assert parsed["2"]["kind"] == "automated"
    (edge,) = graph.findall("g:edge", NS)
    assert (edge.attrib["source"], edge.attrib["target"]) == ("1", "2")
    assert _data(edge) == {
        "weight": "5",
        "a_to_b": "3",
        "b_to_a": "1",
        "cc": "1",
        "first_date": "2019-03-01T08:30:00+00:00",
    }


def test_markup_and_control_characters_in_names() -> None:
    nodes = [GraphmlNode(7, 'Müller & <Söhne> "AG"\x07', "a@b.example", "b.example", None, 0)]
    root = _parse(nodes, [])
    node = root.find("g:graph/g:node", NS)
    assert node is not None
    assert _data(node)["label"] == 'Müller & <Söhne> "AG"'


def test_empty_graph() -> None:
    graph = _parse([], []).find("g:graph", NS)
    assert graph is not None
    assert list(graph) == []
