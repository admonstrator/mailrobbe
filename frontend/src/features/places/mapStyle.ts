// The style of the maps, as one function of what they show (D244, D245, D247): the overview map
// shipped below public/map with the towns of GET /api/map/towns as labels; the detail map, when
// one is downloaded, from its PMTiles file with the layers of the Protomaps basemap (flavour
// light in the app's colours, German names) within its region; and the page's three layers with
// the point shown on the side. The map applies a new style as a diff, so a change of the data
// only replaces the data.

import { layers as basemapLayers, namedFlavor } from "@protomaps/basemaps";
// Types only: maplibre-gl installs both packages and its own types are written in them.
import type {
  ExpressionSpecification,
  LayerSpecification,
  StyleSpecification,
} from "@maplibre/maplibre-gl-style-spec";
import type { Feature, FeatureCollection, Point, Polygon } from "geojson";

import type {
  BBox,
  DetailMap,
  EventPlace,
  PhotoPoint,
  TextPlace,
  TownLabel,
} from "../../api/types";
import type { LayerKey } from "./urlState";

export type { LayerSpecification, StyleSpecification };

/** The colours of the maps, close to the app's tokens (styles/global.css, SPEC 7). */
export const MAP_COLORS = {
  water: "#d4e2ee",
  land: "#f7f6f3",
  boundary: "#a9b1bd",
  region: "#cdd2d9",
  river: "#bcd1e4",
  label: "#3b4250",
  country: "#5b6270",
  halo: "#ffffff",
  waterLabel: "#5d7d99",
  photos: "#1d5bd6",
  texts: "#7c3aed",
  events: "#0f766e",
  selected: "#16181d",
} as const;

/** Below this zoom the detail map's tiles would cover much more than its region; the overview
 *  alone shows it. */
export const DETAIL_MIN_ZOOM = 5;

/** The lowest zoom the detail map shows: the one whose tiles are about as wide as its region,
 *  so the extract of a small view does not draw its coarse tiles as a block far around it;
 *  never below DETAIL_MIN_ZOOM nor above its highest zoom. */
export function detailMinZoom([west, south, east, north]: BBox, maxZoom: number): number {
  const span = Math.max(east - west, north - south);
  const zoom = span > 0 ? Math.floor(Math.log2(360 / span)) : maxZoom;
  return Math.min(Math.max(DETAIL_MIN_ZOOM, zoom), maxZoom);
}

/** The layers of the page a click picks a point from, topmost first. */
export const CLICK_LAYERS = ["photos-cluster", "photos-point", "events-circle", "texts-circle"];

const FONT = {
  regular: ["Noto Sans Regular"],
  medium: ["Noto Sans Medium"],
  italic: ["Noto Sans Italic"],
};

export interface StyleInput {
  /** The server's origin: the worker reads the GeoJSON files and needs whole URLs. */
  origin: string;
  towns: TownLabel[] | undefined;
  detail: DetailMap | null;
  photos?: PhotoPoint[];
  texts?: TextPlace[];
  events?: EventPlace[];
  /** The layers switched off. */
  off?: readonly LayerKey[];
  /** The point the side shows, ringed; the small maps' marker. */
  marked?: { lat: number; lon: number; radius?: number } | null;
}

type Properties = Record<string, string | number | boolean>;

function points<T>(
  items: readonly T[] | undefined,
  at: (item: T) => [lon: number, lat: number],
  properties: (item: T) => Properties,
): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: (items ?? []).map((item): Feature<Point> => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: at(item) },
      properties: properties(item),
    })),
  };
}

/** The zoom from which a town is labelled: capitals and the largest first. */
export function townMinZoom(town: TownLabel): number {
  if (town.capital) return 3;
  const steps: [number, number][] = [
    [1_000_000, 4],
    [300_000, 5],
    [100_000, 6],
    [30_000, 7],
    [10_000, 8],
  ];
  return steps.find(([population]) => town.population >= population)?.[1] ?? 9;
}

/** The radius of a circle for a count, between min and max pixels by the square root of its
 *  share of the largest count, so the area grows with the count. */
export function circleRadius(count: number, largest: number, min: number, max: number): number {
  if (largest <= 0) return min;
  return Math.round((min + (max - min) * Math.sqrt(Math.max(0, count) / largest)) * 10) / 10;
}

const largest = (counts: number[]) => counts.reduce((a, b) => Math.max(a, b), 0);

export function textPlaceRadius(places: readonly TextPlace[]) {
  const top = largest(places.map((place) => place.mails));
  return (place: TextPlace) => circleRadius(place.mails, top, 5, 22);
}

export function eventPlaceRadius(places: readonly EventPlace[]) {
  const top = largest(places.map((place) => place.events));
  return (place: EventPlace) => circleRadius(place.events, top, 5, 13);
}

function bboxPolygon([west, south, east, north]: BBox): Polygon {
  return {
    type: "Polygon",
    coordinates: [
      [
        [west, south],
        [east, south],
        [east, north],
        [west, north],
        [west, south],
      ],
    ],
  };
}

/** The flavour of the detail map: Protomaps light, in the colours of the overview, so the edge
 *  of its region does not show. */
function detailFlavor() {
  return {
    ...namedFlavor("light"),
    background: MAP_COLORS.water,
    earth: MAP_COLORS.land,
    water: MAP_COLORS.water,
    boundaries: MAP_COLORS.boundary,
    city_label: MAP_COLORS.label,
    country_label: MAP_COLORS.country,
  };
}

/** The detail map's layers on its source, without the basemap's background, which would cover
 *  the overview around the region. */
export function detailLayers(): LayerSpecification[] {
  return (basemapLayers("detail", detailFlavor(), { lang: "de" }) as LayerSpecification[]).filter(
    (layer) => layer.type !== "background",
  );
}

/** The detail map's attribution: OpenStreetMap's data, Protomaps' build (D244). */
export const DETAIL_ATTRIBUTION =
  '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap-Mitwirkende</a>, Protomaps';

const shown = (on: boolean) => ({ visibility: on ? ("visible" as const) : ("none" as const) });

/** The whole style for input. */
export function mapStyle(input: StyleInput): StyleSpecification {
  const { origin, detail } = input;
  const off = new Set(input.off ?? []);
  const file = (name: string) => `${origin}/map/${name}`;
  // Labels of the overview inside the detail map's region: the detail map has its own there.
  const outside = (filter: ExpressionSpecification): ExpressionSpecification =>
    detail ? ["all", filter, ["!", ["within", bboxPolygon(detail.bbox)]]] : filter;
  const fromZoom: ExpressionSpecification = ["<=", ["get", "min_zoom"], ["zoom"]];
  const textRadius = textPlaceRadius(input.texts ?? []);
  const eventRadius = eventPlaceRadius(input.events ?? []);

  const sources: StyleSpecification["sources"] = {
    countries: { type: "geojson", data: file("countries.json") },
    states: { type: "geojson", data: file("states.json") },
    lakes: { type: "geojson", data: file("lakes.json") },
    rivers: { type: "geojson", data: file("rivers.json") },
    labels: { type: "geojson", data: file("labels.json") },
    towns: {
      type: "geojson",
      data: points(
        input.towns,
        (town) => [town.lon, town.lat],
        (town) => ({
          name: town.name,
          population: town.population,
          capital: town.capital,
          min_zoom: townMinZoom(town),
        }),
      ),
    },
    photos: {
      type: "geojson",
      data: points(
        input.photos,
        (photo) => [photo.lon, photo.lat],
        (photo) => ({ id: photo.id }),
      ),
      cluster: true,
      clusterRadius: 44,
      clusterMaxZoom: 15,
    },
    texts: {
      type: "geojson",
      data: points(
        input.texts,
        (place) => [place.lon, place.lat],
        (place) => ({ id: place.entity_id, mails: place.mails, r: textRadius(place) }),
      ),
    },
    events: {
      type: "geojson",
      data: points(
        input.events,
        (place) => [place.lon, place.lat],
        (place) => ({ lat: place.lat, lon: place.lon, r: eventRadius(place) }),
      ),
    },
    marked: {
      type: "geojson",
      data: points(
        input.marked ? [input.marked] : [],
        (point) => [point.lon, point.lat],
        (point) => ({ r: point.radius ?? 7 }),
      ),
    },
  };
  if (detail) {
    sources.detail = {
      type: "vector",
      tiles: [`pmtiles://${new URL(detail.url, origin).href}/{z}/{x}/{y}`],
      bounds: detail.bbox,
      minzoom: detailMinZoom(detail.bbox, detail.max_zoom),
      maxzoom: detail.max_zoom,
      attribution: DETAIL_ATTRIBUTION,
    };
  }

  const base: LayerSpecification[] = [
    { id: "background", type: "background", paint: { "background-color": MAP_COLORS.water } },
    {
      id: "countries-fill",
      type: "fill",
      source: "countries",
      paint: { "fill-color": MAP_COLORS.land },
    },
    { id: "states-fill", type: "fill", source: "states", paint: { "fill-color": MAP_COLORS.land } },
    {
      id: "lakes-fill",
      type: "fill",
      source: "lakes",
      filter: ["<=", ["get", "min_zoom"], ["+", ["zoom"], 1]],
      paint: { "fill-color": MAP_COLORS.water },
    },
    {
      id: "rivers-line",
      type: "line",
      source: "rivers",
      filter: fromZoom,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": MAP_COLORS.river,
        "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.5, 7, 1.2, 10, 2.2],
      },
    },
    {
      id: "states-line",
      type: "line",
      source: "states",
      minzoom: 4,
      paint: {
        "line-color": MAP_COLORS.region,
        "line-width": ["interpolate", ["linear"], ["zoom"], 4, 0.6, 9, 1.4],
        "line-dasharray": [3, 2],
      },
    },
    {
      id: "countries-line",
      type: "line",
      source: "countries",
      layout: { "line-join": "round" },
      paint: {
        "line-color": MAP_COLORS.boundary,
        "line-width": ["interpolate", ["linear"], ["zoom"], 2, 0.6, 6, 1.1, 10, 1.8],
      },
    },
  ];

  const halo = { "text-halo-color": MAP_COLORS.halo, "text-halo-width": 1.4 };
  const labels: LayerSpecification[] = [
    {
      id: "rivers-label",
      type: "symbol",
      source: "rivers",
      minzoom: 7,
      filter: outside(["all", ["has", "name"], fromZoom]),
      layout: {
        "symbol-placement": "line",
        "text-field": ["get", "name"],
        "text-font": FONT.italic,
        "text-size": 11,
        "symbol-spacing": 400,
      },
      paint: { "text-color": MAP_COLORS.waterLabel, ...halo },
    },
    {
      id: "lakes-label",
      type: "symbol",
      source: "labels",
      filter: outside(["all", ["==", ["get", "kind"], "lake"], fromZoom]),
      layout: { "text-field": ["get", "name"], "text-font": FONT.italic, "text-size": 11 },
      paint: { "text-color": MAP_COLORS.waterLabel, ...halo },
    },
    {
      id: "states-label",
      type: "symbol",
      source: "labels",
      minzoom: 5.5,
      maxzoom: 10,
      filter: outside(["==", ["get", "kind"], "state"]),
      layout: {
        "text-field": ["get", "name"],
        "text-font": FONT.regular,
        "text-size": 11,
        "text-letter-spacing": 0.06,
        "text-max-width": 8,
      },
      paint: { "text-color": MAP_COLORS.country, "text-opacity": 0.75, ...halo },
    },
    {
      id: "countries-label",
      type: "symbol",
      source: "labels",
      maxzoom: 8,
      filter: outside(["all", ["==", ["get", "kind"], "country"], fromZoom]),
      layout: {
        "text-field": ["get", "name"],
        "text-font": FONT.medium,
        "text-size": ["interpolate", ["linear"], ["zoom"], 2, 11, 6, 14],
        "text-letter-spacing": 0.04,
        "text-max-width": 7,
      },
      paint: { "text-color": MAP_COLORS.country, ...halo },
    },
    {
      id: "towns",
      type: "symbol",
      source: "towns",
      filter: outside(fromZoom),
      layout: {
        "symbol-sort-key": ["-", ["get", "population"]],
        "icon-image": [
          "step",
          ["zoom"],
          ["case", ["==", ["get", "capital"], true], "capital", "townspot"],
          10,
          "",
        ],
        "icon-size": 0.8,
        "text-field": ["get", "name"],
        "text-font": [
          "case",
          [">=", ["get", "population"], 1_000_000],
          ["literal", FONT.medium],
          ["literal", FONT.regular],
        ],
        "text-size": [
          "case",
          ["any", ["==", ["get", "capital"], true], [">=", ["get", "population"], 1_000_000]],
          13,
          [">=", ["get", "population"], 100_000],
          12,
          11,
        ],
        "text-variable-anchor": ["left", "right", "top", "bottom"],
        "text-radial-offset": 0.55,
        "text-justify": "auto",
        "text-max-width": 9,
      },
      paint: { "text-color": MAP_COLORS.label, ...halo },
    },
  ];

  const data: LayerSpecification[] = [
    {
      id: "texts-circle",
      type: "circle",
      source: "texts",
      layout: shown(!off.has("texts")),
      paint: {
        "circle-radius": ["get", "r"],
        "circle-color": MAP_COLORS.texts,
        "circle-opacity": 0.28,
        "circle-stroke-color": MAP_COLORS.texts,
        "circle-stroke-width": 1.2,
      },
    },
    {
      id: "events-circle",
      type: "circle",
      source: "events",
      layout: shown(!off.has("events")),
      paint: {
        "circle-radius": ["get", "r"],
        "circle-color": MAP_COLORS.events,
        "circle-opacity": 0.85,
        "circle-stroke-color": MAP_COLORS.halo,
        "circle-stroke-width": 1.5,
      },
    },
    {
      id: "photos-cluster",
      type: "circle",
      source: "photos",
      filter: ["has", "point_count"],
      layout: shown(!off.has("photos")),
      paint: {
        "circle-radius": ["step", ["get", "point_count"], 12, 10, 15, 100, 19, 1000, 23],
        "circle-color": MAP_COLORS.photos,
        "circle-opacity": 0.88,
        "circle-stroke-color": MAP_COLORS.halo,
        "circle-stroke-width": 2,
      },
    },
    {
      id: "photos-count",
      type: "symbol",
      source: "photos",
      filter: ["has", "point_count"],
      layout: {
        ...shown(!off.has("photos")),
        "text-field": ["number-format", ["get", "point_count"], { locale: "de-DE" }],
        "text-font": FONT.medium,
        "text-size": 11,
        "text-allow-overlap": true,
      },
      paint: { "text-color": MAP_COLORS.halo },
    },
    {
      id: "photos-point",
      type: "circle",
      source: "photos",
      filter: ["!", ["has", "point_count"]],
      layout: shown(!off.has("photos")),
      paint: {
        "circle-radius": 5.5,
        "circle-color": MAP_COLORS.photos,
        "circle-stroke-color": MAP_COLORS.halo,
        "circle-stroke-width": 1.5,
      },
    },
    {
      id: "marked",
      type: "circle",
      source: "marked",
      paint: {
        "circle-radius": ["+", ["get", "r"], 4],
        "circle-color": "rgba(0, 0, 0, 0)",
        "circle-stroke-color": MAP_COLORS.selected,
        "circle-stroke-width": 2.5,
      },
    },
  ];

  return {
    version: 8,
    glyphs: `${origin}/map/fonts/{fontstack}/{range}.pbf`,
    sprite: `${origin}/map/sprites/light`,
    sources,
    layers: [...base, ...(detail ? detailLayers() : []), ...labels, ...data],
  };
}
