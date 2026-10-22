import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BBox, MapStatus } from "../../api/types";
import * as fx from "../../test/fixtures";
import { fixtureApi, renderElement, type ApiCall } from "../../test/render";
import { MapDataCard } from "./MapDataCard";

const VIEW: BBox = [9.4712345, 47.04, 9.64, 47.27];

/** The fake backend answering the map status with status, after a start or stop with after,
 *  and a start with error when given. */
function withStatus(
  status: MapStatus,
  error?: { code: string; status: number },
  after: MapStatus = status,
) {
  let written = false;
  return (call: ApiCall) => {
    if (call.url.pathname === "/api/map/status") return written ? after : status;
    if (error && call.url.pathname === "/api/map/download" && call.method === "POST") {
      return Response.json({ detail: { code: error.code, message: "" } }, { status: error.status });
    }
    if (call.method !== "GET") written = true;
    return fixtureApi(call);
  };
}

const stopping = {
  ...fx.mapStatusRunning,
  job: { ...fx.mapJobRunning, stop_requested: true },
};

const writes = (calls: ApiCall[]) => calls.filter((call) => call.method !== "GET");

async function card(): Promise<HTMLElement> {
  const title = await screen.findByRole("heading", { name: "Kartendaten" });
  return title.closest("section")!;
}

describe("the card Kartendaten (D245, D246)", () => {
  it("is not there when the server offers no download and has no detail map", async () => {
    const { calls } = renderElement(<MapDataCard view={VIEW} />, withStatus(fx.mapStatusOff));
    await waitFor(() =>
      expect(calls.some((call) => call.url.pathname === "/api/map/status")).toBe(true),
    );
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(screen.queryByRole("heading", { name: "Kartendaten" })).toBeNull();
  });

  it("offers regions and details with their sizes, the free space and where the data comes from", async () => {
    renderElement(<MapDataCard view={VIEW} />, withStatus(fx.mapStatus));
    const box = within(await card());
    expect(box.getByText(/zeigt den mitgelieferten Überblick/)).toBeTruthy();
    const regions = within(box.getByRole("group", { name: "Region" }));
    const germany = regions.getByRole("radio", { name: /Deutschland/ });
    expect((germany as HTMLInputElement).checked).toBe(true);
    expect(germany.closest("label")!.textContent).toBe("Deutschland3,5 GB");
    expect(regions.getByRole("radio", { name: /DACH/ }).closest("label")!.textContent).toBe(
      "DACH5,2 GB",
    );
    expect(
      regions.getByRole("radio", { name: /Aktueller Kartenausschnitt/ }).closest("label")!
        .textContent,
    ).toBe("Aktueller KartenausschnittGröße wird beim Start ermittelt");
    const details = within(box.getByRole("group", { name: "Detail" }));
    expect(details.getByRole("radio", { name: /Straßen/ }).closest("label")!.textContent).toBe(
      "Straßenjede Straße, bis Zoomstufe 143,5 GB",
    );
    expect(
      details.getByRole("radio", { name: /Überblick/ }).closest("label")!.textContent,
    ).toContain("210,0 MB");
    expect(box.getByText(/Frei auf dem Server: 120,0 GB/)).toBeTruthy();
    expect(box.getByText(/Größen vom Stand 2026-10-22/)).toBeTruthy();
    const note = box.getByText(/lädt dafür einmal Kartendaten aus OpenStreetMap/);
    expect(note.textContent).toBe(
      "Mailrobbe lädt dafür einmal Kartendaten aus OpenStreetMap von build.protomaps.com; sonst geht nichts ins Internet.",
    );
  });

  it("starts a download of the choice and shows it running at once", async () => {
    const { calls } = renderElement(
      <MapDataCard view={VIEW} />,
      withStatus(fx.mapStatus, undefined, fx.mapStatusRunning),
    );
    const box = within(await card());
    fireEvent.click(box.getByRole("radio", { name: /Österreich/ }));
    fireEvent.click(box.getByRole("radio", { name: /Alle Details/ }));
    expect(
      box.getByRole("radio", { name: /Alle Details/ }).closest("label")!.textContent,
    ).toContain("2,2 GB");
    fireEvent.click(box.getByRole("button", { name: "Detailkarte laden" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0]).toMatchObject({
      method: "POST",
      body: { region: "at", detail: "full" },
    });
    expect(writes(calls)[0].url.pathname).toBe("/api/map/download");
    expect(await box.findByText("Download läuft")).toBeTruthy();
  });

  it("downloads the map's current view by its box", async () => {
    const { calls } = renderElement(<MapDataCard view={VIEW} />, withStatus(fx.mapStatus));
    const box = within(await card());
    fireEvent.click(box.getByRole("radio", { name: /Aktueller Kartenausschnitt/ }));
    fireEvent.click(box.getByRole("button", { name: "Detailkarte laden" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toEqual({
      region: "view",
      detail: "streets",
      bbox: [9.47123, 47.04, 9.64, 47.27],
    });
  });

  it("does not start what does not fit, nor the view before the map has one", async () => {
    renderElement(
      <MapDataCard view={null} />,
      withStatus({ ...fx.mapStatus, free_bytes: 2 * 1024 ** 3 }),
    );
    const box = within(await card());
    expect(box.getByText("Dafür reicht der freie Platz auf dem Server nicht.")).toBeTruthy();
    const start = box.getByRole("button", { name: "Detailkarte laden" }) as HTMLButtonElement;
    expect(start.disabled).toBe(true);
    fireEvent.click(box.getByRole("radio", { name: /Überblick/ }));
    expect(start.disabled).toBe(false);
    fireEvent.click(box.getByRole("radio", { name: /Aktueller Kartenausschnitt/ }));
    expect(start.disabled).toBe(true);
  });

  it("shows a running download with its steps and stops it", async () => {
    const { calls } = renderElement(
      <MapDataCard view={VIEW} />,
      withStatus(fx.mapStatusRunning, undefined, stopping),
    );
    const box = within(await card());
    const run = within(box.getByRole("group", { name: "Download der Detailkarte" }));
    expect(run.getByText("Download läuft")).toBeTruthy();
    expect(run.getByText(/Deutschland, Straßen/).textContent).toBe(
      "Deutschland, Straßen1,3 GB von 3,4 GB",
    );
    const steps = within(run.getByRole("list", { name: "Schritte des Laufs" }));
    expect(steps.getByText("Verzeichnis der Kartendatei lesen")).toBeTruthy();
    expect(steps.getByText("Kartenkacheln laden")).toBeTruthy();
    expect(
      steps.getByText(/1,3 GB von 3,4 GB · 1,1 MB\/s · Restzeit geschätzt 33 min/),
    ).toBeTruthy();
    expect(steps.getByText("Detailkarte fertigstellen")).toBeTruthy();
    // No new choice while it runs.
    expect(box.queryByRole("form", { name: "Detailkarte laden" })).toBeNull();

    fireEvent.click(run.getByRole("button", { name: "Anhalten" }));
    await waitFor(() =>
      expect(writes(calls).map((call) => call.url.pathname)).toEqual(["/api/map/download/stop"]),
    );
    expect(await run.findByText("Download wird angehalten …")).toBeTruthy();
  });

  it("continues a stopped download of the same choice", async () => {
    const { calls } = renderElement(
      <MapDataCard view={VIEW} />,
      withStatus(fx.mapStatusPartial, undefined, fx.mapStatusRunning),
    );
    const box = within(await card());
    expect(box.getByText(/Österreich, Alle Details/).closest("p")!.textContent).toBe(
      "Angehaltener Download: Österreich, Alle Details921,6 MB von 2,2 GB geladen",
    );
    // A new choice is a step further, and says that it starts over.
    expect(box.queryByRole("button", { name: "Detailkarte laden" })).toBeNull();
    fireEvent.click(box.getByRole("button", { name: "Andere Detailkarte laden …" }));
    expect(
      box.getByText(/beginnt von vorn; der angehaltene Download wird dann verworfen/),
    ).toBeTruthy();
    fireEvent.click(box.getByRole("button", { name: "Abbrechen" }));

    fireEvent.click(box.getByRole("button", { name: "Fortsetzen" }));
    await waitFor(() => expect(writes(calls)).toHaveLength(1));
    expect(writes(calls)[0].body).toEqual({ region: "at", detail: "full" });
    expect(await box.findByText("Download läuft")).toBeTruthy();
  });

  it("shows the detail map there is and deletes it after asking", async () => {
    const { calls } = renderElement(<MapDataCard view={VIEW} />, withStatus(fx.mapStatusDetail));
    const box = within(await card());
    expect(box.getByText(/Detailkarte: Deutschland, Straßen/).closest("p")!.textContent).toBe(
      "Detailkarte: Deutschland, Straßen3,4 GB · geladen am 22.10.2026 · OpenStreetMap-Stand 20261021",
    );
    fireEvent.click(box.getByRole("button", { name: "Andere Detailkarte laden …" }));
    expect(box.getByText(/ersetzt die vorhandene, sobald sie vollständig ist/)).toBeTruthy();

    fireEvent.click(box.getByRole("button", { name: "Detailkarte löschen" }));
    const dialog = within(screen.getByRole("dialog", { name: "Detailkarte löschen?" }));
    expect(
      dialog.getByText(
        /Die Detailkarte \(Deutschland, Straßen, 3,4 GB\) wird auf dem Server gelöscht/,
      ),
    ).toBeTruthy();
    expect(writes(calls)).toHaveLength(0);
    fireEvent.click(dialog.getByRole("button", { name: "Löschen" }));
    await waitFor(() =>
      expect(writes(calls).map((call) => `${call.method} ${call.url.pathname}`)).toEqual([
        "DELETE /api/map/detail",
      ]),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("keeps a detail map's delete when downloads are switched off", async () => {
    renderElement(
      <MapDataCard view={VIEW} />,
      withStatus({ ...fx.mapStatusDetail, offered: false, source_host: null }),
    );
    const box = within(await card());
    expect(box.getByRole("button", { name: "Detailkarte löschen" })).toBeTruthy();
    expect(box.queryByRole("button", { name: /Detailkarte laden/ })).toBeNull();
  });

  it("says in German why a start was refused, and how the last run failed", async () => {
    renderElement(
      <MapDataCard view={VIEW} />,
      withStatus(fx.mapStatusFailed, { code: "map_off", status: 409 }),
    );
    const box = within(await card());
    expect(box.getByText(/Der letzte Download ist abgebrochen/)).toBeTruthy();
    expect(
      box.getByText("range request failed three times: HTTP 503 from build.protomaps.com"),
    ).toBeTruthy();
    fireEvent.click(box.getByRole("button", { name: "Detailkarte laden" }));
    expect((await box.findByRole("alert")).textContent).toBe(
      "Der Download von Kartendaten ist auf diesem Server abgeschaltet (MAILROBBE_MAP_SOURCE=off).",
    );
  });

  it("says when a map run is already going", async () => {
    renderElement(
      <MapDataCard view={VIEW} />,
      withStatus(fx.mapStatus, { code: "job_running", status: 409 }),
    );
    const box = within(await card());
    fireEvent.click(box.getByRole("button", { name: "Detailkarte laden" }));
    expect((await box.findByRole("alert")).textContent).toBe(
      "Es läuft bereits ein Download der Detailkarte.",
    );
  });
});
