import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { entityFacetsFiltered, summaryFiltered } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const facetCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/mails/facets");

async function facets(): Promise<HTMLElement> {
  const heading = await screen.findByRole("heading", { name: "Entitäten", level: 2 });
  return heading.closest("section")!;
}

function group(panel: HTMLElement, name: string): HTMLElement {
  return within(panel).getByRole("group", { name });
}

/** The panel once its entities are there. */
async function loadedFacets(): Promise<HTMLElement> {
  const panel = await facets();
  await within(panel).findByRole("group", { name: "Themenbegriffe" });
  return panel;
}

describe("entity facets beside the mail list", () => {
  it("show the top entities per kind group, the themes' terms first", async () => {
    const { calls } = renderApp("/mails");
    const panel = await facets();
    await within(panel).findByText("in allen Mails");

    const groups = within(panel)
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent);
    expect(groups).toEqual([
      "Themenbegriffe",
      "Beträge",
      "Konten",
      "Organisationen",
      "Personen",
      "Orte",
      "Web",
      "E-Mail",
      "Telefon",
      "Daten",
    ]);
    const terms = group(panel, "Themenbegriffe");
    expect(
      within(terms)
        .getAllByRole("button")
        .map((chip) => chip.textContent),
    ).toEqual(["Spende 412", "Barspende 88", "Waffe 31"]);
    // IBANs and account numbers in one group, most mails first.
    expect(
      within(group(panel, "Konten"))
        .getAllByRole("button")
        .map((chip) => chip.textContent),
    ).toEqual(["DE89 3704 0044 0532 0130 00 12", "1234567 (BLZ 370 400 44) 4"]);
    expect(within(terms).getByRole("link", { name: "Seite von Spende" }).getAttribute("href")).toBe(
      "/entitaeten/302",
    );
    expect(within(panel).getByRole("link", { name: "Alle Entitäten" }).getAttribute("href")).toBe(
      "/entitaeten",
    );
    // Its own request with the list's filters (none), so the list never waits for it.
    expect(facetCalls(calls).map((call) => call.url.search)).toEqual([""]);
  });

  it("narrow the list with a click, keep the other filters, and widen it with a second", async () => {
    const { router, calls } = renderApp("/mails?has_attachment=true");
    const panel = await loadedFacets();
    const spende = await within(group(panel, "Themenbegriffe")).findByRole("button", {
      name: "Spende 77",
    });
    expect(within(panel).getByText("in 1.207 Treffern")).toBeTruthy();
    expect(spende.getAttribute("aria-pressed")).toBe("false");

    fireEvent.click(spende);
    expect(router.state.location.search).toBe("?has_attachment=true&entity=302");
    const chip = await screen.findByRole("button", {
      name: "Filter entfernen: Themenbegriff: Spende",
    });
    expect(chip).toBeTruthy();
    await waitFor(() =>
      expect(facetCalls(calls).at(-1)!.url.search).toBe("?has_attachment=true&entity=302"),
    );
    const refs = calls.filter((call) => call.url.pathname === "/api/entities/refs");
    expect(refs.map((call) => call.url.search)).toEqual(["?id=302"]);

    // A second entity narrows further (D86).
    fireEvent.click(
      within(group(panel, "Beträge")).getByRole("button", { name: /12\.500,00 EUR/ }),
    );
    expect(new URLSearchParams(router.state.location.search).getAll("entity")).toEqual([
      "302",
      "312",
    ]);
    await screen.findByRole("button", { name: "Filter entfernen: Betrag: 12.500,00 EUR" });

    const selected = within(group(panel, "Themenbegriffe")).getByRole("button", {
      name: "Spende 77",
    });
    expect(selected.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(selected);
    expect(router.state.location.search).toBe("?has_attachment=true&entity=312");
  });

  it("load up to 50 of a group on request", async () => {
    const { calls } = renderApp("/mails");
    const panel = await loadedFacets();
    const amounts = group(panel, "Beträge");
    await within(amounts).findByRole("button", { name: /100\.000,00 EUR/ });
    expect(within(amounts).getAllByRole("button", { pressed: false })).toHaveLength(8);
    // Groups with fewer entities than asked for have nothing more.
    expect(
      within(group(panel, "Themenbegriffe")).queryByRole("button", { name: "mehr" }),
    ).toBeNull();

    fireEvent.click(within(amounts).getByRole("button", { name: "mehr" }));
    await within(amounts).findByRole("button", { name: /80,00 EUR/ });
    expect(within(amounts).getAllByRole("button", { pressed: false })).toHaveLength(10);
    const more = facetCalls(calls).at(-1)!;
    expect(more.url.searchParams.getAll("kind")).toEqual(["amount"]);
    expect(more.url.searchParams.get("limit")).toBe("50");

    fireEvent.click(within(amounts).getByRole("button", { name: "weniger" }));
    expect(within(amounts).queryByRole("button", { name: /80,00 EUR/ })).toBeNull();
  });

  it("say when they count a sample of the matches", async () => {
    renderApp("/mails?q=Vertrag", (call) => {
      if (call.url.pathname === "/api/mails/facets") {
        return { ...entityFacetsFiltered, mails: 10000, sampled: true };
      }
      if (call.url.pathname === "/api/mails/summary") {
        return { ...summaryFiltered, total: 23456, exact: true };
      }
      return fixtureApi(call);
    });
    const panel = await facets();
    expect(
      await within(panel).findByText("in 10.000 von 23.456 Treffern (Stichprobe)"),
    ).toBeTruthy();
  });

  it("say nothing was found, and why while mails wait for the next import", async () => {
    renderApp("/mails", (call) =>
      call.url.pathname === "/api/mails/facets"
        ? { kinds: {}, mails: null, sampled: false }
        : fixtureApi(call),
    );
    const panel = await facets();
    expect(await within(panel).findByText("Keine Entitäten erkannt")).toBeTruthy();
    expect(
      await within(panel).findByText(
        "Sie erscheinen nach dem nächsten Import: 12.000 Mails sind noch nicht ausgewertet.",
      ),
    ).toBeTruthy();
  });

  it("step aside when the filter has no hits", async () => {
    const { calls } = renderApp("/mails?q=nichts", (call) =>
      call.url.pathname === "/api/mails/facets"
        ? { kinds: {}, mails: 0, sampled: false }
        : fixtureApi(call),
    );
    await waitFor(() => expect(facetCalls(calls)).toHaveLength(1));
    await waitFor(() =>
      expect(screen.queryByRole("heading", { name: "Entitäten", level: 2 })).toBeNull(),
    );
    expect(screen.queryByText("Keine Entitäten erkannt")).toBeNull();
  });

  it("offer a retry when they fail, while the list stays", async () => {
    renderApp("/mails", (call) =>
      call.url.pathname === "/api/mails/facets"
        ? Response.json({ detail: "boom" }, { status: 500 })
        : fixtureApi(call),
    );
    const panel = await facets();
    expect(
      await within(panel).findByText("Die Entitäten konnten nicht geladen werden."),
    ).toBeTruthy();
    expect(within(panel).getByRole("button", { name: "Erneut versuchen" })).toBeTruthy();
    expect(
      screen.getByRole("link", {
        name: "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung",
      }),
    ).toBeTruthy();
  });

  it("fold away, remembered in this browser, and ask for nothing while folded", async () => {
    const first = renderApp("/mails");
    const panel = await facets();
    await within(panel).findByText("in allen Mails");
    const hide = within(panel).getByRole("button", { name: "Ausblenden" });
    expect(hide.getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(hide);
    expect(localStorage.getItem("mailrobbe.facets")).toBe("closed");
    expect(within(panel).queryByRole("group", { name: "Themenbegriffe" })).toBeNull();
    first.router.dispose();
    cleanup();

    const { calls } = renderApp("/mails?has_attachment=true");
    const again = await facets();
    expect(within(again).getByRole("button", { name: "Einblenden" })).toBeTruthy();
    await screen.findByRole("link", {
      name: "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung",
    });
    expect(facetCalls(calls)).toHaveLength(0);
  });
});

describe("entity and amount filters of the mail list", () => {
  it("name entity chips by their labels, asked for in one request", async () => {
    const { router, calls } = renderApp("/mails?entity=312&entity=321&entity=999");
    expect(
      await screen.findByRole("button", { name: "Filter entfernen: Betrag: 12.500,00 EUR" }),
    ).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Filter entfernen: IBAN: DE89 3704 0044 0532 0130 00" }),
    ).toBeTruthy();
    // An id the archive no longer has keeps its number, so it can be removed.
    const unknown = screen.getByRole("button", { name: "Filter entfernen: Entität #999" });
    const refs = calls.filter((call) => call.url.pathname === "/api/entities/refs");
    expect(refs.map((call) => call.url.search)).toEqual(["?id=312&id=321&id=999"]);
    const page = calls.find((call) => call.url.pathname === "/api/mails")!;
    expect(page.url.searchParams.getAll("entity")).toEqual(["312", "321", "999"]);

    fireEvent.click(unknown);
    expect(router.state.location.search).toBe("?entity=312&entity=321");
  });

  it("read the amount in German notation on Enter and on leaving the field", async () => {
    const { router, calls } = renderApp("/mails");
    const column = screen.getByRole("complementary", { name: "Filter" });
    const field = within(column).getByRole("textbox", { name: "ab" });

    fireEvent.change(field, { target: { value: "10.000" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(router.state.location.search).toBe("?amount_min=10000");
    expect(
      await screen.findByRole("button", { name: "Filter entfernen: Betrag ab 10.000" }),
    ).toBeTruthy();
    await waitFor(() =>
      expect(calls.filter((call) => call.url.pathname === "/api/mails").at(-1)!.url.search).toBe(
        "?amount_min=10000",
      ),
    );

    fireEvent.change(field, { target: { value: "1.500,50" } });
    fireEvent.blur(field);
    expect(router.state.location.search).toBe("?amount_min=1500.5");
    expect((field as HTMLInputElement).value).toBe("1.500,5");

    // Not an amount: the filter stays.
    fireEvent.change(field, { target: { value: "viel" } });
    fireEvent.blur(field);
    expect(router.state.location.search).toBe("?amount_min=1500.5");
    expect((field as HTMLInputElement).value).toBe("1.500,5");

    fireEvent.change(field, { target: { value: "" } });
    fireEvent.keyDown(field, { key: "Enter" });
    expect(router.state.location.search).toBe("");
  });

  it("filter by the contexts of amounts, each a chip of its own", async () => {
    const { router } = renderApp("/mails?amount_min=5000");
    const column = screen.getByRole("complementary", { name: "Filter" });
    expect((within(column).getByRole("textbox", { name: "ab" }) as HTMLInputElement).value).toBe(
      "5.000",
    );
    const contexts = within(column).getByRole("group", { name: "Im Zusammenhang mit" });
    fireEvent.click(within(contexts).getByRole("checkbox", { name: "Quittung" }));
    fireEvent.click(within(contexts).getByRole("checkbox", { name: "Bargeld" }));
    expect(router.state.location.search).toBe(
      "?amount_min=5000&amount_context=cash&amount_context=receipt",
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Filter entfernen: Betrag: Bargeld" }),
    );
    expect(router.state.location.search).toBe("?amount_min=5000&amount_context=receipt");
    expect(within(contexts).getByRole("checkbox", { name: "Quittung" })).toHaveProperty(
      "checked",
      true,
    );
  });
});
