import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ImportStatus, ImportSummary } from "../../api/types";
import { importJob, importStatus, importSummary } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const noDocuments: ImportSummary["documents"] = {
  pending: 0,
  text: 0,
  empty: 0,
  scanned: 0,
  encrypted: 0,
  unsupported: 0,
  too_large: 0,
  failed: 0,
  timeout: 0,
  unreadable: 0,
};

function backend(status: ImportStatus, summary: ImportSummary = importSummary) {
  return (call: ApiCall): unknown => {
    if (call.url.pathname === "/api/import/status") return status;
    if (call.url.pathname === "/api/import/summary") return summary;
    return fixtureApi(call);
  };
}

function tile(label: string): HTMLElement {
  const tiles = screen.getByRole("list", { name: "Kennzahlen des Archivs" });
  return within(tiles).getByText(label).closest("li")!;
}

describe("attachments on the import dashboard", () => {
  it("shows the attachments phase with its progress, rate and remaining time", async () => {
    const status: ImportStatus = {
      ...importStatus,
      import_job: {
        ...importJob,
        phase: "attachments",
        progress: {
          ...importJob.progress,
          documents_total: 5_000,
          documents_done: 1_200,
          documents_per_second: 40,
        },
      },
    };
    renderApp("/import", backend(status));
    expect(
      await screen.findByText(
        "Anhänge auswerten: Text aus 1.200 von 5.000 Dokumenten gelesen · 40 Dokumente/s · Restzeit ca. 2 min",
      ),
    ).toBeTruthy();
  });

  const slowRun = (done: number, rate: number): ImportStatus => ({
    ...importStatus,
    import_job: {
      ...importJob,
      phase: "attachments",
      progress: {
        ...importJob.progress,
        documents_total: 80,
        documents_done: done,
        documents_per_second: rate,
      },
    },
  });

  it("shows the phase before its rate is known", async () => {
    renderApp("/import", backend(slowRun(0, 0)));
    expect(
      await screen.findByText("Anhänge auswerten: Text aus 0 von 80 Dokumenten gelesen"),
    ).toBeTruthy();
  });

  it("shows a slow rate with a decimal", async () => {
    renderApp("/import", backend(slowRun(20, 0.4)));
    expect(
      await screen.findByText(
        "Anhänge auswerten: Text aus 20 von 80 Dokumenten gelesen · 0,4 Dokumente/s · Restzeit ca. 3 min",
      ),
    ).toBeTruthy();
  });

  it("counts attachments and documents by text status, each leading to its list", async () => {
    renderApp("/import");
    const attachments = await screen.findByText("118.204");
    expect(attachments.closest("li")).toBe(tile("Anhänge"));
    expect(
      within(tile("Anhänge"))
        .getByRole("link", { name: "79.110 verschiedene Dokumente" })
        .getAttribute("href"),
    ).toBe("/anhaenge");

    const card = screen.getByRole("heading", { name: "Anhänge ausgewertet" }).closest("section")!;
    const rows = within(card)
      .getAllByRole("listitem")
      .map((row) => row.textContent);
    expect(rows).toEqual([
      "Mit Text41.380",
      "Gescannt (ohne Text)6.904",
      "Verschlüsselt87",
      "Fehler391",
      "Zeitüberschreitung6",
      "Zu groß14",
      "Ohne Text212",
      "Nicht unterstützt30.116",
    ]);
    expect(
      within(card).getByRole("link", { name: "Gescannt (ohne Text)" }).getAttribute("href"),
    ).toBe("/anhaenge?text_status=scanned");
    expect(
      within(card).getByText("79.110 verschiedene Dokumente aus 118.204 Anhängen."),
    ).toBeTruthy();
    expect(within(card).getByRole("img").getAttribute("aria-label")).toContain("52 % Mit Text");
  });

  it("says that the next import evaluates attachments without documents", async () => {
    renderApp(
      "/import",
      backend(importStatus, { ...importSummary, attachments: 4_211, documents: noDocuments }),
    );
    expect(await screen.findByText("werden beim nächsten Import ausgewertet")).toBeTruthy();
    expect(
      screen.getByText(
        "Die 4.211 Anhänge werden beim nächsten Import ausgewertet: Gleiche Dateien werden zu Dokumenten zusammengefasst und ihr Text wird gelesen.",
      ),
    ).toBeTruthy();
  });

  it("says when the archive has no attachments", async () => {
    renderApp(
      "/import",
      backend(importStatus, { ...importSummary, attachments: 0, documents: noDocuments }),
    );
    expect(await screen.findByText("keine Anhänge")).toBeTruthy();
    expect(screen.getByText("Noch keine Anhänge im Archiv.")).toBeTruthy();
  });

  it("notes documents waiting for the next import", async () => {
    renderApp(
      "/import",
      backend(importStatus, {
        ...importSummary,
        documents: { ...noDocuments, pending: 300, text: 700 },
      }),
    );
    expect(await screen.findByText(/Ausstehende liest der nächste Import\./)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Ausstehend" }).getAttribute("href")).toBe(
      "/anhaenge?text_status=pending",
    );
  });
});
