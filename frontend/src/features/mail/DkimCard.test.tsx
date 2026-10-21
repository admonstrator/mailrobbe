import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mailDetailKeys } from "../../test/fixtures";
import { fixtureApi, renderApp } from "../../test/render";

const card = () => screen.getByRole("heading", { name: "DKIM-Prüfung" }).closest("section")!;

function signature(number: number): HTMLElement {
  return within(card()).getByRole("heading", { name: `Signatur ${number}` }).parentElement!;
}

describe("DKIM box", () => {
  it("names the key's origin and, for a reconstructed key, what it does not show", async () => {
    renderApp("/mails/170311", (call) =>
      call.url.pathname === "/api/mails/170311" ? mailDetailKeys : fixtureApi(call),
    );
    await screen.findByRole("heading", { name: "Jahresabschluss 2020 – Unterlagen" });
    // The mail's own status in the header.
    expect(screen.getAllByText("Signatur stimmig").length).toBeGreaterThan(0);

    const first = signature(1);
    expect(within(first).getByText("consistent")).toBeTruthy();
    expect(within(first).getByText("rekonstruiert").getAttribute("title")).toBe(
      "Aus Signaturen berechnet: Die Signaturen stammen vom selben privaten Schlüssel, an die Domain bindet ihn das nicht.",
    );
    expect(
      within(first).getByText(
        "Die Signatur passt zu einem aus Signaturen berechneten Schlüssel. Das zeigt, dass diese Mails mit demselben privaten Schlüssel signiert wurden, nicht, dass die Domain ihn veröffentlicht hat.",
      ),
    ).toBeTruthy();
    expect(within(first).getByText("9c1e5f0a7b3d4e2f…")).toBeTruthy();
    expect(within(first).getByText("RSA · 2.048 Bit")).toBeTruthy();
    const evidence = within(first).getByRole("list", { name: "Belege" });
    expect(
      within(evidence)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["Rekonstruktion · berechnet 21.10.2026 · aus 2 Signaturen"]);
    expect(within(first).getByRole("link", { name: "Selektor ansehen" }).getAttribute("href")).toBe(
      "/import/selektoren/s2019._domainkey.nordlicht-gmbh.example",
    );

    // A lost key: no origin, the reason and the way to its selector.
    const second = signature(2);
    expect(within(second).getByText("no_key")).toBeTruthy();
    expect(within(second).queryByText("rekonstruiert")).toBeNull();
    expect(within(second).queryByText(/Die Signatur passt zu einem/)).toBeNull();
    expect(within(second).getByText(/Schlüssel nicht im DNS \(Selector gelöscht\)/)).toBeTruthy();
    expect(
      within(second).getByRole("link", { name: "Selektor ansehen" }).getAttribute("href"),
    ).toBe("/import/selektoren/list._domainkey.verteiler-nord.example");
  });

  it("marks a key from today's DNS without a key block", async () => {
    renderApp("/mails/184221");
    await screen.findByText("DNS heute");
    expect(within(card()).getByText("DNS heute").getAttribute("title")).toBe(
      "Die Domain veröffentlicht diesen Schlüssel heute im DNS.",
    );
    expect(within(card()).queryByRole("link", { name: "Selektor ansehen" })).toBeNull();
    expect(within(card()).queryByRole("list", { name: "Belege" })).toBeNull();
  });
});
