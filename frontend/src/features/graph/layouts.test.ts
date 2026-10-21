import { describe, expect, it } from "vitest";

import { graph } from "../../test/fixtures";
import { graphVisuals } from "./elements";
import type { GraphLayout } from "./graphState";
import {
  circleLayout,
  computeLayout,
  domainLayout,
  forceLayout,
  treeLayout,
  type LayoutInput,
  type Positions,
} from "./layouts";

const visuals = graphVisuals(graph, { color: true });
const input: LayoutInput = { nodes: visuals.nodes, edges: visuals.edges, roots: visuals.roots };
const distance = (positions: Positions, a: number, b: number) => {
  const p = positions.get(a)!;
  const q = positions.get(b)!;
  return Math.hypot(p.x - q.x, p.y - q.y);
};

/** A sparse random-looking graph from a fixed recipe: n nodes in a few domains. */
function synthetic(n: number): LayoutInput {
  const nodes = Array.from({ length: n }, (_, i) => ({
    id: i + 1,
    size: 12 + ((i * 37) % 50),
    domain: `d${i % 7}.example`,
    mails: n - i,
  }));
  const edges = nodes.flatMap((node, i) =>
    [1, 7, 31]
      .map((step) => (i + step) % n)
      .filter((j) => j > i)
      .map((j) => ({ source: node.id, target: j + 1, weight: 1 + ((i * j) % 40) })),
  );
  return { nodes, edges, roots: [1] };
}

describe("layouts", () => {
  it.each<GraphLayout>(["force", "domains", "circle", "tree"])(
    "%s places every node at a finite spot, the same way each time",
    (layout) => {
      const first = computeLayout(layout, input);
      expect([...first.keys()].sort()).toEqual(graph.nodes.map((node) => node.id).sort());
      for (const point of first.values()) {
        expect(Number.isFinite(point.x) && Number.isFinite(point.y)).toBe(true);
      }
      expect(computeLayout(layout, input)).toEqual(first);
    },
  );

  it("force keeps big nodes apart and fixed nodes where they are", () => {
    const positions = forceLayout(input);
    for (const a of visuals.nodes) {
      for (const b of visuals.nodes) {
        if (a.id < b.id)
          expect(distance(positions, a.id, b.id)).toBeGreaterThan((a.size + b.size) / 2);
      }
    }
    const fixed: Positions = new Map([
      [11, { x: 500, y: -200 }],
      [12, { x: 650, y: -150 }],
    ]);
    const kept = forceLayout(input, fixed);
    expect(kept.get(11)).toEqual({ x: 500, y: -200 });
    expect(kept.get(12)).toEqual({ x: 650, y: -150 });
    // The others start next to their fixed neighbours and stay near them.
    expect(distance(kept, 11, 18)).toBeLessThan(800);
  });

  it("force copes with 2,000 nodes", () => {
    const big = synthetic(2000);
    const positions = forceLayout(big);
    expect(positions.size).toBe(2000);
    const xs = [...positions.values()].map((point) => point.x);
    expect(Math.max(...xs) - Math.min(...xs)).toBeGreaterThan(500);
  });

  it("tree puts the root in the middle and rings outward by distance", () => {
    const positions = treeLayout(input);
    expect(positions.get(11)).toEqual({ x: 0, y: 0 });
    const radius = (id: number) => Math.hypot(positions.get(id)!.x, positions.get(id)!.y);
    // Everyone is a neighbour of Anna here: one ring.
    const ring = graph.nodes.filter((node) => node.id !== 11).map((node) => radius(node.id));
    expect(Math.max(...ring) - Math.min(...ring)).toBeLessThan(1e-6);

    const chain = treeLayout({
      nodes: [1, 2, 3, 4].map((id) => ({ id, size: 20, domain: "a.example", mails: 10 - id })),
      edges: [
        { source: 1, target: 2, weight: 1 },
        { source: 2, target: 3, weight: 1 },
      ],
      roots: [1],
    });
    const r = (id: number) => Math.hypot(chain.get(id)!.x, chain.get(id)!.y);
    expect(r(1)).toBe(0);
    expect(r(2)).toBeLessThan(r(3));
    expect(r(3)).toBeLessThan(r(4)); // 4 is not reached: outermost
  });

  it("domains keep each domain together, the largest in the middle", () => {
    const positions = domainLayout(input);
    // nordlicht-gmbh.example has the most nodes (Anna, Lukas, billing, purchasing).
    expect(positions.get(11)).toEqual({ x: 0, y: 0 });
    expect(distance(positions, 11, 14)).toBeLessThan(distance(positions, 11, 12));
    expect(distance(positions, 12, 15)).toBeLessThan(distance(positions, 12, 14));
  });

  it("circle groups the domains", () => {
    const positions = circleLayout(input);
    const radii = [...positions.values()].map((point) => Math.hypot(point.x, point.y));
    expect(Math.max(...radii) - Math.min(...radii)).toBeLessThan(1e-6);
    expect(distance(positions, 11, 14)).toBeLessThan(distance(positions, 11, 13));
  });

  it("keep fixed positions in the other layouts, too", () => {
    const fixed: Positions = new Map([[13, { x: 1, y: 2 }]]);
    expect(computeLayout("circle", input, fixed).get(13)).toEqual({ x: 1, y: 2 });
  });
});
