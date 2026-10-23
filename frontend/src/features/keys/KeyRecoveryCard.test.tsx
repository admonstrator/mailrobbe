import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DkimKeysJob, ErrorCode, ImportStatus, KeyArchivePreview } from "../../api/types";
import {
  archivePreview,
  archivePreviewPublic,
  importStatusPaused,
  keysJobDone,
  keysJobRunning,
} from "../../test/fixtures";
import { fixtureApi, renderElement, type ApiCall } from "../../test/render";
import { fetchRequest } from "./ArchivePreviewDialog";
import { KeyRecoveryCard } from "./KeyRecoveryCard";

/** The fixture backend with no import alive and a key run the test changes; answer handles a
 *  call first when it returns something. */
function backend(job: DkimKeysJob | null, answer?: (call: ApiCall) => unknown) {
  let status: ImportStatus = { ...importStatusPaused, keys_job: job };
  return {
    set: (next: DkimKeysJob | null) => {
      status = { ...status, keys_job: next };
    },
    api: (call: ApiCall): unknown => {
      const custom = answer?.(call);
      if (custom !== undefined) return custom;
      return call.url.pathname === "/api/import/status" ? status : fixtureApi(call);
    },
  };
}

const posts = (calls: ApiCall[], path: string) =>
  calls.filter((call) => call.method === "POST" && call.url.pathname === path);
const apiError = (status: number, code: ErrorCode, message = "refused") =>
  Response.json({ detail: { code, message } }, { status });
const card = () => screen.getByRole("region", { name: "Gelöschte Selektoren" });

function figure(term: string): string {
  const dt = within(card()).getByText(term, { selector: "dt" });
  return dt.parentElement!.querySelector("dd")!.textContent!;
}

describe("key recovery card", () => {
  it("shows what is missing, what was found and leads to the selector list", async () => {
    renderElement(<KeyRecoveryCard />, backend(null).api);
    await within(card()).findByText("Ohne Schlüssel");
    expect(figure("Ohne Schlüssel")).toBe("178 Selektoren · 8.622 Mails");
    expect(figure("davon rekonstruierbar")).toBe("164 Selektoren");
    expect(figure("Geklärt")).toBe("12 Selektoren");
    expect(figure("Signatur stimmig")).toBe("5.336 Mails");
    expect(figure("Gefundene Schlüssel")).toBe(
      "3 im DNS beobachtet · 1 dokumentiert · 11 rekonstruiert",
    );
    expect(figure("Aus dem DNS aufbewahrt")).toBe("2.417 Schlüssel");
    expect(
      within(card()).getByText(/1 Schlüssel teilt einen Primfaktor mit einem anderen/),
    ).toBeTruthy();
    expect(within(card()).getByText("Zuletzt gesucht 21.10.2026 12:30")).toBeTruthy();
    expect(
      within(card()).getByRole("link", { name: "Alle Selektoren ansehen" }).getAttribute("href"),
    ).toBe("/import/selektoren");
    for (const name of [
      "Schlüssel rekonstruieren",
      "Im Archiv suchen",
      "Schlüsselarchiv abfragen …",
    ]) {
      expect(within(card()).getByRole("button", { name }).hasAttribute("disabled")).toBe(false);
    }
  });

  it("starts a reconstruction and a search and shows the live run", async () => {
    const server = backend(null, (call) => {
      if (call.method === "POST") server.set({ ...keysJobRunning });
      return undefined;
    });
    const { calls } = renderElement(<KeyRecoveryCard />, server.api);
    await within(card()).findByText("Ohne Schlüssel");

    fireEvent.click(within(card()).getByRole("button", { name: "Schlüssel rekonstruieren" }));
    await within(card()).findByText("Rekonstruktion läuft");
    expect(posts(calls, "/api/dkim/keys/run").map((call) => call.body)).toEqual([
      { task: "reconstruct" },
    ]);
    const run = within(card()).getByRole("group", { name: "Schlüsselsuche" });
    expect(within(run).getByText("· 4 Worker")).toBeTruthy();
    expect(within(run).getByText("Schlüssel werden aus Signaturen berechnet")).toBeTruthy();
    expect(within(run).getByText("164 Schlüsselnamen · 37 Schlüssel gefunden")).toBeTruthy();
    expect(within(run).getByText("gestartet 21.10.2026 11:30")).toBeTruthy();
    // One run at a time.
    const search = within(card()).getByRole("button", { name: "Im Archiv suchen" });
    expect(search.hasAttribute("disabled")).toBe(true);
    expect(search.getAttribute("title")).toBe("Es läuft gerade eine Schlüsselsuche.");

    server.set(keysJobDone);
    // A search is a run of its own once the reconstruction ended.
    await waitFor(
      () =>
        expect(
          within(card()).getByRole("button", { name: "Im Archiv suchen" }).hasAttribute("disabled"),
        ).toBe(false),
      { timeout: 4000 },
    );
    expect(
      within(card()).getByText(
        ": 164 Schlüsselnamen · 152 Schlüssel gefunden · 1 faktorisierbar · 9.859 Mails geprüft, 9.212 geändert",
        { exact: false },
      ),
    ).toBeTruthy();
    expect(within(card()).getByText("Rekonstruktion fertig")).toBeTruthy();
    fireEvent.click(within(card()).getByRole("button", { name: "Im Archiv suchen" }));
    await waitFor(() => expect(posts(calls, "/api/dkim/keys/run")).toHaveLength(2));
    expect(posts(calls, "/api/dkim/keys/run")[1].body).toEqual({ task: "search" });
  });

  it("stops a running run", async () => {
    const server = backend(keysJobRunning, (call) => {
      if (call.url.pathname === "/api/dkim/keys/run/stop") {
        server.set({ ...keysJobRunning, stop_requested: true });
      }
      return undefined;
    });
    const { calls } = renderElement(<KeyRecoveryCard />, server.api);
    fireEvent.click(await within(card()).findByRole("button", { name: "Anhalten" }));
    await within(card()).findByRole("button", { name: "Wird angehalten …" });
    expect(posts(calls, "/api/dkim/keys/run/stop")).toHaveLength(1);
    expect(within(card()).getByText("Rekonstruktion wird angehalten …")).toBeTruthy();
  });

  it("lists the steps of a running run with key names as their unit", async () => {
    renderElement(<KeyRecoveryCard />, backend(keysJobRunning).api);
    const step = await within(card()).findByText("Schlüssel rekonstruieren", { selector: "li *" });
    expect(step.closest("li")!.textContent).toContain(
      "41 von 164 Selektoren · 3,6 Selektoren/min · Restzeit geschätzt 34 min",
    );
  });

  it("says in German why a run did not start", async () => {
    const { api } = backend(null, (call) =>
      call.method === "POST" ? apiError(409, "job_running") : undefined,
    );
    renderElement(<KeyRecoveryCard />, api);
    await within(card()).findByText("Ohne Schlüssel");
    fireEvent.click(within(card()).getByRole("button", { name: "Schlüssel rekonstruieren" }));
    expect((await within(card()).findByRole("alert")).textContent).toBe(
      "Es läuft bereits ein Import, eine DKIM-Prüfung oder eine Schlüsselsuche. Bitte warten, bis sie fertig ist.",
    );
  });

  it("keeps the buttons off while an import runs", async () => {
    renderElement(<KeyRecoveryCard />); // the fixture status has a live import
    await waitFor(() =>
      expect(
        within(card())
          .getByRole("button", { name: "Schlüssel rekonstruieren" })
          .getAttribute("title"),
      ).toBe("Es läuft gerade ein Import."),
    );
    expect(
      within(card())
        .getByRole("button", { name: "Schlüssel rekonstruieren" })
        .hasAttribute("disabled"),
    ).toBe(true);
  });
});

describe("archive preview", () => {
  async function openPreview(preview?: KeyArchivePreview, answer?: (call: ApiCall) => unknown) {
    const server = backend(null, (call) => {
      if (preview && call.url.pathname === "/api/dkim/archive/preview") return preview;
      return answer?.(call);
    });
    const rendered = renderElement(<KeyRecoveryCard />, server.api);
    await within(card()).findByText("Ohne Schlüssel");
    fireEvent.click(within(card()).getByRole("button", { name: "Schlüsselarchiv abfragen …" }));
    return {
      ...rendered,
      dialog: await screen.findByRole("dialog", { name: "Schlüsselarchiv abfragen" }),
    };
  }

  it("lists the domains, says what goes out and fetches the chosen ones", async () => {
    const { dialog, calls } = await openPreview();
    await within(dialog).findByText("nordlicht-gmbh.example");
    expect(within(dialog).getByText("http://127.0.0.1:8200")).toBeTruthy();
    expect(
      within(dialog).getByText(
        "Mailrobbe schickt dem Archiv nur die Namen der angehakten Domains, eine Anfrage je Domain. Selektoren, Mails, Adressen und alles andere bleiben hier; hochgeladen wird nichts. Die Anfragen gehen nacheinander hinaus; ein angehaltener Lauf macht beim nächsten Start weiter.",
      ),
    ).toBeTruthy();
    const rows = within(dialog).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual([
      "nordlicht-gmbh.example46.21001.10.2026 12:00",
      "stadtwerke-beispiel.example21.904noch nie",
      "verein-nord.example11noch nie",
    ]);
    const boxes = within(dialog).getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes.map((box) => box.checked)).toEqual([true, true, true]);
    expect(within(dialog).getByText("3 von 3 Domains gewählt")).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("checkbox", { name: "stadtwerke-beispiel.example" }));
    expect(within(dialog).getByText("2 von 3 Domains gewählt")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Abfragen" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    // every domain but the one unchecked, without a list of all others (D107)
    expect(posts(calls, "/api/dkim/keys/run").map((call) => call.body)).toEqual([
      { task: "fetch", skip_domains: ["stadtwerke-beispiel.example"] },
    ]);
  });

  it("fetches every domain without a limit", async () => {
    const domains = Array.from({ length: 2_500 }, (_, index) => ({
      domain: `domain-${String(index).padStart(4, "0")}.example`,
      names: 1,
      mails: 2_500 - index,
      last_asked_at: null,
      done: false,
    }));
    const { dialog, calls } = await openPreview({ ...archivePreview, domains });
    expect(await within(dialog).findByText("2.500 von 2.500 Domains gewählt")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Abfragen" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(posts(calls, "/api/dkim/keys/run").map((call) => call.body)).toEqual([
      { task: "fetch" },
    ]);
  });

  it("goes on after an interrupted fetch", async () => {
    const [first, ...rest] = archivePreview.domains;
    const preview: KeyArchivePreview = {
      ...archivePreview,
      domains: [{ ...first!, done: true }, ...rest],
      continues: "2026-10-22T08:00:00Z",
    };
    const { dialog, calls } = await openPreview(preview);
    expect(
      await within(dialog).findByText(
        "Die Abfrage vom 22.10.2026 10:00 ist nicht zu Ende gelaufen. 1 Domain hat seither geantwortet und bleibt diesmal aus.",
      ),
    ).toBeTruthy();
    const boxes = within(dialog).getAllByRole("checkbox") as HTMLInputElement[];
    expect(boxes.map((box) => box.checked)).toEqual([false, true, true]);
    expect(within(dialog).getByText("01.10.2026 12:00 · beantwortet")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Abfragen" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(posts(calls, "/api/dkim/keys/run").map((call) => call.body)).toEqual([
      { task: "fetch" },
    ]);
  });

  it("sends nothing without a chosen domain", async () => {
    const { dialog } = await openPreview();
    await within(dialog).findByText("nordlicht-gmbh.example");
    fireEvent.click(within(dialog).getByRole("button", { name: "Keine" }));
    expect(within(dialog).getByText("0 von 3 Domains gewählt")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Abfragen" }).hasAttribute("disabled")).toBe(
      true,
    );
  });

  it("names the reserved domains it leaves out", async () => {
    const { dialog } = await openPreview(archivePreviewPublic);
    expect(await within(dialog).findByText("https://archive.zk.email")).toBeTruthy();
    expect(
      within(dialog).getByText(
        "Nicht gefragt, weil ihre Endung reserviert ist (.example, .test, …); solche Domains gehen nur an ein Archiv auf diesem Rechner: nordlicht-gmbh.example, stadtwerke-beispiel.example.",
      ),
    ).toBeTruthy();
    expect(within(dialog).queryAllByRole("checkbox")).toHaveLength(0);
    expect(within(dialog).getByRole("button", { name: "Abfragen" }).hasAttribute("disabled")).toBe(
      true,
    );
  });

  it("says when the archive is off and offers nothing", async () => {
    const { dialog } = await openPreview({ url: null, domains: [], skipped: [], continues: null });
    expect(
      await within(dialog).findByText(/Das Schlüsselarchiv ist in den Einstellungen abgeschaltet/),
    ).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Abfragen" })).toBeNull();
    fireEvent.click(within(dialog).getByRole("button", { name: "Schließen" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("shows a refusal of the fetch in the dialog", async () => {
    const { dialog } = await openPreview(undefined, (call) =>
      call.method === "POST" ? apiError(409, "archive_off") : undefined,
    );
    await within(dialog).findByText("nordlicht-gmbh.example");
    fireEvent.click(within(dialog).getByRole("button", { name: "Abfragen" }));
    expect((await within(dialog).findByRole("alert")).textContent).toBe(
      "Das Schlüsselarchiv ist in den Einstellungen abgeschaltet („off“).",
    );
  });
});

describe("fetchRequest", () => {
  const domain = (name: string, done = false) => ({
    domain: name,
    names: 1,
    mails: 1,
    last_asked_at: null,
    done,
  });
  const domains = [domain("a.example", true), domain("b.example"), domain("c.example")];

  it("asks every domain the interrupted fetch did not answer, less the unchecked", () => {
    expect(fetchRequest(domains, new Set(["a.example"]))).toEqual({ task: "fetch" });
    expect(fetchRequest(domains, new Set(["a.example", "c.example"]))).toEqual({
      task: "fetch",
      skip_domains: ["c.example"],
    });
  });

  it("names the domains when an answered one is checked again", () => {
    expect(fetchRequest(domains, new Set(["b.example"]))).toEqual({
      task: "fetch",
      domains: ["a.example", "c.example"],
    });
  });

  it("refuses lists longer than one request takes", () => {
    const many = Array.from({ length: 2_002 }, (_, index) => domain(`d${index}.example`));
    const half = new Set(many.slice(0, 1_001).map(({ domain: name }) => name));
    expect(fetchRequest(many, half)).toBeNull();
    expect(fetchRequest(many, new Set())).toEqual({ task: "fetch" });
  });
});
