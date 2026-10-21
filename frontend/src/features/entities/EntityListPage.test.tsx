import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { entitySummary } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const listCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/entities");

function row(name: string): HTMLElement {
  return screen.getByRole("link", { name }).closest("tr")!;
}

describe("entity list", () => {
  it("is in the navigation after Anhänge", async () => {
    renderApp("/entitaeten");
    const navigation = screen.getByRole("navigation", { name: "Hauptnavigation" });
    const labels = within(navigation)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(labels.slice(0, 4)).toEqual(["Mails", "Personen", "Anhänge", "Entitäten"]);
    expect(within(navigation).getByRole("link", { name: "Entitäten" }).getAttribute("href")).toBe(
      "/entitaeten",
    );
    await screen.findByRole("link", { name: "Spende" });
  });

  it("renders tabs with counts, the waiting notice and the rows", async () => {
    const { calls } = renderApp("/entitaeten");
    await screen.findByRole("link", { name: "Spende" });
    expect(document.title).toBe("Entitäten · Mailrobbe");
    expect(screen.getByRole("heading", { name: "Entitäten", level: 1 })).toBeTruthy();

    const tabs = await screen.findAllByRole("tab");
    await waitFor(() => expect(tabs[0].textContent).toBe("Alle (22.454)"));
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Alle (22.454)",
      "Beträge (4.210)",
      "Konten (137)",
      "Organisationen (1.830)",
      "Personen (2.650)",
      "Orte (410)",
      "Telefon (1.203)",
      "E-Mail (2.290)",
      "Web (3.760)",
      "Daten (5.900)",
      "Themenbegriffe (64)",
    ]);
    expect(
      screen.getByText(
        /Entitäten werden beim nächsten Import ergänzt: 12\.000 Mails und 40 Dokumente sind noch nicht ausgewertet\./,
      ),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "Zum Import" }).getAttribute("href")).toBe("/import");

    // The kind in "Alle", the theme of a term, the country of an IBAN.
    expect(screen.getAllByRole("columnheader").map((header) => header.textContent)).toEqual([
      "Entität",
      "Art",
      "Mails",
      "Dokumente",
      "Zeitraum",
      "Mailliste",
    ]);
    const term = within(row("Spende")).getAllByRole("cell");
    expect(term.slice(1).map((cell) => cell.textContent)).toEqual([
      "SpendeSpendenaffären",
      "Themenbegriff",
      "412",
      "14",
      "14.03.2019 – 18.10.2026",
      "Mails",
    ]);
    expect(within(row("Spende")).getByRole("link", { name: "Spende" }).getAttribute("href")).toBe(
      "/entitaeten/302",
    );
    expect(
      within(row("Spende")).getByRole("link", { name: "Mails mit Spende" }).getAttribute("href"),
    ).toBe("/mails?entity=302");
    const iban = row("DE89 3704 0044 0532 0130 00");
    expect(within(iban).getByTitle("Deutschland").textContent).toBe("DE");
    // No document a dash; one day once; no dated mail a dash.
    expect(within(row("Köln")).getAllByRole("cell")[4].textContent).toBe("–");
    expect(within(row("12.500,00 EUR")).getAllByRole("cell")[5].textContent).toBe("14.03.2019");
    expect(
      within(row("kasse@freundeskreis-nord.example")).getAllByRole("cell")[5].textContent,
    ).toBe("–");

    expect(screen.getByText("1–7 von 22.454")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Weiter ›" }).getAttribute("href")).toBe(
      "/entitaeten?cursor=entities-page-2&page=2",
    );
    expect(listCalls(calls)[0].url.search).toBe("");
  });

  it("puts tabs, search and sort into the URL with the API's names", async () => {
    const { router, calls } = renderApp("/entitaeten");
    await screen.findByRole("link", { name: "Spende" });

    fireEvent.click(screen.getByRole("tab", { name: /^Konten/ }));
    expect(router.state.location.search).toBe("?kind=iban&kind=account");
    await waitFor(() =>
      expect(listCalls(calls).at(-1)!.url.search).toBe("?kind=iban&kind=account"),
    );
    // The kind column is for "Alle" only; the icon names the kind here.
    expect(screen.queryByRole("columnheader", { name: "Art" })).toBeNull();
    expect(screen.getAllByRole("img", { name: "IBAN" }).length).toBeGreaterThan(0);

    fireEvent.change(screen.getByRole("searchbox", { name: "Entitäten durchsuchen" }), {
      target: { value: " DE89 " },
    });
    await waitFor(() =>
      expect(router.state.location.search).toBe("?kind=iban&kind=account&q=DE89"),
    );
    expect(router.state.historyAction).toBe("REPLACE");

    const sort = screen.getByRole("combobox", { name: "Sortierung" });
    expect([...sort.querySelectorAll("option")].map((option) => option.textContent)).toEqual([
      "Meiste Mails",
      "Zuletzt erwähnt",
      "Zuerst erwähnt",
      "Name",
    ]);
    fireEvent.change(sort, { target: { value: "recent" } });
    expect(router.state.location.search).toBe("?kind=iban&kind=account&q=DE89&sort=recent");
    await waitFor(() =>
      expect(listCalls(calls).at(-1)!.url.search).toBe(
        "?kind=iban&kind=account&q=DE89&sort=recent",
      ),
    );
  });

  it("sorts amounts by value and takes a value range in German notation", async () => {
    const { router, calls } = renderApp("/entitaeten?kind=amount");
    await screen.findByRole("link", { name: "Spende" });
    const sort = screen.getByRole("combobox", { name: "Sortierung" });
    fireEvent.change(sort, { target: { value: "value" } });
    expect(router.state.location.search).toBe("?kind=amount&sort=value");

    const from = screen.getByRole("textbox", { name: "von" });
    fireEvent.change(from, { target: { value: "10.000" } });
    fireEvent.keyDown(from, { key: "Enter" });
    const to = screen.getByRole("textbox", { name: "bis" });
    fireEvent.change(to, { target: { value: "1 Mio" } });
    fireEvent.blur(to);
    expect((to as HTMLInputElement).value).toBe("");
    fireEvent.change(to, { target: { value: "250.000,50" } });
    fireEvent.blur(to);
    expect(router.state.location.search).toBe(
      "?kind=amount&value_min=10000&value_max=250000.5&sort=value",
    );
    await waitFor(() =>
      expect(listCalls(calls).at(-1)!.url.search).toBe(
        "?kind=amount&value_min=10000&value_max=250000.5&sort=value",
      ),
    );

    // Another tab drops the range and the sort by value.
    fireEvent.click(screen.getByRole("tab", { name: /^Themenbegriffe/ }));
    expect(router.state.location.search).toBe("?kind=term");
  });

  it("filters the terms by theme", async () => {
    const { router } = renderApp("/entitaeten?kind=term");
    const theme = await screen.findByRole("combobox", { name: "Thema" });
    expect([...theme.querySelectorAll("option")].map((option) => option.textContent)).toEqual([
      "Alle Themen",
      "Spendenaffären",
      "Gewalt",
    ]);
    fireEvent.change(theme, { target: { value: "gewalt" } });
    expect(router.state.location.search).toBe("?kind=term&detail=gewalt");
  });

  it("tells an empty archive from a search without a match", async () => {
    const empty = { items: [], next_cursor: null, prev_cursor: null };
    const noEntities = {
      ...entitySummary,
      kinds: Object.fromEntries(Object.keys(entitySummary.kinds).map((kind) => [kind, 0])),
      mails_waiting: 0,
      documents_waiting: 0,
    };
    renderApp("/entitaeten", (call) => {
      if (call.url.pathname === "/api/entities") return empty;
      if (call.url.pathname === "/api/entities/summary") return noEntities;
      return fixtureApi(call);
    });
    expect(await screen.findByText("Noch keine Entitäten")).toBeTruthy();
    expect(screen.queryByText(/beim nächsten Import ergänzt/)).toBeNull();
  });

  it("offers a reset when nothing matches", async () => {
    renderApp("/entitaeten?kind=iban&kind=account&q=XY99", (call) =>
      call.url.pathname === "/api/entities"
        ? { items: [], next_cursor: null, prev_cursor: null }
        : fixtureApi(call),
    );
    expect(await screen.findByText("Keine Entität gefunden")).toBeTruthy();
    expect(screen.getByText("Keine Entität dieser Art enthält „XY99“.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Filter zurücksetzen" }).getAttribute("href")).toBe(
      "/entitaeten?kind=iban&kind=account",
    );
  });
});
