import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DkimKeysJob, ImportStatus } from "../../api/types";
import {
  importStatusPaused,
  keysJobRunning,
  manualKey,
  reconstructedKey,
  s2019Name,
} from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const PATH = `/import/selektoren/${s2019Name}`;

/** The fixture backend with no run alive until a key run starts. */
function backend() {
  let status: ImportStatus = { ...importStatusPaused, keys_job: null };
  return (call: ApiCall): unknown => {
    if (call.method === "POST" && call.url.pathname === "/api/dkim/keys/run") {
      const job = fixtureApi(call) as Response;
      const started = {
        ...keysJobRunning,
        options: { ...keysJobRunning.options, ...(call.body as object) },
      };
      status = { ...status, keys_job: started as DkimKeysJob };
      return job;
    }
    return call.url.pathname === "/api/import/status" ? status : fixtureApi(call);
  };
}

const posts = (calls: ApiCall[], path: string) =>
  calls.filter((call) => call.method === "POST" && call.url.pathname === path);

function section(title: string | RegExp): HTMLElement {
  return screen.getByRole("heading", { name: title }).closest("section")!;
}

const keyBlock = (sha256: string) => screen.getByRole("listitem", { name: `Schlüssel ${sha256}` });

afterEach(() => {
  Reflect.deleteProperty(navigator, "clipboard"); // jsdom has none
});

describe("selector page", () => {
  it("shows today's DNS answer, the figures and the latest mails", async () => {
    renderApp(PATH, backend());
    expect(await screen.findByRole("heading", { level: 1, name: s2019Name })).toBeTruthy();
    expect(document.title).toBe(`${s2019Name} · Mailrobbe`);
    const crumbs = screen.getByRole("navigation", { name: "Pfad" });
    expect(
      within(crumbs).getByRole("link", { name: "Gelöschte Selektoren" }).getAttribute("href"),
    ).toBe("/import/selektoren");
    const fact = (term: string) =>
      screen.getByText(term, { selector: "dt" }).parentElement!.querySelector("dd")!.textContent;
    expect(fact("DNS heute")).toBe("nicht im DNS · abgefragt 20.10.2026 03:14");
    expect(fact("Signaturen")).toBe("Signatur stimmig412Schlüssel nicht abrufbar3");

    const tiles = within(screen.getByRole("list", { name: "Kennzahlen" }))
      .getAllByRole("listitem")
      .map((tile) => tile.textContent);
    expect(tiles).toEqual([
      "415 Signaturenohne Duplikate",
      "415 Mailsmit dieser Signatur",
      "415 RSA-Signaturenrekonstruierbar",
      "11.02.2019 – 30.12.2020 Zeitraumerste bis letzte Signatur (t=)",
    ]);

    // keys, lookups and mails each have a tab, the keys first
    const tabs = screen.getByRole("tablist", { name: "Bereiche des Selektors" });
    expect(
      within(tabs)
        .getAllByRole("tab")
        .map((tab) => tab.textContent),
    ).toEqual(["Schlüssel2", "Abfragen3", "Mails415"]);
    fireEvent.click(within(tabs).getByRole("tab", { name: /^Mails/ }));
    const mails = section("Mails, neueste zuerst");
    const rows = within(mails).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual([
      "30.12.2020 18:00Jahresabschluss 2020 – UnterlagenAnna KellerSignatur stimmigrekonstruiert",
      "02.11.2020 11:12AW: SpendenquittungenLukas VogtSchlüssel nicht abrufbarVorhandene Schlüssel passen nicht–",
      "11.02.2019 09:00(kein Betreff)–Signatur stimmig(Signatur 2)rekonstruiert",
    ]);
    expect(
      within(mails)
        .getByRole("link", { name: "Jahresabschluss 2020 – Unterlagen" })
        .getAttribute("href"),
    ).toBe("/mails/170311");
  });

  it("shows each key with its origin and evidence", async () => {
    renderApp(PATH, backend());
    await screen.findByRole("heading", { level: 1, name: s2019Name });
    expect(screen.getByRole("heading", { name: "Schlüssel aus anderen Quellen (2)" })).toBeTruthy();

    // The manual key: documented, verified nothing yet, with the editor's evidence.
    const manual = keyBlock(manualKey.key_sha256);
    expect(within(manual).getAllByText("dokumentiert")).toHaveLength(2);
    expect(within(manual).getByText("RSA · 1.024 Bit")).toBeTruthy();
    expect(within(manual).getByText("4b7a2c9d0e1f3a5b…").getAttribute("title")).toBe(
      manualKey.key_sha256,
    );
    expect(within(manual).getByText("0 Signaturen bestätigt")).toBeTruthy();
    expect(within(manual).getByText(/Er hat bisher keine Signatur bestätigt/)).toBeTruthy();
    expect(within(manual).getByText("Von Hand eingetragen")).toBeTruthy();
    expect(within(manual).getByText("eingetragen 21.10.2026 12:15 von Lena Vogt")).toBeTruthy();
    expect(within(manual).getByText("laut Quelle ab 01.03.2019")).toBeTruthy();
    const reference = within(manual).getByRole("link", {
      name: "https://wiki.nordlicht-gmbh.example/it/dkim",
    });
    expect(reference.getAttribute("target")).toBe("_blank");
    expect(reference.getAttribute("rel")).toBe("noreferrer noopener");
    expect(within(manual).getByText("Aus der IT-Dokumentation, Stand März 2019.")).toBeTruthy();
    const download = within(manual).getByRole("link", { name: "Antwort der Quelle herunterladen" });
    expect(download.getAttribute("href")).toBe("/api/dkim/lookups/502/raw");
    expect(download.hasAttribute("download")).toBe(true);
    expect(within(manual).getByText("47 KB")).toBeTruthy();

    // The reconstructed key: the signatures it was computed from lead to their mails.
    const reconstructed = keyBlock(reconstructedKey.key_sha256);
    expect(within(reconstructed).getAllByText("rekonstruiert")).toHaveLength(2);
    expect(within(reconstructed).getByText("RSA · 2.048 Bit")).toBeTruthy();
    expect(within(reconstructed).getByText("412 Signaturen bestätigt")).toBeTruthy();
    expect(within(reconstructed).queryByText(/keine Signatur bestätigt/)).toBeNull();
    expect(within(reconstructed).getByText("berechnet 21.10.2026 11:38")).toBeTruthy();
    expect(within(reconstructed).getByText("Berechnet aus 2 Signaturen:")).toBeTruthy();
    expect(
      within(reconstructed).getByRole("link", { name: "Mail #152004" }).getAttribute("href"),
    ).toBe("/mails/152004");
    expect(
      within(reconstructed).getByText("Mail nicht mehr im Archiv (SHA-256 07aa1e2b3c4d5e6f…)"),
    ).toBeTruthy();
    expect(within(reconstructed).queryByText("Antwort der Quelle herunterladen")).toBeNull();
    expect(within(reconstructed).getByText(reconstructedKey.record)).toBeTruthy();
  });

  it("lists every lookup with its answer", async () => {
    renderApp(PATH, backend());
    await screen.findByRole("heading", { level: 1, name: s2019Name });
    fireEvent.click(screen.getByRole("tab", { name: /^Abfragen/ }));
    const lookups = section("Abfragen (3)");
    const rows = within(lookups).getAllByRole("row").slice(1);
    expect(
      rows.map((row) =>
        within(row)
          .getAllByRole("cell")
          .map((cell) => cell.textContent),
      ),
    ).toEqual([
      [
        "21.10.2026 12:30",
        "ZK-Email-Archiv",
        "https://archive.zk.email/api/key?domain=nordlicht-gmbh.example",
        "nichts gefunden HTTP 200",
        "0",
        "Herunterladen (2 B)",
      ],
      [
        "21.10.2026 12:15Lena Vogt",
        "Von Hand eingetragen",
        s2019Name,
        "gefunden",
        "1",
        "Herunterladen (47 KB)",
      ],
      [
        "21.10.2026 11:38",
        "Rekonstruktion",
        s2019Name,
        "gefundenmodulus from 2 signatures, e=65537",
        "1",
        "–",
      ],
    ]);
    expect(
      within(rows[0]).getByRole("link", { name: "Herunterladen (2 B)" }).getAttribute("href"),
    ).toBe("/api/dkim/lookups/503/raw");
  });

  it("copies a key's whole SHA-256", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderApp(PATH, backend());
    await screen.findByRole("heading", { level: 1, name: s2019Name });
    const block = keyBlock(reconstructedKey.key_sha256);
    fireEvent.click(
      within(block).getByRole("button", {
        name: `SHA-256 ${reconstructedKey.key_sha256} kopieren`,
      }),
    );
    expect(await within(block).findByText("Kopiert")).toBeTruthy();
    expect(writeText).toHaveBeenCalledWith(reconstructedKey.key_sha256);
  });

  it("starts a reconstruction and a check for this name and shows the run", async () => {
    const { calls } = renderApp(PATH, backend());
    await screen.findByRole("heading", { level: 1, name: s2019Name });
    fireEvent.click(screen.getByRole("button", { name: "Schlüssel rekonstruieren" }));
    expect(await screen.findByText("Rekonstruktion läuft")).toBeTruthy();
    expect(posts(calls, "/api/dkim/keys/run").map((call) => call.body)).toEqual([
      { task: "reconstruct", names: [s2019Name] },
    ]);
    // Another run cannot start beside it.
    const check = within(keyBlock(manualKey.key_sha256)).getByRole("button", {
      name: "Signaturen prüfen",
    });
    expect(check.hasAttribute("disabled")).toBe(true);
    expect(
      screen.getByRole("button", { name: "Schlüssel rekonstruieren" }).getAttribute("title"),
    ).toBe("Es läuft gerade eine Schlüsselsuche.");
  });

  it("checks the mails of a key that verified nothing yet", async () => {
    const { calls } = renderApp(PATH, backend());
    await screen.findByRole("heading", { level: 1, name: s2019Name });
    fireEvent.click(
      within(keyBlock(manualKey.key_sha256)).getByRole("button", { name: "Signaturen prüfen" }),
    );
    await waitFor(() => expect(posts(calls, "/api/dkim/keys/run")).toHaveLength(1));
    expect(posts(calls, "/api/dkim/keys/run")[0].body).toEqual({
      task: "check",
      names: [s2019Name],
    });
    expect(await screen.findByText("Prüfung mit den gefundenen Schlüsseln läuft")).toBeTruthy();
  });

  it("does not offer a reconstruction with fewer than two RSA signatures", async () => {
    renderApp(PATH, (call) =>
      call.url.pathname === `/api/dkim/selectors/${s2019Name}`
        ? { ...(fixtureApi(call) as object), rsa_signatures: 1 }
        : backend()(call),
    );
    await screen.findByRole("heading", { level: 1, name: s2019Name });
    const button = screen.getByRole("button", { name: "Schlüssel rekonstruieren" });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(button.getAttribute("title")).toBe(
      "Dafür braucht es mindestens zwei verschiedene RSA-Signaturen dieses Selektors.",
    );
  });

  it("says when a name has no signatures", async () => {
    renderApp("/import/selektoren/alt._domainkey.nirgends.example", backend());
    expect(await screen.findByText("Diesen Selektor gibt es nicht.")).toBeTruthy();
    expect(
      screen.getByText(
        "Keine Signatur im Archiv nennt den Schlüsselnamen „alt._domainkey.nirgends.example“.",
      ),
    ).toBeTruthy();
  });
});
