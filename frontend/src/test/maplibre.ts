// The stand-in for features/places/maplibre.ts in every test (src/test/setup.ts): jsdom has no
// WebGL. It keeps the maps made with their options, every style they were given and the camera
// moves asked for, and lets a test move a map, click it and say what lies under the click.

import type { StyleSpecification } from "../features/places/mapStyle";

type Handler = (event: unknown) => void;
type BBox = [west: number, south: number, east: number, north: number];

export const ATTRIBUTION = "Natural Earth, GeoNames";

/** A point of a layer as queryRenderedFeatures gives it. */
export interface FakeFeature {
  layer: { id: string };
  properties: Record<string, unknown>;
  geometry: { type: "Point"; coordinates: [number, number] };
}

export class FakeMap {
  readonly options: Record<string, unknown>;
  readonly controls: boolean;
  /** Every style, the first from the options, then each setStyle. */
  readonly styles: StyleSpecification[] = [];
  readonly eased: { center?: [number, number]; zoom?: number }[] = [];
  /** What a click finds, topmost first. */
  features: FakeFeature[] = [];
  clusterZoom = 9;
  removed = false;
  private center: { lng: number; lat: number };
  private zoom: number;
  private bounds: BBox;
  private readonly handlers = new Map<string, Set<Handler>>();
  private readonly canvas = { style: { cursor: "" } };

  constructor(options: Record<string, unknown>, controls: boolean) {
    this.options = options;
    this.controls = controls;
    this.styles.push(options.style as StyleSpecification);
    const [lng, lat] = (options.center as [number, number] | undefined) ?? [0, 0];
    this.center = { lng, lat };
    this.zoom = (options.zoom as number | undefined) ?? 0;
    this.bounds = [lng - 8, lat - 4, lng + 8, lat + 4];
  }

  get style(): StyleSpecification {
    return this.styles[this.styles.length - 1];
  }

  getContainer(): HTMLElement {
    return this.options.container as HTMLElement;
  }

  on(type: string, handler: Handler) {
    let set = this.handlers.get(type);
    if (!set) this.handlers.set(type, (set = new Set()));
    set.add(handler);
    return this;
  }

  off(type: string, handler: Handler) {
    this.handlers.get(type)?.delete(handler);
    return this;
  }

  /** The style "loads" at once, so the map is ready within the render that made it. */
  once(type: string, handler: Handler) {
    if (type === "load") {
      handler({});
      return this;
    }
    const wrapped: Handler = (event) => {
      this.off(type, wrapped);
      handler(event);
    };
    return this.on(type, wrapped);
  }

  fire(type: string, event: unknown = {}) {
    for (const handler of [...(this.handlers.get(type) ?? [])]) handler(event);
  }

  /** A click at a pixel, on whatever features says lies there. */
  click(features: FakeFeature[]) {
    this.features = features;
    this.fire("click", { point: { x: 10, y: 10 } });
  }

  /** The camera moved to center and zoom, showing bounds, as a drag ends. */
  move(center: { lat: number; lon: number }, zoom: number, bounds: BBox) {
    this.center = { lng: center.lon, lat: center.lat };
    this.zoom = zoom;
    this.bounds = bounds;
    this.fire("moveend");
  }

  setStyle(
    style: StyleSpecification,
    options?: {
      transformStyle?: (
        current: StyleSpecification | undefined,
        next: StyleSpecification,
      ) => StyleSpecification;
    },
  ) {
    this.styles.push(options?.transformStyle?.(this.style, style) ?? style);
  }

  getCenter() {
    return this.center;
  }

  getZoom() {
    return this.zoom;
  }

  getBounds() {
    const [west, south, east, north] = this.bounds;
    return {
      getWest: () => west,
      getSouth: () => south,
      getEast: () => east,
      getNorth: () => north,
      contains: ([lon, lat]: [number, number]) =>
        lon >= west && lon <= east && lat >= south && lat <= north,
    };
  }

  queryRenderedFeatures(_point: unknown, options: { layers: string[] }) {
    return this.features.filter((feature) => options.layers.includes(feature.layer.id));
  }

  getSource(id: string) {
    return id === "photos"
      ? { getClusterExpansionZoom: () => Promise.resolve(this.clusterZoom) }
      : undefined;
  }

  easeTo(options: { center?: [number, number]; zoom?: number }) {
    this.eased.push(options);
    if (options.center) this.center = { lng: options.center[0], lat: options.center[1] };
    if (options.zoom !== undefined) this.zoom = options.zoom;
  }

  getCanvas() {
    return this.canvas;
  }

  resize() {}

  remove() {
    this.removed = true;
  }
}

/** The maps of the current test, and whether the "browser" has WebGL 2. */
export const fakeMaps = {
  drawable: true,
  made: [] as FakeMap[],
  last(): FakeMap {
    const map = this.made[this.made.length - 1];
    if (!map) throw new Error("no map was made");
    return map;
  },
  reset() {
    this.drawable = true;
    this.made = [];
  },
};

export function canDraw(): boolean {
  return fakeMaps.drawable;
}

export function createMap(options: Record<string, unknown>, controls = false): FakeMap {
  const map = new FakeMap(options, controls);
  fakeMaps.made.push(map);
  return map;
}
