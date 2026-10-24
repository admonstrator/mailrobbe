import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { PersonLabel, PersonLabelUpdate, Timeline } from "../../api/types";
import { readHistory } from "../../lib/history";
import { annaProfile, mergeLogPage } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const mailCalls = (calls: ApiCall[]) => calls.filter((call) => call.url.pathname === "/api/mails");
const lastMailQuery = (calls: ApiCall[]) => mailCalls(calls).at(-1)!.url.searchParams;
const personMailQuery = (calls: ApiCall[]) =>
  mailCalls(calls)
    .filter((call) => call.url.searchParams.get("limit") !== "5")
    .at(-1)!.url.searchParams;

function section(heading: string): HTMLElement {
  return screen.getByRole("heading", { name: heading }).closest("section")!;
}

function figure(label: string): string {
  const item = within(screen.getByRole("list", { name: "Kennzahlen" }))
    .getByText(label)
    .closest("li")!;
  return [...item.children].map((child) => child.textContent).join(" ");
}

const tabNames = () => screen.getAllByRole("tab").map((tab) => tab.textContent);
const roleNames = () =>
  within(screen.getByRole("group", { name: "Rolle der Person" }))
    .getAllByRole("button")
    .map((button) => button.textContent);

/** Opens the menu "…" of the profile and chooses label. */
function chooseAction(label: string) {
  fireEvent.click(screen.getByRole("button", { name: "Weitere Aktionen" }));
  fireEvent.click(screen.getByRole("menuitem", { name: label }));
}

/** Shows the addresses of the profile's column. */
async function showAddresses(): Promise<HTMLElement> {
  fireEvent.click(await screen.findByRole("button", { name: "zeigen" }));
  return screen.getByRole("list", { name: "Adressen" });
}

/** A day timeline of 2026 with mails on three days, the busiest the 2nd of March. */
function dayTimeline(): Timeline {
  const starts: string[] = [];
  for (let time = Date.UTC(2026, 0, 1); time < Date.UTC(2027, 0, 1); time += 86_400_000) {
    starts.push(new Date(time).toISOString().slice(0, 10));
  }
  const busy: Record<string, number> = { "2026-01-05": 1, "2026-03-02": 8, "2026-03-03": 3 };
  const counts = starts.map((day) => busy[day] ?? 0);
  return {
    bucket: "day",
    coarsened: false,
    starts,
    total: {
      key: "all",
      label: null,
      person: null,
      thread_id: null,
      term: null,
      counts,
      total: 12,
      outliers: [],
      silent_from: null,
    },
    series: [],
    undated: 0,
    archive_end: "2026-10-18",
    timed_out: false,
  };
}

describe("person profile", () => {
  it("shows who it is in the column and the overview's figures, contacts and mails", async () => {
    const { calls } = renderApp("/personen/11");

    expect(await screen.findByRole("heading", { name: "Anna Keller", level: 1 })).toBeTruthy();
    expect(document.title).toBe("Anna Keller · Mailrobbe");
    const path = screen.getByRole("navigation", { name: "Pfad" });
    expect(within(path).getByRole("link", { name: "Personen" }).getAttribute("href")).toBe(
      "/personen",
    );
    expect(within(path).getByText("Anna Keller")).toBeTruthy();

    const facts = screen.getByRole("list", { name: "Angaben" });
    expect(
      within(facts).getByRole("link", { name: "nordlicht-gmbh.example" }).getAttribute("href"),
    ).toBe("/mails?sender_domain=nordlicht-gmbh.example");
    expect(within(facts).getByText("3 Adressen")).toBeTruthy();
    expect(
      within(facts).getByText(
        "Heißt in Mails „Anna Keller“ (3.201), „Keller, Anna“ (188), „Nordlicht Einkauf“ (23)",
      ),
    ).toBeTruthy();
    expect(within(facts).getByText("Aktiv 11.03.2016 bis 18.10.2026")).toBeTruthy();
    expect(within(facts).getByText("DKIM gültig bei 97,8 % der gesendeten Mails")).toBeTruthy();
    const addresses = await showAddresses();
    expect(within(addresses).getByText("anna.keller@nordlicht-gmbh.example")).toBeTruthy();
    const alias = within(addresses).getByText("a.keller@nordlicht-gmbh.example").closest("li")!;
    expect(alias.getAttribute("title")).toBe("1.840 Mails");

    // The most frequent contacts as avatars, every one in the tab.
    const frequent = section("Häufigste Kontakte");
    expect(within(frequent).getAllByRole("link")).toHaveLength(10);
    expect(within(frequent).getByRole("link", { name: "Jonas Brandt" }).getAttribute("title")).toBe(
      "Jonas Brandt, 388 Mails",
    );

    expect(screen.getByRole("link", { name: "Im Graphen zeigen" }).getAttribute("href")).toBe(
      "/karte?center=11",
    );
    expect(tabNames()).toEqual([
      "Überblick",
      "Mails 11.318",
      "Kontakte 214",
      "Anhänge",
      "Termine 3",
      "Signale 8",
      "KI fragen",
    ]);
    expect(screen.getByRole("tab", { name: "Überblick" }).getAttribute("aria-selected")).toBe(
      "true",
    );

    expect(figure("Mails")).toBe("11.318 Mails");
    expect(figure("Gesendet")).toBe("3.412 Gesendet");
    expect(figure("Empfangen (An/Cc)")).toBe("7.906 Empfangen (An/Cc)");
    expect(figure("Nur Cc")).toBe("1.204 Nur Cc");
    expect(figure("Kontakte")).toBe("214 Kontakte");

    const bars = within(section("Mit wem am meisten")).getAllByRole("listitem");
    expect(bars).toHaveLength(10);
    const jonas = within(bars[0]).getByRole("link");
    expect(jonas.getAttribute("href")).toBe("/personen/12");
    expect(jonas.textContent).toMatch(/Jonas Brandt388$/);

    const recent = await screen.findByRole("list", { name: "Neueste Mails" });
    const first = within(recent).getByRole("link", { name: /finale Fassung/ });
    expect(first.getAttribute("href")).toBe("/mails/184221?hide_duplicates=true&person=11");
    expect(within(first.closest("li")!).getByLabelText("gesendet")).toBeTruthy();
    const latest = mailCalls(calls).find((call) => call.url.searchParams.get("limit") === "5")!;
    expect(latest.url.search).toBe("?hide_duplicates=true&person=11&limit=5");
    expect(screen.getByRole("button", { name: "Alle 11.318 Mails" })).toBeTruthy();
  });

  it("keeps the tab in the URL and the mail state beside it", async () => {
    const { router } = renderApp("/personen/11");
    await screen.findByRole("heading", { name: "Anna Keller", level: 1 });

    fireEvent.click(screen.getByRole("tab", { name: "Mails 11.318" }));
    expect(router.state.location.search).toBe("?tab=mails");
    expect(await screen.findByRole("group", { name: "Rolle der Person" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Gesendet 3.412" }));
    // A narrowed mail list implies the tab Mails.
    expect(router.state.location.search).toBe("?role=sent");
    expect(screen.getByRole("tab", { name: "Mails 11.318" }).getAttribute("aria-selected")).toBe(
      "true",
    );

    fireEvent.click(screen.getByRole("tab", { name: "Termine 3" }));
    expect(router.state.location.search).toBe("?tab=termine&role=sent");
    expect(await screen.findByRole("heading", { name: "Termine" })).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Überblick" }));
    expect(router.state.location.search).toBe("?tab=ueberblick&role=sent");
    fireEvent.click(screen.getByRole("tab", { name: "Mails 11.318" }));
    expect(router.state.location.search).toBe("?role=sent");
    expect(roleNames()).toContain("Gesendet 3.412");
    expect(
      within(screen.getByRole("group", { name: "Rolle der Person" }))
        .getByRole("button", { name: "Gesendet 3.412" })
        .getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("opens the tab a link names and records the visit", async () => {
    renderApp("/personen/11?tab=signale");
    expect(await screen.findByRole("heading", { name: "Signale gesendeter Mails" })).toBeTruthy();
    expect(
      (await screen.findByRole("tab", { name: "Signale 8" })).getAttribute("aria-selected"),
    ).toBe("true");
    expect(screen.queryByRole("list", { name: "Kennzahlen" })).toBeNull();
    const [visit] = readHistory();
    expect(visit).toMatchObject({
      kind: "person",
      id: 11,
      title: "Anna Keller",
      subtitle: "anna.keller@nordlicht-gmbh.example",
      path: "/personen/11",
    });
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
    await showAddresses();

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
    expect(screen.getByText("annakeller78@mail.example")).toBeTruthy();
    const unmerge = calls.find((call) => call.url.pathname.endsWith("/unmerge"))!;
    expect(unmerge.method).toBe("POST");
    expect(unmerge.url.pathname).toBe("/api/persons/21/unmerge");
    expect(confirm).not.toHaveBeenCalled();
  });

  it("merges a searched person from the dialog and shows the merged profile", async () => {
    const { calls } = renderApp("/personen/11");
    await screen.findByRole("heading", { name: "Anna Keller", level: 1 });
    chooseAction("Adresse zusammenführen …");
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
    expect(screen.getByText("4 Adressen")).toBeTruthy();
    expect(within(await showAddresses()).getByText("keller.anna@post.example")).toBeTruthy();
    expect(calls.filter((call) => call.url.pathname === "/api/persons/11")).toHaveLength(1);
  });

  it("opens the merge dialog from the column's suggestions", async () => {
    renderApp("/personen/11");
    fireEvent.click(await screen.findByRole("button", { name: "2 Vorschläge zum Zusammenführen" }));
    expect(screen.getByRole("dialog", { name: "Adresse zusammenführen" })).toBeTruthy();
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
    await screen.findByRole("heading", { name: "Anna Keller", level: 1 });
    chooseAction("Adresse zusammenführen …");
    const dialog = screen.getByRole("dialog", { name: "Adresse zusammenführen" });
    fireEvent.click(within(dialog).getByRole("radio", { name: /keller\.anna@post\.example/ }));
    fireEvent.click(within(dialog).getByRole("button", { name: "Zusammenführen" }));
    expect((await within(dialog).findByRole("alert")).textContent).toMatch(
      /^Eine der Personen gibt es so nicht mehr/,
    );
    expect(screen.getByRole("dialog")).toBeTruthy();
  });

  it("offers the rarer actions in the menu", async () => {
    const { router } = renderApp("/personen/11");
    await screen.findByRole("heading", { name: "Anna Keller", level: 1 });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      expect(this.getAttribute("href")).toBe(
        "/api/mails/export.csv?person=11&hide_duplicates=true",
      );
      expect(this.hasAttribute("download")).toBe(true);
    });
    chooseAction("Alle Mails exportieren");
    expect(click).toHaveBeenCalledOnce();
    click.mockRestore();

    chooseAction("Anhänge dieser Person");
    expect(router.state.location.pathname).toBe("/anhaenge");
    expect(router.state.location.search).toBe("?person=11");
  });

  it("narrows the mail list by year, role and contact", async () => {
    const { router, calls } = renderApp("/personen/11?tab=mails");
    await screen.findByRole("link", { name: /finale Fassung/ });
    expect(roleNames()).toEqual([
      "Alle 11.318",
      "Gesendet 3.412",
      "Empfangen 7.906",
      "Nur Cc 1.204",
    ]);
    const first = screen.getByRole("link", { name: /finale Fassung/ }).closest("tr")!;
    expect(within(first).getByText("Von")).toBeTruthy();
    expect(within(first).getByRole("link", { name: "Jonas Brandt" })).toBeTruthy();
    expect(within(first).getByText("+2")).toBeTruthy();
    expect(screen.getByText("1–9 von 11.318")).toBeTruthy();
    expect(personMailQuery(calls).toString()).toBe("hide_duplicates=true&person=11");
    // The counts of the whole person are its figures; nothing to count.
    expect(calls.some((call) => call.url.pathname.endsWith("/mail-counts"))).toBe(false);

    fireEvent.change(screen.getByRole("combobox", { name: "Jahr" }), {
      target: { value: "2023" },
    });
    expect(router.state.location.search).toBe("?year=2023");
    await waitFor(() => expect(personMailQuery(calls).get("date_from")).toBe("2023-01-01"));
    expect(personMailQuery(calls).get("date_to")).toBe("2023-12-31");
    // Counts for a year come from mail-counts; Cc ran out of time.
    await waitFor(() =>
      expect(roleNames()).toEqual(["Alle 1.555", "Gesendet 455", "Empfangen 1.100", "Nur Cc –"]),
    );
    const counts = calls.filter((call) => call.url.pathname === "/api/persons/11/mail-counts");
    expect(counts.at(-1)!.url.search).toBe("?year=2023");

    fireEvent.click(screen.getByRole("button", { name: "Gesendet 455" }));
    expect(router.state.location.search).toBe("?role=sent&year=2023");
    await waitFor(() => expect(personMailQuery(calls).get("person_role")).toBe("sent"));
    expect(
      screen
        .getByRole("link", { name: "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung" })
        .getAttribute("href"),
    ).toBe(
      "/mails/184221?date_from=2023-01-01&date_to=2023-12-31&hide_duplicates=true&person=11&person_role=sent",
    );

    fireEvent.change(screen.getByRole("combobox", { name: "Jahr" }), { target: { value: "" } });
    expect(router.state.location.search).toBe("?role=sent");

    fireEvent.change(screen.getByRole("combobox", { name: "Mit Kontakt" }), {
      target: { value: "12" },
    });
    expect(router.state.location.search).toBe("?role=sent&contact=12");
    await waitFor(() => expect(personMailQuery(calls).getAll("between")).toEqual(["11", "12"]));
    expect(personMailQuery(calls).has("date_from")).toBe(false);
    await waitFor(() =>
      expect(
        calls.filter((call) => call.url.pathname === "/api/persons/11/mail-counts").at(-1)!.url
          .search,
      ).toBe("?contact=12"),
    );
  });

  it("searches only the person's mails, in every role (D330)", async () => {
    const { router, calls } = renderApp("/personen/11?role=sent");
    await screen.findByRole("link", { name: /finale Fassung/ });
    const field = screen.getByRole("searchbox", { name: "In den Mails der Person suchen" });

    fireEvent.change(field, { target: { value: "  Kasse " } });
    fireEvent.submit(field.closest("form")!);
    expect(router.state.location.search).toBe("?role=sent&q=Kasse");
    await waitFor(() => expect(lastMailQuery(calls).get("q")).toBe("Kasse"));
    expect(lastMailQuery(calls).getAll("person")).toEqual(["11"]);
    await waitFor(() =>
      expect(
        calls.filter((call) => call.url.pathname === "/api/persons/11/mail-counts").at(-1)!.url
          .search,
      ).toBe("?q=Kasse"),
    );
    expect(screen.getByRole("link", { name: "In der Mailliste öffnen" }).getAttribute("href")).toBe(
      "/mails?q=Kasse&hide_duplicates=true&person=11&person_role=sent",
    );

    fireEvent.change(field, { target: { value: "" } });
    expect(router.state.location.search).toBe("?role=sent");
  });

  it("shows a year of the person's mails by day and opens a day's mails", async () => {
    const { router, calls } = renderApp("/personen/11", (call) =>
      call.url.pathname === "/api/timeline" ? dayTimeline() : fixtureApi(call),
    );
    expect(await screen.findByRole("heading", { name: "12 Mails in 2026" })).toBeTruthy();
    const request = calls.find((call) => call.url.pathname === "/api/timeline")!;
    expect(request.url.search).toBe(
      "?person=11&hide_duplicates=true&bucket=day&date_from=2026-01-01&date_to=2026-12-31",
    );
    const activity = section("12 Mails in 2026");
    expect(within(activity).getByText("182 gesendet · 394 empfangen")).toBeTruthy();
    const days = within(activity).getByRole("group", { name: "Mails pro Tag in 2026" });
    expect(within(days).getAllByRole("button")).toHaveLength(365);
    const busiest = within(days).getByRole("button", { name: "8 Mails am 02.03.2026" });
    expect(busiest.getAttribute("data-level")).toBe("4");
    expect(
      within(days)
        .getByRole("button", { name: "3 Mails am 03.03.2026" })
        .getAttribute("data-level"),
    ).toBe("2");
    expect(
      within(days).getByRole("button", { name: "1 Mail am 05.01.2026" }).getAttribute("data-level"),
    ).toBe("1");
    expect(
      within(days)
        .getByRole("button", { name: "Keine Mail am 06.01.2026" })
        .getAttribute("data-level"),
    ).toBe("0");
    expect(
      within(activity).getByRole("link", { name: "In der Zeitachse öffnen" }).getAttribute("href"),
    ).toBe("/zeitachse?person=11");

    // The newest seven years are buttons, the older ones a menu; a year asks for its days.
    const years = within(activity).getByRole("group", { name: "Jahr" });
    expect(
      within(years)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["2026", "2025", "2024", "2023", "2022", "2021", "2020"]);
    expect(within(years).getByRole("button", { name: "2023" }).getAttribute("title")).toBe(
      "455 gesendet, 1.100 empfangen",
    );
    fireEvent.change(within(years).getByRole("combobox", { name: "Älteres Jahr" }), {
      target: { value: "2017" },
    });
    await waitFor(() =>
      expect(calls.filter((call) => call.url.pathname === "/api/timeline").at(-1)!.url.search).toBe(
        "?person=11&hide_duplicates=true&bucket=day&date_from=2017-01-01&date_to=2017-12-31",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "2026" }));
    fireEvent.click(await screen.findByRole("button", { name: "8 Mails am 02.03.2026" }));
    expect(router.state.location.pathname).toBe("/mails");
    expect(router.state.location.search).toBe(
      "?person=11&hide_duplicates=true&date_from=2026-03-02&date_to=2026-03-02",
    );
  });

  it("pages through the person's mails in the profile's URL", async () => {
    const { calls } = renderApp("/personen/11?role=cc&cursor=person-mails-2&page=2");
    expect(await screen.findByText("51–59 von 1.204")).toBeTruthy();
    expect(personMailQuery(calls).get("cursor")).toBe("person-mails-2");
    expect(personMailQuery(calls).get("person_role")).toBe("cc");
    expect(screen.getByRole("link", { name: "Weiter ›" }).getAttribute("href")).toBe(
      "/personen/11?role=cc&cursor=person-mails-2&page=3",
    );
  });

  it("lists all contacts in their tab, a page at a time", async () => {
    const { router, calls } = renderApp("/personen/11");
    await screen.findByRole("heading", { name: "Häufigste Kontakte" });
    fireEvent.click(
      within(section("Häufigste Kontakte")).getByRole("button", { name: "Alle 214" }),
    );
    expect(router.state.location.search).toBe("?tab=kontakte");
    const contacts = await screen.findByRole("list", { name: "Kontakte von Anna Keller" });
    expect(screen.getByText("10 von 214 Kontakten")).toBeTruthy();
    expect(
      within(contacts).getByRole("link", { name: "Mails mit Jonas Brandt" }).getAttribute("href"),
    ).toBe("/personen/11?contact=12");
    fireEvent.click(screen.getByRole("button", { name: "Weitere laden" }));
    expect(
      await within(contacts).findByRole("link", { name: "noreply@bank.example" }),
    ).toBeTruthy();
    const pages = calls.filter((call) => call.url.pathname === "/api/persons/11/contacts");
    expect(pages.map((call) => call.url.search)).toEqual(["", "?cursor=contacts-page-2"]);
  });

  it("lists the person's attachments and leads to the attachment list", async () => {
    const { calls } = renderApp("/personen/11?tab=anhaenge");
    const documents = await screen.findByRole("list", { name: "Anhänge der Person" });
    expect(within(documents).getAllByRole("listitem").length).toBeGreaterThan(0);
    const request = calls.find((call) => call.url.pathname === "/api/documents")!;
    expect(request.url.search).toBe("?person=11&limit=25");
    expect(
      screen.getByRole("link", { name: "In der Anhangsliste öffnen" }).getAttribute("href"),
    ).toBe("/anhaenge?person=11");
  });

  it("explains missing figures and counts the mails instead", async () => {
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
    expect(screen.queryByRole("heading", { name: "Häufigste Kontakte" })).toBeNull();
    fireEvent.click(screen.getByRole("tab", { name: "Mails" }));
    expect(await screen.findByRole("button", { name: "Alle 1.555" })).toBeTruthy();
  });

  it("says so when there is no such person", async () => {
    renderApp("/personen/999");
    expect(await screen.findByText("Diese Person gibt es nicht.")).toBeTruthy();
    expect(screen.getByText("Im Archiv gibt es keine Person mit der Nummer #999.")).toBeTruthy();
  });

  it("undoes a logged merge of the profile's aliases", async () => {
    // Anna's aliases came in by merge 40 until it is undone.
    let undone = false;
    const merged = { ...annaProfile, merges: [mergeLogPage.items[2]] };
    const { calls } = renderApp("/personen/11", (call) => {
      if (call.url.pathname === "/api/persons/merges/40/undo") {
        undone = true;
        return { merges: 1, persons: 2 };
      }
      if (call.url.pathname === "/api/persons/11") return undone ? annaProfile : merged;
      return fixtureApi(call);
    });
    const merges = await screen.findByRole("list", { name: "Zusammenführungen" });
    expect(section("Zusammengeführt")).toBeTruthy();
    const [row] = within(merges).getAllByRole("listitem");
    expect(row.textContent).toMatch(
      /^a\.keller@nordlicht-gmbh\.example, annakeller78@mail\.example20\.10\.2026 11:12/,
    );
    fireEvent.click(within(row).getByRole("button", { name: "Zusammenführung rückgängig" }));
    expect(
      await screen.findByText(
        "Zusammenführung rückgängig gemacht: a.keller@nordlicht-gmbh.example, annakeller78@mail.example sind wieder eigenständig.",
      ),
    ).toBeTruthy();
    const undo = calls.find((call) => call.url.pathname === "/api/persons/merges/40/undo")!;
    expect(undo.method).toBe("POST");
    // The profile is asked again and has no logged merge left.
    await waitFor(() =>
      expect(screen.queryByRole("list", { name: "Zusammenführungen" })).toBeNull(),
    );
  });

  it("shows no merge block without logged merges", async () => {
    renderApp("/personen/11");
    await screen.findByRole("heading", { name: "Anna Keller", level: 1 });
    expect(screen.queryByRole("heading", { name: "Zusammengeführt" })).toBeNull();
  });

  it("folds the uncertain suggestions behind their count in the merge dialog", async () => {
    renderApp("/personen/11", (call) =>
      call.url.pathname === "/api/persons/11"
        ? { ...annaProfile, suggestion_counts: { certain: 1, uncertain: 14 } }
        : fixtureApi(call),
    );
    await screen.findByRole("heading", { name: "Anna Keller", level: 1 });
    chooseAction("Adresse zusammenführen …");
    const dialog = screen.getByRole("dialog", { name: "Adresse zusammenführen" });
    const folded = within(dialog)
      .getByText("14 unsichere Vorschläge, hier die 1 mit den meisten Mails")
      .closest("details")!;
    expect(folded.open).toBe(false);
    expect(within(folded).getByRole("radio", { name: /a\.keller@mail\.example/ })).toBeTruthy();
    // The certain one stands outside.
    const certain = within(dialog).getByRole("radio", { name: /keller\.anna@post\.example/ });
    expect(folded.contains(certain)).toBe(false);
  });
});

describe("the team's label of a person (D156)", () => {
  const own: PersonLabel = {
    email: annaProfile.email,
    name: "Kassenwartin Nord",
    role: "Schatzmeisterin",
    note: `Führt die Kasse des Fördervereins. ${"Belege prüfen. ".repeat(20)}Ende der Notiz.`,
    editor: "Mara",
    updated_at: "2026-10-20T09:00:00Z",
  };

  /** The fixtures with a label that PUT /api/persons/11/label changes as the backend does. */
  function labelApi(start: PersonLabel | null) {
    let label = start;
    return (call: ApiCall) => {
      if (call.url.pathname === "/api/persons/11") return { ...annaProfile, label };
      if (call.url.pathname === "/api/persons/11/label" && call.method === "PUT") {
        const { name, role, note } = call.body as PersonLabelUpdate;
        label =
          name || role || note
            ? {
                email: annaProfile.email,
                name: name || null,
                role: role || null,
                note: note || null,
                editor: call.headers.get("X-Mailrobbe-Editor"),
                updated_at: "2026-10-21T08:00:00Z",
              }
            : null;
        return { ...annaProfile, label };
      }
      return fixtureApi(call);
    };
  }

  const labelCalls = (calls: ApiCall[]) =>
    calls.filter((call) => call.url.pathname === "/api/persons/11/label");

  it("shows the label as the title, the mails' name below it and the note shortened", async () => {
    const aliases = annaProfile.aliases.map((alias, index) =>
      index === 0 ? { ...alias, label: { name: "Einkauf Nord", role: null } } : alias,
    );
    renderApp("/personen/11", (call) =>
      call.url.pathname === "/api/persons/11"
        ? { ...annaProfile, aliases, label: own }
        : fixtureApi(call),
    );

    expect(
      await screen.findByRole("heading", { name: "Kassenwartin Nord", level: 1 }),
    ).toBeTruthy();
    expect(document.title).toBe("Kassenwartin Nord · Mailrobbe");
    expect(screen.getByText("Schatzmeisterin")).toBeTruthy();
    expect(screen.getByText(/^Anna Keller ·/).parentElement!.textContent).toBe(
      "Anna Keller · anna.keller@nordlicht-gmbh.example",
    );
    expect(screen.getByText("Benennung des Teams (Mara, 20.10.2026)")).toBeTruthy();
    expect(screen.queryByText(/Ende der Notiz\.$/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "mehr" }));
    expect(screen.getByText(/Ende der Notiz\./)).toBeTruthy();
    expect(screen.getByRole("button", { name: "weniger" })).toBeTruthy();

    const addresses = await showAddresses();
    expect(within(addresses).getByText("„Einkauf Nord“")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Benennung bearbeiten" })).toBeTruthy();
  });

  it("names a person under the editor's name", async () => {
    localStorage.setItem("mailrobbe.editor", "Mara");
    const { calls } = renderApp("/personen/11", labelApi(null));
    fireEvent.click(await screen.findByRole("button", { name: "Benennen" }));

    const dialog = screen.getByRole("dialog", { name: "Benennen" });
    expect(within(dialog).getByText(/^Die Benennung gilt für die Adresse/).textContent).toMatch(
      /anna\.keller@nordlicht-gmbh\.example und erscheint überall, wo die Person auftaucht/,
    );
    expect(within(dialog).getByText("Mara")).toBeTruthy();
    expect(within(dialog).queryByRole("button", { name: "Benennung entfernen" })).toBeNull();
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Klarname" }), {
      target: { value: "Kassenwartin Nord" },
    });
    fireEvent.change(within(dialog).getByRole("textbox", { name: "Rolle" }), {
      target: { value: "Schatzmeisterin" },
    });
    expect(within(dialog).getByText("17 / 200")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Speichern" }));

    expect(
      await screen.findByRole("heading", { name: "Kassenwartin Nord", level: 1 }),
    ).toBeTruthy();
    expect(screen.queryByRole("dialog")).toBeNull();
    const [put] = labelCalls(calls);
    expect(put.method).toBe("PUT");
    expect(put.body).toEqual({ name: "Kassenwartin Nord", role: "Schatzmeisterin", note: "" });
    expect(put.headers.get("X-Mailrobbe-Editor")).toBe("Mara");
    expect(screen.getByText("Schatzmeisterin")).toBeTruthy();
    expect(screen.getByText("Benennung des Teams (Mara, 21.10.2026)")).toBeTruthy();
  });

  it("shows an alias's label until the person's own address is named", async () => {
    const alias = annaProfile.aliases[0].email;
    renderApp("/personen/11", labelApi({ ...own, email: alias, note: null }));

    expect(
      await screen.findByRole("heading", { name: "Kassenwartin Nord", level: 1 }),
    ).toBeTruthy();
    expect(
      screen.getByText(`Benennung des Teams (Mara, 20.10.2026), von der Adresse ${alias}`),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Benennen" }));
    const dialog = screen.getByRole("dialog", { name: "Benennen" });
    expect(
      within(dialog).getByText(/^Bisher zeigt die Person die Benennung ihrer Adresse/).textContent,
    ).toBe(`Bisher zeigt die Person die Benennung ihrer Adresse ${alias}.`);
    expect(within(dialog).queryByRole("button", { name: "Benennung entfernen" })).toBeNull();
  });

  it("removes the label, and the mails' name is the title again", async () => {
    const { calls } = renderApp("/personen/11", labelApi(own));
    fireEvent.click(await screen.findByRole("button", { name: "Benennung bearbeiten" }));

    const dialog = screen.getByRole("dialog", { name: "Benennung bearbeiten" });
    expect(within(dialog).getByRole("textbox", { name: "Klarname" })).toHaveProperty(
      "value",
      "Kassenwartin Nord",
    );
    expect(within(dialog).getByText("Wird ohne Namen gespeichert.")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Benennung entfernen" }));

    expect(await screen.findByRole("heading", { name: "Anna Keller", level: 1 })).toBeTruthy();
    expect(labelCalls(calls).map((call) => call.body)).toEqual([{ name: "", role: "", note: "" }]);
    expect(screen.queryByText("Schatzmeisterin")).toBeNull();
    expect(screen.getByRole("button", { name: "Benennen" })).toBeTruthy();
  });
});

describe("a profile's mails by page (D193)", () => {
  it("jumps to a page at a page size, and another role goes back to the first page", async () => {
    const { router, calls } = renderApp("/personen/11?limit=25&page=3");
    await waitFor(() => expect(lastMailQuery(calls).get("page")).toBe("3"));
    expect(lastMailQuery(calls).get("limit")).toBe("25");
    expect(lastMailQuery(calls).has("cursor")).toBe(false);
    const nav = await screen.findByRole("navigation", { name: "Seiten" });
    expect(within(nav).getByRole("link", { name: "Seite 3" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(screen.getByRole("combobox", { name: "Pro Seite" })).toHaveProperty("value", "25");

    fireEvent.click(screen.getByRole("button", { name: /^Gesendet/ }));
    expect(router.state.location.search).toBe("?role=sent&limit=25");
    await waitFor(() => expect(lastMailQuery(calls).get("person_role")).toBe("sent"));
    expect(lastMailQuery(calls).has("page")).toBe(false);
  });
});
