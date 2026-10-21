// The map itself: one Cytoscape instance, loaded on first use (its own chunk) and kept for the
// life of the page. A new graph replaces the elements and runs the layout; another layout moves
// the nodes; colours, arrows and the selection change data, styles and classes in place.

import type { Core, ElementDefinition } from "cytoscape";
import { useEffect, useImperativeHandle, useMemo, useRef, useState, type Ref } from "react";

import type { Graph } from "../../api/types";
import {
  graphStylesheet,
  graphVisuals,
  LARGE_EDGES,
  type EdgeVisual,
  type GraphVisuals,
  type NodeVisual,
} from "./elements";
import styles from "./GraphCanvas.module.css";
import type { GraphLayout } from "./graphState";
import { computeLayout, type Positions } from "./layouts";
import { graphSvg } from "./svgExport";

export interface GraphCanvasHandle {
  zoomBy: (factor: number) => void;
  fit: () => void;
  png: () => Blob | null;
  svg: () => string | null;
}

const PADDING = 40;
/** Up to this many nodes another layout moves the nodes visibly instead of jumping. */
const ANIMATE_NODES = 600;
/** Larger PNGs are scaled down to fit (browsers refuse bigger canvases). */
const PNG_MAX = 8000;

// What the stylesheet reads, without the ids (strings in Cytoscape). Its [?field] selectors take
// "" as absent.
function nodeData(node: NodeVisual) {
  return {
    label: node.label,
    size: node.size,
    font: node.font,
    color: node.color,
    center: node.center,
    kind: node.kind ?? "",
  };
}

function edgeData(edge: EdgeVisual) {
  return {
    width: edge.width,
    color: edge.color,
    center: edge.center,
    label: edge.label ?? "",
    toTarget: edge.toTarget,
    toSource: edge.toSource,
  };
}

function elements(visuals: GraphVisuals, positions: Positions): ElementDefinition[] {
  const nodes = visuals.nodes.map((node): ElementDefinition => ({
    group: "nodes",
    data: { id: String(node.id), ...nodeData(node) },
    position: { ...(positions.get(node.id) ?? { x: 0, y: 0 }) },
  }));
  const edges = visuals.edges.map((edge): ElementDefinition => ({
    group: "edges",
    data: {
      id: edge.id,
      source: String(edge.source),
      target: String(edge.target),
      ...edgeData(edge),
    },
  }));
  return [...nodes, ...edges];
}

function layoutInput(visuals: GraphVisuals) {
  return { nodes: visuals.nodes, edges: visuals.edges, roots: visuals.roots };
}

function currentPositions(cy: Core): Positions {
  return new Map(cy.nodes().map((node) => [Number(node.id()), { ...node.position() }]));
}

interface GraphCanvasProps {
  graph: Graph | undefined;
  layout: GraphLayout;
  color: boolean;
  arrows: boolean;
  selected: number | null;
  onSelect: (id: number | null) => void;
  /** Year playback: nodes already on the map stay where they are. */
  keepPositions: boolean;
  ref?: Ref<GraphCanvasHandle>;
}

export function GraphCanvas(props: GraphCanvasProps) {
  const large = (props.graph?.edges.length ?? 0) > LARGE_EDGES;
  // Hiding the edges while panning and zooming keeps a large map responsive (frames of 17 ms
  // instead of 400 ms in a measurement with 27,000 edges), but Cytoscape takes that option only
  // when it starts: a graph on the other side of the line gets a new instance.
  return <Canvas key={large ? "large" : "small"} {...props} large={large} />;
}

function Canvas({
  graph,
  layout,
  color,
  arrows,
  selected,
  onSelect,
  keepPositions,
  ref,
  large,
}: GraphCanvasProps & { large: boolean }) {
  const container = useRef<HTMLDivElement>(null);
  const [cy, setCy] = useState<Core | null>(null);
  const [failed, setFailed] = useState(false);
  const drawn = useRef<{ graph: Graph | null; layout: GraphLayout | null }>({
    graph: null,
    layout: null,
  });
  const memory = useRef<Positions>(new Map());
  // The view still shows the whole graph (nobody zoomed or panned): a resize fits it again.
  const fitted = useRef(true);
  const select = useRef(onSelect);
  const keep = useRef(keepPositions);
  const visuals = useMemo(() => graph && graphVisuals(graph, { color }), [graph, color]);

  useEffect(() => {
    select.current = onSelect;
    keep.current = keepPositions;
  }, [onSelect, keepPositions]);

  useEffect(() => {
    let instance: Core | null = null;
    let cancelled = false;
    import("cytoscape")
      .then(({ default: cytoscape }) => {
        if (cancelled || !container.current) return;
        instance = cytoscape({
          container: container.current,
          minZoom: 0.02,
          maxZoom: 3,
          boxSelectionEnabled: false,
          autounselectify: true,
          hideEdgesOnViewport: large,
        });
        instance.on("tap", (event) => {
          if (event.target === instance) select.current(null);
          else if (event.target.isNode?.()) select.current(Number(event.target.id()));
        });
        instance.on("dragpan scrollzoom pinchzoom", () => {
          fitted.current = false;
        });
        setCy(instance);
      })
      .catch(() => setFailed(true));
    return () => {
      cancelled = true;
      instance?.destroy();
    };
  }, [large]); // fixed for this instance: GraphCanvas keys it

  useEffect(() => {
    if (!cy || !container.current) return;
    // Cytoscape follows window resizes only; the panels and the legend change the container's
    // size, too.
    const observer = new ResizeObserver(() => {
      cy.resize();
      if (fitted.current) cy.fit(undefined, PADDING);
    });
    observer.observe(container.current);
    return () => observer.disconnect();
  }, [cy]);

  useEffect(() => {
    cy?.style(graphStylesheet({ arrows, large }));
  }, [cy, arrows, large]);

  useEffect(() => {
    if (!cy) return;
    if (!visuals || !graph) {
      // An error instead of a graph: an empty map under the message.
      cy.elements().remove();
      drawn.current = { graph: null, layout };
      return;
    }
    const previous = drawn.current;
    drawn.current = { graph, layout };
    if (previous.graph !== graph) {
      const start = performance.now();
      if (keep.current) {
        for (const [id, point] of currentPositions(cy)) memory.current.set(id, point);
      } else {
        memory.current.clear();
      }
      const positions = computeLayout(layout, layoutInput(visuals), memory.current);
      cy.batch(() => {
        cy.elements().remove();
        cy.add(elements(visuals, positions));
      });
      // The size Cytoscape knows may be stale: the legend arrives with the graph.
      cy.resize();
      cy.fit(undefined, PADDING);
      fitted.current = true;
      cy.one("render", () => {
        performance.measure("mailrobbe:map-drawn", {
          start,
          end: performance.now(),
          detail: { nodes: graph.nodes.length, edges: graph.edges.length },
        });
      });
    } else if (previous.layout !== layout) {
      const positions = computeLayout(layout, layoutInput(visuals));
      cy.resize();
      fitted.current = true;
      cy.nodes()
        .layout({
          name: "preset",
          positions: Object.fromEntries(
            [...positions].map(([id, point]) => [String(id), { ...point }]),
          ),
          fit: true,
          padding: PADDING,
          animate: visuals.nodes.length <= ANIMATE_NODES,
          animationDuration: 400,
        })
        .run();
    } else {
      // Same graph and layout: the colours changed.
      cy.batch(() => {
        for (const node of visuals.nodes) cy.getElementById(String(node.id)).data(nodeData(node));
        for (const edge of visuals.edges) cy.getElementById(edge.id).data(edgeData(edge));
      });
    }
  }, [cy, graph, layout, visuals]);

  useEffect(() => {
    if (!cy) return;
    cy.batch(() => {
      cy.elements().removeClass("faded focus selected");
      const node = selected === null ? null : cy.getElementById(String(selected));
      if (!node || node.empty()) return;
      cy.elements().not(node.closedNeighborhood()).addClass("faded");
      node.addClass("selected");
      node.connectedEdges().addClass("focus");
    });
  }, [cy, selected, graph]);

  useImperativeHandle(
    ref,
    () => ({
      zoomBy: (factor) => {
        if (!cy) return;
        fitted.current = false;
        cy.zoom({
          level: cy.zoom() * factor,
          renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 },
        });
      },
      fit: () => {
        if (!cy) return;
        fitted.current = true;
        cy.fit(undefined, PADDING);
      },
      png: () => {
        if (!cy || cy.elements().empty()) return null;
        const box = cy.elements().boundingBox();
        const tooBig = Math.max(box.w, box.h) * 2 > PNG_MAX;
        return cy.png({
          output: "blob",
          full: true,
          bg: "#FFFFFF",
          ...(tooBig ? { maxWidth: PNG_MAX, maxHeight: PNG_MAX } : { scale: 2 }),
        });
      },
      svg: () =>
        cy && visuals
          ? graphSvg(visuals.nodes, visuals.edges, currentPositions(cy), { arrows })
          : null,
    }),
    [cy, visuals, arrows],
  );

  return (
    <div className={styles.canvas}>
      <div ref={container} className={styles.cytoscape} />
      {failed && <p className={styles.failed}>Die Kartenansicht konnte nicht geladen werden.</p>}
    </div>
  );
}
