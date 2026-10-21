import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { documentPage } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const listCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/documents");
const summaryCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/documents/summary");

function row(name: string): HTMLElement {
  return screen.getByRole("link", { name }).closest("tr")!;
}

const column = () => screen.getByRole("complementary", { name: "Filter" });

describe("document list", () => {
  it("is in the navigation after Personen", async () => {
    renderApp("/anhaenge");
    const navigation = screen.getByRole("navigation", { name: "Hauptnavigation" });
    const labels = within(navigation)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(labels.slice(0, 3)).toEqual(["Mails", "Personen", "Anhänge"]);
    expect(within(navigation).getByRole("link", { name: "Anhänge" }).getAttribute("href")).toBe(
      "/anhaenge",
    );
    await screen.findByRole("link", { name: "Rahmenvereinbarung_2026_final.pdf" });
  });

  it("renders rows, figures and the range from the API", async () => {
    const { calls } = renderApp("/anhaenge");

    const name = await screen.findByRole("link", { name: "Rahmenvereinbarung_2026_final.pdf" });
    expect(name.getAttribute("href")).toBe("/anhaenge/5101");
    expect(screen.getByRole("heading", { name: "Anhänge", level: 1 })).toBeTruthy();
    expect(document.title).toBe("Anhänge · Mailrobbe");
    expect(await screen.findByText("79.110 Dokumente")).toBeTruthy();

    const cells = within(row("Rahmenvereinbarung_2026_final.pdf")).getAllByRole("cell");
    expect(cells.slice(1).map((cell) => cell.textContent)).toEqual([
      "Rahmenvereinbarung_2026_final.pdf+2 Namen" +
        "§ 7 Zahlungen: Die Spende über 12.500,00 EUR geht auf das Konto DE89 3704 0044 0532 0130 00; weitere Spenden nach Absprache.",
      "PDF14 Seiten",
      "168 KB",
      "in 6 Mails",
      "28.09.2026",
      "18.10.2026",
      "Lukas Vogt",
    ]);
    expect(within(cells[7]).getByRole("link", { name: "Lukas Vogt" }).getAttribute("href")).toBe(
      "/personen/14",
    );
    // Without search words nothing is marked.
    expect(document.querySelectorAll("mark")).toHaveLength(0);

    // The text status shows only where it says something.
    expect(within(row("Aenderungsprotokoll.xlsx")).queryByText("Mit Text")).toBeNull();
    for (const [file, label] of [
      ["Scan_Vorstandssitzung_2019-03.pdf", "Gescannt"],
      ["Spendenliste_2019.xlsx", "Verschlüsselt"],
      ["IMG_2041.jpg", "Nicht unterstützt"],
      ["Kalkulation.ods", "Fehler"],
      ["Mitgliederliste.docx", "Ausstehend"],
    ]) {
      expect(within(row(file)).getByText(label)).toBeTruthy();
    }
    expect(within(row("(ohne Dateinamen)")).getByText("(unbekannt)")).toBeTruthy();
    expect(within(row("IMG_2041.jpg")).getByText("in 3 Mails")).toBeTruthy();
    expect(within(row("Unterlagen.zip")).getByText("in 1 Mail")).toBeTruthy();

    expect(screen.getByText("1–9 von 79.110")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Weiter ›" }).getAttribute("href")).toBe(
      "/anhaenge?cursor=documents-page-2&page=2",
    );
    expect(listCalls(calls)[0].url.search).toBe("");
    // One summary for the list and both groups of checkboxes while nothing is checked.
    expect(summaryCalls(calls).map((call) => call.url.search)).toEqual([""]);

    const filters = column();
    expect(
      within(filters).getByRole("checkbox", { name: /PDF/ }).closest("label")!.textContent,
    ).toBe("PDF21.904");
    expect(
      within(filters)
        .getByRole("checkbox", { name: /Gescannt \(ohne Text\)/ })
        .closest("label")!.textContent,
    ).toBe("Gescannt (ohne Text)6.904");
    expect(
      within(filters).getByText(/Ohne Textebene: Die Volltextsuche findet sie nicht/),
    ).toBeTruthy();
    // Rare statuses appear once documents have them; "pending" has none here.
    expect(within(filters).getByRole("checkbox", { name: /Zeitüberschreitung/ })).toBeTruthy();
    expect(within(filters).queryByRole("checkbox", { name: /Ausstehend/ })).toBeNull();
  });

  it("puts the search into the URL, marks its words and asks for them", async () => {
    const { router, calls } = renderApp("/anhaenge");
    await screen.findByRole("link", { name: "Rahmenvereinbarung_2026_final.pdf" });
    const field = screen.getByRole("searchbox", { name: "Anhänge durchsuchen" });
    expect(field.getAttribute("placeholder")).toBe("Text und Dateinamen der Anhänge durchsuchen …");

    fireEvent.change(field, { target: { value: " Spende -intern " } });
    await waitFor(() => expect(router.state.location.search).toBe("?q=Spende+-intern"));
    expect(router.state.historyAction).toBe("REPLACE");
    await waitFor(() =>
      expect(listCalls(calls).at(-1)!.url.searchParams.get("q")).toBe("Spende -intern"),
    );
    await waitFor(() =>
      expect([...document.querySelectorAll("mark")].map((mark) => mark.textContent)).toEqual([
        "Spende",
        "Spende",
      ]),
    );
    expect(await screen.findByText("214 Dokumente gefunden")).toBeTruthy();
  });

  it("filters by kind and status and counts each group without its own selection", async () => {
    const { router, calls } = renderApp("/anhaenge");
    const pdf = await within(column()).findByRole("checkbox", { name: /PDF/ });
    fireEvent.click(pdf);
    expect(router.state.location.search).toBe("?kind=pdf");
    fireEvent.click(within(column()).getByRole("checkbox", { name: /Tabelle/ }));
    expect(new URLSearchParams(router.state.location.search).getAll("kind")).toEqual([
      "pdf",
      "spreadsheet",
    ]);
    fireEvent.click(within(column()).getByRole("checkbox", { name: /Gescannt/ }));
    const search = new URLSearchParams(router.state.location.search);
    expect(search.getAll("text_status")).toEqual(["scanned"]);

    await waitFor(() =>
      expect(listCalls(calls).at(-1)!.url.search).toBe(
        "?kind=pdf&kind=spreadsheet&text_status=scanned",
      ),
    );
    await waitFor(() => {
      const asked = summaryCalls(calls).map((call) => call.url.search);
      // The figures, the kinds without the kind filter, the statuses without the status filter.
      expect(asked).toContain("?kind=pdf&kind=spreadsheet&text_status=scanned");
      expect(asked).toContain("?text_status=scanned");
      expect(asked).toContain("?kind=pdf&kind=spreadsheet");
    });

    fireEvent.change(screen.getByRole("combobox", { name: "Sortierung" }), {
      target: { value: "size" },
    });
    expect(router.state.location.search).toBe(
      "?kind=pdf&kind=spreadsheet&text_status=scanned&sort=size",
    );
    expect(
      [...screen.getByRole("combobox", { name: "Sortierung" }).querySelectorAll("option")].map(
        (option) => option.textContent,
      ),
    ).toEqual(["Neueste zuerst", "Älteste zuerst", "Meiste Mails", "Größte zuerst"]);
  });

  it("reads every filter from a shared link", async () => {
    const link = new URLSearchParams([
      ["name", "liste"],
      ["kind", "spreadsheet"],
      ["text_status", "encrypted"],
      ["date_from", "2019-01-01"],
      ["date_to", "2019-12-31"],
      ["person", "11"],
      ["person_role", "sent"],
      ["shared", "true"],
      ["external", "true"],
      ["sort", "oldest"],
    ]);
    const { calls } = renderApp(`/anhaenge?${link}`);
    await screen.findByRole("link", { name: "Rahmenvereinbarung_2026_final.pdf" });
    expect(listCalls(calls)[0].url.search).toBe(`?${link}`);

    const filters = column();
    expect(within(filters).getByRole("searchbox", { name: "Dateiname enthält" })).toHaveProperty(
      "value",
      "liste",
    );
    expect(within(filters).getByRole("checkbox", { name: /Tabelle/ })).toHaveProperty(
      "checked",
      true,
    );
    expect(within(filters).getByRole("checkbox", { name: /Verschlüsselt/ })).toHaveProperty(
      "checked",
      true,
    );
    expect(within(filters).getByLabelText("von")).toHaveProperty("value", "2019-01-01");
    expect(within(filters).getByRole("checkbox", { name: "In mehreren Mails" })).toHaveProperty(
      "checked",
      true,
    );
    expect(within(filters).getByRole("checkbox", { name: "Nur extern ↔ intern" })).toHaveProperty(
      "checked",
      true,
    );
    // The person comes with its name from the profile.
    expect(
      await within(filters).findByRole("button", { name: "Person entfernen: Anna Keller" }),
    ).toBeTruthy();
    expect(within(filters).getByRole("combobox", { name: "Rolle der Person" })).toHaveProperty(
      "value",
      "sent",
    );
    expect(screen.getByRole("combobox", { name: "Sortierung" })).toHaveProperty("value", "oldest");
    expect(await screen.findByText("214 Dokumente gefunden")).toBeTruthy();
  });

  it("types the file name filter into the URL", async () => {
    const { router } = renderApp("/anhaenge?kind=pdf");
    fireEvent.change(
      await within(column()).findByRole("searchbox", { name: "Dateiname enthält" }),
      {
        target: { value: "protokoll" },
      },
    );
    await waitFor(() => expect(router.state.location.search).toBe("?name=protokoll&kind=pdf"));
    expect(router.state.historyAction).toBe("REPLACE");
  });

  it("picks a person with its role, and removes it", async () => {
    const { router } = renderApp("/anhaenge");
    const field = await within(column()).findByRole("combobox", { name: "Person suchen" });
    fireEvent.focus(field);
    fireEvent.change(field, { target: { value: "Jonas" } });
    const option = await screen.findByRole("option", { name: /Jonas Brandt/ });
    fireEvent.click(option);
    expect(router.state.location.search).toBe("?person=12");

    const role = await within(column()).findByRole("combobox", { name: "Rolle der Person" });
    expect([...role.querySelectorAll("option")].map((item) => item.textContent)).toEqual([
      "gesendet oder empfangen",
      "gesendet",
      "empfangen",
    ]);
    fireEvent.change(role, { target: { value: "received" } });
    expect(router.state.location.search).toBe("?person=12&person_role=received");

    fireEvent.click(within(column()).getByRole("button", { name: /Person entfernen/ }));
    expect(router.state.location.search).toBe("");
  });

  it("opens from a person profile with the person filtered for", async () => {
    const { router, calls } = renderApp("/personen/11");
    fireEvent.click(await screen.findByRole("link", { name: "Anhänge dieser Person" }));
    expect(router.state.location.pathname).toBe("/anhaenge");
    expect(router.state.location.search).toBe("?person=11");
    expect(
      await within(column()).findByRole("button", { name: "Person entfernen: Anna Keller" }),
    ).toBeTruthy();
    await waitFor(() => expect(listCalls(calls).at(-1)!.url.search).toBe("?person=11"));
  });

  it("resets the filter column but keeps search and sort", async () => {
    const { router } = renderApp("/anhaenge?q=Spende&kind=pdf&shared=true&sort=mails");
    await screen.findByRole("link", { name: "Rahmenvereinbarung_2026_final.pdf" });
    fireEvent.click(within(column()).getByRole("button", { name: "Zurücksetzen" }));
    expect(router.state.location.search).toBe("?q=Spende&sort=mails");
  });

  it("shows a lower bound as mehr als", async () => {
    renderApp("/anhaenge?q=Vertrag", (call) =>
      call.url.pathname === "/api/documents/summary"
        ? { total: 10_000, exact: false, kinds: null, text_status: null }
        : fixtureApi(call),
    );
    expect(await screen.findByText("mehr als 10.000 Dokumente gefunden")).toBeTruthy();
    expect(screen.getByText("1–9 von mehr als 10.000")).toBeTruthy();
    // Out of time for the groups: no counters, the boxes stay.
    const pdf = within(column()).getByRole("checkbox", { name: /PDF/ });
    expect(pdf.closest("label")!.textContent).toBe("PDF");
  });

  it("goes back to the first page without a cursor", async () => {
    renderApp("/anhaenge?sort=size&cursor=documents-page-2&page=2", (call) =>
      call.url.pathname === "/api/documents"
        ? { ...documentPage, prev_cursor: "documents-page-1" }
        : fixtureApi(call),
    );
    expect(await screen.findByText("51–59 von 79.110")).toBeTruthy();
    expect(screen.getByRole("link", { name: "‹ Zurück" }).getAttribute("href")).toBe(
      "/anhaenge?sort=size",
    );
  });

  it("explains an empty result with and without filters", async () => {
    const empty = (call: ApiCall) =>
      call.url.pathname === "/api/documents"
        ? { items: [], next_cursor: null, prev_cursor: null }
        : fixtureApi(call);
    renderApp("/anhaenge?q=Niemand", empty);
    expect(await screen.findByText("Kein Dokument gefunden")).toBeTruthy();
    expect(
      screen.getByText(/Gescannte PDFs ohne Textebene findet die Volltextsuche nicht/),
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Alle Filter zurücksetzen" }).getAttribute("href"),
    ).toBe("/anhaenge");
  });

  it("explains an archive without documents", async () => {
    renderApp("/anhaenge", (call) =>
      call.url.pathname === "/api/documents"
        ? { items: [], next_cursor: null, prev_cursor: null }
        : fixtureApi(call),
    );
    expect(await screen.findByText("Noch keine Anhänge")).toBeTruthy();
  });

  it("offers a retry when the list fails", async () => {
    renderApp("/anhaenge", (call) =>
      call.url.pathname === "/api/documents"
        ? Response.json({ detail: "boom" }, { status: 500 })
        : fixtureApi(call),
    );
    expect(await screen.findByText("Die Anhänge konnten nicht geladen werden.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Erneut versuchen" })).toBeTruthy();
  });

  it("offers the first page for a stale cursor", async () => {
    renderApp("/anhaenge?kind=pdf&cursor=old&page=3", (call) =>
      call.url.pathname === "/api/documents"
        ? Response.json(
            { detail: { code: "invalid_cursor", message: "bad cursor" } },
            { status: 400 },
          )
        : fixtureApi(call),
    );
    expect(await screen.findByText("Diese Seite gibt es nicht mehr.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Zur ersten Seite" }).getAttribute("href")).toBe(
      "/anhaenge?kind=pdf",
    );
  });
});
