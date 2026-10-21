// What the map draws, as plain data: node sizes, colours and labels, edge widths, arrows and
// labels, and the domain legend. The canvas hands it to Cytoscape and the SVG export draws the
// same values, so both look alike. Pure, so the rules are tested without a browser.

import type { StylesheetJson } from "cytoscape";

import type { Graph, GraphNode, PersonKind } from "../../api/types";
import { formatNumber } from "../../lib/format";

/** The eight domains with the most nodes in the excerpt, in this order (SPEC 7). */
export const DOMAIN_PALETTE = [
  "#1D5BD6",
  "#0F766E",
  "#B45309",
  "#7C3AED",
  "#BE185D",
  "#0E7490",
  "#4D7C0F",
  "#A16207",
] as const;
export const OTHER_COLOR = "#6B7280";
/** All nodes when "Nach Domain einfärben" is off. */
export const PLAIN_COLOR = "#1D5BD6";
const EDGE_COLOR = "#C3C9D3";
export const CENTER_EDGE_OPACITY = 0.45;

const NODE_MIN = 12;
const NODE_MAX = 64;
const EDGE_MIN = 1;
const EDGE_MAX = 9;
/** Only the strongest edges carry their weight as a label. */
export const EDGE_LABELS = 12;
/** Above this many edges the canvas draws cheaper edges (no curves, hidden while panning). */
export const LARGE_EDGES = 4000;

export interface LegendEntry {
  domain: string;
  color: string;
  nodes: number;
}

export interface DomainColors {
  color: (domain: string) => string;
  legend: LegendEntry[];
  /** Nodes of the remaining domains, drawn grey ("sonstige"). */
  others: number;
}

/** Palette colours for the eight domains with the most nodes (ties by name), grey for the rest. */
export function domainColors(nodes: readonly Pick<GraphNode, "domain">[]): DomainColors {
  const counts = new Map<string, number>();
  for (const node of nodes) counts.set(node.domain, (counts.get(node.domain) ?? 0) + 1);
  const ranked = [...counts].sort(([a, m], [b, n]) => n - m || (a < b ? -1 : a > b ? 1 : 0));
  const legend = ranked.slice(0, DOMAIN_PALETTE.length).map(([domain, count], index) => ({
    domain,
    color: DOMAIN_PALETTE[index],
    nodes: count,
  }));
  const colors = new Map(legend.map((entry) => [entry.domain, entry.color]));
  const others = ranked.slice(DOMAIN_PALETTE.length).reduce((sum, [, count]) => sum + count, 0);
  return { color: (domain) => colors.get(domain) ?? OTHER_COLOR, legend, others };
}

/** The display name, or the local part of the address. */
export function nodeLabel(node: Pick<GraphNode, "name" | "email">): string {
  return node.name?.trim() || node.email.split("@")[0];
}

/** Diameter by area: proportional to the square root of the mails, clamped. */
export function nodeSize(mails: number, maxMails: number): number {
  if (maxMails <= 0) return NODE_MIN;
  const share = Math.sqrt(Math.max(mails, 0) / maxMails);
  return Math.round((NODE_MIN + (NODE_MAX - NODE_MIN) * share) * 10) / 10;
}

/** Line width proportional to the square root of the weight, clamped. */
export function edgeWidth(weight: number, maxWeight: number): number {
  if (maxWeight <= 0) return EDGE_MIN;
  const share = Math.sqrt(Math.max(weight, 0) / maxWeight);
  return Math.round((EDGE_MIN + (EDGE_MAX - EDGE_MIN) * share) * 10) / 10;
}

/** Label size grows with the node, so at a distance the big nodes keep their names while the
 *  small ones drop theirs (Cytoscape hides labels below 7 px on screen); centers at least 18. */
export function labelFont(size: number, center: boolean): number {
  const font = Math.round(11 + (size - NODE_MIN) * 0.35);
  return center ? Math.max(font, 18) : font;
}

export interface NodeVisual {
  id: number;
  label: string;
  domain: string;
  mails: number;
  size: number;
  font: number;
  color: string;
  center: boolean;
  kind: PersonKind | null;
}

export interface EdgeVisual {
  id: string;
  source: number;
  target: number;
  weight: number;
  width: number;
  color: string;
  center: boolean; // touches a center: drawn in its colour, lighter
  label: string | null;
  toTarget: boolean; // a_to_b > 0: an arrow points at the target
  toSource: boolean;
}

export interface GraphVisuals {
  nodes: NodeVisual[];
  edges: EdgeVisual[];
  colors: DomainColors;
  /** Where "hierarchisch" starts: the centers, else the node with the most mails. */
  roots: number[];
}

export function edgeId(source: number, target: number): string {
  return `${source}-${target}`;
}

/** Everything the map draws for graph; color is the "Nach Domain einfärben" option. */
export function graphVisuals(graph: Graph, { color }: { color: boolean }): GraphVisuals {
  const colors = domainColors(graph.nodes);
  const maxMails = Math.max(0, ...graph.nodes.map((node) => node.mails));
  const nodes = graph.nodes.map((node): NodeVisual => {
    const size = nodeSize(node.mails, maxMails);
    return {
      id: node.id,
      label: nodeLabel(node),
      domain: node.domain,
      mails: node.mails,
      size,
      font: labelFont(size, node.center),
      color: color ? colors.color(node.domain) : PLAIN_COLOR,
      center: node.center,
      kind: node.kind,
    };
  });
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const maxWeight = Math.max(0, ...graph.edges.map((edge) => edge.weight));
  const labelled = new Set(
    [...graph.edges]
      .sort((a, b) => b.weight - a.weight)
      .slice(0, EDGE_LABELS)
      .map((edge) => edgeId(edge.source, edge.target)),
  );
  const edges = graph.edges.map((edge): EdgeVisual => {
    const id = edgeId(edge.source, edge.target);
    const center = [byId.get(edge.source), byId.get(edge.target)].find((node) => node?.center);
    return {
      id,
      source: edge.source,
      target: edge.target,
      weight: edge.weight,
      width: edgeWidth(edge.weight, maxWeight),
      color: center ? center.color : EDGE_COLOR,
      center: center !== undefined,
      label: labelled.has(id) ? formatNumber(edge.weight) : null,
      toTarget: edge.a_to_b > 0,
      toSource: edge.b_to_a > 0,
    };
  });
  const roots = graph.centers.length
    ? graph.centers.filter((id) => byId.has(id))
    : [...graph.nodes]
        .sort((a, b) => b.mails - a.mails || a.id - b.id)
        .slice(0, 1)
        .map((n) => n.id);
  return { nodes, edges, colors, roots };
}

const FONT = '"Inter Variable", Inter, system-ui, sans-serif';

/** The Cytoscape stylesheet; element looks come from the data fields of NodeVisual/EdgeVisual. */
export function graphStylesheet({ arrows, large }: { arrows: boolean; large: boolean }) {
  const sheet: StylesheetJson = [
    {
      selector: "node",
      style: {
        width: "data(size)",
        height: "data(size)",
        "background-color": "data(color)",
        "border-width": 0,
        label: "data(label)",
        "font-family": FONT,
        "font-size": "data(font)",
        "font-weight": 500,
        color: "#16181D",
        "text-valign": "bottom",
        "text-margin-y": 4,
        "text-background-color": "#FFFFFF",
        "text-background-opacity": 0.85,
        "text-background-padding": "2px",
        "text-background-shape": "roundrectangle",
        "min-zoomed-font-size": 7,
        "overlay-opacity": 0,
      },
    },
    {
      // Lists and automated senders: hollow with a dashed ring.
      selector: "node[?kind]",
      style: {
        "background-color": "#FFFFFF",
        "border-width": 3,
        "border-style": "dashed",
        "border-color": "data(color)",
      },
    },
    {
      selector: "node[?center]",
      style: {
        "border-width": 4,
        "border-style": "solid",
        "border-color": "#FFFFFF",
        "outline-width": 3,
        "outline-color": "data(color)",
        "font-weight": 600,
      },
    },
    {
      selector: "edge",
      style: {
        width: "data(width)",
        "line-color": "data(color)",
        "curve-style": arrows ? "straight" : large ? "haystack" : "straight",
        "haystack-radius": 0,
        "overlay-opacity": 0,
      },
    },
    {
      selector: "edge[?center]",
      style: { "line-opacity": CENTER_EDGE_OPACITY },
    },
    {
      selector: "edge[?label]",
      style: {
        label: "data(label)",
        "font-family": FONT,
        "font-size": 11,
        "font-weight": 600,
        color: "#5B6270",
        "text-background-color": "#FFFFFF",
        "text-background-opacity": 0.85,
        "text-background-padding": "1px",
        "min-zoomed-font-size": 7,
      },
    },
    {
      selector: ".faded",
      style: { opacity: 0.15, "text-opacity": 0 },
    },
    {
      selector: "edge.focus",
      style: { "line-color": "#1D5BD6", "line-opacity": 0.85, "z-index": 10 },
    },
    {
      selector: "node.selected",
      style: {
        "outline-width": 3,
        "outline-color": "#16181D",
        "outline-offset": 2,
        "z-index": 10,
      },
    },
  ];
  if (arrows) {
    sheet.push(
      {
        selector: "edge[?toTarget]",
        style: {
          "target-arrow-shape": "triangle",
          "target-arrow-color": "data(color)",
          "arrow-scale": 1.1,
        },
      },
      {
        selector: "edge[?toSource]",
        style: {
          "source-arrow-shape": "triangle",
          "source-arrow-color": "data(color)",
          "arrow-scale": 1.1,
        },
      },
      {
        selector: "edge.focus",
        style: { "target-arrow-color": "#1D5BD6", "source-arrow-color": "#1D5BD6" },
      },
    );
  }
  return sheet;
}
