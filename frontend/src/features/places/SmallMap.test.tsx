import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AttachmentInfo, MetadataSummary } from "../../api/types";
import * as fx from "../../test/fixtures";
import { fakeMaps } from "../../test/maplibre";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";
import type { StyleSpecification } from "./mapStyle";
import { photoPosition } from "./PhotoPosition";
import { smallMapZoom } from "./SmallMap";

const features = (style: StyleSpecification, source: string) =>
  (style.sources[source] as { data: { features: { geometry: { coordinates: number[] } }[] } }).data
    .features;

const summary: MetadataSummary = {
  author: null,
  modified_by: null,
  software: null,
  device: "Canon EOS 80D",
  created: null,
  gps: true,
  latitude: 48.1371,
  longitude: 11.5754,
};

describe("whether and how a small map shows (D249)", () => {
  it("shows a position with both coordinates, never 0, 0", () => {
    expect(photoPosition(summary)).toEqual({ lat: 48.1371, lon: 11.5754 });
    expect(photoPosition({ ...summary, latitude: null })).toBeNull();
    expect(photoPosition({ ...summary, latitude: 0, longitude: 0 })).toBeNull();
    expect(photoPosition({ ...summary, latitude: 0, longitude: 11.5 })).toEqual({
      lat: 0,
      lon: 11.5,
    });
    expect(photoPosition(null)).toBeNull();
  });

  it("shows the streets inside the detail map and the towns elsewhere", () => {
    expect(smallMapZoom(null, 48.1371, 11.5754)).toBe(7);
    expect(smallMapZoom(fx.detailMap, 48.1371, 11.5754)).toBe(14);
    expect(smallMapZoom({ ...fx.detailMap, max_zoom: 10 }, 48.1371, 11.5754)).toBe(11);
    expect(smallMapZoom(fx.detailMap, 48.2085, 16.3721)).toBe(7); // Wien, outside
  });
});

describe("the small map on the document page", () => {
  it("shows a photo's position, still, with the page Orte and OpenStreetMap", async () => {
    renderApp("/anhaenge/5105");
    const place = await screen.findByRole("region", { name: "Ort" });
    expect(
      await within(place).findByRole("img", { name: "Kleine Karte mit dem Aufnahmeort" }),
    ).toBeTruthy();
    const map = fakeMaps.last();
    expect(map.options).toMatchObject({
      center: [9.9661667, 53.5438333],
      zoom: 7,
      interactive: false,
    });
    expect(map.controls).toBe(false);
    expect(features(map.style, "marked")[0].geometry.coordinates).toEqual([9.9661667, 53.5438333]);
    expect(map.style.sources.detail).toBeUndefined();
    expect(
      within(place).getByRole("link", { name: "Auf der Orte-Seite zeigen" }).getAttribute("href"),
    ).toBe("/orte?at=53.54383%2C9.96617%2C13&point=photo%3A5105");
    // The link to OpenStreetMap stays where it was, once.
    expect(within(place).getAllByRole("link", { name: "auf OpenStreetMap ansehen" })).toHaveLength(
      1,
    );
    expect(within(place).getByText("53.5438333, 9.9661667")).toBeTruthy();
  });

  it("draws the detail map where there is one, close up", async () => {
    renderApp("/anhaenge/5105", (call) =>
      call.url.pathname === "/api/map/status" ? fx.mapStatusDetail : fixtureApi(call),
    );
    const place = await screen.findByRole("region", { name: "Ort" });
    await within(place).findByRole("img", { name: "Kleine Karte mit dem Aufnahmeort" });
    const map = fakeMaps.last();
    expect(map.options.zoom).toBe(14);
    expect(map.style.sources.detail).toMatchObject({ type: "vector", maxzoom: 14 });
  });

  it("is not there without a position", async () => {
    const { calls } = renderApp("/anhaenge/5101");
    await screen.findByRole("heading", { name: "Metadaten" });
    expect(screen.queryByRole("region", { name: "Ort" })).toBeNull();
    expect(fakeMaps.made).toHaveLength(0);
    expect(calls.some((call) => call.url.pathname.startsWith("/api/map/"))).toBe(false);
  });

  it("says so when the browser cannot draw it, and keeps the links", async () => {
    fakeMaps.drawable = false;
    renderApp("/anhaenge/5105");
    const place = await screen.findByRole("region", { name: "Ort" });
    expect(
      await within(place).findByText("Die Karte braucht WebGL, das in diesem Browser fehlt."),
    ).toBeTruthy();
    expect(within(place).getByRole("link", { name: "Auf der Orte-Seite zeigen" })).toBeTruthy();
  });
});

describe("the small map in a mail's attachments", () => {
  const [pdf, sheet] = fx.mailDetail.attachments;
  const photo = (
    id: number,
    filename: string,
    latitude: number,
    longitude: number,
  ): AttachmentInfo => ({
    ...sheet,
    id,
    filename,
    mime_type: "image/jpeg",
    document_id: id + 5000,
    kind: "image",
    text_status: "unsupported",
    pages: null,
    preview: "image",
    metadata: { ...summary, latitude, longitude },
  });
  const munich = photo(903, "IMG_0412.jpg", 48.1371, 11.5754);
  const vienna = photo(904, "IMG_0413.jpg", 48.2085, 16.3721);
  const api = (call: ApiCall) =>
    call.url.pathname === "/api/mails/184221"
      ? { ...fx.mailDetail, attachments: [pdf, munich, vienna] }
      : fixtureApi(call);

  it("shows one photo's position at a time, the first, or the one chosen", async () => {
    renderApp("/mails/184221", api);
    const heading = await screen.findByRole("heading", { name: /^Anhänge \(\d+\)$/ });
    const card = heading.closest("section")!;
    const item = (name: string) => within(card).getByText(name).closest("li")!;
    expect(
      await within(item("IMG_0412.jpg")).findByRole("img", {
        name: "Kleine Karte mit dem Aufnahmeort",
      }),
    ).toBeTruthy();
    expect(
      within(card).getAllByRole("img", { name: "Kleine Karte mit dem Aufnahmeort" }),
    ).toHaveLength(1);
    expect(fakeMaps.last().options.center).toEqual([11.5754, 48.1371]);
    const first = within(item("IMG_0412.jpg"));
    expect(
      first.getByRole("link", { name: "Auf der Orte-Seite zeigen" }).getAttribute("href"),
    ).toBe("/orte?at=48.13710%2C11.57540%2C13&point=photo%3A5903");
    expect(first.getByRole("link", { name: "auf OpenStreetMap ansehen" })).toBeTruthy();
    expect(
      within(item("Rahmenvereinbarung_2026_final.pdf")).queryByRole("button", {
        name: /Aufnahmeort/,
      }),
    ).toBeNull();

    fireEvent.click(
      within(item("IMG_0413.jpg")).getByRole("button", {
        name: "Aufnahmeort von IMG_0413.jpg zeigen",
      }),
    );
    await waitFor(() =>
      expect(
        within(item("IMG_0413.jpg")).getByRole("img", { name: "Kleine Karte mit dem Aufnahmeort" }),
      ).toBeTruthy(),
    );
    expect(
      within(card).getAllByRole("img", { name: "Kleine Karte mit dem Aufnahmeort" }),
    ).toHaveLength(1);
    expect(fakeMaps.last().options.center).toEqual([16.3721, 48.2085]);
    expect(
      within(item("IMG_0412.jpg")).getByRole("button", { name: /Aufnahmeort von IMG_0412.jpg/ }),
    ).toBeTruthy();
  });
});
