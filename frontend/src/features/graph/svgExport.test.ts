import { describe, expect, it } from "vitest";

import { graph } from "../../test/fixtures";
import { graphVisuals, type NodeVisual } from "./elements";
import type { Positions } from "./layouts";
import { graphSvg } from "./svgExport";

const visuals = graphVisuals(graph, { color: true });
const positions: Positions = new Map(
  visuals.nodes.map((node, index) => [node.id, { x: index * 100, y: (index % 3) * 80 - 40 }]),
);

function parse(svg: string): Document {
  const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
  expect(doc.getElementsByTagName("parsererror")).toHaveLength(0);
  return doc;
}

describe("SVG export", () => {
  it("is a standalone SVG document with a white background and a fitted viewBox", () => {
    const svg = graphSvg(visuals.nodes, visuals.edges, positions, { arrows: false });
    expect(svg.startsWith('<?xml version="1.0" encoding="UTF-8"?>')).toBe(true);
    const root = parse(svg).documentElement;
    expect(root.getAttribute("xmlns")).toBe("http://www.w3.org/2000/svg");
    const [x, y, width, height] = root.getAttribute("viewBox")!.split(" ").map(Number);
    for (const node of visuals.nodes) {
      const { x: cx, y: cy } = positions.get(node.id)!;
      expect(cx - node.size / 2).toBeGreaterThanOrEqual(x);
      expect(cx + node.size / 2).toBeLessThanOrEqual(x + width);
      expect(cy - node.size / 2).toBeGreaterThanOrEqual(y);
      expect(cy + node.size / 2).toBeLessThanOrEqual(y + height);
    }
    const background = root.querySelector("rect")!;
    expect(background.getAttribute("fill")).toBe("#FFFFFF");
    expect(Number(background.getAttribute("width"))).toBe(width);
  });

  it("draws a line per edge, a circle per node (three for a center) and the labels", () => {
    const doc = parse(graphSvg(visuals.nodes, visuals.edges, positions, { arrows: false }));
    expect(doc.querySelectorAll("line")).toHaveLength(graph.edges.length);
    expect(doc.querySelectorAll("circle")).toHaveLength(graph.nodes.length + 2);
    expect(doc.querySelectorAll("polygon")).toHaveLength(0);
    const texts = [...doc.querySelectorAll("text")].map((text) => text.textContent);
    expect(texts).toContain("Anna Keller");
    expect(texts).toContain("388");

    const widest = doc.querySelector("line")!;
    expect(widest.getAttribute("stroke-width")).toBe("9");
    expect(widest.getAttribute("stroke")).toBe("#1D5BD6");
    expect(widest.getAttribute("stroke-opacity")).toBe("0.45");
    // The list is hollow with a dashed ring.
    expect(doc.querySelectorAll("circle[stroke-dasharray]")).toHaveLength(1);
  });

  it("adds an arrowhead for each direction with mails when arrows are on", () => {
    const doc = parse(graphSvg(visuals.nodes, visuals.edges, positions, { arrows: true }));
    const directions = graph.edges.reduce(
      (sum, edge) => sum + (edge.a_to_b > 0 ? 1 : 0) + (edge.b_to_a > 0 ? 1 : 0),
      0,
    );
    expect(doc.querySelectorAll("polygon")).toHaveLength(directions);
  });

  it("escapes labels and leaves out nodes without a position", () => {
    const odd: NodeVisual = { ...visuals.nodes[1], id: 99, label: 'Müller & "Söhne" <GmbH>' };
    const doc = parse(
      graphSvg(
        [...visuals.nodes, odd],
        visuals.edges,
        new Map([...positions, [99, { x: 0, y: 0 }]]),
        {
          arrows: false,
        },
      ),
    );
    expect([...doc.querySelectorAll("text")].map((text) => text.textContent)).toContain(
      'Müller & "Söhne" <GmbH>',
    );
    const missing = parse(graphSvg(visuals.nodes, visuals.edges, new Map(), { arrows: false }));
    expect(missing.querySelectorAll("circle, line")).toHaveLength(0);
  });
});
