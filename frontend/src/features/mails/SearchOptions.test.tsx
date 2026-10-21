import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { hitsPage } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

/** The list answers with the page of a search for "Neger" whenever q holds it. */
const negerApi = (call: ApiCall) =>
  call.url.pathname === "/api/mails" && call.url.searchParams.get("q") === "Neger"
    ? hitsPage
    : fixtureApi(call);

function group(): HTMLElement {
  const column = screen.getByRole("complementary", { name: "Filter" });
  return within(column).getByRole("group", { name: "Suche" });
}

const search = (location: { search: string }) => new URLSearchParams(location.search);

describe("the group Suche of the filter column (D177)", () => {
  it("comes first, with every place ticked, no whole words and no minimum", async () => {
    renderApp("/mails?q=Neger", negerApi);
    const column = screen.getByRole("complementary", { name: "Filter" });
    const legends = [...column.querySelectorAll("legend")].map((legend) => legend.textContent);
    expect(legends[0]).toBe("Suche");
    expect(legends[1]).toBe("Zeitraum");
    const places = within(group()).getByRole("group", { name: "Suchen in" });
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
    expect(within(group()).getByRole("checkbox", { name: "Ganzes Wort" })).toHaveProperty(
      "checked",
      false,
    );
    expect(
      within(group()).getByText(
        "ohne Wortstamm und Teilwörter, Groß/Klein egal, Umlaute und Akzente zählen",
      ),
    ).toBeTruthy();
    expect(within(group()).getByRole("textbox", { name: "Mindestens Treffer" })).toHaveProperty(
      "value",
      "",
    );
    // q has words: no note that the options need them.
    await screen.findAllByText("Dateiname 2");
    expect(within(group()).queryByText("Wirkt auf die Wörter der Suche oben")).toBeNull();
  });

  it("limits the places by unticking, and keeps the last one ticked", async () => {
    const { router, calls } = renderApp("/mails?q=Neger", negerApi);
    const box = (name: string) => within(group()).getByRole("checkbox", { name });

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

    // Ticking all four again is the default, everywhere.
    for (const name of ["Betreff", "Anhangstext", "Dateiname"]) fireEvent.click(box(name));
    expect(router.state.location.search).toBe("?q=Neger");
  });

  it("searches whole words and asks for a minimum, ignoring what is no number", async () => {
    const { router } = renderApp("/mails?q=Neger&cursor=abc&page=2", negerApi);
    fireEvent.click(within(group()).getByRole("checkbox", { name: "Ganzes Wort" }));
    expect(router.state.location.search).toBe("?q=Neger&whole_word=true");

    const field = within(group()).getByRole("textbox", { name: "Mindestens Treffer" });
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

  it("says that it acts on the words of the search when q has none", async () => {
    renderApp(
      `/mails?${new URLSearchParams({ q: "subject:Vertrag to:@stadtwerke-beispiel.example" })}`,
    );
    expect(await within(group()).findByText("Wirkt auf die Wörter der Suche oben")).toBeTruthy();
    // still usable
    fireEvent.click(within(group()).getByRole("checkbox", { name: "Ganzes Wort" }));
    expect(within(group()).getByRole("checkbox", { name: "Ganzes Wort" })).toHaveProperty(
      "checked",
      true,
    );
  });

  it("shows the syntax in a disclosure", () => {
    renderApp("/mails");
    expect(within(group()).getByText("Wirkt auf die Wörter der Suche oben")).toBeTruthy();
    const syntax = within(group()).getByText("Suchsyntax").closest("details")!;
    expect(syntax.open).toBe(false);
    const lines = [...syntax.querySelectorAll("li")].map((line) => line.textContent);
    expect(lines).toEqual([
      "betreff:Wort nur im Betreff",
      "text:Wort nur im Mailtext",
      "anhang:Wort nur im Text der Anhänge",
      "datei:Wort nur in Dateinamen",
      "-datei:NEG Minus schließt aus, auch vor from:, has: usw.",
      "Wort or Wort eines der beiden",
      '"genaue Phrase" die Wörter in dieser Folge',
      "subject:Wort Teil des Betreffs, auch mitten im Wort",
    ]);
  });

  it("is reset with the other filters, keeping the search text", async () => {
    const { router } = renderApp(
      "/mails?q=Neger&scope=subject&whole_word=true&min_hits=2&dkim=pass",
      negerApi,
    );
    const column = screen.getByRole("complementary", { name: "Filter" });
    expect(within(group()).getByRole("textbox", { name: "Mindestens Treffer" })).toHaveProperty(
      "value",
      "2",
    );
    fireEvent.click(within(column).getByRole("button", { name: "Zurücksetzen" }));
    expect(router.state.location.search).toBe("?q=Neger");
    await waitFor(() =>
      expect(within(group()).getByRole("textbox", { name: "Mindestens Treffer" })).toHaveProperty(
        "value",
        "",
      ),
    );
  });
});
