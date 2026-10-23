import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { METADATA_VALUES_LIMIT } from "../../api/types";
import { documentSummary } from "../../test/fixtures";
import { openFilter } from "../../test/mailList";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

/** The popover of the facet's chip, which this opens. */
async function facet(name: string): Promise<HTMLElement> {
  await screen.findByRole("link", { name: "Rahmenvereinbarung_2026_final.pdf" });
  return openFilter(name);
}

const calls = (all: ApiCall[], path: string) => all.filter((call) => call.url.pathname === path);

describe("the facets Autor and Programm of the document list", () => {
  it("list the most frequent values with their documents", async () => {
    renderApp("/anhaenge");
    const author = await facet("Autor");
    await within(author).findByText("Peter Hofmann");
    const rows = within(author).getAllByRole("checkbox");
    expect(rows.map((box) => box.closest("label")!.textContent)).toEqual([
      "Peter Hofmann412",
      "Anna Keller233",
      "Buchhaltung87",
    ]);
    const program = await facet("Programm");
    expect(within(program).getByText("LibreOffice/7.6.4.1$Linux_X86_64")).toBeTruthy();
  });

  it("filter by a value, show it as a chip and count without their own selection", async () => {
    const { calls: all, router } = renderApp("/anhaenge");
    const author = await facet("Autor");
    fireEvent.click(await within(author).findByRole("checkbox", { name: /Anna Keller/ }));

    await waitFor(() => expect(router.state.location.search).toBe("?author=Anna+Keller"));
    const chip = within(author).getByRole("button", { name: "Autor entfernen: Anna Keller" });
    expect(within(author).queryByRole("checkbox", { name: /Anna Keller/ })).toBeNull();
    await waitFor(() =>
      expect(calls(all, "/api/documents").at(-1)!.url.search).toBe("?author=Anna+Keller"),
    );
    // The list's figures with the filter, the author facet's without it.
    const summaries = calls(all, "/api/documents/summary").map((call) => call.url.search);
    expect(summaries).toContain("?author=Anna+Keller");
    expect(summaries).toContain("");

    fireEvent.click(chip);
    await waitFor(() => expect(router.state.location.search).toBe(""));
  });

  it("search within every value", async () => {
    const { calls: all } = renderApp("/anhaenge?kind=pdf");
    const author = await facet("Autor");
    fireEvent.change(within(author).getByRole("searchbox", { name: "Autor suchen" }), {
      target: { value: "hofmann" },
    });

    expect(await within(author).findByText("Peter Hofmann-Berg")).toBeTruthy();
    const search = calls(all, "/api/documents/metadata-values").at(-1)!.url.searchParams;
    expect([search.getAll("kind"), search.get("field"), search.get("search")]).toEqual([
      ["pdf"],
      "author",
      "hofmann",
    ]);
    fireEvent.click(within(author).getByRole("checkbox", { name: /Peter Hofmann-Berg/ }));
    expect(
      await within(author).findByRole("button", { name: "Autor entfernen: Peter Hofmann-Berg" }),
    ).toBeTruthy();
    expect(
      (within(author).getByRole("searchbox", { name: "Autor suchen" }) as HTMLInputElement).value,
    ).toBe("");
  });

  it("show more of a capped list and point to the search for the rest", async () => {
    const authors = Array.from({ length: METADATA_VALUES_LIMIT }, (_, index) => ({
      value: `Person ${index + 1}`,
      documents: 100 - index,
    }));
    renderApp("/anhaenge", (call) =>
      call.url.pathname === "/api/documents/summary"
        ? { ...documentSummary, authors }
        : fixtureApi(call),
    );
    const author = await facet("Autor");
    await within(author).findByText("Person 1");
    expect(within(author).getAllByRole("checkbox")).toHaveLength(6);
    fireEvent.click(within(author).getByRole("button", { name: "mehr anzeigen" }));
    expect(within(author).getAllByRole("checkbox")).toHaveLength(METADATA_VALUES_LIMIT);
    expect(within(author).getByText("Die 20 häufigsten; weitere über die Suche.")).toBeTruthy();
    expect(within(author).getByRole("button", { name: "weniger" })).toBeTruthy();
  });
});
