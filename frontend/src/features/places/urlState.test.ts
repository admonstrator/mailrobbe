import { describe, expect, it } from "vitest";

import { DEFAULT_LIST_STATE, parseListState, withFilters } from "../mails/listState";
import {
  areaMailsHref,
  areaParam,
  DEFAULT_PLACES_STATE,
  parsePlacesState,
  photoPlacesHref,
  placesHref,
  placesHrefOf,
  placesSearch,
  samePoint,
  textPlaceMailsHref,
  toPlaceParams,
} from "./urlState";

const parse = (query: string) => parsePlacesState(new URLSearchParams(query));

describe("the state of the page Orte in the URL (D247)", () => {
  it("is the default for an empty query string, and back", () => {
    expect(parse("")).toEqual(DEFAULT_PLACES_STATE);
    expect(placesHref(DEFAULT_PLACES_STATE)).toBe("/orte");
  });

  it("keeps filters, photo filters, layers, view and point, and survives the round trip", () => {
    const query =
      "q=Spende&person=11&person_role=sent&collection=3&taken_from=2026-01-01&taken_to=2026-06-30" +
      "&device=Canon+EOS+80D&off=texts&at=50.98012,11.32903,12.5&point=photo:5107";
    const state = parse(query);
    expect(state.list).toMatchObject({
      q: "Spende",
      person: [11],
      person_role: "sent",
      collection: [3],
    });
    expect(state).toMatchObject({
      taken_from: "2026-01-01",
      taken_to: "2026-06-30",
      device: "Canon EOS 80D",
      off: ["texts"],
      view: { lat: 50.98012, lon: 11.32903, zoom: 12.5 },
      point: { kind: "photo", id: 5107 },
    });
    expect(parse(placesSearch(state).toString())).toEqual(state);
    expect(placesSearch(state).toString()).toBe(
      "q=Spende&person=11&person_role=sent&collection=3&taken_from=2026-01-01&taken_to=2026-06-30" +
        "&device=Canon+EOS+80D&off=texts&at=50.98012%2C11.32903%2C12.5&point=photo%3A5107",
    );
  });

  it("knows the three kinds of point", () => {
    expect(parse("point=place:353").point).toEqual({ kind: "place", id: 353 });
    expect(parse("point=event:53.55073,9.99302").point).toEqual({
      kind: "event",
      lat: 53.55073,
      lon: 9.99302,
    });
    expect(
      placesSearch({ ...DEFAULT_PLACES_STATE, point: { kind: "event", lat: 53.5, lon: 10 } }).get(
        "point",
      ),
    ).toBe("event:53.50000,10.00000");
    expect(samePoint({ lat: 53.550731, lon: 9.993021 }, { lat: 53.55073, lon: 9.99302 })).toBe(
      true,
    );
    expect(samePoint({ lat: 53.5508, lon: 9.99302 }, { lat: 53.55073, lon: 9.99302 })).toBe(false);
  });

  it("ignores values it cannot use", () => {
    const state = parse(
      "taken_from=gestern&off=roads&off=photos&at=95,10,5&point=photo:abc&point=house:3&sort=date_asc&page=4",
    );
    expect(state).toEqual({ ...DEFAULT_PLACES_STATE, off: ["photos"] });
    expect(parse("at=50,10,30").view).toEqual({ lat: 50, lon: 10, zoom: 18 });
    expect(parse("point=event:91,10").point).toBeNull();
  });

  it("hands the mail filters and the photos' own filters to the layers", () => {
    const state = parse(
      "q=Spende&dkim=pass&taken_from=2026-01-01&device=Canon+EOS+80D&off=photos&at=50,10,6&point=place:7",
    );
    expect(toPlaceParams(state)).toEqual({
      q: "Spende",
      dkim: ["pass"],
      taken_from: "2026-01-01",
      device: "Canon EOS 80D",
    });
  });
});

describe("links to and from the page Orte", () => {
  it("opens with a mail list's filters, without its order, page and area (Auf der Karte)", () => {
    const list = {
      ...parseListState(
        new URLSearchParams(
          "q=Spende&has_attachment=true&sort=date_asc&page=3&photo_area=5,47,15,55",
        ),
      ),
    };
    expect(placesHrefOf(list)).toBe("/orte?q=Spende&has_attachment=true");
    expect(placesHrefOf(DEFAULT_LIST_STATE)).toBe("/orte");
  });

  it("leaves the area of a link to it out: the view takes its place", () => {
    expect(parse("photo_area=5,47,15,55&q=a").list).toEqual(
      withFilters(DEFAULT_LIST_STATE, { q: "a" }),
    );
  });

  it("shows one photo of the small maps (D249)", () => {
    expect(photoPlacesHref(5105, 53.5438333, 9.9661667)).toBe(
      "/orte?at=53.54383%2C9.96617%2C13&point=photo%3A5105",
    );
    expect(photoPlacesHref(null, 53.5, 10)).toBe("/orte?at=53.50000%2C10.00000%2C13");
  });

  it("opens the mail list of the view's photos with the page's mail filters (D248)", () => {
    const state = parse("q=Spende&taken_from=2026-01-01&device=X&at=50,10,6&point=photo:1");
    expect(areaMailsHref(state, [5.871234, 47.27, 15.04, 55.06])).toBe(
      "/mails?q=Spende&photo_area=5.87123%2C47.27%2C15.04%2C55.06",
    );
  });

  it("opens the mail list of the mails naming a place (D86)", () => {
    expect(textPlaceMailsHref(parse("q=Spende&entity=12"), 353)).toBe(
      "/mails?q=Spende&entity=12&entity=353",
    );
    expect(textPlaceMailsHref(parse("entity=353"), 353)).toBe("/mails?entity=353");
  });
});

describe("the area of a view as photo_area (D248)", () => {
  it("rounds the edges and keeps the latitudes on the globe", () => {
    expect(areaParam([5.8712345, 47.2701, 15.0409, 55.0581])).toBe(
      "5.87123,47.2701,15.0409,55.0581",
    );
    expect(areaParam([-20, -91, 20, 95])).toBe("-20,-90,20,90");
  });

  it("brings longitudes beyond the 180th meridian back, and a view wider than the world is all", () => {
    expect(areaParam([170, -10, 190, 10])).toBe("170,-10,-170,10");
    expect(areaParam([-200, -10, -170, 10])).toBe("160,-10,-170,10");
    expect(areaParam([-300, -60, 300, 60])).toBe("-180,-60,180,60");
    expect(areaParam([100, -10, 180, 10])).toBe("100,-10,180,10");
  });
});
