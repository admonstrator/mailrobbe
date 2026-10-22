import { useEffect, useRef, useState, type RefObject } from "react";

import { canDraw, createMap, type MapInstance, type MapOptions } from "./maplibre";
import type { StyleSpecification } from "./mapStyle";

/** A MapLibre map in container for as long as the component lives, created with the first
 *  style and options. Once that style has loaded, map is set and every later style is applied
 *  as a diff, so only what changed is replaced. failed: the browser cannot draw it (no WebGL 2),
 *  and the caller shows something else in the container's place. */
export function useMap(
  container: RefObject<HTMLDivElement | null>,
  style: StyleSpecification,
  options: Omit<MapOptions, "container" | "style">,
  controls = false,
): { map: MapInstance | null; failed: boolean } {
  const [map, setMap] = useState<MapInstance | null>(null);
  const [failed] = useState(() => !canDraw());
  const first = useRef({ style, options, controls });
  const applied = useRef(style);

  useEffect(() => {
    const element = container.current;
    if (!element || failed) return;
    const { style, options, controls } = first.current;
    const instance = createMap({ container: element, style, ...options }, controls);
    instance.once("load", () => setMap(instance));
    // MapLibre follows window resizes only; the side panel changes the container's size, too.
    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => instance.resize());
    observer?.observe(element);
    return () => {
      observer?.disconnect();
      instance.remove();
      setMap(null);
    };
  }, [container, failed]);

  useEffect(() => {
    if (!map || applied.current === style) return;
    const last = applied.current;
    applied.current = style;
    map.setStyle(style, { transformStyle: (current, next) => keepFiles(last, current, next) });
  }, [map, style]);

  return { map, failed };
}

/** MapLibre diffs a new style against the map's own, in which a GeoJSON source loaded from a
 *  file stands as the file's data, no longer its URL. Every new style would differ there and
 *  load and parse the overview's files again (3 MB), so a file source whose definition did not
 *  change since last keeps the map's copy. */
export function keepFiles(
  last: StyleSpecification,
  current: StyleSpecification | undefined,
  next: StyleSpecification,
): StyleSpecification {
  if (!current) return next;
  const sources = { ...next.sources };
  for (const [id, source] of Object.entries(next.sources)) {
    const before: Record<string, unknown> | undefined = last.sources[id];
    const unchanged =
      source.type === "geojson" &&
      typeof source.data === "string" &&
      before !== undefined &&
      Object.keys(before).length === Object.keys(source).length &&
      Object.entries(source).every(([key, value]) => before[key] === value);
    if (unchanged && current.sources[id]) sources[id] = current.sources[id];
  }
  return { ...next, sources };
}
