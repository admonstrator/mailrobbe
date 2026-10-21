// Node positions for the four layouts, computed here and handed to Cytoscape as a preset.
// Cytoscape's own force layout (cose) compares every pair of nodes and needs seconds for 2,000
// nodes, and it starts from random positions; this one uses a Barnes-Hut quadtree, starts from a
// spiral and is deterministic, so the same excerpt always looks the same. All functions are pure.

import type { GraphLayout } from "./graphState";

export interface Point {
  x: number;
  y: number;
}
export type Positions = Map<number, Point>;

export interface LayoutNode {
  id: number;
  size: number; // diameter
  domain: string;
  mails: number;
}

export interface LayoutEdge {
  source: number;
  target: number;
  weight: number;
}

export interface LayoutInput {
  nodes: readonly LayoutNode[];
  edges: readonly LayoutEdge[];
  roots: readonly number[];
}

const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
const GAP = 14; // between neighbouring nodes in the ring and cluster layouts

/** Positions for layout; nodes in fixed keep theirs (year playback), the others are placed. */
export function computeLayout(layout: GraphLayout, input: LayoutInput, fixed?: Positions) {
  if (layout === "force") return forceLayout(input, fixed);
  const positions =
    layout === "circle"
      ? circleLayout(input)
      : layout === "domains"
        ? domainLayout(input)
        : treeLayout(input);
  for (const [id, point] of fixed ?? []) if (positions.has(id)) positions.set(id, point);
  return positions;
}

function meanSize(nodes: readonly LayoutNode[]): number {
  return nodes.reduce((sum, node) => sum + node.size, 0) / Math.max(1, nodes.length);
}

/** Domains by number of nodes (ties by name), each with its nodes by mails. */
function domainGroups(nodes: readonly LayoutNode[]): LayoutNode[][] {
  const groups = new Map<string, LayoutNode[]>();
  for (const node of nodes) {
    const group = groups.get(node.domain);
    if (group) group.push(node);
    else groups.set(node.domain, [node]);
  }
  return [...groups.values()]
    .map((group) => group.sort(byMails))
    .sort((a, b) => b.length - a.length || (a[0].domain < b[0].domain ? -1 : 1));
}

function byMails(a: LayoutNode, b: LayoutNode): number {
  return b.mails - a.mails || a.id - b.id;
}

/** A disc of nodes around (cx, cy), the first in the middle (phyllotaxis); returns its radius. */
function spiral(
  nodes: readonly LayoutNode[],
  cx: number,
  cy: number,
  step: number,
  out: Positions,
) {
  nodes.forEach((node, index) => {
    const r = step * Math.sqrt(index);
    out.set(node.id, {
      x: cx + r * Math.cos(index * GOLDEN_ANGLE),
      y: cy + r * Math.sin(index * GOLDEN_ANGLE),
    });
  });
  return step * Math.sqrt(Math.max(0, nodes.length - 1)) + (nodes[0]?.size ?? 0) / 2;
}

/** All nodes on one circle, grouped by domain, each domain by mails. */
export function circleLayout({ nodes }: LayoutInput): Positions {
  const ordered = domainGroups(nodes).flat();
  const radius = Math.max(60, (ordered.length * (meanSize(nodes) + GAP)) / (2 * Math.PI));
  const positions: Positions = new Map();
  ordered.forEach((node, index) => {
    const angle = (2 * Math.PI * index) / ordered.length - Math.PI / 2;
    positions.set(node.id, { x: radius * Math.cos(angle), y: radius * Math.sin(angle) });
  });
  return positions;
}

/** One disc per domain, sized by its nodes, the heaviest node in the middle of each. The largest
 *  domain sits in the middle and the others on rings around it, larger ones further in; two
 *  domains end up side by side. */
export function domainLayout({ nodes }: LayoutInput): Positions {
  const step = (meanSize(nodes) + GAP) * 1.3; // neighbours about 1.8 steps apart: room for labels
  const gap = 3 * step;
  const groups = domainGroups(nodes);
  const radii = groups.map((group) => step * Math.sqrt(group.length - 1) + group[0].size / 2);
  const positions: Positions = new Map();
  if (groups.length === 0) return positions;
  spiral(groups[0], 0, 0, step, positions);
  let extent = radii[0];
  for (let first = 1; first < groups.length;) {
    // The ring's radius follows its largest disc, which is its first; it takes discs while they fit.
    const ring = extent + gap + radii[first];
    const room = 2 * Math.PI * ring;
    let last = first;
    let used = 0;
    while (last < groups.length && (last === first || used + 2 * radii[last] + gap <= room)) {
      used += 2 * radii[last] + gap;
      last++;
    }
    let arc = 0;
    for (let i = first; i < last; i++) {
      arc += radii[i] + gap / 2;
      const angle =
        Math.PI + (2 * Math.PI * (arc - radii[first] - gap / 2)) / Math.max(used, room / 2);
      spiral(groups[i], ring * Math.cos(angle), ring * Math.sin(angle), step, positions);
      arc += radii[i] + gap / 2;
    }
    extent = ring + radii[first];
    first = last;
  }
  return positions;
}

/** Rings by distance from the roots (the centers, or the heaviest node): the roots in the
 *  middle, their neighbours on the first ring, and so on; nodes the roots do not reach go on the
 *  outermost ring. Each ring is ordered by the angle of its nodes' parents, which keeps
 *  branches together. */
export function treeLayout({ nodes, edges, roots }: LayoutInput): Positions {
  const positions: Positions = new Map();
  if (nodes.length === 0) return positions;
  const known = new Map(nodes.map((node) => [node.id, node]));
  const neighbours = adjacency(nodes, edges);
  const start = roots.filter((id) => known.has(id));
  if (start.length === 0) start.push([...nodes].sort(byMails)[0].id);

  const level = new Map(start.map((id) => [id, 0]));
  const queue = [...start];
  for (let head = 0; head < queue.length; head++) {
    const id = queue[head];
    for (const next of neighbours.get(id) ?? []) {
      if (!level.has(next)) {
        level.set(next, level.get(id)! + 1);
        queue.push(next);
      }
    }
  }
  const deepest = Math.max(...level.values());
  const rings: LayoutNode[][] = Array.from({ length: deepest + 1 }, () => []);
  for (const node of nodes) {
    const ring = level.get(node.id);
    if (ring === undefined) (rings[deepest + 1] ??= []).push(node);
    else rings[ring].push(node);
  }

  // Rings evenly spaced out to the one that needs the most room, wider where a ring is crowded.
  const spacing = meanSize(nodes) + GAP;
  const needed = rings.map((ring) => (ring.length * spacing) / (2 * Math.PI));
  const outer = Math.max(...needed);
  const angle = new Map<number, number>();
  let radius = 0;
  rings.forEach((ring, depth) => {
    const parentAngle = (node: LayoutNode) => {
      const angles = (neighbours.get(node.id) ?? []).flatMap((id) =>
        level.get(id) === depth - 1 && angle.has(id) ? [angle.get(id)!] : [],
      );
      return angles.length ? angles.reduce((sum, a) => sum + a, 0) / angles.length : 0;
    };
    const keyed = ring.map((node) => ({ node, key: parentAngle(node) }));
    keyed.sort(
      (a, b) =>
        a.key - b.key ||
        (a.node.domain < b.node.domain ? -1 : a.node.domain > b.node.domain ? 1 : 0) ||
        byMails(a.node, b.node),
    );
    if (depth === 0) radius = ring.length === 1 ? 0 : Math.max(needed[0], spacing);
    else {
      radius = Math.max(needed[depth], radius + 3 * spacing, (outer * depth) / (rings.length - 1));
    }
    keyed.forEach(({ node }, index) => {
      const a = -Math.PI + (2 * Math.PI * (index + 0.5)) / ring.length;
      angle.set(node.id, a);
      positions.set(node.id, { x: radius * Math.cos(a), y: radius * Math.sin(a) });
    });
  });
  return positions;
}

function adjacency(nodes: readonly LayoutNode[], edges: readonly LayoutEdge[]) {
  const neighbours = new Map<number, number[]>(nodes.map((node) => [node.id, []]));
  for (const edge of edges) {
    neighbours.get(edge.source)?.push(edge.target);
    neighbours.get(edge.target)?.push(edge.source);
  }
  return neighbours;
}

// Force layout ---------------------------------------------------------------------------------

const THETA = 0.9; // Barnes-Hut: a cell this much smaller than its distance counts as one body

interface Cell {
  x: number; // centre of the square
  y: number;
  half: number;
  mass: number;
  mx: number; // centre of mass
  my: number;
  body: number; // index of the only body, -1 when empty, -2 when split
  kids: (Cell | null)[] | null;
}

interface Bodies {
  xs: Float64Array;
  ys: Float64Array;
  mass: Float64Array;
}

function newCell(x: number, y: number, half: number): Cell {
  return { x, y, half, mass: 0, mx: 0, my: 0, body: -1, kids: null };
}

function insert(cell: Cell, i: number, bodies: Bodies, depth: number) {
  const m = bodies.mass[i];
  cell.mx = (cell.mx * cell.mass + bodies.xs[i] * m) / (cell.mass + m);
  cell.my = (cell.my * cell.mass + bodies.ys[i] * m) / (cell.mass + m);
  cell.mass += m;
  if (cell.body === -1 && cell.kids === null) {
    cell.body = i;
    return;
  }
  // Bodies on (almost) the same spot share a leaf instead of splitting forever.
  if (depth > 24) return;
  if (cell.kids === null) {
    cell.kids = [null, null, null, null];
    const previous = cell.body;
    cell.body = -2;
    place(cell, previous, bodies, depth);
  }
  place(cell, i, bodies, depth);
}

function place(cell: Cell, i: number, bodies: Bodies, depth: number) {
  const right = bodies.xs[i] >= cell.x ? 1 : 0;
  const lower = bodies.ys[i] >= cell.y ? 1 : 0;
  const half = cell.half / 2;
  const kids = cell.kids!;
  kids[right + 2 * lower] ??= newCell(
    cell.x + (right ? half : -half),
    cell.y + (lower ? half : -half),
    half,
  );
  insert(kids[right + 2 * lower]!, i, bodies, depth + 1);
}

/** A deterministic angle for a node id, to spread nodes that start on the same spot. */
function idAngle(id: number): number {
  return ((Math.imul(id, 2654435761) >>> 0) / 2 ** 32) * 2 * Math.PI;
}

/** Forces in the manner of ForceAtlas2: nodes repel in proportion to their degrees (so hubs get
 *  room), edges pull linearly and heavier ones a little harder, and a pull to the middle keeps
 *  unconnected parts close. Distances are measured between node borders, so big nodes do not
 *  overlap. Repulsion goes through a Barnes-Hut quadtree, O(n log n) per step. The start is a
 *  spiral with the heaviest nodes in the middle; nodes not in fixed start next to their fixed
 *  neighbours and only they move. */
export function forceLayout({ nodes, edges }: LayoutInput, fixed?: Positions): Positions {
  const n = nodes.length;
  const positions: Positions = new Map();
  if (n === 0) return positions;
  const index = new Map(nodes.map((node, i) => [node.id, i]));
  const links = edges.flatMap((edge) => {
    const a = index.get(edge.source);
    const b = index.get(edge.target);
    return a === undefined || b === undefined || a === b ? [] : [{ a, b, w: edge.weight }];
  });
  const maxWeight = Math.max(1, ...links.map((link) => link.w));
  const pull = links.map((link) => 0.5 + (0.5 * Math.log1p(link.w)) / Math.log1p(maxWeight));

  const bodies: Bodies = {
    xs: new Float64Array(n),
    ys: new Float64Array(n),
    mass: new Float64Array(n).fill(1),
  };
  const { xs, ys, mass } = bodies;
  const radius = Float64Array.from(nodes, (node) => node.size / 2);
  const neighbours: number[][] = nodes.map(() => []);
  for (const { a, b } of links) {
    neighbours[a].push(b);
    neighbours[b].push(a);
    mass[a] += 1;
    mass[b] += 1;
  }
  const k = meanSize(nodes) + 60; // gap between two joined leaves, room for a label
  // Two joined leaves settle about k apart; denser graphs are not spread further than sparse ones.
  const meanMass = mass.reduce((sum, m) => sum + m, 0) / n;
  const repulsion = (k * k) / 4 / meanMass;
  const reach = k * Math.sqrt(n); // about the radius of the finished layout
  const gravity = 1;

  // Start: fixed nodes where they are, the rest next to placed neighbours or on a spiral.
  const pinned = new Uint8Array(n);
  for (const [i, node] of nodes.entries()) {
    const point = fixed?.get(node.id);
    if (point) {
      xs[i] = point.x;
      ys[i] = point.y;
      pinned[i] = 1;
    }
  }
  const anyPinned = pinned.includes(1);
  let free = 0;
  for (const i of nodes.map((_, i) => i).sort((a, b) => byMails(nodes[a], nodes[b]))) {
    if (pinned[i]) continue;
    const placed = neighbours[i].filter((j) => pinned[j]);
    const angle = idAngle(nodes[i].id);
    if (placed.length) {
      xs[i] = placed.reduce((sum, j) => sum + xs[j], 0) / placed.length + k * Math.cos(angle);
      ys[i] = placed.reduce((sum, j) => sum + ys[j], 0) / placed.length + k * Math.sin(angle);
    } else {
      const r = k * 0.8 * Math.sqrt(free + (anyPinned ? n : 0));
      xs[i] = r * Math.cos(free * GOLDEN_ANGLE);
      ys[i] = r * Math.sin(free * GOLDEN_ANGLE);
    }
    free++;
  }

  const iterations = free === 0 ? 0 : Math.round(Math.min(300, Math.max(80, 4_000 / Math.sqrt(n))));
  const fx = new Float64Array(n);
  const fy = new Float64Array(n);
  let temperature = k * Math.max(2, Math.sqrt(n) / 2);
  const cooling = (temperature - 1) / Math.max(1, iterations);
  const stack: Cell[] = [];

  for (let step = 0; step < iterations; step++) {
    fx.fill(0);
    fy.fill(0);
    let x0 = Infinity;
    let y0 = Infinity;
    let x1 = -Infinity;
    let y1 = -Infinity;
    for (let i = 0; i < n; i++) {
      x0 = Math.min(x0, xs[i]);
      y0 = Math.min(y0, ys[i]);
      x1 = Math.max(x1, xs[i]);
      y1 = Math.max(y1, ys[i]);
    }
    const root = newCell((x0 + x1) / 2, (y0 + y1) / 2, Math.max(x1 - x0, y1 - y0) / 2 + 1);
    for (let i = 0; i < n; i++) insert(root, i, bodies, 0);

    for (let i = 0; i < n; i++) {
      if (pinned[i]) continue;
      stack.push(root);
      while (stack.length) {
        const cell = stack.pop()!;
        if (cell.mass === 0 || cell.body === i) continue;
        const leaf = cell.body >= 0;
        let ox = xs[i] - cell.mx;
        let oy = ys[i] - cell.my;
        let d2 = ox * ox + oy * oy;
        if (!leaf && (2 * cell.half) ** 2 >= THETA * THETA * d2) {
          for (const kid of cell.kids!) if (kid) stack.push(kid);
          continue;
        }
        if (d2 < 1e-6) {
          const angle = idAngle(nodes[i].id);
          ox = Math.cos(angle);
          oy = Math.sin(angle);
          d2 = 1;
        }
        const d = Math.sqrt(d2);
        const span = leaf ? Math.max(0.5, d - radius[i] - radius[cell.body]) : d;
        const force = (repulsion * mass[i] * cell.mass) / span;
        fx[i] += (ox / d) * force;
        fy[i] += (oy / d) * force;
      }
    }

    links.forEach(({ a, b }, l) => {
      const ox = xs[b] - xs[a];
      const oy = ys[b] - ys[a];
      const d = Math.sqrt(ox * ox + oy * oy);
      if (d < 1e-6) return;
      const force = (Math.max(0, d - radius[a] - radius[b]) * pull[l]) / d;
      fx[a] += ox * force;
      fy[a] += oy * force;
      fx[b] -= ox * force;
      fy[b] -= oy * force;
    });

    for (let i = 0; i < n; i++) {
      if (pinned[i]) continue;
      const pullToMiddle = (gravity * mass[i]) / reach;
      fx[i] -= xs[i] * pullToMiddle * k;
      fy[i] -= ys[i] * pullToMiddle * k;
      const length = Math.hypot(fx[i], fy[i]) / mass[i];
      if (length < 1e-9) continue;
      const move = Math.min(length, temperature) / (length * mass[i]);
      xs[i] += fx[i] * move;
      ys[i] += fy[i] * move;
    }
    temperature -= cooling;
  }

  nodes.forEach((node, i) => positions.set(node.id, { x: xs[i], y: ys[i] }));
  return positions;
}
