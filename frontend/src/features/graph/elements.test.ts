import { describe, expect, it } from "vitest";

import type { Graph, GraphEdge, GraphNode } from "../../api/types";
import { graph } from "../../test/fixtures";
import {
  DOMAIN_PALETTE,
  domainColors,
  EDGE_LABELS,
  edgeWidth,
  graphStylesheet,
  graphVisuals,
  labelFont,
  nodeLabel,
  nodeSize,
  OTHER_COLOR,
  PLAIN_COLOR,
} from "./elements";

const inDomain = (domain: string, count: number) =>
  Array.from({ length: count }, () => ({ domain }));

describe("domain colours", () => {
  it("go to the eight domains with the most nodes, in palette order, the rest grey", () => {
    const nodes = [
      ...inDomain("b.example", 5),
      ...inDomain("a.example", 5), // tie with b: by name
      ...inDomain("c.example", 9),
      ...["d", "e", "f", "g", "h", "i"].flatMap((name) => inDomain(`${name}.example`, 2)),
      ...inDomain("j.example", 1),
      ...inDomain("k.example", 1),
    ];
    const colors = domainColors(nodes);
    expect(colors.legend.map((entry) => entry.domain)).toEqual([
      "c.example",
      "a.example",
      "b.example",
      "d.example",
      "e.example",
      "f.example",
      "g.example",
      "h.example",
    ]);
    expect(colors.legend.map((entry) => entry.color)).toEqual([...DOMAIN_PALETTE]);
    expect(colors.legend[0].nodes).toBe(9);
    expect(colors.color("c.example")).toBe("#1D5BD6");
    expect(colors.color("i.example")).toBe(OTHER_COLOR);
    expect(colors.color("j.example")).toBe(OTHER_COLOR);
    expect(colors.others).toBe(4);
  });

  it("have no grey rest for eight domains or fewer", () => {
    const colors = domainColors([...inDomain("x.test", 2), ...inDomain("y.test", 1)]);
    expect(colors.legend).toHaveLength(2);
    expect(colors.others).toBe(0);
  });
});

describe("sizes and labels", () => {
  it("scale nodes and edges by the logarithm, within fixed bounds", () => {
    expect(nodeSize(100, 100)).toBe(40);
    expect(nodeSize(1, 100)).toBe(12);
    expect(nodeSize(0, 100)).toBe(12);
    expect(nodeSize(10, 100)).toBe(26); // half the diameter range at the square root of the mails
    expect(nodeSize(5, 0)).toBe(12);
    expect(nodeSize(7, 1)).toBe(12);
    expect(edgeWidth(400, 400)).toBe(6);
    expect(edgeWidth(20, 400)).toBe(3.5);
    expect(edgeWidth(1, 400)).toBe(1);
    expect(edgeWidth(1, 0)).toBe(1);
  });

  it("label nodes with the name or the address's local part", () => {
    expect(nodeLabel({ name: "Anna Keller", email: "anna@x.example" })).toBe("Anna Keller");
    expect(nodeLabel({ name: null, email: "einkauf@x.example" })).toBe("einkauf");
    expect(nodeLabel({ name: "  ", email: "info@x.example" })).toBe("info");
  });

  it("keep labels between 11 and 14 px, centers at 14", () => {
    expect(labelFont(12, false)).toBe(11);
    expect(labelFont(26, false)).toBe(13);
    expect(labelFont(40, false)).toBe(14);
    expect(labelFont(64, false)).toBe(14);
    expect(labelFont(12, true)).toBe(14);
  });

  it("stay readable when one person has a thousand times the mails of the others", () => {
    const hub = graphNode(1, 120_000, { center: true });
    const skewed: Graph = {
      ...graph,
      centers: [1],
      nodes: [
        hub,
        ...Array.from({ length: 30 }, (_, i) => graphNode(i + 2, 120 - i * 3)),
        graphNode(40, 1),
      ],
      edges: [
        ...Array.from({ length: 30 }, (_, i) => graphEdge(1, i + 2, 4_000 - i * 100)),
        graphEdge(2, 3, 2),
        graphEdge(3, 40, 1),
      ],
    };
    const { nodes, edges } = graphVisuals(skewed, { color: true });
    const size = (id: number) => nodes.find((node) => node.id === id)!.size;
    expect(size(1)).toBe(40);
    expect(size(40)).toBe(12);
    // The others are told apart from the one-mail node and from each other.
    expect(size(2)).toBeGreaterThan(22);
    expect(size(2)).toBeGreaterThan(size(31) + 1);
    // On a square-root scale they would all be within a pixel or two of the minimum.
    expect(Math.round(12 + 52 * Math.sqrt(120 / 120_000))).toBe(14);
    expect(Math.min(...nodes.map((node) => node.font))).toBeGreaterThanOrEqual(11);
    expect(Math.max(...nodes.map((node) => node.font))).toBeLessThanOrEqual(14);
    const width = (id: string) => edges.find((edge) => edge.id === id)!.width;
    expect(width("1-2")).toBe(6);
    expect(width("3-40")).toBe(1);
    expect(width("2-3")).toBeGreaterThan(1);
  });
});

function graphNode(id: number, mails: number, patch: Partial<GraphNode> = {}): GraphNode {
  return {
    id,
    name: `Person ${id}`,
    email: `p${id}@x.example`,
    domain: "x.example",
    kind: null,
    mails,
    contacts: 1,
    center: false,
    ...patch,
  };
}

function graphEdge(source: number, target: number, weight: number): GraphEdge {
  return { source, target, a_to_b: weight, b_to_a: 0, cc: 0, weight };
}

describe("graph visuals", () => {
  it("colour by domain, ring the centers and mark lists", () => {
    const visuals = graphVisuals(graph, { color: true });
    const anna = visuals.nodes.find((node) => node.id === 11)!;
    expect(anna).toMatchObject({ center: true, size: 40, label: "Anna Keller", color: "#1D5BD6" });
    expect(visuals.nodes.find((node) => node.id === 19)!.kind).toBe("list");
    expect(visuals.roots).toEqual([11]);
    expect(visuals.colors.legend[0].domain).toBe("nordlicht-gmbh.example");

    const plain = graphVisuals(graph, { color: false });
    expect(new Set(plain.nodes.map((node) => node.color))).toEqual(new Set([PLAIN_COLOR]));
  });

  it("draw edges of a center in its colour and label only the strongest", () => {
    const visuals = graphVisuals(graph, { color: true });
    const annaJonas = visuals.edges.find((edge) => edge.id === "11-12")!;
    expect(annaJonas).toMatchObject({ center: true, color: "#1D5BD6", width: 6, label: "388" });
    expect(annaJonas.toTarget && annaJonas.toSource).toBe(true);
    const jonasPeter = visuals.edges.find((edge) => edge.id === "12-15")!;
    expect(jonasPeter).toMatchObject({ center: false, color: "#C3C9D3" });
    const purchasing = visuals.edges.find((edge) => edge.id === "11-19")!;
    expect(purchasing).toMatchObject({ toTarget: true, toSource: false });
    expect(visuals.edges.filter((edge) => edge.label).length).toBe(
      Math.min(EDGE_LABELS, graph.edges.length),
    );
  });

  it("start the hierarchy at the heaviest node without centers", () => {
    const top: Graph = {
      ...graph,
      centers: [],
      nodes: graph.nodes.map((node): GraphNode => ({ ...node, center: false })),
    };
    expect(graphVisuals(top, { color: true }).roots).toEqual([11]);
    expect(graphVisuals({ ...top, nodes: [], edges: [] }, { color: true }).roots).toEqual([]);
  });

  it("have arrows in the stylesheet only when they are on", () => {
    const selectors = (arrows: boolean) =>
      graphStylesheet({ arrows, large: false }).map((block) => block.selector);
    expect(selectors(true)).toContain("edge[?toTarget]");
    expect(selectors(false)).not.toContain("edge[?toTarget]");
    const edgeStyle = (arrows: boolean, large: boolean) =>
      graphStylesheet({ arrows, large }).find((block) => block.selector === "edge")!;
    expect(JSON.stringify(edgeStyle(false, true))).toContain("haystack");
    expect(JSON.stringify(edgeStyle(true, true))).toContain("straight");
  });
});
