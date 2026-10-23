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
  const attachmentsRun = (done: number, rate: number | null, eta: number | null): ImportStatus => ({
    ...importStatus,
    import_job: {
      ...importJob,
      phase: "attachments",
      progress: {
        ...importJob.progress,
        workers: 0,
        steps: importJob.progress.steps.map((step) =>
          step.key !== "attachments"
            ? { ...step, status: step.status === "skipped" ? "skipped" : "done", rate: null }
            : {
                ...step,
                status: "running",
                unit: "documents",
                done,
                total: 5_000,
                started_at: "2026-10-20T01:14:00Z",
                seconds: 30,
                rate,
                eta_seconds: eta,
              },
        ),
      },
    },
  });

  /** The running step's detail, chosen at first beside the run's steps. */
  async function attachmentsStep(): Promise<string> {
    const detail = await screen.findByRole("region", { name: "Gewählter Schritt" });
    expect(within(detail).getByRole("heading").textContent).toBe("Text aus Anhängen lesen");
    return detail.querySelector("p")!.textContent!;
  }

  it("shows the attachments step with its progress, rate and estimated remaining time", async () => {
    renderApp("/import", backend(attachmentsRun(1_200, 40, 95)));
    expect(await attachmentsStep()).toBe(
      "1.200 von 5.000 Dokumenten · 40 Dokumente/s · Restzeit geschätzt 2 min · läuft seit 31 s",
    );
    const bar = screen.getByRole("progressbar", { name: "Text aus Anhängen lesen" });
    expect(bar.getAttribute("aria-valuenow")).toBe("24");
  });

  it("shows the step before its rate is known", async () => {
    renderApp("/import", backend(attachmentsRun(0, null, null)));
    expect(await attachmentsStep()).toBe("0 von 5.000 Dokumenten · läuft seit 31 s");
  });

  it("shows a slow rate with a decimal", async () => {
    renderApp("/import", backend(attachmentsRun(20, 0.4, 12_450)));
    expect(await attachmentsStep()).toBe(
      "20 von 5.000 Dokumenten · 0,4 Dokumente/s · Restzeit geschätzt 3 h 28 min · läuft seit 31 s",
    );
  });

  it("counts attachments and documents by text status, each leading to its list", async () => {
    renderApp("/import?tab=ergebnis");
    const tiles = await screen.findByRole("list", { name: "Kennzahlen des Archivs" });
    const attachments = within(tiles).getByText("118.204");
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
      "/import?tab=ergebnis",
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
      "/import?tab=ergebnis",
      backend(importStatus, { ...importSummary, attachments: 0, documents: noDocuments }),
    );
    expect(await screen.findByText("keine Anhänge")).toBeTruthy();
    expect(screen.getByText("Noch keine Anhänge im Archiv.")).toBeTruthy();
  });

  it("notes documents waiting for the next import", async () => {
    renderApp(
      "/import?tab=ergebnis",
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
