import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { fixtureApi, renderApp } from "../../test/render";

function card(name: string): HTMLElement {
  return screen.getByRole("heading", { name }).closest("section")!;
}

const href = (element: HTMLElement) => element.getAttribute("href");

describe("entity page", () => {
  it("names the entity and leads into the mail list, for amounts by context", async () => {
    const { calls } = renderApp("/entitaeten/312");
    const heading = await screen.findByRole("heading", { name: "12.500,00 EUR", level: 1 });
    expect(document.title).toBe("12.500,00 EUR · Entitäten · Mailrobbe");
    expect(calls.some((call) => call.url.pathname === "/api/entities/312")).toBe(true);

    const breadcrumb = screen.getByRole("navigation", { name: "Pfad" });
    expect(href(within(breadcrumb).getByRole("link", { name: "Entitäten" }))).toBe("/entitaeten");
    expect(breadcrumb.textContent).toContain("12.500,00 EUR");

    const header = heading.closest("section")!;
    expect(within(header).getByText("Betrag in Euro")).toBeTruthy();
    // The normalised key, as it differs from the label.
    expect(within(header).getByText("EUR 12500.00")).toBeTruthy();
    expect(href(within(header).getByRole("link", { name: "In der Mailliste zeigen" }))).toBe(
      "/mails?entity=312",
    );
    expect(href(within(header).getByRole("link", { name: "Nur Mails mit Bargeld-Bezug" }))).toBe(
      "/mails?entity=312&amount_context=cash",
    );
    expect(href(within(header).getByRole("link", { name: "Nur Mails mit Spenden-Bezug" }))).toBe(
      "/mails?entity=312&amount_context=donation",
    );
    // No mail with a receipt: no button for it.
    expect(within(header).queryByRole("link", { name: /Quittungs-Bezug/ })).toBeNull();
    expect(within(header).queryByText(/Im Archiv/)).toBeNull();
  });

  it("shows the figures, the years and the earliest mentions", async () => {
    renderApp("/entitaeten/312");
    await screen.findByRole("heading", { name: "12.500,00 EUR", level: 1 });

    // The figures as a row; what each counts, and the time of day, in its tooltip.
    const figures = within(screen.getByRole("list", { name: "Kennzahlen" })).getAllByRole(
      "listitem",
    );
    expect(figures.map((figure) => [figure.textContent, figure.title])).toEqual([
      ["41Mails", "ohne Duplikate"],
      ["2Dokumente", "Anhänge, die es erwähnen"],
      ["14.03.2019Erste Erwähnung", expect.stringMatching(/^\d\d:\d\d Uhr$/)],
      ["18.10.2026Letzte Erwähnung", expect.stringMatching(/^\d\d:\d\d Uhr$/)],
    ]);

    const years = card("Mails pro Jahr");
    expect(
      within(years)
        .getAllByRole("link")
        .map((year) => [year.getAttribute("aria-label"), href(year)]),
    ).toEqual([
      ["2019: 4 Mails", "/mails?date_from=2019-01-01&date_to=2019-12-31&entity=312"],
      ["2021: 9 Mails", "/mails?date_from=2021-01-01&date_to=2021-12-31&entity=312"],
      ["2026: 28 Mails", "/mails?date_from=2026-01-01&date_to=2026-12-31&entity=312"],
    ]);

    const samples = card("Früheste Erwähnungen");
    expect(href(within(samples).getByRole("link", { name: "Alle in der Mailliste" }))).toBe(
      "/mails?entity=312&sort=date_asc",
    );
    const items = within(samples).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(href(within(items[0]).getByRole("link", { name: "Spende Freundeskreis" }))).toBe(
      "/mails/183011",
    );
    expect(within(items[0]).getByText("12.500,00 EUR").tagName).toBe("MARK");
    // Marked as written; the mention in the attachment names it.
    expect(within(items[1]).getByText("12.500,00 eur").tagName).toBe("MARK");
    expect(items[1].textContent).toContain("im Anhang Rahmenvereinbarung_2026_final.pdf");
    expect(
      href(within(items[1]).getByRole("link", { name: "Rahmenvereinbarung_2026_final.pdf" })),
    ).toBe("/anhaenge/5101");
  });

  it("lists contexts, persons and what is mentioned with it", async () => {
    renderApp("/entitaeten/312");
    await screen.findByRole("heading", { name: "12.500,00 EUR", level: 1 });
    const side = screen.getByRole("complementary", { name: "Zur Entität" });

    const contexts = within(side).getByRole("heading", { name: "Im Zusammenhang mit" });
    expect(
      within(contexts.closest("section")!)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["Bargeld3", "Spende12", "Quittung0"]);

    const senders = card("Absender (7)");
    expect(
      within(senders)
        .getAllByRole("link")
        .map((link) => [link.textContent, href(link)]),
    ).toEqual([
      ["Anna Keller", "/personen/11"],
      ["Lukas Vogt", "/personen/14"],
    ]);
    expect(within(senders).getByText("Die 2 häufigsten von 7.")).toBeTruthy();
    // All recipients shown: no note.
    expect(card("Empfänger (2)").querySelector("p")).toBeNull();

    const related = card("Gemeinsam erwähnt");
    const iban = within(related).getByRole("link", { name: /^DE89 3704 0044 0532 0130 00/ });
    expect(href(iban)).toBe("/entitaeten/321");
    expect(iban.textContent).toBe("DE89 3704 0044 0532 0130 00 11");
    expect(
      href(
        within(related).getByRole("link", {
          name: "Mails mit beiden: 12.500,00 EUR und DE89 3704 0044 0532 0130 00",
        }),
      ),
    ).toBe("/mails?entity=312&entity=321");
  });

  it("links an address to the archive's person and says when persons are a sample", async () => {
    renderApp("/entitaeten/371");
    const heading = await screen.findByRole("heading", {
      name: "kasse@freundeskreis-nord.example",
      level: 1,
    });
    const header = heading.closest("section")!;
    expect(within(header).getByText("E-Mail-Adresse")).toBeTruthy();
    expect(header.textContent).toContain("Im Archiv: Kasse Freundeskreis");
    expect(
      href(
        within(header).getByRole("link", {
          name: "Kasse Freundeskreis (kasse@freundeskreis-nord.example)",
        }),
      ),
    ).toBe("/personen/20");
    // Neither context buttons nor a context card for an address.
    expect(within(header).getAllByRole("link", { name: /Mail/ })).toHaveLength(1);
    expect(screen.queryByRole("heading", { name: "Im Zusammenhang mit" })).toBeNull();

    expect(within(card("Absender (1)")).getByText("Gezählt über 10.000 der Mails.")).toBeTruthy();
    expect(within(card("Empfänger (0)")).getByText("Kein Empfänger bekannt.")).toBeTruthy();
    expect(
      within(card("Gemeinsam erwähnt")).getByText("Nichts anderes in denselben Mails erkannt."),
    ).toBeTruthy();
    expect(
      within(card("Früheste Erwähnungen")).getByText("Keine Mail mit diesem Eintrag gefunden."),
    ).toBeTruthy();
  });

  it("says when the entity does not exist", async () => {
    renderApp("/entitaeten/999");
    expect(await screen.findByText("Diese Entität gibt es nicht.")).toBeTruthy();
    expect(screen.getByText(/keine Entität mit der Nummer #999/)).toBeTruthy();
    expect(href(screen.getByRole("link", { name: "Zu den Entitäten" }))).toBe("/entitaeten");
    expect(document.title).toBe("Entität · Entitäten · Mailrobbe");
  });

  it("asks for nothing with an id that is no number", () => {
    const { calls } = renderApp("/entitaeten/abc");
    expect(screen.getByText("Diese Entität gibt es nicht.")).toBeTruthy();
    expect(calls.filter((call) => call.url.pathname.startsWith("/api/entities/"))).toHaveLength(0);
  });

  it("offers a retry when loading fails", async () => {
    renderApp("/entitaeten/312", (call) =>
      call.url.pathname === "/api/entities/312"
        ? Response.json({ detail: "boom" }, { status: 500 })
        : fixtureApi(call),
    );
    expect(await screen.findByText("Die Entität konnte nicht geladen werden.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Erneut versuchen" })).toBeTruthy();
  });
});
