import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp } from "../../test/render";
import { withExcluded } from "./GlobalSearch";

const toggle = () => screen.getByRole("button", { name: /^Suchmenü/ });
/** The menu's panel, also while it is hidden. */
const menu = () => document.getElementById(toggle().getAttribute("aria-controls")!)!;
const field = () => screen.getByRole("searchbox", { name: "Suche" });

function searchFor(q: string) {
  fireEvent.change(field(), { target: { value: q } });
  fireEvent.submit(field().closest("form")!);
}

describe("the search menu of the header", () => {
  it("opens below the field and closes on Escape, a click outside and its button", () => {
    renderApp("/personen");
    expect(toggle().getAttribute("aria-expanded")).toBe("false");
    expect(menu().hidden).toBe(true);

    fireEvent.click(toggle());
    expect(toggle().getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("dialog", { name: "Suchmenü" })).toBe(menu());
    // the focus moves into the panel, to its first control
    expect(document.activeElement).toBe(within(menu()).getByRole("checkbox", { name: "Betreff" }));

    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(menu().hidden).toBe(true);
    expect(document.activeElement).toBe(toggle());

    fireEvent.click(toggle());
    fireEvent.pointerDown(document.body);
    expect(toggle().getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(toggle());
    fireEvent.click(toggle());
    expect(menu().hidden).toBe(true);
    expect(document.activeElement).toBe(toggle());
  });

  it("keeps its options on other screens and applies them to the next search", () => {
    const { router } = renderApp("/personen");
    fireEvent.click(toggle());
    expect(within(menu()).getByText("Gilt für die nächste Suche")).toBeTruthy();
    fireEvent.click(within(menu()).getByRole("checkbox", { name: "Dateiname" }));
    fireEvent.click(within(menu()).getByRole("checkbox", { name: "Ganzes Wort" }));
    const minHits = within(menu()).getByRole("textbox", { name: "Mindestens Treffer" });
    fireEvent.change(minHits, { target: { value: "4" } });
    fireEvent.keyDown(minHits, { key: "Enter" });
    // nothing changed yet but the menu and its badge
    expect(router.state.location.pathname).toBe("/personen");
    expect(toggle().getAttribute("aria-label")).toBe("Suchmenü, 3 Optionen geändert");

    searchFor("Vertrag");
    expect(router.state.location.pathname).toBe("/mails");
    expect(router.state.location.search).toBe(
      "?q=Vertrag&scope=subject&scope=body&scope=attachment&whole_word=true&min_hits=4",
    );
    expect(toggle().getAttribute("aria-expanded")).toBe("false");
  });

  it("appends excluded words to the search, at once on the list", () => {
    const { router } = renderApp("/mails?q=Vertrag");
    fireEvent.click(toggle());
    const exclude = within(menu()).getByRole("textbox", { name: "Wörter ausschließen" });
    fireEvent.change(exclude, { target: { value: "Entwurf -from:@beispiel.de" } });
    fireEvent.keyDown(exclude, { key: "Enter" });
    expect(search(router.state.location).get("q")).toBe("Vertrag -Entwurf -from:@beispiel.de");
    expect(field()).toHaveProperty("value", "Vertrag -Entwurf -from:@beispiel.de");
    expect(exclude).toHaveProperty("value", "");
  });

  it("puts excluded words into the field on other screens", () => {
    const { router } = renderApp("/personen");
    fireEvent.change(field(), { target: { value: "Spende" } });
    fireEvent.click(toggle());
    const exclude = within(menu()).getByRole("textbox", { name: "Wörter ausschließen" });
    fireEvent.change(exclude, { target: { value: '"Spende an"' } });
    fireEvent.click(within(menu()).getByRole("button", { name: "Ausschließen" }));
    expect(router.state.location.pathname).toBe("/personen");
    expect(field()).toHaveProperty("value", 'Spende -"Spende an"');
  });

  it("lists the saved searches, which open the list", async () => {
    const { router } = renderApp("/personen");
    fireEvent.click(toggle());
    const saved = within(menu()).getByRole("region", { name: "Gespeicherte Suchen" });
    const link = await within(saved).findByRole("link", { name: "Nordstahl an Einkauf" });
    expect(within(saved).getAllByRole("link")).toHaveLength(2);
    // nothing to save away from the list
    expect(within(menu()).getByRole("button", { name: "Aktuelle Suche speichern" })).toHaveProperty(
      "disabled",
      true,
    );
    fireEvent.click(link);
    expect(router.state.location.pathname).toBe("/mails");
    expect(router.state.location.search).toBe("?q=from%3Anordstahl&sort=date_asc");
    expect(toggle().getAttribute("aria-expanded")).toBe("false");
  });

  it("saves the list's search in the dialog of the list", async () => {
    renderApp("/mails?q=Vertrag&dkim=pass");
    fireEvent.click(toggle());
    fireEvent.click(within(menu()).getByRole("button", { name: "Aktuelle Suche speichern" }));
    const dialog = await screen.findByRole("dialog", { name: "Suche speichern" });
    expect(within(dialog).getByRole("textbox", { name: "Name" })).toHaveProperty(
      "value",
      "Vertrag",
    );
    await waitFor(() => expect(menu().hidden).toBe(true));
  });
});

describe("withExcluded", () => {
  it("prefixes every word with a minus, keeping phrases and existing minus signs", () => {
    expect(withExcluded("", "Entwurf")).toBe("-Entwurf");
    expect(withExcluded(" Vertrag ", 'Entwurf "erste Fassung" -has:attachment')).toBe(
      'Vertrag -Entwurf -"erste Fassung" -has:attachment',
    );
    expect(withExcluded("Vertrag", " - ")).toBe("Vertrag");
  });
});

const search = (location: { search: string }) => new URLSearchParams(location.search);
