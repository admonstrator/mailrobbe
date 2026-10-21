import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { firstMentions, timelineAll } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const timelineCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/timeline");
const mentionCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/timeline/first-mentions");

/** The fixture backend with some answers replaced. */
function withApi(answer: (call: ApiCall) => unknown) {
  return (call: ApiCall) => answer(call) ?? fixtureApi(call);
}

/** Moves a lane's keyboard position to bucket index. */
function moveTo(lane: HTMLElement, index: number) {
  fireEvent.focus(lane);
  fireEvent.keyDown(lane, { key: "Home" });
  for (let step = 0; step < index; step++) fireEvent.keyDown(lane, { key: "ArrowRight" });
}

const lane = (name: string) => screen.findByRole("slider", { name });
const segment = (group: string, name: string) =>
  within(screen.getByRole("group", { name: group })).getByRole("button", { name });

describe("timeline screen", () => {
  it("is in the navigation after Karte and counts the archive by month", async () => {
    const { calls } = renderApp("/zeitachse");
    const total = await lane("Alle Treffer");
    const navigation = screen.getByRole("navigation", { name: "Hauptnavigation" });
    const labels = within(navigation)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(labels.indexOf("Zeitachse")).toBe(labels.indexOf("Karte") + 1);
    expect(document.title).toBe("Zeitachse · Mailrobbe");
    expect(screen.getByRole("heading", { name: "Zeitachse", level: 1 })).toBeTruthy();
    expect(screen.getByText("Mailaufkommen für die aktuelle Suche und Filter")).toBeTruthy();
    expect(screen.getByRole("link", { name: "In der Mailliste öffnen" }).getAttribute("href")).toBe(
      "/mails",
    );
    expect(timelineCalls(calls).map((call) => call.url.search)).toEqual([""]);
    expect(mentionCalls(calls).map((call) => call.url.search)).toEqual([""]);

    const sum = timelineAll.total!.total.toLocaleString("de-DE");
    expect(
      screen.getByText(
        `${sum} Mails von Januar 2023 bis Dezember 2025 · 214 Treffer ohne Datum sind nicht auf der Achse.`,
      ),
    ).toBeTruthy();
    expect(screen.getByText("Automatisch gewählt: nach Monaten.")).toBeTruthy();
    expect(segment("Zeiteinheit", "Automatisch").getAttribute("aria-pressed")).toBe("true");
    expect(segment("Aufschlüsseln", "Gesamt").getAttribute("aria-pressed")).toBe("true");

    // One ▲ over March 2024, one ▽ under March 2025; nothing falls silent.
    const high = total.querySelector('[data-mark="high"]')!.getAttribute("d")!;
    const low = total.querySelector('[data-mark="low"]')!.getAttribute("d")!;
    expect([high.match(/M/g), low.match(/M/g)].map((moves) => moves?.length)).toEqual([1, 1]);
    expect(total.querySelector('[data-mark="silent"]')).toBeNull();

    // The keyboard walks the buckets; the tooltip names each with its figures.
    fireEvent.focus(total);
    expect(total.getAttribute("aria-valuetext")).toBe("Januar 2023: 1.100 Mails");
    expect(screen.getByText("Januar 2023: 1.100 Mails")).toBeTruthy();
    moveTo(total, 14);
    expect(total.getAttribute("aria-valuetext")).toBe(
      "März 2024: 4.300 Mails · üblich etwa 1.216 · ▲ viel mehr als üblich",
    );
    expect(screen.getByText("März 2024: 4.300 Mails · üblich etwa 1.216")).toBeTruthy();
    moveTo(total, 26);
    expect(total.getAttribute("aria-valuetext")).toBe(
      "März 2025: 240 Mails · üblich etwa 1.180 · ▽ viel weniger als üblich",
    );
    fireEvent.keyDown(total, { key: "End" });
    expect(total.getAttribute("aria-valuemax")).toBe("35");
    expect(total.getAttribute("aria-valuenow")).toBe("35");

    // The marks are explained beside the chart, with the numbers of the month rules.
    expect(screen.getByText(/mit den sechs Monaten davor verglichen/)).toBeTruthy();
    expect(screen.getByText(/mindestens dreimal so viele Mails/)).toBeTruthy();
    expect(screen.getByText(/mindestens 3 Monate lang/)).toBeTruthy();
    const legend = screen.getByRole("list", { name: "Zeichen in der Zeitachse" });
    expect(
      within(legend)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["▲ viel mehr als üblich", "▽ viel weniger als üblich"]);

    // The first mentions are dots on the same axis.
    const mentions = await lane("Erste Erwähnungen");
    moveTo(mentions, 1);
    expect(mentions.getAttribute("aria-valuetext")).toBe(
      "Februar 2023: zuerst Lukas Vogt, Anna Keller",
    );
    expect(mentions.querySelectorAll("circle")).toHaveLength(3);
  });

  it("opens the mails of a bucket of the total within the filter's Zeitraum", async () => {
    const { router } = renderApp("/zeitachse?q=Spende&date_from=2024-03-10");
    const total = await lane("Alle Treffer");
    moveTo(total, 14);
    fireEvent.keyDown(total, { key: "Enter" });
    await waitFor(() => expect(router.state.location.pathname).toBe("/mails"));
    expect(router.state.location.search).toBe("?q=Spende&date_from=2024-03-10&date_to=2024-03-31");
  });

  it("switches the split and the unit in the URL and the request", async () => {
    const { router, calls } = renderApp("/zeitachse");
    await lane("Alle Treffer");

    fireEvent.click(segment("Aufschlüsseln", "Personen"));
    await waitFor(() => expect(router.state.location.search).toBe("?split=person"));
    expect(timelineCalls(calls).at(-1)!.url.search).toBe("?split=person");
    const anna = await lane("Anna Keller");
    // The lane's label links to the profile, as the first mentions below do.
    expect(
      screen.getAllByRole("link", { name: "Anna Keller" }).map((link) => link.getAttribute("href")),
    ).toEqual(["/personen/11", "/personen/11"]);
    expect(anna.querySelector('[data-mark="high"]')!.getAttribute("d")).toMatch(/^M\S+ \S+h8/);
    expect(
      screen.getByText(
        "Ohne Auswahl: die sechs Personen mit den meisten Treffern, ohne Verteiler und Automaten.",
      ),
    ).toBeTruthy();

    // Lukas falls silent in July 2025: a hatched band to the end of the axis.
    const lukas = await lane("Lukas Vogt");
    expect(lukas.querySelector('[data-mark="silent"]')).toBeTruthy();
    expect(within(lukas).getByText("verstummt")).toBeTruthy();
    // Named in its label and in the legend, which lists only the marks that occur.
    expect(screen.getAllByText("verstummt seit Juli 2025")).toHaveLength(2);
    const legend = screen.getByRole("list", { name: "Zeichen in der Zeitachse" });
    expect(
      within(legend)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["▲ viel mehr als üblich", "▽ viel weniger als üblich", "verstummt seit Juli 2025"]);
    fireEvent.focus(lukas);
    fireEvent.keyDown(lukas, { key: "End" });
    expect(lukas.getAttribute("aria-valuetext")).toBe(
      "Dezember 2025: 0 Mails · verstummt seit Juli 2025",
    );

    fireEvent.click(segment("Aufschlüsseln", "Threads"));
    await waitFor(() => expect(router.state.location.search).toBe("?split=thread"));
    expect(await lane("Rahmenvertrag Stadtwerke 2024")).toBeTruthy();
    expect(await lane("(kein Betreff)")).toBeTruthy();

    fireEvent.click(segment("Zeiteinheit", "Woche"));
    await waitFor(() => expect(router.state.location.search).toBe("?bucket=week&split=thread"));
    expect(timelineCalls(calls).at(-1)!.url.search).toBe("?bucket=week&split=thread");

    fireEvent.click(segment("Aufschlüsseln", "Gesamt"));
    await waitFor(() => expect(router.state.location.search).toBe("?bucket=week"));
    expect(screen.queryByRole("slider", { name: "Rahmenvertrag Stadtwerke 2024" })).toBeNull();
  });

  it("adds and removes search strings of the term split", async () => {
    const { router, calls } = renderApp("/zeitachse?split=term");
    await lane("Alle Treffer");
    expect(
      screen.getByText(
        "Fügen Sie oben Suchbegriffe hinzu, um sie einzeln über die Zeit zu vergleichen.",
      ),
    ).toBeTruthy();
    // Without a search string yet the API counts the total alone.
    expect(timelineCalls(calls)[0].url.searchParams.has("split")).toBe(false);
    expect(screen.getByRole("button", { name: "Suchbegriffe", pressed: true })).toBeTruthy();
    const field = screen.getByRole("textbox", { name: "Suchbegriff" });
    fireEvent.change(field, { target: { value: " Spende " } });
    fireEvent.click(screen.getByRole("button", { name: "Hinzufügen" }));
    await waitFor(() => expect(router.state.location.search).toBe("?split=term&term=Spende"));
    fireEvent.change(field, { target: { value: '"schwarze Kasse"' } });
    fireEvent.submit(field.closest("form")!);
    await waitFor(() =>
      expect(router.state.location.search).toBe(
        "?split=term&term=Spende&term=%22schwarze+Kasse%22",
      ),
    );
    expect(timelineCalls(calls).at(-1)!.url.searchParams.getAll("term")).toEqual([
      "Spende",
      '"schwarze Kasse"',
    ]);
    expect(await lane('"schwarze Kasse"')).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Suchbegriff entfernen: Spende" }));
    await waitFor(() =>
      expect(router.state.location.search).toBe("?split=term&term=%22schwarze+Kasse%22"),
    );
  });

  it("opens a series' bucket with its person, thread or search string", async () => {
    const people = renderApp("/zeitachse?person=12&person_role=sent&split=person");
    const anna = await lane("Anna Keller");
    const width = Number(anna.getAttribute("width"));
    fireEvent.click(anna, { clientX: (14.5 / 36) * width });
    await waitFor(() => expect(people.router.state.location.pathname).toBe("/mails"));
    expect(people.router.state.location.search).toBe(
      "?date_from=2024-03-01&date_to=2024-03-31&person=12&person=11",
    );
  });

  it("opens a thread's and a search string's bucket", async () => {
    const threads = renderApp("/zeitachse?split=thread");
    const contract = await lane("Rahmenvertrag Stadtwerke 2024");
    moveTo(contract, 13);
    fireEvent.keyDown(contract, { key: "Enter" });
    await waitFor(() =>
      expect(threads.router.state.location.search).toBe(
        "?date_from=2024-02-01&date_to=2024-02-29&thread=184001",
      ),
    );
  });

  it("appends a search string's series to q", async () => {
    const { router } = renderApp("/zeitachse?q=intern&split=term&term=Spende");
    const spende = await lane("Spende");
    moveTo(spende, 14);
    expect(spende.getAttribute("aria-valuetext")).toBe(
      "März 2024: 41 Mails · üblich etwa 5 · ▲ viel mehr als üblich",
    );
    fireEvent.keyDown(spende, { key: "Enter" });
    await waitFor(() =>
      expect(router.state.location.search).toBe(
        "?q=intern+Spende&date_from=2024-03-01&date_to=2024-03-31",
      ),
    );
  });

  it("adds chosen persons to the person split and removes them", async () => {
    const { router } = renderApp("/zeitachse?split=person");
    await lane("Anna Keller");
    fireEvent.change(screen.getByRole("combobox", { name: "Person hinzufügen" }), {
      target: { value: "Stein" },
    });
    fireEvent.click(await screen.findByRole("option", { name: /Dr\. Miriam Steiner/ }));
    await waitFor(() => expect(router.state.location.search).toBe("?split=person&split_id=13"));
    fireEvent.click(
      await screen.findByRole("button", { name: "Person entfernen: Dr. Miriam Steiner" }),
    );
    await waitFor(() => expect(router.state.location.search).toBe("?split=person"));
  });

  it("shows the filters as chips, searches and links to the same mail list", async () => {
    const { router, calls } = renderApp("/zeitachse?q=Spende&has_attachment=true&person=11");
    await lane("Alle Treffer");
    expect(timelineCalls(calls)[0].url.search).toBe("?q=Spende&has_attachment=true&person=11");
    expect(screen.getByRole("link", { name: "In der Mailliste öffnen" }).getAttribute("href")).toBe(
      "/mails?q=Spende&has_attachment=true&person=11",
    );
    // Anna is named once the first mentions, which list her, are there.
    expect(
      await screen.findByRole("button", { name: "Filter entfernen: Person: Anna Keller" }),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Filter entfernen: Suche: „Spende“" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Filter entfernen: Mit Anhang" }));
    await waitFor(() => expect(router.state.location.search).toBe("?q=Spende&person=11"));

    const field = screen.getByRole("searchbox", { name: "Mails durchsuchen" });
    expect((field as HTMLInputElement).value).toBe("Spende");
    fireEvent.change(field, { target: { value: "Kasse " } });
    fireEvent.submit(field.closest("form")!);
    await waitFor(() => expect(router.state.location.search).toBe("?q=Kasse&person=11"));
  });

  it("lists who appears first, with links and the role toggle", async () => {
    const { router, calls } = renderApp("/zeitachse?q=Spende");
    const card = (
      await screen.findByRole("heading", { name: "Wer taucht wann zuerst auf" })
    ).closest("section")!;
    const table = await within(card).findByRole("table");
    expect(within(card).getByText("4 Personen")).toBeTruthy();
    const rows = within(table).getAllByRole("row").slice(1);
    expect(
      rows.map((row) =>
        within(row)
          .getAllByRole("cell")
          .map((cell) => cell.textContent),
      ),
    ).toEqual([
      ["14.02.2023", "Lukas Vogt", "schrieb", "Spende des Fördervereins", "12"],
      ["14.02.2023", "Anna Keller", "erhielt", "Spende des Fördervereins", "31"],
      ["02.05.2023", "Dr. Miriam Steiner", "in Cc", "AW: Quittung ohne Betrag", "4"],
      ["11.03.2024", "Jonas Brandt", "schrieb", "Rahmenvertrag Stadtwerke 2024", "9"],
    ]);
    const lukas = rows[0];
    expect(within(lukas).getByRole("link", { name: "Lukas Vogt" }).getAttribute("href")).toBe(
      "/personen/14",
    );
    expect(
      within(lukas).getByRole("link", { name: "Spende des Fördervereins" }).getAttribute("href"),
    ).toBe("/mails/183001?q=Spende");
    const mails = () =>
      within(lukas).getByRole("link", { name: "12 Mails von Lukas Vogt in der Mailliste" });
    expect(mails().getAttribute("href")).toBe("/mails?q=Spende&person=14");

    fireEvent.click(within(card).getByRole("checkbox", { name: "Nur Absender" }));
    await waitFor(() => expect(router.state.location.search).toBe("?q=Spende&role=sent"));
    expect(mentionCalls(calls).at(-1)!.url.search).toBe("?q=Spende&role=sent");
    // The timeline itself does not change with the first mentions' toggles.
    expect(timelineCalls(calls).at(-1)!.url.search).toBe("?q=Spende");
    await waitFor(() =>
      expect(mails().getAttribute("href")).toBe("/mails?q=Spende&person=14&person_role=sent"),
    );

    fireEvent.click(
      within(card).getByRole("checkbox", { name: "Verteiler und Automaten einbeziehen" }),
    );
    await waitFor(() =>
      expect(router.state.location.search).toBe("?q=Spende&role=sent&lists=true"),
    );
    expect(mentionCalls(calls).at(-1)!.url.search).toBe("?q=Spende&role=sent&lists=true");
  });

  it("shows more first mentions on request", async () => {
    const { calls } = renderApp(
      "/zeitachse",
      withApi((call) =>
        call.url.pathname === "/api/timeline/first-mentions"
          ? { ...firstMentions, persons: 250 }
          : undefined,
      ),
    );
    const card = (
      await screen.findByRole("heading", { name: "Wer taucht wann zuerst auf" })
    ).closest("section")!;
    expect(await within(card).findByText("4 von 250 Personen")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Mehr anzeigen" }));
    await waitFor(() => expect(mentionCalls(calls).at(-1)!.url.search).toBe("?limit=200"));
  });

  it("says which unit it shows when the chosen one has too many buckets", async () => {
    renderApp(
      "/zeitachse?bucket=day",
      withApi((call) =>
        call.url.pathname === "/api/timeline"
          ? { ...timelineAll, bucket: "week", coarsened: true }
          : undefined,
      ),
    );
    expect(
      await screen.findByText("Angezeigt nach Wochen: nach Tagen wären es mehr als 1.500 Balken."),
    ).toBeTruthy();
    expect(segment("Zeiteinheit", "Tag").getAttribute("aria-pressed")).toBe("true");
  });

  it("asks for a narrower search when the count runs out of time", async () => {
    renderApp(
      "/zeitachse?q=der",
      withApi((call) =>
        call.url.pathname === "/api/timeline"
          ? { ...timelineAll, total: null, undated: null, timed_out: true }
          : call.url.pathname === "/api/timeline/first-mentions"
            ? { items: [], persons: null, timed_out: true }
            : undefined,
      ),
    );
    expect(await screen.findByText("Die Zählung hat zu lange gedauert.")).toBeTruthy();
    expect(screen.getByText("Die Suche hat zu lange gedauert.")).toBeTruthy();
    expect(screen.getAllByText("Grenzen Sie die Suche ein, etwa mit einem Zeitraum.")).toHaveLength(
      2,
    );
    expect(screen.queryByRole("slider")).toBeNull();
  });

  it("says when nothing matches", async () => {
    renderApp(
      "/zeitachse?q=nirgends",
      withApi((call) =>
        call.url.pathname === "/api/timeline"
          ? {
              ...timelineAll,
              total: { ...timelineAll.total!, counts: [], total: 0, outliers: [] },
              starts: [],
              undated: 0,
            }
          : undefined,
      ),
    );
    expect(await screen.findByText("Keine Mails gefunden")).toBeTruthy();
    expect(screen.getByText("Kein Treffer für diese Suche und Filter.")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Alle Filter zurücksetzen" }).getAttribute("href"),
    ).toBe("/zeitachse");
  });

  it("names the search string the API did not understand", async () => {
    const { router } = renderApp(
      "/zeitachse?q=Spende&split=term&term=dkim:foo",
      withApi((call) =>
        call.url.pathname === "/api/timeline"
          ? Response.json(
              {
                detail: {
                  code: "invalid_query",
                  message: "dkim: takes one of pass, fail, no_key, unsigned: dkim:foo",
                },
              },
              { status: 400 },
            )
          : undefined,
      ),
    );
    expect(await screen.findByText("Suchbegriff nicht verstanden: dkim:foo")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Suchbegriff entfernen" }));
    await waitFor(() => expect(router.state.location.search).toBe("?q=Spende&split=term"));
  });

  it("names the part of q the API did not understand", async () => {
    renderApp(
      "/zeitachse?q=Spende+after:gestern",
      withApi((call) =>
        call.url.pathname.startsWith("/api/timeline")
          ? Response.json(
              {
                detail: {
                  code: "invalid_query",
                  message: "after: takes a day as YYYY-MM-DD or DD.MM.YYYY: after:gestern",
                },
              },
              { status: 400 },
            )
          : undefined,
      ),
    );
    expect(await screen.findByText("Suche nicht verstanden: after:gestern")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Suche leeren" })).toBeTruthy();
    // The first mentions leave the explanation to the chart.
    expect(await screen.findByText("Diese Suche lässt sich so nicht auswerten.")).toBeTruthy();
  });
});
