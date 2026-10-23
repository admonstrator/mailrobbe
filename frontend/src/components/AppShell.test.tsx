import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { recordVisit } from "../lib/history";
import { renderApp } from "../test/render";
import { visitTime } from "./HistoryMenu";

function searchFor(q: string) {
  const field = screen.getByRole("searchbox", { name: "Suche" });
  fireEvent.change(field, { target: { value: q } });
  fireEvent.submit(field.closest("form")!);
}

describe("the header's search", () => {
  it("keeps the list's search options for a new search, and nothing else (D177)", () => {
    const { router } = renderApp(
      "/mails?q=Neger&dkim=pass&scope=filename&whole_word=true&min_hits=2&cursor=abc&page=2",
    );
    expect(screen.getByRole("searchbox", { name: "Suche" })).toHaveProperty("value", "Neger");
    searchFor("  Jude ");
    expect(router.state.location.pathname).toBe("/mails");
    expect(router.state.location.search).toBe("?q=Jude&scope=filename&whole_word=true&min_hits=2");
  });

  it("keeps them when the search is emptied", () => {
    const { router } = renderApp("/mails?q=Neger&whole_word=true");
    searchFor("");
    expect(router.state.location.search).toBe("?whole_word=true");
  });

  it("keeps them from a mail opened from the list too", () => {
    const { router } = renderApp("/mails/184221?q=Neger&scope=subject&scope=body");
    searchFor("Jude");
    expect(router.state.location.pathname).toBe("/mails");
    expect(router.state.location.search).toBe("?q=Jude&scope=subject&scope=body");
  });

  it("starts plain from other screens, and an empty search opens the whole list", () => {
    const { router } = renderApp("/personen?q=anna&scope=subject");
    searchFor("Jude");
    expect(router.state.location.pathname).toBe("/mails");
    expect(router.state.location.search).toBe("?q=Jude");

    searchFor("");
    expect(router.state.location.pathname).toBe("/mails");
    expect(router.state.location.search).toBe("");
  });
});

describe("the sidebar (D332)", () => {
  it("holds every screen in its groups and marks the open one", async () => {
    const { router } = renderApp("/ki");
    const navigation = screen.getByRole("navigation", { name: "Hauptnavigation" });
    const links = within(navigation).getAllByRole("link");
    const labels = links.map((link) => link.title);
    for (const label of ["Mails", "Personen", "Anhänge", "Akten", "Zeitachse", "Beziehungskarte"]) {
      expect(labels).toContain(label);
    }
    expect(labels.slice(-4)).toEqual(["Import", "KI", "Ausgeblendet", "Einstellungen"]);
    const ki = within(navigation).getByRole("link", { name: "KI" });
    expect(ki.getAttribute("aria-current")).toBe("page");
    expect(within(navigation).getByRole("heading", { name: "Auswerten" })).toBeTruthy();
    expect(within(navigation).getByRole("heading", { name: "System" })).toBeTruthy();

    fireEvent.click(within(navigation).getByRole("link", { name: "Import" }));
    expect(router.state.location.pathname).toBe("/import");
  });

  it("shows the counts of the archive and the team's saved searches", async () => {
    const { router } = renderApp("/personen");
    const navigation = screen.getByRole("navigation", { name: "Hauptnavigation" });
    const mails = within(navigation).getByRole("link", { name: "Mails" });
    await waitFor(() => expect(mails.textContent).toMatch(/^Mails\d/));
    const search = await within(navigation).findByRole("link", { name: "Nordstahl an Einkauf" });
    expect(within(navigation).getByRole("heading", { name: "Gespeicherte Suchen" })).toBeTruthy();
    fireEvent.click(search);
    expect(router.state.location.pathname).toBe("/mails");
    expect(router.state.location.search).toBe("?q=from%3Anordstahl&sort=date_asc");
    expect(search.getAttribute("aria-current")).toBe("page");
  });

  it("folds to icons and remembers it in this browser", () => {
    renderApp("/mails");
    const sidebar = screen.getByRole("complementary", { name: "Seitenleiste" });
    const header = screen.getByRole("button", { name: "Seitenleiste einklappen" });
    expect(header.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(within(sidebar).getByRole("button", { name: "Einklappen" }));
    expect(localStorage.getItem("mailrobbe.sidebar")).toBe("folded");
    expect(sidebar.className).toMatch(/folded/);
    expect(header.getAttribute("aria-label")).toBe("Seitenleiste ausklappen");
    // the labels stay for screen readers and tooltips
    expect(screen.getByRole("link", { name: "Personen" }).title).toBe("Personen");

    fireEvent.click(header);
    expect(localStorage.getItem("mailrobbe.sidebar")).toBe("open");
    expect(sidebar.className).not.toMatch(/folded/);
  });

  it("starts folded on a narrow window unless it was unfolded", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query.includes("1279"),
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
    renderApp("/mails");
    expect(screen.getByRole("complementary", { name: "Seitenleiste" }).className).toMatch(/folded/);
    cleanup();
    localStorage.setItem("mailrobbe.sidebar", "open");
    renderApp("/mails");
    expect(screen.getByRole("complementary", { name: "Seitenleiste" }).className).not.toMatch(
      /folded/,
    );
  });

  it("lists the three newest entries of the history", () => {
    recordVisit({ kind: "mail", id: 1, title: "Erste Mail", path: "/mails/1" });
    recordVisit({ kind: "person", id: 2, title: "Anna Keller", path: "/personen/2" });
    recordVisit({ kind: "akte", id: 3, title: "Story Nordstahl", path: "/akten/3" });
    recordVisit({ kind: "document", id: 4, title: "vertrag.pdf", path: "/anhaenge/4" });
    renderApp("/mails");
    const recent = screen.getByRole("region", { name: "Zuletzt angesehen" });
    expect(
      within(recent)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["vertrag.pdf", "Story Nordstahl", "Anna Keller"]);
  });
});

describe("the history (D333)", () => {
  const openHistory = () => {
    fireEvent.click(screen.getByRole("button", { name: "Zuletzt angesehen" }));
    return screen.getByRole("dialog", { name: "Zuletzt angesehen" });
  };

  it("lists the entries by day and kind, removes one and clears all", () => {
    const now = Date.now();
    recordVisit({
      kind: "person",
      id: 7,
      title: "Anna Keller",
      path: "/personen/7",
      at: now - 3 * 86_400_000,
    });
    recordVisit({
      kind: "document",
      id: 9,
      title: "vertrag.pdf",
      subtitle: "aus Angebot",
      path: "/anhaenge/9",
      at: now - 120_000,
    });
    recordVisit({
      kind: "mail",
      id: 5,
      title: "Rechnung 2026",
      subtitle: "Niklas Voigt",
      path: "/mails/5",
      at: now - 60_000,
    });
    const { router } = renderApp("/mails");
    let dialog = openHistory();
    expect(
      within(dialog).getByText("Nur in diesem Browser gespeichert, höchstens 100 Einträge."),
    ).toBeTruthy();
    const older = within(dialog).getByRole("region", { name: "Älter" });
    expect(within(older).getByText("Anna Keller")).toBeTruthy();
    const today = within(dialog).getByRole("region", { name: "Heute" });
    expect(
      within(today)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["Rechnung 2026Niklas Voigtvor 1 Min.", "vertrag.pdfaus Angebotvor 2 Min."]);

    fireEvent.click(within(dialog).getByRole("button", { name: "Dokumente" }));
    expect(within(dialog).getAllByRole("listitem")).toHaveLength(1);
    expect(
      within(dialog).getByRole("button", { name: "Dokumente" }).getAttribute("aria-pressed"),
    ).toBe("true");
    fireEvent.click(within(dialog).getByRole("button", { name: "Alle" }));

    fireEvent.click(
      within(dialog).getByRole("button", { name: "Aus dem Verlauf entfernen: vertrag.pdf" }),
    );
    expect(within(dialog).queryByText("vertrag.pdf")).toBeNull();
    expect(JSON.parse(localStorage.getItem("mailrobbe.history")!)).toHaveLength(2);

    fireEvent.click(within(dialog).getByRole("link", { name: /Rechnung 2026/ }));
    expect(router.state.location.pathname).toBe("/mails/5");
    expect(screen.queryByRole("dialog", { name: "Zuletzt angesehen" })).toBeNull();

    dialog = openHistory();
    fireEvent.click(within(dialog).getByRole("button", { name: "Verlauf leeren" }));
    expect(
      within(dialog).getByText(
        "Noch nichts angesehen. Geöffnete Mails, Personen, Dokumente und Akten erscheinen hier.",
      ),
    ).toBeTruthy();
  });

  it("closes on Escape and on a click outside, the focus back on its button", () => {
    renderApp("/mails");
    const button = screen.getByRole("button", { name: "Zuletzt angesehen" });
    openHistory();
    expect(button.getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Zuletzt angesehen" })).toBeNull();
    expect(document.activeElement).toBe(button);
    openHistory();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("dialog", { name: "Zuletzt angesehen" })).toBeNull();
  });

  it("says when an entry was opened", () => {
    const now = new Date(2026, 9, 23, 18, 0);
    expect(visitTime(now.getTime() - 4 * 60_000, now)).toBe("vor 4 Min.");
    expect(visitTime(new Date(2026, 9, 23, 9, 12).getTime(), now)).toBe("09:12");
    expect(visitTime(new Date(2026, 9, 22, 17, 42).getTime(), now)).toBe("17:42");
    expect(visitTime(new Date(2026, 9, 19, 11, 0).getTime(), now)).toBe("Mo., 19.10.");
  });
});

describe("the header", () => {
  it("shows the editor as initials and a running import with its share", async () => {
    localStorage.setItem("mailrobbe.editor", "Lena Vogt");
    renderApp("/mails");
    const editor = screen.getByRole("button", { name: "Bearbeitet als Lena Vogt" });
    expect(editor.textContent).toBe("LV");
    expect(editor.title).toBe("Bearbeitet als Lena Vogt");
    const state = await screen.findByRole("link", { name: /^Import/ });
    expect(state.getAttribute("href")).toBe("/import");
  });
});
