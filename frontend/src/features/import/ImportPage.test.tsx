import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { ErrorCode, ImportJob, ImportStatus, ImportSummary } from "../../api/types";
import { formatBytes, formatPercent } from "../../lib/format";
import {
  dkimJobRunning,
  importJob,
  importStatus,
  importStatusEmpty,
  importStatusPaused,
  importSummary,
} from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

/** The fixture backend with a status the test changes; answer handles calls first when it
 *  returns something. */
function backend(initial: ImportStatus, answer?: (call: ApiCall) => unknown) {
  let status = initial;
  return {
    set: (next: ImportStatus) => {
      status = next;
    },
    api: (call: ApiCall): unknown => {
      const custom = answer?.(call);
      if (custom !== undefined) return custom;
      return call.url.pathname === "/api/import/status" ? status : fixtureApi(call);
    },
  };
}

const withJob = (patch: Partial<ImportJob>): ImportStatus => ({
  ...importStatusPaused,
  import_job: { ...importStatusPaused.import_job!, ...patch },
});
const posts = (calls: ApiCall[], path: string) =>
  calls.filter((call) => call.method === "POST" && call.url.pathname === path);
const button = (name: string | RegExp) => screen.getByRole("button", { name });
const apiError = (status: number, code: ErrorCode, message = "refused") =>
  Response.json({ detail: { code, message } }, { status });

async function heading(name: string) {
  return screen.findByRole("heading", { level: 1, name });
}

function figures(): string[] {
  const list = screen.getByRole("list", { name: "Importfortschritt" });
  return within(list)
    .getAllByRole("listitem")
    .map((item) => item.textContent!);
}

afterEach(() => {
  vi.useRealTimers();
});

describe("run card", () => {
  it("shows a running import with workers, throughput and remaining time", async () => {
    renderApp("/import");
    await heading("Import läuft");
    expect(document.title).toBe("Import · Mailrobbe");
    expect(screen.getByText("8 Worker aktiv")).toBeTruthy();
    const { totals } = importStatus;
    expect(
      screen.getByText(`Quelle: /data/mbox · 72 Dateien · ${formatBytes(totals.size_bytes)}`),
    ).toBeTruthy();
    expect(screen.getByText("Gestartet 20.10.2026 01:02 · Restzeit ca. 1 h 40 min")).toBeTruthy();
    const percent = Math.floor((totals.bytes_done / totals.size_bytes) * 100);
    expect(
      screen.getByRole("progressbar", { name: "Gesamtfortschritt" }).getAttribute("aria-valuenow"),
    ).toBe(String(percent));
    expect(await screen.findByText(/Duplikate/)).toBeTruthy();
    expect(figures()).toEqual([
      `313.491 von ca. 430.996 Mails geparst (${percent} %)`,
      "1.420 Mails/s Parsing",
      "1.397 Mails/s DKIM",
      "1.912 Duplikate (Message-ID + Hash)",
      "58 Importfehler",
    ]);

    expect(button("Pausieren")).toHaveProperty("disabled", false);
    for (const name of [/DKIM für/, "Verzeichnis neu scannen"]) {
      expect(button(name)).toHaveProperty("disabled", true);
      expect(button(name).title).toMatch(/^Es läuft gerade ein Import/);
    }
    expect(screen.queryByRole("button", { name: /Import (starten|fortsetzen)/ })).toBeNull();
  });

  it("names the phase of a live import", async () => {
    const status = {
      ...importStatus,
      import_job: {
        ...importJob,
        phase: "headers" as const,
        progress: {
          ...importJob.progress,
          workers: 0,
          headers_done: 81_200,
          headers_total: 292_746,
        },
      },
    };
    renderApp("/import", backend(status).api);
    await heading("Import läuft");
    expect(
      screen.getByText(
        "Header älterer Mails werden neu gelesen (Verteiler und Automaten), 81.200 von 292.746",
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/Worker aktiv/)).toBeNull();
  });

  it("pauses the import and waits for it to stop", async () => {
    const server = backend(importStatus, (call) => {
      if (call.url.pathname === "/api/import/pause") {
        server.set({ ...importStatus, import_job: { ...importJob, stop_requested: true } });
      }
      return undefined;
    });
    const { calls } = renderApp("/import", server.api);
    await heading("Import läuft");

    fireEvent.click(button("Pausieren"));
    expect(await heading("Import wird pausiert …")).toBeTruthy();
    expect(posts(calls, "/api/import/pause")).toHaveLength(1);
    expect(button("Wird pausiert …")).toHaveProperty("disabled", true);
  });

  it("offers to resume a paused import and leaves out the rates", async () => {
    renderApp("/import", backend(importStatusPaused).api);
    await heading("Import pausiert");
    expect(screen.getByText("Gestartet 20.10.2026 01:02 · pausiert 20.10.2026 03:15")).toBeTruthy();
    await screen.findByText(/Duplikate/);
    expect(figures().some((text) => text.includes("Mails/s"))).toBe(false);
    for (const name of ["Import fortsetzen", /DKIM für/, "Verzeichnis neu scannen"]) {
      expect(button(name)).toHaveProperty("disabled", false);
    }
    expect(button(/DKIM für/).title).toBe(
      "Prüft Mails ohne Ergebnis, mit „Schlüssel fehlt“ oder mit DNS-Fehler erneut.",
    );
  });

  it("starts anew after a finished import", async () => {
    const files = importStatus.files.map((file) => ({
      ...file,
      status: "done" as const,
      bytes_done: file.size_bytes,
      worker_id: null,
    }));
    const status = {
      ...withJob({ status: "done", stop_requested: false }),
      files,
      totals: { ...importStatus.totals, done: 72, running: 0, pending: 0, error: 0 },
    };
    renderApp("/import", backend(status).api);
    await heading("Import fertig");
    expect(button("Import starten")).toBeTruthy();
  });

  it("shows a run whose process died as aborted", async () => {
    renderApp(
      "/import",
      backend(withJob({ status: "running", finished_at: null, message: null })).api,
    );
    await heading("Import abgebrochen");
    expect(screen.getByText(/Der Importprozess endete, ohne sein Ende zu melden/)).toBeTruthy();
    expect(screen.getByText(/letzte Meldung 20\.10\.2026 03:15/)).toBeTruthy();
    expect(button("Import fortsetzen")).toBeTruthy();
  });

  it("shows the message of a failed run", async () => {
    renderApp(
      "/import",
      backend(withJob({ status: "failed", message: "database connection lost" })).api,
    );
    await heading("Import abgebrochen");
    expect(screen.getByText("database connection lost")).toBeTruthy();
    expect(screen.queryByText(/ohne sein Ende zu melden/)).toBeNull();
  });

  it("explains an empty archive and offers the scan", async () => {
    const { calls } = renderApp("/import", backend(importStatusEmpty).api);
    await heading("Noch kein Import");
    expect(screen.getByText("Noch keine MBOX-Dateien")).toBeTruthy();
    expect(
      screen.getByText("Lege MBOX-Dateien in das Verzeichnis /data/mbox und scanne es neu."),
    ).toBeTruthy();
    expect(button("Import starten")).toBeTruthy();
    const scans = screen.getAllByRole("button", { name: "Verzeichnis neu scannen" });
    expect(scans).toHaveLength(2);
    fireEvent.click(scans[1]);
    await waitFor(() => expect(posts(calls, "/api/import/rescan")).toHaveLength(1));
  });

  it("warns when the server cannot read the MBOX directory", async () => {
    renderApp("/import", backend({ ...importStatusPaused, mbox_dir_ok: false }).api);
    await heading("Import pausiert");
    expect(screen.getByText(/Das MBOX-Verzeichnis ist für den Server nicht lesbar/)).toBeTruthy();
    for (const name of ["Import fortsetzen", "Verzeichnis neu scannen"]) {
      expect(button(name)).toHaveProperty("disabled", true);
      expect(button(name).title).toBe("Das MBOX-Verzeichnis ist für den Server nicht lesbar.");
    }
    expect(button(/DKIM für/)).toHaveProperty("disabled", false);
  });

  it("explains a status that cannot be loaded", async () => {
    renderApp("/import", (call) =>
      call.url.pathname === "/api/import/status"
        ? Response.json({ detail: "boom" }, { status: 500 })
        : fixtureApi(call),
    );
    expect(await screen.findByText("Der Importstatus konnte nicht geladen werden.")).toBeTruthy();
    expect(button("Erneut versuchen")).toBeTruthy();
  });
});

describe("actions", () => {
  it("starts with the changed settings and shows the defaults again", async () => {
    const server = backend(importStatusPaused, (call) => {
      if (call.url.pathname === "/api/import/start") server.set(importStatus);
      return undefined;
    });
    const { calls } = renderApp("/import", server.api);
    await heading("Import pausiert");

    const workers = screen.getByRole("spinbutton", { name: "Parallele Worker" });
    expect(workers).toHaveProperty("value", "8");
    fireEvent.change(workers, { target: { value: "4" } });
    fireEvent.change(screen.getByRole("spinbutton", { name: "Anhang-Limit für Hash" }), {
      target: { value: "20" },
    });
    const dns = screen.getByRole("textbox", { name: "DNS-Resolver" });
    expect(dns).toHaveProperty("placeholder", "System-Resolver");
    fireEvent.change(dns, { target: { value: "9.9.9.9 " } });
    fireEvent.click(button("Import fortsetzen"));

    await heading("Import läuft");
    expect(posts(calls, "/api/import/start").map((call) => call.body)).toEqual([
      { workers: 4, attachment_hash_limit: 20 * 1024 ** 2, dkim_nameservers: "9.9.9.9" },
    ]);
    expect(button("Pausieren")).toBeTruthy();
    await waitFor(() => expect(workers).toHaveProperty("value", "8"));
    expect(dns).toHaveProperty("value", "1.1.1.1, 9.9.9.9");
  });

  it("keeps an edited setting while the status is polled", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { calls } = renderApp("/import");
    await heading("Import läuft");
    const workers = screen.getByRole("spinbutton", { name: "Parallele Worker" });
    fireEvent.change(workers, { target: { value: "12" } });
    const before = calls.filter((call) => call.url.pathname === "/api/import/status").length;
    await act(() => vi.advanceTimersByTimeAsync(2_100));
    expect(calls.filter((call) => call.url.pathname === "/api/import/status").length).toBe(
      before + 1,
    );
    expect(workers).toHaveProperty("value", "12");
  });

  it("refuses a setting it cannot send", async () => {
    const { calls } = renderApp("/import", backend(importStatusPaused).api);
    await heading("Import pausiert");
    fireEvent.change(screen.getByRole("spinbutton", { name: "Parallele Worker" }), {
      target: { value: "0" },
    });
    fireEvent.click(button("Import fortsetzen"));
    expect(screen.getByRole("alert").textContent).toBe(
      "Eine Einstellung ist ungültig: Parallele Worker: eine ganze Zahl von 1 bis 64.",
    );
    expect(posts(calls, "/api/import/start")).toEqual([]);
  });

  it.each([
    [409, "job_running", "Es läuft bereits ein Import oder eine DKIM-Prüfung."],
    [409, "mbox_dir_missing", "Das MBOX-Verzeichnis ist für den Server nicht lesbar."],
    [400, "invalid_option", "Eine Einstellung ist ungültig: dkim_nameservers: not an IP address"],
    [
      500,
      "job_failed",
      "Der Import konnte nicht starten. Details stehen im Server-Log (docker compose logs backend).",
    ],
  ] as const)("explains a refused start (%s %s)", async (status, code, text) => {
    renderApp(
      "/import",
      backend(importStatusPaused, (call) =>
        call.url.pathname === "/api/import/start"
          ? apiError(status, code, "dkim_nameservers: not an IP address")
          : undefined,
      ).api,
    );
    await heading("Import pausiert");
    fireEvent.click(button("Import fortsetzen"));
    expect((await screen.findByRole("alert")).textContent).toBe(text);

    fireEvent.click(button("Hinweis schließen"));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("explains a pause with nothing to stop", async () => {
    renderApp(
      "/import",
      backend(importStatus, (call) =>
        call.url.pathname === "/api/import/pause" ? apiError(409, "no_job") : undefined,
      ).api,
    );
    await heading("Import läuft");
    fireEvent.click(button("Pausieren"));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Es läuft gerade nichts, das angehalten werden könnte.",
    );
  });

  it("rescans the directory and lists what it found", async () => {
    const { calls } = renderApp("/import", backend(importStatusPaused).api);
    await heading("Import pausiert");
    fireEvent.click(button("Verzeichnis neu scannen"));

    const summary = await screen.findByText(/^74 Dateien gefunden/);
    const notice = summary.closest<HTMLElement>("[role=status]")!;
    expect(posts(calls, "/api/import/rescan").map((call) => call.body)).toEqual([{}]);
    expect(summary.textContent).toBe(
      "74 Dateien gefunden, 2 neu, 1 geändert (werden neu importiert), 1 nicht lesbar; 19 zu importieren",
    );
    expect(
      within(notice)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "Neu: export-2026-Q1.mbox, export-2026-Q2.mbox",
      "Geändert: export-2019-Q4.mbox (first MiB changed)",
      "Nicht lesbar: export-2026-Q3.mbox ([Errno 13] Permission denied)",
    ]);
  });

  it("runs the DKIM recheck and stops it", async () => {
    const server = backend(importStatusPaused, (call) => {
      if (call.url.pathname === "/api/dkim/recheck") {
        server.set({ ...importStatusPaused, dkim_job: dkimJobRunning });
      }
      if (call.url.pathname === "/api/dkim/recheck/stop") {
        server.set({
          ...importStatusPaused,
          dkim_job: { ...dkimJobRunning, stop_requested: true },
        });
      }
      return undefined;
    });
    const { calls } = renderApp("/import", server.api);
    await heading("Import pausiert");
    fireEvent.click(button(/DKIM für/));

    expect(
      await screen.findByText(
        "DKIM-Prüfung läuft: 12.408 von 64.790 Mails · 312 Mails/s · Restzeit ca. 3 min",
      ),
    ).toBeTruthy();
    expect(posts(calls, "/api/dkim/recheck").map((call) => call.body)).toEqual([{}]);
    for (const name of ["Import fortsetzen", /DKIM für/, "Verzeichnis neu scannen"]) {
      expect(button(name)).toHaveProperty("disabled", true);
      expect(button(name).title).toBe("Es läuft gerade eine DKIM-Prüfung.");
    }

    fireEvent.click(button("DKIM-Prüfung abbrechen"));
    expect(await screen.findByText("DKIM-Prüfung wird abgebrochen …")).toBeTruthy();
    expect(button("Wird abgebrochen …")).toHaveProperty("disabled", true);
    expect(posts(calls, "/api/dkim/recheck/stop")).toHaveLength(1);
  });

  it("tells how the latest DKIM run ended", async () => {
    const ended = {
      ...dkimJobRunning,
      status: "stopped" as const,
      alive: false,
      finished_at: "2026-10-20T01:24:10Z",
    };
    renderApp("/import", backend({ ...importStatusPaused, dkim_job: ended }).api);
    expect(
      await screen.findByText(
        "DKIM-Prüfung abgebrochen: 12.408 von 64.790 Mails geprüft · 20.10.2026 03:24",
      ),
    ).toBeTruthy();
  });

  it("loads everything again when a run ends", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const server = backend(importStatus);
    const { calls } = renderApp("/import", server.api);
    await heading("Import läuft");
    await screen.findByText(/Duplikate/);
    const count = (path: string) => calls.filter((call) => call.url.pathname === path).length;
    expect(count("/api/stats")).toBe(1);
    expect(count("/api/import/summary")).toBe(1);

    server.set(withJob({ status: "done", stop_requested: false }));
    await act(() => vi.advanceTimersByTimeAsync(2_100));
    await heading("Import fertig");
    await waitFor(() => expect(count("/api/stats")).toBe(2));
    expect(count("/api/import/summary")).toBe(2);
  });
});

describe("file table", () => {
  it("lists running, failed and waiting files and collapses the done ones", async () => {
    renderApp("/import");
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2 + 1 + 8 + 1 + 15);

    const cells = (row: HTMLElement) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent);
    expect(cells(rows[3])).toEqual([
      "export-2020-Q1.mbox",
      "4,0 GB",
      "4.926",
      "",
      "Läuft · W1",
      "0",
    ]);
    expect(cells(rows[11])).toEqual(["export-2022-Q1.mbox", "4,0 GB", "3.152", "", "Fehler", "53"]);
    expect(cells(rows[12])).toEqual(["export-2022-Q2.mbox", "3,8 GB", "–", "", "Wartet", "–"]);
    expect(
      within(rows[3])
        .getByRole("progressbar", { name: "Fortschritt export-2020-Q1.mbox" })
        .getAttribute("aria-valuenow"),
    ).toBe("81"); // never rounded up to more than is done

    fireEvent.click(within(rows[2]).getByRole("button", { name: "46 weitere fertig" }));
    expect(within(table).getAllByRole("row")).toHaveLength(1 + 48 + 1 + 8 + 1 + 15);
    fireEvent.click(within(table).getByRole("button", { name: "Fertige einklappen" }));
    expect(within(table).getAllByRole("row")).toHaveLength(1 + 27);
  });

  it("filters by status, with the counts in the options", async () => {
    renderApp("/import");
    const select = await screen.findByRole("combobox", { name: "Status" });
    expect(
      within(select)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["Alle 72", "Fertig 48", "Läuft 8", "Fehler 1", "Wartet 15"]);

    fireEvent.change(select, { target: { value: "running" } });
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(1 + 8);
    fireEvent.change(select, { target: { value: "done" } });
    expect(within(table).getAllByRole("row")).toHaveLength(1 + 48);
  });

  it("opens the error log of a file", async () => {
    const { calls } = renderApp("/import");
    fireEvent.click(
      await screen.findByRole("button", { name: "53 Fehler in export-2022-Q1.mbox anzeigen" }),
    );
    const dialog = await screen.findByRole("dialog", { name: "Fehlerprotokoll" });
    expect(within(dialog).getByRole("combobox", { name: "Datei" })).toHaveProperty("value", "157");
    expect(await within(dialog).findByText("50 von 53 Fehlern")).toBeTruthy();
    const request = calls.find(
      (call) =>
        call.url.pathname === "/api/import/errors" && call.url.searchParams.has("mbox_file"),
    );
    expect(request?.url.searchParams.get("mbox_file")).toBe("157");
  });
});

describe("archive figures", () => {
  it("shows sizes, DNS cache, persons and edges", async () => {
    renderApp("/import");
    const tiles = await screen.findByRole("list", { name: "Kennzahlen des Archivs" });
    const texts = within(tiles)
      .getAllByRole("listitem")
      .map((tile) => tile.textContent);
    const share = formatPercent(importSummary.db_size_bytes / importSummary.raw_size_bytes);
    expect(texts.slice(0, 4)).toEqual([
      `DB-Größe (Metadaten + Index)9,8 GBca. ${share} der Rohdaten`,
      "Volltextindex4,1 GBBetreff + Textteil",
      "DNS-Cache6.218Selector-Einträge · 99,4 % Cache-Treffer",
      "Personen erkannt8.942312 Alias-Vorschläge offen",
    ]);
    expect(texts[4]).toMatch(/^Kantentabelle61\.207Personenpaare · aktualisiert /);
    expect(
      within(tiles).getByRole("link", { name: "312 Alias-Vorschläge offen" }).getAttribute("href"),
    ).toBe("/personen?tab=vorschlaege");
  });

  it("shows the DKIM result with the most frequent reasons", async () => {
    const summary: ImportSummary = {
      ...importSummary,
      dkim: { ...importSummary.dkim, temp_error: 41 },
    };
    renderApp("/import", (call) =>
      call.url.pathname === "/api/import/summary" ? summary : fixtureApi(call),
    );
    const card = (await screen.findByRole("heading", { name: "DKIM-Ergebnis bisher" })).closest(
      "section",
    )!;
    expect(
      within(card)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "Gültig190.412",
      "Ungültig2.203",
      "Schlüssel fehlt64.790",
      "Unsigniert35.341",
      "DNS-Fehler41",
    ]);
    expect(within(card).getByRole("img").getAttribute("aria-label")).toMatch(
      /^Anteile: 65 % Gültig, 1 % Ungültig, 22 % Schlüssel fehlt, 12 % Unsigniert, 0 % DNS-Fehler$/,
    );
    expect(
      within(card).getByText(
        "Häufigste Ungültig-Gründe: Body nach dem Signieren verändert (1.640), Signatur passt nicht (Header verändert oder anderer Schlüssel) (380), Schlüssel widerrufen (leeres p=) (183).",
      ),
    ).toBeTruthy();
    expect(within(card).getByText("Stand 20.10.2026 03:12")).toBeTruthy();
  });
});

describe("error log", () => {
  it("lists the newest five and opens all of them, a page at a time", async () => {
    const { calls } = renderApp("/import");
    const card = (await screen.findByRole("heading", { name: "Fehlerprotokoll" })).closest(
      "section",
    )!;
    const entries = await within(card).findAllByRole("listitem");
    expect(entries).toHaveLength(5);
    expect(entries[0].textContent).toBe(
      "03:11:42export-2022-Q1.mbox @ 2.104.881.900: Datei nicht lesbar[Errno 5] Input/output error while reading at byte 2104881900",
    );
    expect(within(entries[2]).getByText(/DKIM-Prüfung gescheitert/)).toBeTruthy();

    fireEvent.click(within(card).getByRole("button", { name: "Alle 58" }));
    const dialog = await screen.findByRole("dialog", { name: "Fehlerprotokoll" });
    expect(await within(dialog).findByText("50 von 58 Fehlern")).toBeTruthy();
    expect(within(dialog).getAllByRole("listitem")[0].textContent).toMatch(
      /^20\.10\.2026 03:11:42export-2022-Q1\.mbox/,
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Weitere laden" }));
    expect(await within(dialog).findByText("58 von 58 Fehlern")).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Weitere laden" })).toBeNull();
    expect(
      calls.filter((call) => call.url.searchParams.get("cursor") === "50").length,
    ).toBeGreaterThan(0);

    const kind = within(dialog).getByRole("combobox", { name: "Art" });
    expect(within(kind).getAllByRole("option")[0].textContent).toBe("Alle Arten (58)");
    expect(within(kind).getByRole("option", { name: "Datei nicht lesbar (1)" })).toBeTruthy();
    fireEvent.change(kind, { target: { value: "io" } });
    expect(await within(dialog).findByText("1 von 1 Fehlern")).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Schließen" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says when there are no errors", async () => {
    renderApp("/import", (call) =>
      call.url.pathname === "/api/import/errors"
        ? { items: [], next_cursor: null, total: 0, kinds: {} }
        : fixtureApi(call),
    );
    expect(await screen.findByText("Der Import hat keine Fehler gemeldet.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /^Alle/ })).toBeNull();
  });
});
