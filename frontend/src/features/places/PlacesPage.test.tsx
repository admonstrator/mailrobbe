import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { StyleSpecification } from "./mapStyle";
import * as fx from "../../test/fixtures";
import { fakeMaps, type FakeFeature } from "../../test/maplibre";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const callsTo = (calls: ApiCall[], path: string) =>
  calls.filter((call) => call.url.pathname === path);
const query = (call: ApiCall) => decodeURIComponent(call.url.searchParams.toString());
const search = (router: { state: { location: { search: string } } }) =>
  decodeURIComponent(router.state.location.search);

function features(style: StyleSpecification, source: string): unknown[] {
  return (style.sources[source] as { data: { features: unknown[] } }).data.features;
}

function visibility(style: StyleSpecification, id: string): unknown {
  const layer = style.layers.find((one) => one.id === id) as { layout?: { visibility?: string } };
  return layer.layout?.visibility;
}

const point = (
  layer: string,
  properties: Record<string, unknown>,
  lon = 10,
  lat = 50,
): FakeFeature => ({
  layer: { id: layer },
  properties,
  geometry: { type: "Point", coordinates: [lon, lat] },
});

/** The map of the page, once the layers' answers are drawn. */
async function drawnMap() {
  await waitFor(() => expect(features(fakeMaps.last().style, "photos")).toHaveLength(105));
  return fakeMaps.last();
}

const filterColumn = () => screen.getByRole("complementary", { name: "Filter" });
const details = () => screen.getByRole("complementary", { name: "Details" });
const layerRow = (name: string) =>
  within(filterColumn())
    .getByRole("checkbox", { name: new RegExp(`^${name}`) })
    .closest("div")!;

describe("the page Orte (D247)", () => {
  it("is in the navigation after Karte and draws the three layers with their counts", async () => {
    const { calls } = renderApp("/orte");
    const map = await drawnMap();
    const navigation = screen.getByRole("navigation", { name: "Hauptnavigation" });
    const labels = within(navigation)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(labels.indexOf("Orte")).toBe(labels.indexOf("Karte") + 1);
    expect(document.title).toBe("Orte · Mailrobbe");
    expect(screen.getByRole("heading", { level: 1, name: "Orte" })).toBeTruthy();

    expect(within(layerRow("Fotos")).getByText("105")).toBeTruthy();
    expect(within(layerRow("Orte aus Texten")).getByText("6")).toBeTruthy();
    expect(within(layerRow("Termine")).getByText("2")).toBeTruthy();
    expect(features(map.style, "texts")).toHaveLength(6);
    expect(features(map.style, "events")).toHaveLength(2);
    await waitFor(() => expect(features(map.style, "towns")).toHaveLength(fx.towns.length));

    // The map over Germany, Austria and Switzerland, with zoom buttons and scale.
    expect(map.options).toMatchObject({ center: [10.8, 50.2], zoom: 5, maxZoom: 18 });
    expect(map.controls).toBe(true);
    // Without filters every layer asks for everything; the side shows the overview.
    for (const path of ["/api/places/photos", "/api/places/texts", "/api/places/events"]) {
      expect(callsTo(calls, path).map(query)).toEqual([""]);
    }
    expect(within(details()).getByText("Orte im Archiv")).toBeTruthy();
    expect(within(details()).getByText("1.204")).toBeTruthy();
  });

  it("hands the URL's filters to the layers and shows the mail list's others as chips", async () => {
    const { calls, router } = renderApp(
      "/orte?q=Spende&has_attachment=true&person=11&person_role=sent&taken_from=2026-01-01&device=Canon+EOS+80D",
    );
    await drawnMap();
    const expected =
      "q=Spende&has_attachment=true&person=11&person_role=sent&taken_from=2026-01-01&device=Canon+EOS+80D";
    expect(callsTo(calls, "/api/places/photos").map(query)).toEqual([expected]);
    expect(callsTo(calls, "/api/places/texts").map(query)).toEqual([expected]);
    expect(callsTo(calls, "/api/places/events").map(query)).toEqual([expected]);

    const column = filterColumn();
    expect(within(column).getByRole<HTMLInputElement>("searchbox").value).toBe("Spende");
    expect(within(column).getByRole<HTMLSelectElement>("combobox", { name: "Gerät" }).value).toBe(
      "Canon EOS 80D",
    );
    expect(
      within(column).getByRole<HTMLSelectElement>("combobox", { name: "Zeitraum nach" }).value,
    ).toBe("taken");
    expect(within(column).getByLabelText<HTMLInputElement>("von").value).toBe("2026-01-01");
    expect(await within(column).findByRole("button", { name: /Person entfernen/ })).toBeTruthy();
    // The capture time and the device are the map's own: the mail list does not know them.
    expect(screen.getByText(/filtern nur die Karte/)).toBeTruthy();

    const chips = within(column).getByRole("group", { name: "Weitere Filter" });
    fireEvent.click(within(chips).getByRole("button", { name: "Filter entfernen: Mit Anhang" }));
    await waitFor(() => expect(search(router)).not.toContain("has_attachment"));
    expect(search(router)).toContain("q=Spende");

    fireEvent.change(within(column).getByRole("combobox", { name: "Gerät" }), {
      target: { value: "Apple iPhone 13 mini" },
    });
    await waitFor(() => expect(search(router)).toContain("device=Apple+iPhone+13+mini"));
  });

  it("moves the days to the other kind of period", async () => {
    const { router } = renderApp("/orte?taken_from=2026-01-01&taken_to=2026-06-30");
    await drawnMap();
    fireEvent.change(screen.getByRole("combobox", { name: "Zeitraum nach" }), {
      target: { value: "sent" },
    });
    await waitFor(() => expect(search(router)).toBe("?date_from=2026-01-01&date_to=2026-06-30"));
  });

  it("switches a layer off in the URL and on the map", async () => {
    const { router } = renderApp("/orte");
    const map = await drawnMap();
    fireEvent.click(within(filterColumn()).getByRole("checkbox", { name: /^Orte aus Texten/ }));
    await waitFor(() => expect(search(router)).toBe("?off=texts"));
    await waitFor(() => expect(visibility(map.style, "texts-circle")).toBe("none"));
    expect(visibility(map.style, "photos-point")).toBe("visible");
  });

  it("says when a layer was cut at its limit or counted over a sample", async () => {
    renderApp("/orte", (call) => {
      if (call.url.pathname === "/api/places/photos") return fx.photoPointsTruncated;
      if (call.url.pathname === "/api/places/texts") return fx.textPlacesSampled;
      return fixtureApi(call);
    });
    await drawnMap();
    expect(within(layerRow("Fotos")).getByText("23.456")).toBeTruthy();
    expect(
      within(layerRow("Fotos")).getByText(
        "Gezeigt sind 105 von 23.456 Fotos; Filter grenzen sie ein.",
      ),
    ).toBeTruthy();
    expect(within(layerRow("Orte aus Texten")).getByText(/Stichprobe von 10.000/)).toBeTruthy();
    expect(within(layerRow("Termine")).queryByText(/Gezeigt/)).toBeNull();
  });

  it("keeps the view in the URL and opens the mails of the view's photos (D248)", async () => {
    const { router } = renderApp("/orte?q=Spende");
    const map = await drawnMap();
    act(() => map.move({ lat: 51, lon: 10.5 }, 7.25, [5.9, 47.3, 15.1, 55.1]));
    await waitFor(() => expect(search(router)).toBe("?q=Spende&at=51.00000,10.50000,7.25"));
    expect(
      screen.getByRole("link", { name: "Mails im Kartenausschnitt" }).getAttribute("href"),
    ).toBe("/mails?q=Spende&photo_area=5.9%2C47.3%2C15.1%2C55.1");
    expect(screen.getByRole("link", { name: "In der Mailliste öffnen" }).getAttribute("href")).toBe(
      "/mails?q=Spende",
    );
  });

  it("reopens a link with its view and its point", async () => {
    renderApp("/orte?at=53.5,10,9&point=photo:5105");
    await drawnMap();
    expect(fakeMaps.last().options).toMatchObject({ center: [10, 53.5], zoom: 9 });
    const panel = within(details());
    expect(await panel.findByRole("heading", { name: "IMG_2041.jpg" })).toBeTruthy();
    expect(panel.getByText("02.10.2026 14:31:07 (ohne Zeitzone)")).toBeTruthy();
    expect(panel.getByText("in Hamburg")).toBeTruthy();
    expect(panel.getByText("unbekannt")).toBeTruthy(); // no device
    expect(panel.queryByRole("region", { name: "Fotos dieses Geräts" })).toBeNull();
  });

  it("without WebGL says why there is no map", async () => {
    fakeMaps.drawable = false;
    renderApp("/orte");
    expect(
      await screen.findByText("Die Karte lässt sich in diesem Browser nicht zeichnen."),
    ).toBeTruthy();
    expect(fakeMaps.made).toHaveLength(0);
  });
});

describe("a point's details (D248)", () => {
  it("shows a photo picked on the map: picture, time, device, place and its mails", async () => {
    const { router } = renderApp("/orte");
    const map = await drawnMap();
    act(() => map.click([point("photos-point", { id: 5107 }, 11.35201, 50.99512)]));
    await waitFor(() => expect(search(router)).toBe("?point=photo:5107"));

    const panel = within(details());
    expect(await panel.findByRole("heading", { name: "IMG_3310.jpg" })).toBeTruthy();
    expect(panel.getByRole("img", { name: "Vorschau von IMG_3310.jpg" }).getAttribute("src")).toBe(
      "/api/attachments/9107/content",
    );
    expect(panel.getByText("14.06.2026 11:12:44")).toBeTruthy();
    expect(panel.getAllByText("Apple iPhone 13 mini").length).toBeGreaterThan(0);
    expect(panel.getByText("2,3 km nordöstlich von Weimar")).toBeTruthy();
    expect(panel.getByText("50,99512, 11,35201")).toBeTruthy();
    expect(
      panel.getByRole("link", { name: "auf OpenStreetMap ansehen" }).getAttribute("href"),
    ).toBe("https://www.openstreetmap.org/?mlat=50.99512&mlon=11.35201#map=16/50.99512/11.35201");
    expect(panel.getByRole("link", { name: "Zum Dokument" }).getAttribute("href")).toBe(
      "/anhaenge/5107",
    );
    const mails = within(panel.getByRole("region", { name: "Mails mit diesem Foto" }));
    const [first, forward] = mails.getAllByRole("link");
    expect(first.getAttribute("href")).toBe("/mails/184060");
    expect(first.textContent).toBe(
      "14.06.2026Sofia Lindqvist → Anna Keller, Jonas BrandtFotos vom Ortstermin",
    );
    expect(forward.textContent).toBe(
      "16.06.2026Anna Keller → Peter Hofmann +2WG: Fotos vom Ortstermin",
    );
    // The point is ringed on the map.
    await waitFor(() => expect(features(map.style, "marked")).toHaveLength(1));

    fireEvent.click(panel.getByRole("button", { name: "Schließen" }));
    await waitFor(() => expect(search(router)).toBe(""));
    expect(within(details()).getByText("Orte im Archiv")).toBeTruthy();
  });

  it("lists the photos around it and of its device, and brings a picked one into view", async () => {
    const { calls, router } = renderApp("/orte?point=photo:5107&device=Apple+iPhone+13+mini");
    const map = await drawnMap();
    const nearby = within(await screen.findByRole("region", { name: "Fotos im Umkreis" }));
    expect(await nearby.findByText("2 weitere Fotos im Umkreis von 2 km")).toBeTruthy();
    expect(nearby.queryByText("IMG_3310.jpg")).toBeNull(); // the photo itself
    const around = callsTo(calls, "/api/places/photo-list").filter((call) =>
      call.url.searchParams.has("lat"),
    );
    expect(query(around[0])).toBe(
      "device=Apple+iPhone+13+mini&lat=50.99512&lon=11.35201&radius_km=2&limit=50",
    );
    fireEvent.click(nearby.getByRole("button", { name: "10 km" }));
    await waitFor(() =>
      expect(callsTo(calls, "/api/places/photo-list").map(query)).toContain(
        "device=Apple+iPhone+13+mini&lat=50.99512&lon=11.35201&radius_km=10&limit=50",
      ),
    );
    expect(nearby.getByRole("button", { name: "10 km" }).getAttribute("aria-pressed")).toBe("true");

    const device = within(screen.getByRole("region", { name: "Fotos dieses Geräts" }));
    expect(
      await device.findByText("3 Fotos mit Apple iPhone 13 mini, nach Aufnahmezeit"),
    ).toBeTruthy();
    expect(device.getByRole("button", { name: /IMG_3310.jpg/ }).getAttribute("aria-current")).toBe(
      "true",
    );

    fireEvent.click(nearby.getByRole("button", { name: /IMG_3311.jpg/ }));
    await waitFor(() => expect(search(router)).toContain("point=photo:6201"));
    await waitFor(() => expect(map.eased).toContainEqual({ center: [11.33, 50.98], zoom: 13 }));
  });

  it("zooms into a bundle of photos", async () => {
    renderApp("/orte");
    const map = await drawnMap();
    map.clusterZoom = 11;
    act(() => map.click([point("photos-cluster", { cluster_id: 3, point_count: 38 }, 10, 53.55)]));
    await waitFor(() => expect(map.eased).toEqual([{ center: [10, 53.55], zoom: 11 }]));
  });

  it("shows a place from the texts with the mails naming it", async () => {
    const { router } = renderApp("/orte?q=Spende");
    const map = await drawnMap();
    act(() => map.click([point("texts-circle", { id: 353, mails: 412 })]));
    await waitFor(() => expect(search(router)).toBe("?q=Spende&point=place:353"));
    const panel = within(details());
    expect(panel.getByRole("heading", { name: "Berlin" })).toBeTruthy();
    expect(panel.getByText("Berlin, DE")).toBeTruthy();
    expect(panel.getByText("412 Mails")).toBeTruthy();
    expect(
      panel.getByRole("link", { name: "Mails, die diesen Ort nennen" }).getAttribute("href"),
    ).toBe("/mails?q=Spende&entity=353");
    expect(panel.getByRole("link", { name: "Zur Entität" }).getAttribute("href")).toBe(
      "/entitaeten/353",
    );
  });

  it("shows an invitation's place with its locations and events", async () => {
    const { router } = renderApp("/orte");
    const map = await drawnMap();
    act(() => map.click([point("events-circle", { lat: 53.55073, lon: 9.99302 })]));
    await waitFor(() => expect(search(router)).toBe("?point=event:53.55073,9.99302"));
    const panel = within(details());
    expect(panel.getByRole("heading", { name: "Hamburg, DE" })).toBeTruthy();
    expect(panel.getByText("3 Termine, 10.03.2026 bis 22.09.2026")).toBeTruthy();
    const locations = within(panel.getByRole("region", { name: "So steht es in den Einladungen" }));
    expect(locations.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Hamburg, Hotel am Hafen, Saal 2",
      "20457 Hamburg",
    ]);
    const events = within(panel.getByRole("region", { name: "Termine" }));
    expect(events.getByText("Die letzten 2 Termine")).toBeTruthy();
    expect(events.getByText("Abstimmung Rahmenvereinbarung")).toBeTruthy();
    expect(events.getByText("Absage")).toBeTruthy();
    expect(events.getAllByRole("link", { name: "Zur Mail" })[0].getAttribute("href")).toBe(
      "/mails/184190",
    );
  });

  it("says when the point is not on the map with these filters", async () => {
    renderApp("/orte?point=place:999");
    await drawnMap();
    const panel = within(details());
    expect(
      panel.getByText("Mit den aktuellen Filtern ist dieser Ort nicht auf der Karte."),
    ).toBeTruthy();
    expect(
      panel.getByRole("link", { name: "Mails, die diesen Ort nennen" }).getAttribute("href"),
    ).toBe("/mails?entity=999");
  });
});
