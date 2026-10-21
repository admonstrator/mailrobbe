import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { annaProfile } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const mailCalls = (calls: ApiCall[]) => calls.filter((call) => call.url.pathname === "/api/mails");
const lastMailQuery = (calls: ApiCall[]) => mailCalls(calls).at(-1)!.url.searchParams;

function card(heading: string): HTMLElement {
  return screen.getByRole("heading", { name: heading }).closest("section")!;
}

function tile(label: string): string {
  const item = within(screen.getByRole("list", { name: "Kennzahlen" }))
    .getByText(label)
    .closest("li")!;
  return item.textContent!.replace(/\s/g, " ");
}

describe("person profile", () => {
  it("renders header, figures, top contacts, years and the person's mails", async () => {
    const { calls } = renderApp("/personen/11");

    expect(await screen.findByRole("heading", { name: "Anna Keller", level: 1 })).toBeTruthy();
    expect(document.title).toBe("Anna Keller · Mailrobbe");
    const path = screen.getByRole("navigation", { name: "Pfad" });
    expect(within(path).getByRole("link", { name: "Personen" }).getAttribute("href")).toBe(
      "/personen",
    );
    expect(within(path).getByText("Anna Keller")).toBeTruthy();

    const addresses = screen.getByRole("list", { name: "Adressen" });
    expect(within(addresses).getByText("Domain: nordlicht-gmbh.example")).toBeTruthy();
    const alias = within(addresses).getByText(/Alias: a\.keller@nordlicht-gmbh\.example/);
    expect(alias.getAttribute("title")).toBe("1.840 Mails");
    expect(
      screen.getByText(
        "Anzeigenamen in Mails: „Anna Keller“ (3.201), „Keller, Anna“ (188), „Nordlicht Einkauf“ (23)",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "Im Graphen zeigen" }).getAttribute("href")).toBe(
      "/karte?center=11",
    );
    expect(screen.getByRole("link", { name: "Alle Mails exportieren" }).getAttribute("href")).toBe(
      "/api/mails/export.csv?person=11&hide_duplicates=true",
    );

    expect(tile("Gesendet")).toBe("Gesendet3.412");
    expect(tile("Empfangen (An/Cc)")).toBe("Empfangen (An/Cc)7.906");
    expect(tile("Kontakte")).toBe("Kontakte214");
    expect(tile("DKIM gültig (gesendet)")).toBe("DKIM gültig (gesendet)97,8 %");
    expect(tile("Erste Mail")).toBe("Erste Mail201611.03.2016");
    expect(tile("Letzte Mail")).toBe("Letzte Mail202618.10.2026");

    const contacts = card("Top-Kontakte");
    const bars = within(contacts).getAllByRole("listitem");
    expect(bars).toHaveLength(10);
    expect(within(bars[0]).getByRole("link", { name: "Jonas Brandt" }).getAttribute("href")).toBe(
      "/personen/12",
    );
    expect(within(bars[0]).getByText("388")).toBeTruthy();
    expect(within(contacts).getByRole("button", { name: "Alle 214" })).toBeTruthy();

    const years = within(card("Aktivität pro Jahr")).getAllByRole("button");
    expect(years).toHaveLength(11);
    expect(years[7].getAttribute("aria-label")).toBe("2023: 455 gesendet, 1.100 empfangen");
    expect(years[7].getAttribute("aria-pressed")).toBe("false");

    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Alle 11.318",
      "Gesendet 3.412",
      "Empfangen 7.906",
      "Nur Cc 1.204",
    ]);
    const first = (await screen.findByRole("link", { name: /finale Fassung/ })).closest("tr")!;
    expect(within(first).getByText("Von")).toBeTruthy();
    expect(within(first).getByRole("link", { name: "Jonas Brandt" })).toBeTruthy();
    expect(within(first).getByText("+2")).toBeTruthy();
    const cc = screen.getByRole("link", { name: "AW: Vertrag Wartung Umspannwerk Süd" });
    expect(within(cc.closest("tr")!).getByText("Cc")).toBeTruthy();
    expect(within(cc.closest("tr")!).getByRole("link", { name: "Jonas Brandt" })).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung" })
        .getAttribute("href"),
    ).toBe("/mails/184221?hide_duplicates=true&person=11");
    expect(screen.getByText("1–9 von 11.318")).toBeTruthy();

    expect(mailCalls(calls)[0].url.search).toBe("?hide_duplicates=true&person=11");
    // The tab counts of the whole person are its figures; nothing to count.
    expect(calls.some((call) => call.url.pathname.endsWith("/mail-counts"))).toBe(false);
  });

  it("replaces an alias's URL with its root's without a second request", async () => {
    const { router, calls } = renderApp("/personen/21?role=sent");
    await waitFor(() => expect(router.state.location.pathname).toBe("/personen/11"));
    expect(router.state.location.search).toBe("?role=sent");
    expect(router.state.historyAction).toBe("REPLACE");
    expect(await screen.findByRole("heading", { name: "Anna Keller", level: 1 })).toBeTruthy();
    const profiles = calls.filter((call) => /^\/api\/persons\/\d+$/.test(call.url.pathname));
    expect(profiles.map((call) => call.url.pathname)).toEqual(["/api/persons/21"]);
  });

  it("unmerges an alias after asking once, inline", async () => {
    const confirm = vi.fn(() => true);
    vi.stubGlobal("confirm", confirm);
    const { calls } = renderApp("/personen/11");

    fireEvent.click(
      await screen.findByRole("button", { name: "Alias a.keller@nordlicht-gmbh.example lösen" }),
    );
    expect(
      screen.getByText("a.keller@nordlicht-gmbh.example wieder als eigene Person führen?"),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ja, lösen" }));

    await waitFor(() => expect(screen.queryByText(/wieder als eigene Person führen/)).toBeNull());
    expect(
      screen.queryByRole("button", { name: "Alias a.keller@nordlicht-gmbh.example lösen" }),
    ).toBeNull();
    expect(screen.getByText(/Alias: annakeller78@mail\.example/)).toBeTruthy();
    const unmerge = calls.find((call) => call.url.pathname.endsWith("/unmerge"))!;
    expect(unmerge.method).toBe("POST");
    expect(unmerge.url.pathname).toBe("/api/persons/21/unmerge");
    expect(confirm).not.toHaveBeenCalled();
  });

  it("merges a searched person from the dialog and shows the merged profile", async () => {
    const { calls } = renderApp("/personen/11");
    fireEvent.click(await screen.findByRole("button", { name: "+ Adresse zusammenführen" }));
    const dialog = screen.getByRole("dialog", { name: "Adresse zusammenführen" });

    // The profile's suggestions come first, with their reasons.
    const suggested = within(dialog).getAllByRole("radio");
    expect(suggested).toHaveLength(2);
    expect(within(dialog).getByText(/Gleicher Name „anna keller“/)).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: "Zusammenführen" })).toHaveProperty(
      "disabled",
      true,
    );

    // The search leaves out this person.
    const search = within(dialog).getByRole("searchbox", { name: "Person oder Adresse suchen" });
    fireEvent.change(search, { target: { value: "keller" } });
    expect(await within(dialog).findByText("Keine andere Person gefunden.")).toBeTruthy();
    fireEvent.change(search, { target: { value: "hofmann" } });
    fireEvent.click(await within(dialog).findByRole("radio", { name: /Peter Hofmann/ }));
    const query = calls.filter((call) => call.url.pathname === "/api/persons").at(-1)!;
    expect(query.url.search).toBe("?q=hofmann&limit=20");
    expect(
      within(dialog).getByText("p.hofmann@stadtwerke-beispiel.example wird Alias von Anna Keller."),
    ).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: "Zusammenführen" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const merge = calls.find((call) => call.url.pathname === "/api/persons/merge")!;
    expect(merge.method).toBe("POST");
    expect(merge.body).toEqual({ target: 11, sources: [15] });
    // The answer is the profile now, without asking for it again.
    expect(screen.getByText(/Alias: keller\.anna@post\.example/)).toBeTruthy();
    expect(calls.filter((call) => call.url.pathname === "/api/persons/11")).toHaveLength(1);
  });

  it("shows a refused merge inside the dialog", async () => {
    renderApp("/personen/11", (call) =>
      call.url.pathname === "/api/persons/merge"
        ? Response.json(
            { detail: { code: "not_found", message: "no person with id 23" } },
            { status: 404 },
          )
        : fixtureApi(call),
    );
    fireEvent.click(await screen.findByRole("button", { name: "+ Adresse zusammenführen" }));
    const dialog = screen.getByRole("dialog", { name: "Adresse zusammenführen" });
    fireEvent.click(within(dialog).getByRole("radio", { name: /keller\.anna@post\.example/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Zusammenführen" }));
    expect((await within(dialog).findByRole("alert")).textContent).toMatch(
      /^Eine der Personen gibt es so nicht mehr/,
    );
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("narrows the mail list by year, tab and contact", async () => {
    const { router, calls } = renderApp("/personen/11");
    const chart = await screen.findByRole("group", { name: "Mails pro Jahr" });
    await screen.findByRole("link", { name: /finale Fassung/ });

    const year = within(chart).getByRole("button", { name: /^2023:/ });
    fireEvent.click(year);
    expect(router.state.location.search).toBe("?year=2023");
    await waitFor(() => expect(lastMailQuery(calls).get("date_from")).toBe("2023-01-01"));
    expect(lastMailQuery(calls).get("date_to")).toBe("2023-12-31");
    expect(year.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("combobox", { name: "Jahr" })).toHaveProperty("value", "2023");
    // Counts for a year come from mail-counts; Cc ran out of time.
    await waitFor(() =>
      expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
        "Alle 1.555",
        "Gesendet 455",
        "Empfangen 1.100",
        "Nur Cc –",
      ]),
    );
    const counts = calls.filter((call) => call.url.pathname === "/api/persons/11/mail-counts");
    expect(counts.at(-1)!.url.search).toBe("?year=2023");

    fireEvent.click(screen.getByRole("tab", { name: "Gesendet 455" }));
    expect(router.state.location.search).toBe("?role=sent&year=2023");
    await waitFor(() => expect(lastMailQuery(calls).get("person_role")).toBe("sent"));
    expect(
      screen
        .getByRole("link", { name: "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung" })
        .getAttribute("href"),
    ).toBe(
      "/mails/184221?date_from=2023-01-01&date_to=2023-12-31&hide_duplicates=true&person=11&person_role=sent",
    );

    fireEvent.click(year);
    expect(router.state.location.search).toBe("?role=sent");
    expect(year.getAttribute("aria-pressed")).toBe("false");

    fireEvent.change(screen.getByRole("combobox", { name: "Mit Kontakt" }), {
      target: { value: "12" },
    });
    expect(router.state.location.search).toBe("?role=sent&contact=12");
    await waitFor(() => expect(lastMailQuery(calls).getAll("between")).toEqual(["11", "12"]));
    expect(lastMailQuery(calls).has("date_from")).toBe(false);
    expect(counts.length).toBeGreaterThan(0);
    await waitFor(() =>
      expect(
        calls.filter((call) => call.url.pathname === "/api/persons/11/mail-counts").at(-1)!.url
          .search,
      ).toBe("?contact=12"),
    );
  });

  it("pages through the person's mails in the profile's URL", async () => {
    const { calls } = renderApp("/personen/11?role=cc&cursor=person-mails-2&page=2");
    expect(await screen.findByText("51–59 von 1.204")).toBeTruthy();
    expect(lastMailQuery(calls).get("cursor")).toBe("person-mails-2");
    expect(lastMailQuery(calls).get("person_role")).toBe("cc");
    expect(screen.getByRole("link", { name: "Weiter ›" }).getAttribute("href")).toBe(
      "/personen/11?role=cc&cursor=person-mails-2&page=3",
    );
  });

  it("lists all contacts in a dialog, a page at a time", async () => {
    const { calls } = renderApp("/personen/11");
    fireEvent.click(await screen.findByRole("button", { name: "Alle 214" }));
    const dialog = screen.getByRole("dialog", { name: "Kontakte von Anna Keller" });
    expect(await within(dialog).findByText("10 von 214 Kontakten")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Weitere laden" }));
    expect(await within(dialog).findByRole("link", { name: "noreply@bank.example" })).toBeTruthy();
    const pages = calls.filter((call) => call.url.pathname === "/api/persons/11/contacts");
    expect(pages.map((call) => call.url.search)).toEqual(["", "?cursor=contacts-page-2"]);
    fireEvent.click(within(dialog).getByRole("button", { name: "Schließen" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("explains missing figures and counts the tabs instead", async () => {
    renderApp("/personen/11", (call) =>
      call.url.pathname === "/api/persons/11"
        ? { ...annaProfile, figures: null, top_contacts: [], years: [] }
        : fixtureApi(call),
    );
    expect(
      await screen.findByText(
        "Die Kennzahlen dieser Person werden beim nächsten Import berechnet.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Kennzahlen" })).toBeNull();
    expect(screen.getByText("Noch keine Kontakte ausgewertet.")).toBeTruthy();
    expect(screen.getByText("Noch keine datierten Mails ausgewertet.")).toBeTruthy();
    expect(await screen.findByRole("tab", { name: "Alle 1.555" })).toBeTruthy();
  });

  it("says so when there is no such person", async () => {
    renderApp("/personen/999");
    expect(await screen.findByText("Diese Person gibt es nicht.")).toBeTruthy();
    expect(screen.getByText("Im Archiv gibt es keine Person mit der Nummer #999.")).toBeTruthy();
  });
});
