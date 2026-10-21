import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { filteredQuery, mailDetail } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const filteredPath = `/mails?${new URLSearchParams({ q: filteredQuery, has_attachment: "true" })}`;

function tile(label: string): HTMLElement {
  return within(screen.getByRole("main")).getByText(label, { selector: "span" }).parentElement!;
}

const timelineCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/timeline");

/** The compact timeline, 36 months laid out 10 px each, as jsdom lays out nothing. */
async function timeline(): Promise<HTMLElement> {
  const slider = await screen.findByRole("slider", { name: "Mails pro Monat" });
  vi.spyOn(slider, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, 360, 80));
  return slider;
}

describe("mail list", () => {
  it("renders rows, chips, tiles and the range from the API", async () => {
    const { calls } = renderApp(filteredPath);

    const subject = await screen.findByRole("link", {
      name: "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung",
    });
    expect(subject.getAttribute("href")).toBe(`/mails/184221?${filteredPath.split("?")[1]}`);
    expect(screen.getAllByRole("row")).toHaveLength(13);
    expect(screen.getByText("(kein Betreff)")).toBeTruthy();
    expect(screen.getAllByRole("img", { name: "DKIM ungültig" })).toHaveLength(1);
    expect(screen.getAllByRole("link", { name: "Anna Keller" })[0].getAttribute("href")).toBe(
      "/personen/11",
    );
    expect(screen.getByText("+11")).toBeTruthy();

    for (const label of ["Betreff: „Vertrag“", "to: @stadtwerke-beispiel.example", "Mit Anhang"]) {
      expect(screen.getByRole("button", { name: `Filter entfernen: ${label}` })).toBeTruthy();
    }

    await waitFor(() => expect(within(tile("Mails im Filter")).getByText("1.207")).toBeTruthy());
    expect(within(tile("DKIM gültig")).getByText("65,7 %")).toBeTruthy();
    expect(within(tile("DKIM gültig")).getByText("von 1.196 signierten Mails")).toBeTruthy();
    expect(within(tile("Schlüssel nicht abrufbar")).getByText("401")).toBeTruthy();
    expect(within(tile("Beteiligte Personen")).getByText("38 Domains")).toBeTruthy();
    expect(screen.getByText("1.207 Treffer · sortiert nach Datum ↓")).toBeTruthy();
    expect(screen.getByText("1–12 von 1.207")).toBeTruthy();

    const page = calls.find((call) => call.url.pathname === "/api/mails")!;
    expect(page.url.searchParams.get("q")).toBe(filteredQuery);
    expect(page.url.searchParams.get("has_attachment")).toBe("true");
    expect(screen.getByRole("link", { name: "Weiter ›" }).getAttribute("href")).toContain(
      "cursor=cursor-page-2&page=2",
    );
    expect(screen.getByRole("link", { name: "Export CSV" }).getAttribute("href")).toBe(
      `/api/mails/export.csv?${new URLSearchParams({ q: filteredQuery, has_attachment: "true" })}`,
    );
  });

  it("removes a chip's term from q and loads the list again", async () => {
    const { router, calls } = renderApp(filteredPath);
    fireEvent.click(
      await screen.findByRole("button", { name: "Filter entfernen: Betreff: „Vertrag“" }),
    );
    const search = new URLSearchParams(router.state.location.search);
    expect(search.get("q")).toBe("to:@stadtwerke-beispiel.example");
    expect(search.get("has_attachment")).toBe("true");
    await waitFor(() =>
      expect(
        calls.some((call) => call.url.searchParams.get("q") === "to:@stadtwerke-beispiel.example"),
      ).toBe(true),
    );
  });

  it("treats all DKIM boxes checked as no filter and unchecking one as a filter", async () => {
    const { router } = renderApp("/mails");
    const column = screen.getByRole("complementary", { name: "Filter" });
    const unsigned = await within(column).findByRole("checkbox", { name: /Nicht signiert/ });
    expect(unsigned).toHaveProperty("checked", true);
    expect(within(column).queryByRole("checkbox", { name: /DNS-Fehler/ })).toBeNull();

    fireEvent.click(unsigned);
    expect(new URLSearchParams(router.state.location.search).getAll("dkim")).toEqual([
      "pass",
      "fail",
      "no_key",
    ]);
    fireEvent.click(await within(column).findByRole("checkbox", { name: /Nicht signiert/ }));
    expect(router.state.location.search).toBe("");
  });

  it("keeps a person's role from the profile and names it in the person's chip", async () => {
    const { router, calls } = renderApp("/mails?person=11&person_role=sent&hide_duplicates=true");
    const chip = await screen.findByRole("button", {
      name: "Filter entfernen: Person: Anna Keller · Gesendet",
    });
    const page = calls.find((call) => call.url.pathname === "/api/mails")!;
    expect(page.url.search).toBe("?hide_duplicates=true&person=11&person_role=sent");
    expect(screen.getByRole("link", { name: "Export CSV" }).getAttribute("href")).toBe(
      "/api/mails/export.csv?hide_duplicates=true&person=11&person_role=sent",
    );
    fireEvent.click(chip);
    expect(router.state.location.search).toBe("?hide_duplicates=true");
  });

  it("explains a query the backend did not understand", async () => {
    renderApp("/mails?q=Vertrag+after%3A2026-13-01", (call) =>
      call.url.pathname === "/api/mails" || call.url.pathname === "/api/mails/summary"
        ? Response.json(
            { detail: { code: "invalid_query", message: "invalid date in 'after:2026-13-01'" } },
            { status: 400 },
          )
        : fixtureApi(call),
    );
    expect(await screen.findByText("Suche nicht verstanden: after:2026-13-01")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Suche leeren" }).getAttribute("href")).toBe("/mails");
    expect(within(tile("Mails im Filter")).getByText("–")).toBeTruthy();
  });

  it("shows more than 10.000 for a lower bound and never 0 for unknown counts", async () => {
    renderApp("/mails?q=Vertrag", (call) =>
      call.url.pathname === "/api/mails/summary"
        ? {
            total: 10000,
            exact: false,
            dkim: null,
            persons: null,
            domains: null,
            date_min: null,
            date_max: null,
          }
        : fixtureApi(call),
    );
    await waitFor(() =>
      expect(within(tile("Mails im Filter")).getByText("mehr als 10.000")).toBeTruthy(),
    );
    expect(within(tile("DKIM gültig")).getAllByText("–")).toHaveLength(2);
    expect(screen.getByText("mehr als 10.000 Treffer · sortiert nach Datum ↓")).toBeTruthy();
    expect(screen.getByText("1–12 von mehr als 10.000")).toBeTruthy();
  });

  it("shows the filter's timeline above the table and narrows the list to a clicked month", async () => {
    const { router, calls } = renderApp(filteredPath);
    const slider = await timeline();
    expect(slider.closest("section")!.querySelector("h2")!.textContent).toBe("Verlauf pro Monat");
    expect(timelineCalls(calls)[0].url.search).toBe(
      `?${new URLSearchParams({ q: filteredQuery, has_attachment: "true" })}`,
    );
    expect(screen.getByRole("link", { name: "Zeitachse öffnen" }).getAttribute("href")).toBe(
      `/zeitachse?${new URLSearchParams({ q: filteredQuery, has_attachment: "true" })}`,
    );

    fireEvent.click(slider, { clientX: 145 });
    const search = new URLSearchParams(router.state.location.search);
    expect(search.get("date_from")).toBe("2024-03-01");
    expect(search.get("date_to")).toBe("2024-03-31");
    expect(search.get("q")).toBe(filteredQuery);
    expect(search.has("cursor")).toBe(false);
    expect(
      await screen.findByRole("button", {
        name: "Filter entfernen: Zeitraum: 01.03.2024 – 31.03.2024",
      }),
    ).toBeTruthy();
    await waitFor(() =>
      expect(timelineCalls(calls).at(-1)!.url.searchParams.get("date_to")).toBe("2024-03-31"),
    );
  });

  it("hides the timeline, remembers it and counts nothing while hidden", async () => {
    renderApp("/mails");
    await timeline();
    fireEvent.click(screen.getByRole("button", { name: "Zeitachse ausblenden" }));
    expect(screen.queryByRole("slider")).toBeNull();
    expect(localStorage.getItem("mailrobbe.timeline")).toBe("hidden");

    cleanup();
    const { calls } = renderApp("/mails");
    await screen.findAllByRole("row");
    const show = screen.getByRole("button", { name: "Zeitachse einblenden" });
    expect(screen.queryByRole("slider")).toBeNull();
    expect(timelineCalls(calls)).toHaveLength(0);
    fireEvent.click(show);
    expect(await screen.findByRole("slider")).toBeTruthy();
    expect(timelineCalls(calls)).toHaveLength(1);
    expect(localStorage.getItem("mailrobbe.timeline")).toBeNull();
  });

  it("limits the list to a thread, named by its first mail's subject", async () => {
    const { router, calls } = renderApp("/mails?thread=184001", (call) =>
      call.url.pathname === "/api/mails/184001"
        ? { ...mailDetail, id: 184001, subject: "Vertragsentwurf Rahmenvereinbarung 2026" }
        : fixtureApi(call),
    );
    const chip = await screen.findByRole("button", {
      name: "Filter entfernen: Thread: Vertragsentwurf Rahmenvereinbarung 2026",
    });
    const page = calls.find((call) => call.url.pathname === "/api/mails")!;
    expect(page.url.search).toBe("?thread=184001");
    expect(timelineCalls(calls)[0].url.search).toBe("?thread=184001");
    fireEvent.click(chip);
    expect(router.state.location.search).toBe("");
  });

  it("names a thread by its id while its first mail is unknown", async () => {
    renderApp("/mails?thread=184001", (call) =>
      call.url.pathname === "/api/mails/184001"
        ? Response.json({ detail: { code: "not_found", message: "no mail" } }, { status: 404 })
        : fixtureApi(call),
    );
    expect(
      await screen.findByRole("button", { name: "Filter entfernen: Thread #184001" }),
    ).toBeTruthy();
  });
});
