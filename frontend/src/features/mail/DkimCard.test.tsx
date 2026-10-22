import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mailDetailKeys } from "../../test/fixtures";
import { fixtureApi, openFolds, renderApp } from "../../test/render";

const card = () => screen.getByRole("heading", { name: "DKIM-Prüfung" }).closest("section")!;

function signature(number: number): HTMLElement {
  return within(card()).getByRole("heading", { name: `Signatur ${number}` }).parentElement!;
}

describe("DKIM box", () => {
  it("is one line below the text until opened, which the badge in the header does", async () => {
    renderApp("/mails/170311", (call) =>
      call.url.pathname === "/api/mails/170311" ? mailDetailKeys : fixtureApi(call),
    );
    await screen.findByRole("heading", { name: "Jahresabschluss 2020 – Unterlagen" });
    const toggle = within(card()).getByRole("button", { name: "DKIM-Prüfung" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(within(card()).queryByRole("heading", { name: "Signatur 1" })).toBeNull();
    expect(
      within(card()).getByText(
        /^2 Signaturen · Signatur stimmig · Schlüssel nicht im DNS \(Selector gelöscht\) · geprüft am /,
      ),
    ).toBeTruthy();
    // Neu prüfen stays in reach while folded.
    expect(within(card()).getByRole("button", { name: "Neu prüfen" })).toBeTruthy();
    // The text comes before it.
    const inhalt = screen.getByRole("region", { name: "Inhalt" });
    expect(inhalt.compareDocumentPosition(card()) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    const scrolled: Element[] = [];
    // jsdom does not scroll
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this);
    };
    fireEvent.click(screen.getByRole("button", { name: "Signatur stimmig" }));
    await waitFor(() => expect(signature(1)).toBeTruthy());
    expect(scrolled).toEqual([card()]);
    expect(localStorage.getItem("mailrobbe.folds")).toBe('{"mail.dkim":true}');
  });

  it("names the key's origin and, for a reconstructed key, what it does not show", async () => {
    openFolds("mail.dkim");
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
    openFolds("mail.dkim");
    renderApp("/mails/184221");
    await screen.findByText("DNS heute");
    expect(within(card()).getByText("DNS heute").getAttribute("title")).toBe(
      "Die Domain veröffentlicht diesen Schlüssel heute im DNS.",
    );
    expect(within(card()).queryByRole("link", { name: "Selektor ansehen" })).toBeNull();
    expect(within(card()).queryByRole("list", { name: "Belege" })).toBeNull();
  });
});
