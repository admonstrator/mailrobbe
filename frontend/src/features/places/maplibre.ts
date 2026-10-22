// The one module that loads MapLibre GL JS (D244). The page "Orte" and the small maps (D249)
// import it lazily, so it comes in a chunk of its own. Its worker is a file this server serves
// (setWorkerUrl, no blob: worker), and the pmtiles protocol reads the detail map from the server
// by range requests (D245). Tests replace this module (src/test/setup.ts): jsdom has no WebGL.

import "maplibre-gl/dist/maplibre-gl.css";

import {
  addProtocol,
  Map as MapLibreMap,
  NavigationControl,
  ScaleControl,
  setWorkerUrl,
  type MapOptions,
} from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { Protocol } from "pmtiles";

setWorkerUrl(new URL(workerUrl, window.location.href).href);
addProtocol("pmtiles", new Protocol().tile);

/** MapLibre's own texts (buttons, attribution) in German. */
const LOCALE: Record<string, string> = {
  "AttributionControl.ToggleAttribution": "Quellen ein- und ausblenden",
  "AttributionControl.MapFeedback": "Rückmeldung zur Karte",
  "Map.Title": "Karte",
  "Marker.Title": "Markierung",
  "NavigationControl.ResetBearing": "Ziehen dreht die Karte, ein Klick richtet sie nach Norden",
  "NavigationControl.ZoomIn": "Vergrößern",
  "NavigationControl.ZoomOut": "Verkleinern",
  "Popup.Close": "Schließen",
  "ScaleControl.Meters": "m",
  "ScaleControl.Kilometers": "km",
};

/** The overview map's sources, named always (D244); the detail map adds its own. */
export const ATTRIBUTION = "Natural Earth, GeoNames";

export type { MapOptions };
export type MapInstance = MapLibreMap;

let drawable: boolean | undefined;

/** Whether this browser can draw the maps: MapLibre needs WebGL 2. Asked once; the context of
 *  the question is let go at once, since a page may hold only a few. */
export function canDraw(): boolean {
  if (drawable === undefined) {
    try {
      const context = document.createElement("canvas").getContext("webgl2");
      drawable = context !== null;
      context?.getExtension("WEBGL_lose_context")?.loseContext();
    } catch {
      drawable = false;
    }
  }
  return drawable;
}

/** A map with the app's settings: German texts, the sources named, no rotation; with controls
 *  the zoom buttons and a scale. */
export function createMap(
  { attributionControl, ...options }: MapOptions,
  controls = false,
): MapLibreMap {
  const map = new MapLibreMap({
    locale: LOCALE,
    dragRotate: false,
    pitchWithRotate: false,
    touchPitch: false,
    ...options,
    attributionControl: {
      compact: false,
      customAttribution: ATTRIBUTION,
      ...(attributionControl || {}),
    },
  });
  if (controls) {
    map.addControl(new NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new ScaleControl({ unit: "metric" }), "bottom-left");
  }
  return map;
}
