import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  topicState,
  topicStateNever,
  topicTermsSampled,
  topicTermsTimedOut,
} from "../../test/fixtures";
import { menuItem, rows } from "../../test/mailList";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

// Intl puts a no-break space before "%".
const plain = (text: string | null | undefined) => text?.replace(/\u00a0/g, " ");

const topicCalls = (calls: ApiCall[], endpoint: string) =>
  calls.filter((call) => call.url.pathname === `/api/topics/${endpoint}`);

/** The fixture backend with some answers replaced. */
function withApi(answer: (call: ApiCall) => unknown) {
  return (call: ApiCall) => answer(call) ?? fixtureApi(call);
}

const href = (link: HTMLElement) => link.getAttribute("href");

/** The figures a term's chip shows on hover or focus. */
function tip(link: HTMLElement): string | undefined {
  return plain(document.getElementById(link.getAttribute("aria-describedby")!)?.textContent);
}

const period = (name: string) => screen.getByRole("heading", { name, level: 3 }).closest("li")!;

describe("topics screen", () => {
  it("is in the navigation after Zeitachse and lists the months with their terms", async () => {
    const { calls } = renderApp("/themen");
    const october = await screen.findByRole("heading", { name: "Oktober 2025" });
    const navigation = screen.getByRole("navigation", { name: "Hauptnavigation" });
    const labels = within(navigation)
      .getAllByRole("link")
      .map((link) => link.textContent);
    // The analysis screens follow the daily ones; Themen ends them.
    // without the counts some links carry
    expect(labels.slice(0, 10).map((label) => label?.replace(/[\d.]+$/, ""))).toEqual([
      "Mails",
      "Personen",
      "Anhänge",
      "Akten",
      "Zeitachse",
      "Karte",
      "Orte",
      "Signale",
      "Entitäten",
      "Themen",
    ]);
    expect(document.title).toBe("Themen · Mailrobbe");
    expect(screen.getByRole("heading", { name: "Themen", level: 1 })).toBeTruthy();
    expect(
      screen.getByText(
        "Berechnet am 21.10.2026, 14:05 über 398.112 Mails. Neue Mails kommen beim nächsten Import dazu.",
      ),
    ).toBeTruthy();
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Zeiträume",
      "Auswahl",
      "Themen 2",
    ]);
    expect(screen.getByRole("tab", { name: "Zeiträume" }).getAttribute("aria-selected")).toBe(
      "true",
    );
    // The months by default, and the years with one term for the state line.
    expect(topicCalls(calls, "periods").map((call) => call.url.search)).toEqual([
      "",
      "?unit=year&limit=1",
    ]);
    expect(screen.getByText("3 Monate mit Mails, neueste zuerst")).toBeTruthy();
    expect(
      screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent),
    ).toEqual(["Oktober 2025", "September 2025", "August 2025"]);

    // A term: its mails in the period, its figures on focus, its theme as a dot and a name.
    const row = october.closest("li")!;
    expect(within(row).getByText("412 Mails")).toBeTruthy();
    const terms = within(row).getByRole("list", { name: "Begriffe Oktober 2025" });
    expect(within(terms).getAllByRole("listitem")).toHaveLength(10);
    const spende = within(terms).getByRole("link", { name: "Spende 37" });
    expect(href(spende)).toBe(
      "/mails?q=Spende&date_from=2025-10-01&date_to=2025-10-31&hide_duplicates=true",
    );
    expect(tip(spende)).toBe(
      "37 von 412 Mails (9 %) · im übrigen Archiv 0,4 % · 22-mal so häufig · Recherchethema: Spendenaffären",
    );
    const kasse = within(terms).getByRole("link", { name: "Kassenprüfung 9" });
    expect(tip(kasse)).toBe("9 von 412 Mails (2 %) · im übrigen Archiv 0 % · nur hier");

    // The period's own links.
    expect(href(within(row).getByRole("link", { name: "Mails von Oktober 2025" }))).toBe(
      "/mails?date_from=2025-10-01&date_to=2025-10-31&hide_duplicates=true",
    );
    expect(href(within(row).getByRole("link", { name: "Zeitachse von Oktober 2025" }))).toBe(
      "/zeitachse?date_from=2025-10-01&date_to=2025-10-31&hide_duplicates=true",
    );
    expect(href(within(row).getByRole("link", { name: "Als Auswahl: Oktober 2025" }))).toBe(
      "/themen?view=selection&date_from=2025-10-01&date_to=2025-10-31",
    );

    // A period with fewer terms has no "mehr"; one without any says so.
    expect(within(period("September 2025")).queryByRole("button", { name: "mehr" })).toBeNull();
    expect(
      within(period("August 2025")).getByText("Kein Wort hebt sich in diesem Zeitraum ab."),
    ).toBeTruthy();

    // The explanation is folded below the head, without a word of rating.
    const explanation = screen
      .getByRole("heading", { name: "So entstehen die Begriffe" })
      .closest("details")!;
    expect(explanation.open).toBe(false);
    expect(explanation.textContent).toMatch(/Spende, Spenden und spenden zählen zusammen/);
    expect(explanation.textContent).toMatch(/nicht aus Anhängen/);
    expect(explanation.textContent).toMatch(/mindestens 3 Mails/);
    expect(explanation.textContent).toMatch(/mindestens doppelt so häufig/);
    expect(explanation.textContent).toMatch(/Log-Likelihood/);
    expect(explanation.textContent).toMatch(/Grußformeln, Wochentage\s+und Monate/);
    expect(explanation.textContent).toMatch(/themes\.toml/);
    expect(explanation.textContent).toMatch(/Spende or Barzahlung/);
    expect(document.body.textContent).not.toMatch(/verdächtig|Hinweis auf|Verdacht/i);
  });

  it("shows the rest of a period's terms on request", async () => {
    const { calls } = renderApp("/themen");
    await screen.findByRole("heading", { name: "Oktober 2025" });
    const row = period("Oktober 2025");
    fireEvent.click(within(row).getByRole("button", { name: "mehr" }));
    expect(await within(row).findByRole("link", { name: "Druckerei 4" })).toBeTruthy();
    expect(within(row).getAllByRole("listitem")).toHaveLength(12);
    expect(topicCalls(calls, "periods").at(-1)!.url.search).toBe(
      "?unit=month&date_from=2025-10-01&date_to=2025-10-31&limit=30",
    );
    fireEvent.click(within(row).getByRole("button", { name: "weniger" }));
    expect(within(row).getAllByRole("listitem")).toHaveLength(10);
  });

  it("switches the unit in the URL and the request", async () => {
    const { router, calls } = renderApp("/themen");
    await screen.findByRole("heading", { name: "Oktober 2025" });
    const units = screen.getByRole("group", { name: "Zeiteinheit" });
    fireEvent.click(within(units).getByRole("button", { name: "Quartal" }));
    await waitFor(() => expect(router.state.location.search).toBe("?unit=quarter"));
    expect(await screen.findByRole("heading", { name: "4. Quartal 2025" })).toBeTruthy();
    expect(topicCalls(calls, "periods").at(-1)!.url.search).toBe("?unit=quarter");
    expect(
      within(units).getByRole("button", { name: "Quartal" }).getAttribute("aria-pressed"),
    ).toBe("true");
    expect(href(screen.getByRole("link", { name: "Als Auswahl: 4. Quartal 2025" }))).toBe(
      "/themen?view=selection&unit=quarter&date_from=2025-10-01&date_to=2025-12-31",
    );

    fireEvent.click(within(units).getByRole("button", { name: "Jahr" }));
    await waitFor(() => expect(router.state.location.search).toBe("?unit=year"));
    expect(await screen.findByRole("heading", { name: "2024" })).toBeTruthy();
  });

  it("says before the first computation that the next import computes the topics", async () => {
    renderApp(
      "/themen",
      withApi(({ url }) =>
        url.pathname === "/api/topics/periods"
          ? { state: topicStateNever, unit: url.searchParams.get("unit") ?? "month", periods: [] }
          : undefined,
      ),
    );
    expect(await screen.findByText("Die Begriffe sind noch nicht berechnet.")).toBeTruthy();
    expect(screen.getByText(/Der nächste Import berechnet sie/)).toBeTruthy();
    expect(href(screen.getByRole("link", { name: "Zum Import" }))).toBe("/import");
    expect(screen.queryByRole("tab")).toBeNull();
    expect(screen.queryByText(/Berechnet am/)).toBeNull();
  });

  it("shows two years of months at first and older ones on request", async () => {
    // 30 months, newest first: December 2025 back to July 2023.
    const months = Array.from({ length: 30 }, (_, back) => {
      const first = new Date(Date.UTC(2025, 11 - back, 1));
      const last = new Date(Date.UTC(2025, 12 - back, 0));
      const day = (date: Date) => date.toISOString().slice(0, 10);
      return { start: day(first), end: day(last), mails: 10, terms: [] };
    });
    renderApp(
      "/themen",
      withApi(({ url }) =>
        url.pathname === "/api/topics/periods" && !url.searchParams.has("unit")
          ? { state: topicState, unit: "month", periods: months }
          : undefined,
      ),
    );
    expect(await screen.findByRole("heading", { name: "Dezember 2025" })).toBeTruthy();
    expect(screen.getByText("30 Monate mit Mails, neueste zuerst")).toBeTruthy();
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(24);
    expect(screen.queryByRole("heading", { name: "Dezember 2023" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ältere Zeiträume zeigen (noch 6)" }));
    expect(screen.getAllByRole("heading", { level: 3 })).toHaveLength(30);
    expect(screen.getByRole("heading", { name: "Juli 2023" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Ältere Zeiträume/ })).toBeNull();
  });
});

describe("topics of a selection", () => {
  it("asks for a person, a Zeitraum or a search without any filter", async () => {
    const { calls } = renderApp("/themen?view=selection");
    expect(
      await screen.findByText("Wählen Sie eine Person, einen Zeitraum oder eine Suche"),
    ).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Auswahl" }).getAttribute("aria-selected")).toBe("true");
    expect(href(screen.getByRole("link", { name: "Zu den Zeiträumen" }))).toBe("/themen");
    expect(topicCalls(calls, "terms")).toHaveLength(0);
  });

  it("counts the terms of the filters, shown as chips, with every figure and link", async () => {
    const { calls } = renderApp("/themen?view=selection&person=11&person_role=sent");
    const table = await screen.findByRole("table");
    expect(topicCalls(calls, "terms").map((call) => call.url.search)).toEqual([
      "?person=11&person_role=sent",
    ]);
    // The person's chip is named by the profile, as the mail list names it.
    expect(
      await screen.findByRole("button", {
        name: "Filter entfernen: Person: Anna Keller · Gesendet",
      }),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "3.412 Mails dieser Auswahl, ohne Duplikate, verglichen mit den übrigen 394.700 Mails des Archivs",
      ),
    ).toBeTruthy();

    const rows = within(table).getAllByRole("row");
    expect(rows.map((row) => plain(row.textContent))).toEqual([
      "BegriffMailsAnteil hierim übrigen ArchivHäufigkeitZeitachse",
      "Rahmenvertrag2126 %0,1 %57-mal so häufigZeitachse",
      "Wartung1805 %0,2 %29-mal so häufigZeitachse",
      "Umspannwerk953 %0,01 %244-mal so häufigZeitachse",
      "SpendeSpendenaffären401 %0,4 %2,9-mal so häufigZeitachse",
      "Kassenprüfung40,1 %0 %nur hierZeitachse",
    ]);
    expect(href(within(table).getByRole("link", { name: "Wartung" }))).toBe(
      "/mails?q=Wartung&hide_duplicates=true&person=11&person_role=sent",
    );
    expect(href(within(table).getByRole("link", { name: "Zeitachse: Wartung" }))).toBe(
      "/zeitachse?hide_duplicates=true&person=11&person_role=sent&split=term&term=Wartung",
    );

    // The common terms apart and muted, with their figures.
    const common = screen.getByRole("heading", {
      name: "In mehr als der Hälfte dieser Mails, oft Signatur, Grußformel oder Fußzeile",
    }).parentElement!;
    const nordlicht = within(common).getByRole("link", { name: "Nordlicht 2.100" });
    expect(href(nordlicht)).toBe(
      "/mails?q=Nordlicht&hide_duplicates=true&person=11&person_role=sent",
    );
    expect(tip(nordlicht)).toBe(
      "2.100 von 3.412 Mails (62 %) · im übrigen Archiv 2 % · 35-mal so häufig",
    );
  });

  it("notes a sample and a count that took too long", async () => {
    let answer: unknown = topicTermsSampled;
    renderApp(
      "/themen?view=selection&q=Vertrag",
      withApi(({ url }) => (url.pathname === "/api/topics/terms" ? answer : undefined)),
    );
    expect(
      await screen.findByText("Gezählt über 5.000 von 48.210 Mails, Zahlen geschätzt"),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Filter entfernen: Suche: „Vertrag“" })).toBeTruthy();

    answer = topicTermsTimedOut;
    fireEvent.change(screen.getByRole("searchbox", { name: "Suchtext" }), {
      target: { value: "Vertrag Wartung" },
    });
    fireEvent.submit(screen.getByRole("searchbox", { name: "Suchtext" }).closest("form")!);
    expect(await screen.findByText("Die Zählung hat zu lange gedauert.")).toBeTruthy();
    expect(screen.getByText(/Grenzen Sie die Auswahl ein/)).toBeTruthy();
  });

  it("sets a person, its role and a Zeitraum on the screen", async () => {
    const { router, calls } = renderApp("/themen?view=selection&date_from=2025-10-01");
    await screen.findByRole("table");
    fireEvent.change(screen.getByRole("combobox", { name: "Person hinzufügen" }), {
      target: { value: "Anna" },
    });
    fireEvent.click(await screen.findByRole("option", { name: /Anna Keller/ }));
    await waitFor(() =>
      expect(router.state.location.search).toBe(
        "?view=selection&date_from=2025-10-01&person=11&person_role=sent",
      ),
    );
    const roles = screen.getByRole("group", { name: "Rolle" });
    fireEvent.click(within(roles).getByRole("button", { name: "Alle Rollen" }));
    await waitFor(() =>
      expect(router.state.location.search).toBe("?view=selection&date_from=2025-10-01&person=11"),
    );
    fireEvent.change(screen.getByLabelText("bis"), { target: { value: "2025-10-31" } });
    await waitFor(() =>
      expect(topicCalls(calls, "terms").at(-1)!.url.search).toBe(
        "?date_from=2025-10-01&date_to=2025-10-31&person=11",
      ),
    );
  });
});

describe("topic clusters", () => {
  it("shows the clusters as cards with their words, months and links", async () => {
    renderApp("/themen?view=clusters");
    const first = (
      await screen.findByRole("heading", { name: "Angebot, Preis, Lieferung" })
    ).closest("li")!;
    expect(
      screen.getAllByRole("heading", { level: 3 }).map((heading) => heading.textContent),
    ).toEqual(["Angebot, Preis, Lieferung", "Spende, Quittung, Barzahlung"]);
    expect(
      screen.getByText(
        "2 Themen, die meisten Mails zuerst. Die Balken zeigen die Mails pro Monat, alle auf derselben Achse von Januar 2024 bis Oktober 2025.",
      ),
    ).toBeTruthy();
    expect(within(first).getByText("1.840 Mails · 01.01.2024 bis 18.10.2025")).toBeTruthy();
    expect(within(first).getByRole("img").getAttribute("aria-label")).toBe(
      "Mails pro Monat; die meisten im Juni 2024: 140",
    );
    // One bar per month with mails.
    expect(within(first).getByRole("img").querySelector("path")!.getAttribute("d")).toMatch(
      /^(M[^M]+){5}$/,
    );

    const angebot = within(first).getByRole("link", { name: "Angebot 1.200" });
    expect(href(angebot)).toBe("/mails?q=Angebot&hide_duplicates=true");
    expect(tip(angebot)).toBe("1.200 Mails im Archiv (0,3 %)");
    expect(href(within(first).getByRole("link", { name: "Mails lesen" }))).toBe(
      "/mails?q=Angebot+or+Preis+or+Lieferung+or+Rabatt+or+Bestellung&hide_duplicates=true",
    );
    expect(href(within(first).getByRole("link", { name: "In der Zeitachse vergleichen" }))).toBe(
      "/zeitachse?hide_duplicates=true&split=term&term=Angebot&term=Preis&term=Lieferung" +
        "&term=Rabatt&term=Bestellung",
    );

    const second = screen
      .getByRole("heading", { name: "Spende, Quittung, Barzahlung" })
      .closest("li")!;
    expect(tip(within(second).getByRole("link", { name: "Spende 1.628" }))).toBe(
      "1.628 Mails im Archiv (0,4 %) · Recherchethema: Spendenaffären",
    );
  });
});

describe("links to the Auswahl", () => {
  it("opens the terms of the mail list's filters from its menu", async () => {
    const { router } = renderApp("/mails?q=Spende&person=11&sort=date_asc");
    await rows();
    menuItem("Begriffe dieser Treffer");
    await waitFor(() => expect(router.state.location.pathname).toBe("/themen"));
    expect(router.state.location.search).toBe("?view=selection&q=Spende&person=11");
  });

  it("leaves the link out of the mail list without filters", async () => {
    renderApp("/mails");
    await rows();
    fireEvent.click(screen.getAllByRole("button", { name: "Weitere Aktionen" })[0]);
    expect(screen.getByRole("menuitem", { name: "Treffer in der Zeitachse" })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: "Begriffe dieser Treffer" })).toBeNull();
  });

  it("opens the terms of the timeline's filters from its head", async () => {
    renderApp("/zeitachse?q=Spende&date_from=2024-01-01&split=person&bucket=week");
    const link = await screen.findByRole("link", { name: "Begriffe" });
    expect(href(link)).toBe("/themen?view=selection&q=Spende&date_from=2024-01-01");
  });
});
