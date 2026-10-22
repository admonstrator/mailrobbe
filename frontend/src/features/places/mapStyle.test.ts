import { describe, expect, it } from "vitest";

import { detailMap, eventPlaces, photoPoints, textPlaces, towns } from "../../test/fixtures";
import {
  circleRadius,
  DETAIL_ATTRIBUTION,
  DETAIL_MIN_ZOOM,
  mapStyle,
  townMinZoom,
  type LayerSpecification,
  type StyleSpecification,
} from "./mapStyle";
import { keepFiles } from "./useMap";

const ORIGIN = "http://127.0.0.1:8024";

const layer = (style: StyleSpecification, id: string) =>
  style.layers.find((one) => one.id === id) as LayerSpecification & {
    layout?: Record<string, unknown>;
    filter?: unknown;
  };

const features = (style: StyleSpecification, source: string) => {
  const data = (style.sources[source] as { data: { features: unknown[] } }).data;
  return data.features;
};

describe("the style of the maps (D244, D245)", () => {
  it("loads the overview from this server only", () => {
    const style = mapStyle({ origin: ORIGIN, towns, detail: null });
    expect(style.glyphs).toBe(`${ORIGIN}/map/fonts/{fontstack}/{range}.pbf`);
    expect(style.sprite).toBe(`${ORIGIN}/map/sprites/light`);
    for (const name of ["countries", "states", "lakes", "rivers", "labels"]) {
      expect(style.sources[name]).toEqual({ type: "geojson", data: `${ORIGIN}/map/${name}.json` });
    }
    expect(features(style, "towns")).toHaveLength(towns.length);
    expect(style.sources.detail).toBeUndefined();
    // Nothing but this server and the GeoJSON given inline.
    const urls = JSON.stringify(style).match(/https?:\/\/[^"/]+/g) ?? [];
    expect(new Set(urls)).toEqual(new Set([ORIGIN]));
  });

  it("adds the detail map by the pmtiles protocol within its region, the overview beneath", () => {
    const style = mapStyle({ origin: ORIGIN, towns, detail: detailMap });
    expect(style.sources.detail).toEqual({
      type: "vector",
      tiles: [`pmtiles://${ORIGIN}/api/map/tiles/detail.pmtiles/{z}/{x}/{y}`],
      bounds: detailMap.bbox,
      minzoom: DETAIL_MIN_ZOOM,
      maxzoom: 14,
      attribution: DETAIL_ATTRIBUTION,
    });
    expect(DETAIL_ATTRIBUTION).toContain("© OpenStreetMap-Mitwirkende");
    expect(DETAIL_ATTRIBUTION).toContain("Protomaps");
    const ids = style.layers.map((one) => one.id);
    const detailLayers = style.layers.filter((one) => "source" in one && one.source === "detail");
    expect(detailLayers.length).toBeGreaterThan(20);
    // No background of its own: it would hide the overview around the region.
    expect(style.layers.filter((one) => one.type === "background")).toHaveLength(1);
    expect(ids.indexOf("countries-line")).toBeLessThan(ids.indexOf(detailLayers[0].id));
    expect(ids.indexOf(detailLayers[0].id)).toBeLessThan(ids.indexOf("towns"));
    // German names, in the shipped fonts; Devanagari only for names in that script.
    expect(JSON.stringify(detailLayers)).toContain("name:de");
    const fonts = new Set(JSON.stringify(detailLayers).match(/Noto Sans [\w ]+/g));
    expect(fonts).toEqual(
      new Set([
        "Noto Sans Regular",
        "Noto Sans Medium",
        "Noto Sans Italic",
        "Noto Sans Devanagari Regular v1",
      ]),
    );
    // The overview's labels leave the region to the detail map's.
    expect(JSON.stringify(layer(style, "towns").filter)).toContain("within");
    expect(
      JSON.stringify(layer(mapStyle({ origin: ORIGIN, towns, detail: null }), "towns").filter),
    ).not.toContain("within");
  });

  it("draws the three layers and hides those switched off", () => {
    const style = mapStyle({
      origin: ORIGIN,
      towns,
      detail: null,
      photos: photoPoints.points,
      texts: textPlaces.places,
      events: eventPlaces.places,
      off: ["texts"],
      marked: { lat: 50.99512, lon: 11.35201, radius: 5.5 },
    });
    expect(features(style, "photos")).toHaveLength(photoPoints.points.length);
    expect(style.sources.photos).toMatchObject({ cluster: true });
    expect(features(style, "texts")).toHaveLength(textPlaces.places.length);
    expect(features(style, "events")).toHaveLength(eventPlaces.places.length);
    expect(features(style, "marked")).toHaveLength(1);
    expect(layer(style, "texts-circle").layout).toEqual({ visibility: "none" });
    for (const id of ["photos-cluster", "photos-count", "photos-point", "events-circle"]) {
      expect(layer(style, id).layout?.visibility).toBe("visible");
    }
  });
});

describe("a new style on a map that has one", () => {
  it("keeps the overview's files the map has loaded, and replaces everything else", () => {
    const last = mapStyle({ origin: ORIGIN, towns, detail: null });
    const loaded = { type: "FeatureCollection" as const, features: [] };
    // As MapLibre serialises its style: a source loaded from a file stands as its data.
    const current: StyleSpecification = {
      ...last,
      sources: { ...last.sources, countries: { type: "geojson", data: loaded } },
    };
    const next = mapStyle({ origin: ORIGIN, towns, detail: detailMap, photos: photoPoints.points });
    const kept = keepFiles(last, current, next);
    expect(kept.sources.countries).toBe(current.sources.countries);
    expect(kept.sources.rivers).toBe(current.sources.rivers);
    expect(kept.sources.photos).toBe(next.sources.photos);
    expect(kept.sources.detail).toBe(next.sources.detail);
    expect(kept.layers).toBe(next.layers);
    // A file of its own is loaded again, and a map without a style takes the new one whole.
    const moved = mapStyle({ origin: "http://127.0.0.1:9000", towns, detail: null });
    expect(keepFiles(last, current, moved).sources.countries).toBe(moved.sources.countries);
    expect(keepFiles(last, undefined, next)).toBe(next);
  });
});

describe("sizes and zooms", () => {
  it("labels capitals and large towns first", () => {
    const [berlin, , bern, vaduz, hamburg] = towns;
    expect(townMinZoom(berlin)).toBe(3);
    expect(townMinZoom(vaduz)).toBe(3);
    expect(townMinZoom(bern)).toBe(3);
    expect(townMinZoom(hamburg)).toBe(4);
    expect(townMinZoom(towns.find((town) => town.name === "Weimar")!)).toBe(7);
    expect(townMinZoom({ ...hamburg, population: 800 })).toBe(9);
  });

  it("grows a circle's area with its count", () => {
    expect(circleRadius(412, 412, 5, 22)).toBe(22);
    expect(circleRadius(103, 412, 5, 22)).toBe(13.5);
    expect(circleRadius(0, 412, 5, 22)).toBe(5);
    expect(circleRadius(3, 0, 5, 22)).toBe(5);
  });
});
