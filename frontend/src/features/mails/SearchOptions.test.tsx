import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { hitsPage } from "../../test/fixtures";
import { openFilter } from "../../test/mailList";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

/** The list answers with the page of a search for "Neger" whenever q holds it. */
const negerApi = (call: ApiCall) =>
  call.url.pathname === "/api/mails" && call.url.searchParams.get("q") === "Neger"
    ? hitsPage
    : fixtureApi(call);

const toggle = () => screen.getByRole("button", { name: /^Suchmenü/ });

/** Opens the header's search menu and returns its panel. */
function openMenu(): HTMLElement {
  if (toggle().getAttribute("aria-expanded") !== "true") fireEvent.click(toggle());
  return screen.getByRole("dialog", { name: "Suchmenü" });
}

const menu = () => screen.getByRole("dialog", { name: "Suchmenü" });
const search = (location: { search: string }) => new URLSearchParams(location.search);

describe("the search options of the search menu (D177)", () => {
  it("are no longer a filter of the filter bar", async () => {
    renderApp("/mails?q=Neger", negerApi);
    const bar = await screen.findByRole("group", { name: "Filter" });
    const chips = within(bar).getAllByRole("button", { expanded: false });
    expect(chips[0].textContent).toBe("Zeitraum");
    expect(within(bar).queryByRole("button", { name: /^Suchen in/ })).toBeNull();
    const more = await openFilter("Weitere Filter");
    expect(within(more).queryByRole("checkbox", { name: "Ganzes Wort" })).toBeNull();
  });

  it("start with every place ticked, no whole words and no minimum", () => {
    renderApp("/mails?q=Neger", negerApi);
    const places = within(openMenu()).getByRole("group", { name: "Suchen in" });
    const boxes = within(places).getAllByRole("checkbox");
    expect(boxes.map((box) => box.parentElement!.textContent)).toEqual([
      "Betreff",
      "Mailtext",
      "Anhangstext",
      "Dateiname",
    ]);
    expect(
      boxes.every((box) => (box as HTMLInputElement).checked && !box.hasAttribute("disabled")),
    ).toBe(true);
    expect(within(menu()).getByRole("checkbox", { name: "Ganzes Wort" })).toHaveProperty(
      "checked",
      false,
    );
    expect(
      within(menu()).getByText(
        "ohne Wortstamm und Teilwörter, Groß/Klein egal, Umlaute und Akzente zählen",
      ),
    ).toBeTruthy();
    expect(within(menu()).getByRole("textbox", { name: "Mindestens Treffer" })).toHaveProperty(
      "value",
      "",
    );
    expect(within(menu()).getByText("Wirkt sofort auf die Liste")).toBeTruthy();
    expect(within(menu()).getByRole("button", { name: "Zurücksetzen" })).toHaveProperty(
      "disabled",
      true,
    );
  });

  it("limits the places by unticking, and keeps the last one ticked", async () => {
    const { router, calls } = renderApp("/mails?q=Neger", negerApi);
    openMenu();
    const box = (name: string) => within(menu()).getByRole("checkbox", { name });

    fireEvent.click(box("Dateiname"));
    expect(search(router.state.location).getAll("scope")).toEqual([
      "subject",
      "body",
      "attachment",
    ]);
    fireEvent.click(box("Anhangstext"));
    fireEvent.click(box("Betreff"));
    expect(search(router.state.location).getAll("scope")).toEqual(["body"]);
    expect(box("Mailtext")).toHaveProperty("checked", true);
    expect(box("Mailtext")).toHaveProperty("disabled", true);
    expect(box("Mailtext").closest("label")!.title).toBe("Mindestens ein Ort bleibt ausgewählt");
    expect(box("Betreff")).toHaveProperty("disabled", false);
    await waitFor(() =>
      expect(calls.some((call) => call.url.search === "?q=Neger&scope=body")).toBe(true),
    );
    expect(toggle().getAttribute("aria-label")).toBe("Suchmenü, 1 Optionen geändert");

    // Ticking all four again is the default, everywhere.
    for (const name of ["Betreff", "Anhangstext", "Dateiname"]) fireEvent.click(box(name));
    expect(router.state.location.search).toBe("?q=Neger");
    expect(toggle().getAttribute("aria-label")).toBe("Suchmenü");
  });

  it("searches whole words and asks for a minimum, ignoring what is no number", async () => {
    const { router } = renderApp("/mails?q=Neger&cursor=abc&page=2", negerApi);
    fireEvent.click(within(openMenu()).getByRole("checkbox", { name: "Ganzes Wort" }));
    expect(router.state.location.search).toBe("?q=Neger&whole_word=true");

    const field = within(menu()).getByRole("textbox", { name: "Mindestens Treffer" });
    fireEvent.change(field, { target: { value: "3" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(router.state.location.search).toBe("?q=Neger&whole_word=true&min_hits=3");

    for (const bad of ["0", "1000", "drei", "2,5"]) {
      fireEvent.change(field, { target: { value: bad } });
      fireEvent.blur(field);
      expect(field).toHaveProperty("value", "3");
    }
    expect(search(router.state.location).get("min_hits")).toBe("3");

    fireEvent.change(field, { target: { value: " " } });
    fireEvent.blur(field);
    expect(router.state.location.search).toBe("?q=Neger&whole_word=true");
    expect(
      await screen.findByRole("button", { name: "Filter entfernen: Ganzes Wort" }),
    ).toBeTruthy();
  });

  it("says that it acts on the words of the search", () => {
    renderApp(
      `/mails?${new URLSearchParams({ q: "subject:Vertrag to:@stadtwerke-beispiel.example" })}`,
    );
    expect(
      within(openMenu()).getByText("Wirkt auf die Wörter der Suche, nicht auf from:, has: usw."),
    ).toBeTruthy();
    fireEvent.click(within(menu()).getByRole("checkbox", { name: "Ganzes Wort" }));
    expect(within(menu()).getByRole("checkbox", { name: "Ganzes Wort" })).toHaveProperty(
      "checked",
      true,
    );
  });

  it("shows the operators in short lines, by group (D340, D341)", () => {
    renderApp("/mails");
    const syntax = within(openMenu()).getByRole("region", { name: "Operatoren" });
    const groups = [...syntax.querySelectorAll("h4")].map((heading) => heading.textContent);
    expect(groups).toEqual(["Wörter", "Personen und Domains", "Weitere"]);
    const lines = [...syntax.querySelectorAll("dt")].map(
      (term) => `${term.textContent} ${term.nextElementSibling!.textContent}`,
    );
    expect(lines).toContain('"finale Fassung" genau so geschrieben, auch ein einzelnes Wort');
    expect(lines).toContain("recipient:.ru an Adressen auf .ru");
    expect(lines).toContain("between:anna,bert die eine Seite schrieb, die andere empfing");
    expect(lines).toContain("-from:@beispiel.de Minus vor einem Operator schließt aus");
    expect(lines).toHaveLength(24);
  });

  it("is reset with the other filters, keeping the search text, and by its own button", async () => {
    const { router } = renderApp(
      "/mails?q=Neger&scope=subject&whole_word=true&min_hits=2&dkim=pass",
      negerApi,
    );
    expect(within(openMenu()).getByRole("textbox", { name: "Mindestens Treffer" })).toHaveProperty(
      "value",
      "2",
    );
    fireEvent.click(within(menu()).getByRole("button", { name: "Zurücksetzen" }));
    expect(router.state.location.search).toBe("?q=Neger&dkim=pass");
    await waitFor(() =>
      expect(within(menu()).getByRole("textbox", { name: "Mindestens Treffer" })).toHaveProperty(
        "value",
        "",
      ),
    );

    fireEvent.click(within(menu()).getByRole("checkbox", { name: "Ganzes Wort" }));
    const bar = screen.getByRole("group", { name: "Filter" });
    fireEvent.click(within(bar).getByRole("button", { name: "Zurücksetzen" }));
    expect(router.state.location.search).toBe("?q=Neger");
    expect(within(menu()).getByRole("checkbox", { name: "Ganzes Wort" })).toHaveProperty(
      "checked",
      false,
    );
  });

  it("act on a mail opened from the list, keeping it open", () => {
    const { router } = renderApp("/mails/184221?q=Neger&cursor=abc&page=2");
    fireEvent.click(within(openMenu()).getByRole("checkbox", { name: "Betreff" }));
    expect(router.state.location.pathname).toBe("/mails/184221");
    expect(router.state.location.search).toBe(
      "?q=Neger&scope=body&scope=attachment&scope=filename",
    );
  });
});
