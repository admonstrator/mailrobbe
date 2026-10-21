// The map as a standalone SVG file, drawn from the node positions on the canvas and the values of
// elements.ts: circles, lines, labels, arrows when they are on, on a white background. Plain SVG
// 1.1 without CSS or markers, so browsers and Inkscape show the same picture.

import { CENTER_EDGE_OPACITY, type EdgeVisual, type NodeVisual } from "./elements";
import type { Point, Positions } from "./layouts";

const PADDING = 24;
const FONT = "Inter, Helvetica, Arial, sans-serif";

function escapeXml(text: string): string {
  return text.replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`);
}

/** n rounded to one decimal, without a trailing ".0". */
function num(n: number): string {
  return String(Math.round(n * 10) / 10);
}

/** The arrowhead at the end of a line from (x1, y1) to the border of a node at (x2, y2). */
function arrowhead(x1: number, y1: number, x2: number, y2: number, inset: number, width: number) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const length = Math.hypot(dx, dy);
  if (length <= inset) return "";
  const ux = dx / length;
  const uy = dy / length;
  const size = 6 + width * 1.6;
  const tipX = x2 - ux * inset;
  const tipY = y2 - uy * inset;
  const baseX = tipX - ux * size;
  const baseY = tipY - uy * size;
  const spread = size * 0.55;
  const points = [
    [tipX, tipY],
    [baseX - uy * spread, baseY + ux * spread],
    [baseX + uy * spread, baseY - ux * spread],
  ];
  return points.map(([x, y]) => `${num(x)},${num(y)}`).join(" ");
}

/** The SVG document of nodes at positions with edges; nodes without a position are left out. */
export function graphSvg(
  nodes: readonly NodeVisual[],
  edges: readonly EdgeVisual[],
  positions: Positions,
  { arrows }: { arrows: boolean },
): string {
  const placed = nodes.filter((node) => positions.has(node.id));
  const byId = new Map(placed.map((node) => [node.id, node]));
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const node of placed) {
    const { x, y } = positions.get(node.id)!;
    const r = node.size / 2 + (node.center ? 7 : 0);
    const labelHalf = (node.label.length * node.font * 0.6) / 2;
    x0 = Math.min(x0, x - r, x - labelHalf);
    x1 = Math.max(x1, x + r, x + labelHalf);
    y0 = Math.min(y0, y - r);
    y1 = Math.max(y1, y + r + node.font + 8);
  }
  if (placed.length === 0) [x0, y0, x1, y1] = [0, 0, 0, 0];
  const left = x0 - PADDING;
  const top = y0 - PADDING;
  const width = x1 - x0 + 2 * PADDING;
  const height = y1 - y0 + 2 * PADDING;

  const lines: string[] = [];
  const heads: string[] = [];
  const edgeLabels: string[] = [];
  for (const edge of edges) {
    const a = byId.get(edge.source);
    const b = byId.get(edge.target);
    if (!a || !b) continue;
    const p = positions.get(a.id)!;
    const q = positions.get(b.id)!;
    const stroke = `stroke="${edge.color}" stroke-width="${num(edge.width)}"${
      edge.center ? ` stroke-opacity="${CENTER_EDGE_OPACITY}"` : ""
    }`;
    lines.push(
      `<line x1="${num(p.x)}" y1="${num(p.y)}" x2="${num(q.x)}" y2="${num(q.y)}" ${stroke} stroke-linecap="round"/>`,
    );
    if (arrows) {
      const ends: [Point, Point, NodeVisual][] = [];
      if (edge.toTarget) ends.push([p, q, b]);
      if (edge.toSource) ends.push([q, p, a]);
      for (const [from, to, node] of ends) {
        const points = arrowhead(from.x, from.y, to.x, to.y, node.size / 2 + 2, edge.width);
        if (points) heads.push(`<polygon points="${points}" fill="${edge.color}"/>`);
      }
    }
    if (edge.label) {
      edgeLabels.push(
        `<text x="${num((p.x + q.x) / 2)}" y="${num((p.y + q.y) / 2 + 4)}" font-size="11" font-weight="600" fill="#5B6270" text-anchor="middle" stroke="#FFFFFF" stroke-width="3" paint-order="stroke">${escapeXml(edge.label)}</text>`,
      );
    }
  }

  const circles: string[] = [];
  const labels: string[] = [];
  for (const node of placed) {
    const { x, y } = positions.get(node.id)!;
    const r = node.size / 2;
    const at = `cx="${num(x)}" cy="${num(y)}"`;
    if (node.center) {
      circles.push(`<circle ${at} r="${num(r + 7)}" fill="${node.color}"/>`);
      circles.push(`<circle ${at} r="${num(r + 4)}" fill="#FFFFFF"/>`);
    }
    circles.push(
      node.kind
        ? `<circle ${at} r="${num(r - 1.5)}" fill="#FFFFFF" stroke="${node.color}" stroke-width="3" stroke-dasharray="5 3"/>`
        : `<circle ${at} r="${num(r)}" fill="${node.color}"/>`,
    );
    const labelY = y + r + (node.center ? 7 : 0) + 4 + node.font;
    labels.push(
      `<text x="${num(x)}" y="${num(labelY)}" font-size="${node.font}" font-weight="${node.center ? 600 : 500}" fill="#16181D" text-anchor="middle" stroke="#FFFFFF" stroke-width="3" paint-order="stroke">${escapeXml(node.label)}</text>`,
    );
  }

  return [
    '<?xml version="1.0" encoding="UTF-8"?>',
    `<svg xmlns="http://www.w3.org/2000/svg" width="${num(width)}" height="${num(height)}" viewBox="${num(left)} ${num(top)} ${num(width)} ${num(height)}">`,
    `<rect x="${num(left)}" y="${num(top)}" width="${num(width)}" height="${num(height)}" fill="#FFFFFF"/>`,
    `<g>${lines.join("")}</g>`,
    `<g>${heads.join("")}</g>`,
    `<g font-family="${FONT}">${edgeLabels.join("")}</g>`,
    `<g>${circles.join("")}</g>`,
    `<g font-family="${FONT}">${labels.join("")}</g>`,
    "</svg>",
    "",
  ].join("\n");
}
