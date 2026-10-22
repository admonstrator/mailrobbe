// The page "Orte" keeps its state in the URL (D247), so a link reopens the same map: the mail
// list's filters with the mail list's parameter names (parsed and written by
// features/mails/listState.ts, so every filter carries over), the photos' own taken_from,
// taken_to and device, the layers switched off (off), the view (at=lat,lon,zoom) and the point
// shown on the side (point=photo:12, place:7 or event:48.13710,11.57540). Defaults are left out.

import { buildQuery } from "../../api/client";
import type { BBox, PlaceParams } from "../../api/types";
import {
  DEFAULT_LIST_STATE,
  isDay,
  listSearch,
  parseListState,
  positiveInt,
  toFilters,
  withFilters,
  type ListState,
} from "../mails/listState";

export type LayerKey = "photos" | "texts" | "events";
export const LAYER_KEYS: readonly LayerKey[] = ["photos", "texts", "events"];

export interface MapView {
  lat: number;
  lon: number;
  zoom: number;
}

/** A point of a layer: a photo (document id), a place of the texts (entity id) or the place of
 *  invitations, which has no id of its own and is found again by its point. */
export type PointRef =
  | { kind: "photo"; id: number }
  | { kind: "place"; id: number }
  | { kind: "event"; lat: number; lon: number };

export interface PlacesState {
  /** The mail filters; sort, cursor and page stay the mail list's defaults. */
  list: ListState;
  /** The photo's capture time (D241), UTC days, inclusive. */
  taken_from: string | null;
  taken_to: string | null;
  device: string | null;
  /** The layers switched off; all three show by default. */
  off: LayerKey[];
  /** null: the map's default view over Germany, Austria and Switzerland. */
  view: MapView | null;
  point: PointRef | null;
}

export const DEFAULT_PLACES_STATE: PlacesState = {
  list: DEFAULT_LIST_STATE,
  taken_from: null,
  taken_to: null,
  device: null,
  off: [],
  view: null,
  point: null,
};

/** The view when the URL names none: Germany, Austria and Switzerland. */
export const DEFAULT_VIEW: MapView = { lat: 50.2, lon: 10.8, zoom: 5 };
export const MAX_MAP_ZOOM = 18;

/** Coordinates as the URL writes them: five decimal places are about a metre. */
export const roundDegrees = (value: number) => Math.round(value * 1e5) / 1e5;

const finite = (value: string) => (/^-?\d+(\.\d+)?$/.test(value) ? Number(value) : NaN);

function parseView(value: string | null): MapView | null {
  const parts = value?.split(",").map(finite) ?? [];
  if (parts.length !== 3) return null;
  const [lat, lon, zoom] = parts;
  if (!(lat >= -85 && lat <= 85 && lon >= -180 && lon <= 180 && zoom >= 0)) return null;
  return { lat, lon, zoom: Math.min(zoom, MAX_MAP_ZOOM) };
}

function parsePoint(value: string | null): PointRef | null {
  const match = /^(photo|place|event):(.+)$/.exec(value ?? "");
  if (!match) return null;
  const [, kind, rest] = match;
  if (kind === "event") {
    const [lat, lon, ...more] = rest.split(",").map(finite);
    if (more.length || !(lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180)) return null;
    return { kind, lat, lon };
  }
  const id = positiveInt(rest);
  return id === null ? null : { kind: kind as "photo" | "place", id };
}

export function pointParam(point: PointRef): string {
  return point.kind === "event"
    ? `event:${point.lat.toFixed(5)},${point.lon.toFixed(5)}`
    : `${point.kind}:${point.id}`;
}

/** Whether two points of the invitations' layer are the same: equal to five decimal places. */
export function samePoint(a: { lat: number; lon: number }, b: { lat: number; lon: number }) {
  return roundDegrees(a.lat) === roundDegrees(b.lat) && roundDegrees(a.lon) === roundDegrees(b.lon);
}

/** A mail list's state as the page keeps it: its filters, without the list's order and page,
 *  and without photo_area, whose place the page's own view takes. */
function mapList(list: ListState): ListState {
  return {
    ...list,
    photo_area: null,
    sort: DEFAULT_LIST_STATE.sort,
    cursor: null,
    limit: DEFAULT_LIST_STATE.limit,
    page: 1,
  };
}

/** The page's state a query string describes; values that cannot be used are ignored. */
export function parsePlacesState(search: URLSearchParams): PlacesState {
  const from = search.get("taken_from");
  const to = search.get("taken_to");
  return {
    list: mapList(parseListState(search)),
    taken_from: isDay(from) ? from : null,
    taken_to: isDay(to) ? to : null,
    device: search.get("device") || null,
    off: LAYER_KEYS.filter((key) => search.getAll("off").includes(key)),
    view: parseView(search.get("at")),
    point: parsePoint(search.get("point")),
  };
}

/** The filters of the three layers (PlaceParams), defaults left out. */
export function toPlaceParams(state: PlacesState): PlaceParams {
  const params: PlaceParams = toFilters(state.list);
  if (state.taken_from) params.taken_from = state.taken_from;
  if (state.taken_to) params.taken_to = state.taken_to;
  if (state.device) params.device = state.device;
  return params;
}

export function viewParam(view: MapView): string {
  return `${view.lat.toFixed(5)},${view.lon.toFixed(5)},${Math.round(view.zoom * 100) / 100}`;
}

/** The query string of state, the inverse of parsePlacesState. */
export function placesSearch(state: PlacesState): URLSearchParams {
  return buildQuery({
    ...toPlaceParams(state),
    off: state.off,
    at: state.view && viewParam(state.view),
    point: state.point && pointParam(state.point),
  });
}

export function placesHref(state: PlacesState): string {
  const search = placesSearch(state).toString();
  return search ? `/orte?${search}` : "/orte";
}

/** The page "Orte" with the filters of a mail list ("Auf der Karte", D247). */
export function placesHrefOf(list: ListState): string {
  return placesHref({ ...DEFAULT_PLACES_STATE, list: mapList(list) });
}

/** The page "Orte" around one photo, shown on the side (the small maps, D249). */
export function photoPlacesHref(documentId: number | null, lat: number, lon: number): string {
  return placesHref({
    ...DEFAULT_PLACES_STATE,
    view: { lat, lon, zoom: 13 },
    point: documentId === null ? null : { kind: "photo", id: documentId },
  });
}

/** The mail list with the page's mail filters, of the mails mentioning one place (D86). */
export function textPlaceMailsHref(state: PlacesState, entityId: number): string {
  const entity = state.list.entity.includes(entityId)
    ? state.list.entity
    : [...state.list.entity, entityId];
  return `/mails?${listSearch(withFilters(state.list, { entity }))}`;
}

/** An area as photo_area takes it (D248): west, south, east and north of a view, rounded, the
 *  longitudes brought into -180 to 180. A view wider than the world is the whole world. */
export function areaParam([west, south, east, north]: BBox): string {
  // Into -180 to 180, the world's eastern edge staying 180.
  const wrap = (x: number) => ((((x + 180) % 360) + 360) % 360) - 180;
  const whole = east - west >= 360;
  const w = whole ? -180 : wrap(west);
  const e = whole ? 180 : wrap(east) === -180 ? 180 : wrap(east);
  const latitude = (y: number) => Math.max(-90, Math.min(90, y));
  return [w, latitude(south), e, latitude(north)]
    .map((value) => String(roundDegrees(value)))
    .join(",");
}

/** The mail list with the page's mail filters and the mails carrying a photo inside the view
 *  ("Mails im Kartenausschnitt", D248). Capture time and device are the photos' own filters,
 *  which the mail list does not have. */
export function areaMailsHref(state: PlacesState, view: BBox): string {
  const search = listSearch({ ...state.list, photo_area: areaParam(view) }).toString();
  return `/mails?${search}`;
}
