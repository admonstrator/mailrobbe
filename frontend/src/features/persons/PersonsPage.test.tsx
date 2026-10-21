import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MergeRequest, SuggestionDismiss, SuggestionPage } from "../../api/types";
import {
  certainMergePlan,
  certainMergeResult,
  mergeLogPage,
  personPage,
  suggestionPage,
  uncertainSuggestionPage,
} from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const personCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/persons");

function row(name: string | RegExp): HTMLElement {
  return screen.getByRole("link", { name }).closest("tr")!;
}

/** The fixture backend, with merged and dismissed suggestions gone from later answers; the
 *  uncertain tier, the run of "Alle sicheren zusammenführen", the merge log and its undo. */
function suggestionsBackend() {
  const gone = new Set<string>();
  const key = (a: number, b: number) => [a, b].sort((x, y) => x - y).join("-");
  return (call: ApiCall): unknown => {
    const path = call.url.pathname;
    if (path === "/api/persons/merge") {
      const { target, sources } = call.body as MergeRequest;
      for (const source of sources) gone.add(key(target, source));
    }
    if (path === "/api/persons/suggestions/dismiss") {
      const [a, b] = (call.body as SuggestionDismiss).persons;
      gone.add(key(a, b));
    }
    if (path === "/api/persons/suggestions" && call.url.searchParams.get("tier") === "uncertain") {
      return uncertainSuggestionPage;
    }
    if (path === "/api/persons/suggestions" && !call.url.searchParams.has("cursor")) {
      const items = suggestionPage.items.filter(
        (item) => !gone.has(key(item.first.id, item.second.id)),
      );
      const certain = suggestionPage.total - gone.size;
      const counts = { ...suggestionPage.counts, certain };
      return { ...suggestionPage, items, total: certain, counts };
    }
    if (path === "/api/persons/merge-certain") {
      return call.method === "POST" ? certainMergeResult : certainMergePlan;
    }
    if (path === "/api/persons/merges") return mergeLogPage;
    if (/^\/api\/persons\/merges\/\d+\/undo$/.test(path)) return { merges: 1, persons: 1 };
    if (path === "/api/persons/merge-batches/7/undo") return { merges: 289, persons: 311 };
    return fixtureApi(call);
  };
}

describe("person list", () => {
  it("renders persons, figures, aliases and the range from the API", async () => {
    const { calls } = renderApp("/personen");

    const anna = await screen.findByRole("link", { name: "Anna Keller" });
    expect(anna.getAttribute("href")).toBe("/personen/11");
    expect(screen.getByRole("heading", { name: "Personen", level: 1 })).toBeTruthy();
    expect(screen.getByText("1.710 Personen")).toBeTruthy();
    expect(await screen.findByRole("tab", { name: "Alias-Vorschläge (4 sicher)" })).toBeTruthy();
    expect(document.title).toBe("Personen · Mailrobbe");

    const cells = within(row("Anna Keller")).getAllByRole("cell");
    // Intl puts a no-break space before "%".
    expect(cells.map((cell) => cell.textContent?.replace(/\s/g, " "))).toEqual([
      "AKAnna Keller+2 Aliaseanna.keller@nordlicht-gmbh.example",
      "nordlicht-gmbh.example",
      "11.318",
      "3.412",
      "7.906",
      "214",
      "18.10.2026",
      "97,8 %",
    ]);
    expect(within(row("Verteiler Einkauf")).getByText("–")).toBeTruthy();
    expect(within(row("noreply@bank.example")).getByText("99,8 %")).toBeTruthy();
    expect(screen.getAllByRole("row")).toHaveLength(13);

    expect(screen.getByText("1–12 von 1.710")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Weiter ›" }).getAttribute("href")).toBe(
      "/personen?cursor=persons-page-2&page=2",
    );
    expect(personCalls(calls)[0].url.search).toBe("");
  });

  it("puts search and sort into the URL and the request", async () => {
    const { router, calls } = renderApp("/personen?cursor=persons-page-2&page=2");
    await screen.findByRole("link", { name: "Anna Keller" });
    expect(personCalls(calls)[0].url.searchParams.get("cursor")).toBe("persons-page-2");

    fireEvent.change(screen.getByRole("searchbox", { name: "Person suchen" }), {
      target: { value: " Keller " },
    });
    await waitFor(() => expect(router.state.location.search).toBe("?q=Keller"));
    // Typing replaces the history entry instead of adding one.
    expect(router.state.historyAction).toBe("REPLACE");
    await waitFor(() => expect(screen.getByText("1 Person gefunden")).toBeTruthy());
    expect(personCalls(calls).at(-1)!.url.search).toBe("?q=Keller");

    fireEvent.change(screen.getByRole("combobox", { name: "Sortierung" }), {
      target: { value: "recent" },
    });
    expect(router.state.location.search).toBe("?q=Keller&sort=recent");
    await waitFor(() =>
      expect(personCalls(calls).at(-1)!.url.search).toBe("?q=Keller&sort=recent"),
    );
  });

  it("goes back to the first page without a cursor", async () => {
    renderApp("/personen?sort=name&cursor=persons-page-2&page=2", (call) =>
      call.url.pathname === "/api/persons"
        ? { ...personPage, prev_cursor: "persons-page-1" }
        : fixtureApi(call),
    );
    expect(await screen.findByText("51–62 von 1.710")).toBeTruthy();
    expect(screen.getByRole("link", { name: "‹ Zurück" }).getAttribute("href")).toBe(
      "/personen?sort=name",
    );
  });

  it("explains an empty search and offers to clear it", async () => {
    renderApp("/personen?q=niemand");
    expect(await screen.findByText("Keine Person gefunden")).toBeTruthy();
    expect(screen.getByText("Kein Name und keine Adresse enthält „niemand“.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Suche leeren" }).getAttribute("href")).toBe(
      "/personen",
    );
  });
});

describe("alias suggestions", () => {
  it("lists both persons with their reasons in German", async () => {
    renderApp("/personen?tab=vorschlaege");
    const list = await screen.findByRole("list", { name: "Alias-Vorschläge" });
    const rows = within(list)
      .getAllByRole("listitem")
      .filter((item) => item.parentElement === list);
    expect(rows).toHaveLength(3);
    expect(within(rows[0]).getByText("Gleicher Name „peter hofmann“")).toBeTruthy();
    expect(within(rows[0]).getByText("Gleicher Adressteil „p.hofmann“")).toBeTruthy();
    expect(within(rows[0]).getByText("Sicher: gleicher Name und gleicher Adressteil")).toBeTruthy();
    expect(within(rows[1]).getByText("keller.anna@post.example")).toBeTruthy();
    expect(within(rows[1]).getByText("11.318 Mails")).toBeTruthy();
    expect(
      within(rows[1]).getByText("Sicher: Name passt zu beiden Adressen, gleiche Organisation"),
    ).toBeTruthy();
    expect(
      screen.getByRole("tab", { name: "Alias-Vorschläge (4 sicher)", selected: true }),
    ).toBeTruthy();
    expect(document.title).toBe("Alias-Vorschläge · Mailrobbe");
  });

  it("merges a suggestion into its first person, removes the row and confirms", async () => {
    const { calls } = renderApp("/personen?tab=vorschlaege", suggestionsBackend());
    const list = await screen.findByRole("list", { name: "Alias-Vorschläge" });
    const anna = within(list).getByText("keller.anna@post.example").closest("li")!;
    fireEvent.click(within(anna).getByRole("button", { name: "Zusammenführen" }));

    expect(
      await screen.findByText(/keller\.anna@post\.example ist jetzt ein Alias von/),
    ).toBeTruthy();
    expect(within(list).queryByText("keller.anna@post.example")).toBeNull();
    const merge = calls.find((call) => call.url.pathname === "/api/persons/merge")!;
    expect(merge.method).toBe("POST");
    expect(merge.body).toEqual({ target: 11, sources: [23] });
    expect(screen.getByRole("status").querySelector("a")?.getAttribute("href")).toBe(
      "/personen/11",
    );
    await waitFor(() =>
      expect(screen.getByRole("tab", { name: "Alias-Vorschläge (3 sicher)" })).toBeTruthy(),
    );
  });

  it("keeps the second person with andersherum and dismisses another", async () => {
    const { calls } = renderApp("/personen?tab=vorschlaege", suggestionsBackend());
    const list = await screen.findByRole("list", { name: "Alias-Vorschläge" });
    const peter = within(list).getByText("p.hofmann@post.example").closest("li")!;
    fireEvent.click(within(peter).getByRole("switch", { name: "andersherum" }));
    expect(
      within(peter)
        .getAllByText(/bleibt|wird Alias/)
        .map((tag) => tag.textContent),
    ).toEqual([" · wird Alias", " · bleibt"]);
    fireEvent.click(within(peter).getByRole("button", { name: "Zusammenführen" }));
    await waitFor(() => expect(within(list).queryByText("p.hofmann@post.example")).toBeNull());
    expect(calls.find((call) => call.url.pathname === "/api/persons/merge")!.body).toEqual({
      target: 26,
      sources: [15],
    });

    const jonas = within(list).getByText("jonas.brandt@mail.example").closest("li")!;
    fireEvent.click(within(jonas).getByRole("button", { name: "Verwerfen" }));
    expect(
      await screen.findByText(
        "Vorschlag verworfen: j.brandt@stadtwerke-beispiel.example und jonas.brandt@mail.example bleiben getrennt.",
      ),
    ).toBeTruthy();
    expect(within(list).queryByText("jonas.brandt@mail.example")).toBeNull();
    const dismiss = calls.find((call) => call.url.pathname === "/api/persons/suggestions/dismiss")!;
    expect(dismiss.method).toBe("POST");
    expect(dismiss.body).toEqual({ persons: [12, 25] });
  });

  it("shows the backend's refusal in the row", async () => {
    renderApp("/personen?tab=vorschlaege", (call) =>
      call.url.pathname === "/api/persons/merge"
        ? Response.json(
            { detail: { code: "invalid_merge", message: "person 15 is an alias" } },
            { status: 400 },
          )
        : fixtureApi(call),
    );
    const list = await screen.findByRole("list", { name: "Alias-Vorschläge" });
    const peter = within(list).getByText("p.hofmann@post.example").closest("li")!;
    fireEvent.click(within(peter).getByRole("button", { name: "Zusammenführen" }));
    expect((await within(peter).findByRole("alert")).textContent).toMatch(/^Das geht nicht/);
    expect(within(list).getByText("p.hofmann@post.example")).toBeTruthy();
  });

  it("loads more suggestions", async () => {
    const { calls } = renderApp("/personen?tab=vorschlaege");
    fireEvent.click(await screen.findByRole("button", { name: "Weitere laden" }));
    expect(await screen.findByText("a.keller@mail.example")).toBeTruthy();
    expect(screen.getByText("Gleicher Adressteil „a.keller“")).toBeTruthy();
    const pages = calls.filter((call) => call.url.pathname === "/api/persons/suggestions");
    expect(pages.at(-1)!.url.searchParams.get("cursor")).toBe("suggestions-page-2");
    expect(screen.queryByRole("button", { name: "Weitere laden" })).toBeNull();
  });

  it("shows the uncertain suggestions behind the switch", async () => {
    const { router, calls } = renderApp("/personen?tab=vorschlaege", suggestionsBackend());
    await screen.findByRole("list", { name: "Alias-Vorschläge" });
    expect(screen.getByRole("button", { name: "Alle sicheren zusammenführen" })).toBeTruthy();
    const tiers = () =>
      calls
        .filter((call) => call.url.pathname === "/api/persons/suggestions")
        .map((call) => call.url.searchParams.get("tier"));
    expect(new Set(tiers())).toEqual(new Set(["certain"]));

    fireEvent.click(screen.getByRole("switch", { name: "Unsichere Vorschläge zeigen (2.180)" }));
    expect(router.state.location.search).toBe("?tab=vorschlaege&unsicher=1");
    expect(await screen.findByText("Unsicher: nur der gleiche Name")).toBeTruthy();
    expect(screen.getByText("Unsicher: nur der gleiche Adressteil")).toBeTruthy();
    expect(
      screen.getByText("Unsicher: Name und Adressteil gleich, aber zu wenige gemeinsame Kontakte"),
    ).toBeTruthy();
    expect(screen.getByText("keller@schule-ost.example")).toBeTruthy();
    expect(screen.queryByText("p.hofmann@post.example")).toBeNull();
    expect(screen.queryByRole("button", { name: "Alle sicheren zusammenführen" })).toBeNull();
    expect(tiers()).toContain("uncertain");
    // The tab still counts the certain ones.
    expect(screen.getByRole("tab", { name: "Alias-Vorschläge (4 sicher)" })).toBeTruthy();
  });

  it("merges every certain suggestion after a confirmation and undoes the run", async () => {
    const { calls } = renderApp("/personen?tab=vorschlaege", suggestionsBackend());
    fireEvent.click(await screen.findByRole("button", { name: "Alle sicheren zusammenführen" }));
    const dialog = screen.getByRole("dialog", { name: "Alle sicheren Vorschläge zusammenführen" });
    expect(await within(dialog).findByText("312 Personen in 290 Zusammenführungen")).toBeTruthy();
    expect(
      within(dialog).getByText(/^4 Gruppen mit 27 Personen bleiben stehen: mehr als fünf/),
    ).toBeTruthy();
    expect(within(dialog).getByText(/lassen sich die Zusammenführungen einzeln/)).toBeTruthy();
    expect(calls.some((call) => call.method === "POST")).toBe(false);

    fireEvent.click(within(dialog).getByRole("button", { name: "312 Personen zusammenführen" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const posts = calls.filter((call) => call.method === "POST");
    expect(posts.map((call) => call.url.pathname)).toEqual(["/api/persons/merge-certain"]);
    const notice = await screen.findByText(
      /^312 Personen in 290 Zusammenführungen zusammengeführt/,
    );
    expect(
      within(notice).getByRole("link", { name: "Zuletzt zusammengeführt" }).getAttribute("href"),
    ).toBe("/personen?tab=zusammengefuehrt");

    fireEvent.click(within(notice).getByRole("button", { name: "Rückgängig" }));
    expect(
      await screen.findByText(
        "Der Lauf ist rückgängig gemacht: 311 Personen sind wieder eigenständig.",
      ),
    ).toBeTruthy();
    const undo = calls.find((call) => call.url.pathname === "/api/persons/merge-batches/7/undo")!;
    expect(undo.method).toBe("POST");
  });

  it("says when the suggestions were not computed yet and where to start that", async () => {
    const empty: SuggestionPage = {
      items: [],
      next_cursor: null,
      total: 0,
      counts: { certain: 0, uncertain: 0 },
      computed: false,
    };
    renderApp("/personen?tab=vorschlaege", (call) =>
      call.url.pathname === "/api/persons/suggestions" ? empty : fixtureApi(call),
    );
    expect(await screen.findByText("Die Vorschläge sind noch nicht berechnet")).toBeTruthy();
    const text = screen.getByText(/beim nächsten Import-Lauf neu berechnet/);
    expect(text.textContent).toBe(
      "Die Vorschläge werden beim nächsten Import-Lauf neu berechnet: unter Import auf „Import fortsetzen“ klicken.",
    );
    expect(within(text).getByRole("link", { name: "Import" }).getAttribute("href")).toBe("/import");
    expect(screen.queryByRole("button", { name: "Alle sicheren zusammenführen" })).toBeNull();
  });
});

describe("merge log", () => {
  it("lists the merges with their run and undoes one merge and a whole run", async () => {
    const { calls } = renderApp("/personen?tab=zusammengefuehrt", suggestionsBackend());
    expect(
      await screen.findByRole("heading", {
        name: "„Alle sicheren zusammenführen“ vom 21.10.2026 16:03",
      }),
    ).toBeTruthy();
    expect(document.title).toBe("Zuletzt zusammengeführt · Mailrobbe");
    expect(
      screen.getByText("290 Zusammenführungen, davon 1 rückgängig gemacht · Lena Vogt"),
    ).toBeTruthy();
    const run = screen.getByRole("list", { name: "Lauf 7" });
    const [peter, jonas] = within(run).getAllByRole("listitem");
    expect(peter.textContent).toMatch(/^p\.hofmann@post\.example in Peter Hofmann/);
    expect(
      within(jonas).getByText(/rückgängig gemacht am 21\.10\.2026 16:10 von Lena Vogt/),
    ).toBeTruthy();
    expect(within(jonas).queryByRole("button")).toBeNull();
    const alone = within(screen.getByRole("list", { name: "Einzeln" })).getByRole("listitem");
    expect(alone.textContent).toMatch(
      /^a\.keller@nordlicht-gmbh\.example, annakeller78@mail\.example in Anna Keller/,
    );

    fireEvent.click(within(peter).getByRole("button", { name: "Rückgängig" }));
    expect(
      await screen.findByText(
        "Rückgängig gemacht: 1 Zusammenführung, 1 Person ist wieder eigenständig.",
      ),
    ).toBeTruthy();
    const undo = calls.find((call) => call.url.pathname === "/api/persons/merges/42/undo")!;
    expect(undo.method).toBe("POST");

    fireEvent.click(screen.getByRole("button", { name: "Ganzen Lauf rückgängig" }));
    expect(
      await screen.findByText(
        "Rückgängig gemacht: 289 Zusammenführungen, 311 Personen sind wieder eigenständig.",
      ),
    ).toBeTruthy();
  });

  it("explains an empty log", async () => {
    renderApp("/personen?tab=zusammengefuehrt", (call) =>
      call.url.pathname === "/api/persons/merges"
        ? { items: [], batches: [], next_cursor: null, total: 0 }
        : fixtureApi(call),
    );
    expect(await screen.findByText("Noch nichts zusammengeführt")).toBeTruthy();
  });
});
