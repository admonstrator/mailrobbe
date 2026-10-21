import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MergeRequest, SuggestionDismiss } from "../../api/types";
import { personPage, suggestionPage } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const personCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/persons");

function row(name: string | RegExp): HTMLElement {
  return screen.getByRole("link", { name }).closest("tr")!;
}

/** The fixture backend, with merged and dismissed suggestions gone from later answers. */
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
    if (path === "/api/persons/suggestions" && !call.url.searchParams.has("cursor")) {
      const items = suggestionPage.items.filter(
        (item) => !gone.has(key(item.first.id, item.second.id)),
      );
      return { ...suggestionPage, items, total: suggestionPage.total - gone.size };
    }
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
    expect(await screen.findByRole("tab", { name: "Alias-Vorschläge (4)" })).toBeTruthy();
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
    expect(within(rows[1]).getByText("keller.anna@post.example")).toBeTruthy();
    expect(within(rows[1]).getByText("11.318 Mails")).toBeTruthy();
    expect(screen.getByRole("tab", { name: "Alias-Vorschläge (4)", selected: true })).toBeTruthy();
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
      expect(screen.getByRole("tab", { name: "Alias-Vorschläge (3)" })).toBeTruthy(),
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
});
