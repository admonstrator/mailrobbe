import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { researchWithTags } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const api = (call: ApiCall) =>
  call.url.pathname === "/api/research" ? researchWithTags : fixtureApi(call);

function researchGroup(): HTMLElement {
  return within(screen.getByRole("complementary", { name: "Filter" })).getByRole("group", {
    name: "Recherche",
  });
}

const search = (router: ReturnType<typeof renderApp>["router"]) =>
  new URLSearchParams(router.state.location.search);

describe("research filters of the mail list", () => {
  it("filters by status, bookmark, note, tag and Akte through the URL", async () => {
    const { router, calls } = renderApp("/mails", api);
    const group = researchGroup();
    expect(within(group).getByText("Zahlen für das ganze Archiv")).toBeTruthy();
    await within(group).findByText("217"); // the overview has loaded
    const relevant = within(group).getByRole("checkbox", { name: /^Relevant/ });
    expect(relevant.closest("label")!.textContent).toBe("Relevant61");

    fireEvent.click(relevant);
    fireEvent.click(within(group).getByRole("checkbox", { name: /^Ungesichtet/ }));
    fireEvent.click(within(group).getByRole("checkbox", { name: /^Nur markierte/ }));
    fireEvent.click(within(group).getByRole("checkbox", { name: "Mit Notiz" }));
    fireEvent.click(within(group).getByRole("checkbox", { name: /^Spendenaffären/ }));
    fireEvent.click(within(group).getByRole("checkbox", { name: /^Story Nordstahl/ }));
    expect(router.state.location.search).toBe(
      "?flagged=true&review=unreviewed&review=relevant&tag=2&collection=1&has_note=true",
    );
    await waitFor(() =>
      expect(calls.some((call) => call.url.search === router.state.location.search)).toBe(true),
    );

    for (const label of [
      "Nur markierte",
      "Mit Notiz",
      "Status: Ungesichtet, Relevant",
      "Schlagwort: Spendenaffären",
      "Akte: Story Nordstahl",
    ]) {
      expect(screen.getByRole("button", { name: `Filter entfernen: ${label}` })).toBeTruthy();
    }
    fireEvent.click(
      screen.getByRole("button", { name: "Filter entfernen: Schlagwort: Spendenaffären" }),
    );
    expect(search(router).getAll("tag")).toEqual([]);
    fireEvent.click(
      screen.getByRole("button", { name: "Filter entfernen: Status: Ungesichtet, Relevant" }),
    );
    expect(router.state.location.search).toBe("?flagged=true&collection=1&has_note=true");
  });

  it("lists the most used tags first and the rest on request", async () => {
    renderApp("/mails", api);
    const tags = await within(researchGroup()).findByRole("group", { name: "Schlagwörter" });
    expect(
      within(tags)
        .getAllByRole("checkbox")
        .map((box) => box.closest("label")!.textContent),
    ).toEqual([
      "Prüfen41",
      "Spendenaffären37",
      "Verschleierung19",
      "Vertrag Nordstahl12",
      "Gewalt8",
    ]);
    fireEvent.click(within(tags).getByRole("button", { name: "Alle 7 anzeigen" }));
    expect(within(tags).getAllByRole("checkbox")).toHaveLength(7);
    expect(within(tags).getByRole("button", { name: "Weniger anzeigen" })).toBeTruthy();
  });

  it("shows ids it does not know by number, so they can be removed", async () => {
    const { router } = renderApp("/mails?tag=12&collection=3&review=seen", api);
    const group = researchGroup();
    const unknownTag = await within(group).findByRole("checkbox", { name: "Schlagwort #12" });
    expect(unknownTag).toHaveProperty("checked", true);
    expect(within(group).getByRole("checkbox", { name: "Akte #3" })).toHaveProperty(
      "checked",
      true,
    );
    expect(screen.getByRole("button", { name: "Filter entfernen: Schlagwort #12" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Filter entfernen: Akte #3" })).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Filter entfernen: Status: Gesichtet" }),
    ).toBeTruthy();
    fireEvent.click(unknownTag);
    expect(router.state.location.search).toBe("?review=seen&collection=3");
  });

  it("keeps the bookmark filter out of the group Weitere", async () => {
    renderApp("/mails?flagged=true", api);
    const column = screen.getByRole("complementary", { name: "Filter" });
    const more = within(column).getByRole("group", { name: "Weitere" });
    expect(within(more).queryByRole("checkbox", { name: /markierte/ })).toBeNull();
    expect(
      await within(researchGroup()).findByRole("checkbox", { name: /^Nur markierte/ }),
    ).toHaveProperty("checked", true);
  });
});
