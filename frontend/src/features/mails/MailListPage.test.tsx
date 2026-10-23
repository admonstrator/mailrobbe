import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  filteredPage,
  filteredQuery,
  hitsPage,
  mailDetail,
  mailItems,
  mailPage,
  summaryAll,
} from "../../test/fixtures";
import {
  downloads,
  figures,
  menuItem,
  openFilter,
  openInsights,
  rowOf,
  rows,
} from "../../test/mailList";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const search = (location: { search: string }) => new URLSearchParams(location.search);

const filteredPath = `/mails?${new URLSearchParams({ q: filteredQuery, has_attachment: "true" })}`;

const timelineCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/timeline");

describe("mail list", () => {
  it("renders rows, chips, figures and the range from the API", async () => {
    const { calls } = renderApp(filteredPath);

    const subject = await screen.findByRole("link", {
      name: "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung",
    });
    expect(subject.getAttribute("href")).toBe(`/mails/184221?${filteredPath.split("?")[1]}`);
    expect(await rows()).toHaveLength(12);
    expect(screen.getByText("(kein Betreff)")).toBeTruthy();
    expect(screen.getAllByRole("img", { name: "DKIM ungültig" })).toHaveLength(1);
    expect(within(rowOf(mailItems[0].subject!)).getByText("Anna Keller")).toBeTruthy();
    expect(screen.getByText(/ an .* \+11$/)).toBeTruthy();

    for (const label of ["Betreff: „Vertrag“", "to: @stadtwerke-beispiel.example", "Mit Anhang"]) {
      expect(screen.getByRole("button", { name: `Filter entfernen: ${label}` })).toBeTruthy();
    }

    const line = figures();
    expect(await within(line).findByText("65,7 %")).toBeTruthy();
    expect(within(line).getByText("65,7 %").parentElement!.getAttribute("title")).toBe(
      "von 1.196 signierten Mails",
    );
    expect(within(line).getByText("401")).toBeTruthy();
    expect(line.textContent).toContain("Personen aus 38 Domains");
    expect(screen.getByText(`1.207 Treffer für „${filteredQuery}“`)).toBeTruthy();
    const pager = screen.getByRole("navigation", { name: "Seite" });
    expect(within(pager).getByText("1–12 von 1.207")).toBeTruthy();

    const page = calls.find((call) => call.url.pathname === "/api/mails")!;
    expect(page.url.searchParams.get("q")).toBe(filteredQuery);
    expect(page.url.searchParams.get("has_attachment")).toBe("true");
    const next = screen.getByRole("link", { name: "Weiter ›" }).getAttribute("href");
    expect(next).toContain("cursor=cursor-page-2&page=2");
    expect(within(pager).getByRole("link", { name: "Nächste Seite" }).getAttribute("href")).toBe(
      next,
    );
    const hrefs = downloads();
    menuItem("Als CSV herunterladen");
    expect(hrefs).toEqual([
      `/api/mails/export.csv?${new URLSearchParams({ q: filteredQuery, has_attachment: "true" })}`,
    ]);
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
    const column = await openFilter("DKIM");
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
    const hrefs = downloads();
    menuItem("Als CSV herunterladen");
    expect(hrefs).toEqual([
      "/api/mails/export.csv?hide_duplicates=true&person=11&person_role=sent",
    ]);
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
    expect(within(figures()).getByText("Zahlen nicht verfügbar")).toBeTruthy();
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
    expect(await screen.findByText("mehr als 10.000 Treffer für „Vertrag“")).toBeTruthy();
    // Without DKIM counts the line names no share and never 0.
    expect(figures().textContent).not.toContain("DKIM");
    expect(figures().textContent).not.toContain("Personen");
    const pager = screen.getByRole("navigation", { name: "Seite" });
    expect(within(pager).getByText("1–12 von mehr als 10.000")).toBeTruthy();
  });

  it("shows the filter's months as small bars and narrows the list to a clicked month", async () => {
    const { router, calls } = renderApp(filteredPath);
    const bars = await screen.findByRole("img", { name: "Mails pro Monat" });
    const sent = timelineCalls(calls)[0].url.searchParams;
    expect([sent.get("q"), sent.get("has_attachment"), sent.get("bucket")]).toEqual([
      filteredQuery,
      "true",
      "month",
    ]);
    expect(within(figures()).getByRole("link", { name: "Zeitachse" }).getAttribute("href")).toBe(
      `/zeitachse?${new URLSearchParams({ q: filteredQuery, has_attachment: "true" })}`,
    );

    const march = bars.querySelectorAll("rect")[14];
    expect(march.querySelector("title")!.textContent).toMatch(/^März 2024: /);
    fireEvent.click(march);
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

  it("remembers the row density and the panel Einblicke in this browser", async () => {
    renderApp("/mails");
    await rows();
    menuItem("Zeilen: kompakt");
    expect(localStorage.getItem("mailrobbe.row-density")).toBe("compact");
    await openInsights();
    expect(localStorage.getItem("mailrobbe.insights")).toBe("open");

    cleanup();
    renderApp("/mails");
    await rows();
    expect(screen.getByRole("complementary", { name: "Einblicke" })).toBeTruthy();
    menuItem("Zeilen: bequem");
    expect(localStorage.getItem("mailrobbe.row-density")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Einblicke" }));
    expect(screen.queryByRole("complementary", { name: "Einblicke" })).toBeNull();
    expect(localStorage.getItem("mailrobbe.insights")).toBeNull();
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
    expect(timelineCalls(calls)[0].url.searchParams.get("thread")).toBe("184001");
    fireEvent.click(chip);
    expect(router.state.location.search).toBe("");
  });

  it("shows under the subject where the search words occur, only where they do (D176)", async () => {
    // The third mail's attachment matched, but the counts say the words do not count there.
    const page = {
      ...hitsPage,
      items: hitsPage.items.map((mail, index) =>
        index === 2 ? { ...mail, attachment_match: true } : mail,
      ),
    };
    renderApp("/mails?q=Neger", (call) =>
      call.url.pathname === "/api/mails" ? page : fixtureApi(call),
    );
    const items = await rows();
    const line = (row: HTMLElement) => row.querySelector('[title^="Suchwörter"]');
    expect(line(items[0])!.textContent).toBe("Betreff 1 · Text 3 · Anhang 2 · Dateiname 2");
    expect(line(items[0])!.getAttribute("title")).toBe(
      "Suchwörter: 1 im Betreff, 3 im Mailtext, 2 im Text von Anhängen, 2 in Dateinamen",
    );
    // in the subject's row
    expect(
      within(line(items[0])!.closest("li")!).getByRole("link", {
        name: "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung",
      }),
    ).toBeTruthy();
    // Found through a file name only, which is the point.
    expect(line(items[1])!.textContent).toBe("Dateiname 2");
    expect(line(items[2])).toBeNull();
    expect(line(items[3])!.textContent).toBe("Text 1");

    // The mark of D73 beside the paperclip follows the counts and names the place.
    const mark = (row: HTMLElement) => within(row).queryByText("im Anhang")?.getAttribute("title");
    expect(mark(items[0])).toBe("Suchbegriff steht im Text und im Dateinamen eines Anhangs");
    expect(mark(items[1])).toBe("Suchbegriff steht im Dateinamen eines Anhangs");
    expect(mark(items[2])).toBeUndefined();
    expect(mark(items[3])).toBeUndefined();
  });

  it("adds no line to rows without hits", async () => {
    renderApp(filteredPath);
    await rows();
    expect(document.querySelector('[title^="Suchwörter"]')).toBeNull();
  });

  it("sends the search options, shows them as chips and drops one by its chip", async () => {
    const options = "q=Neger&scope=subject&scope=body&whole_word=true&min_hits=3";
    const { router, calls } = renderApp(`/mails?${options}`, (call) =>
      call.url.pathname === "/api/mails" ? hitsPage : fixtureApi(call),
    );
    for (const label of ["Nur in: Betreff, Mailtext", "Ganzes Wort", "Mindestens 3 Treffer"]) {
      expect(
        await screen.findByRole("button", { name: `Filter entfernen: ${label}` }),
      ).toBeTruthy();
    }
    for (const path of ["/api/mails", "/api/mails/summary"]) {
      expect(calls.find((call) => call.url.pathname === path)!.url.search).toBe(`?${options}`);
    }
    expect(timelineCalls(calls)[0].url.search).toBe(`?${options}&bucket=month`);
    const hrefs = downloads();
    menuItem("Als CSV herunterladen");
    expect(hrefs).toEqual([`/api/mails/export.csv?${options}`]);
    // The detail links carry them, so the detail marks as the list searched.
    expect(
      screen
        .getByRole("link", { name: "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung" })
        .getAttribute("href"),
    ).toBe(`/mails/184221?${options}`);

    fireEvent.click(
      screen.getByRole("button", { name: "Filter entfernen: Nur in: Betreff, Mailtext" }),
    );
    expect(router.state.location.search).toBe("?q=Neger&whole_word=true&min_hits=3");
  });

  it("names excluded terms and removes them from q", async () => {
    const q = "Neger -datei:NEG -negere";
    const { router } = renderApp(`/mails?${new URLSearchParams({ q })}`, (call) =>
      call.url.pathname === "/api/mails"
        ? {
            ...hitsPage,
            query_terms: [
              { key: "text", value: "Neger", raw: "Neger", negated: false },
              { key: "in_filename", value: "NEG", raw: "-datei:NEG", negated: true },
              { key: "text", value: "-negere", raw: "-negere", negated: false },
            ],
          }
        : fixtureApi(call),
    );
    expect(
      await screen.findByRole("button", { name: "Filter entfernen: Ohne: „negere“" }),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Filter entfernen: Nicht im Dateinamen: „NEG“" }),
    );
    expect(search(router.state.location).get("q")).toBe("Neger -negere");
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

describe("paging with page numbers (D193)", () => {
  const mailCalls = (calls: ApiCall[]) =>
    calls.filter((call) => call.url.pathname === "/api/mails");
  const query = (link: HTMLElement) => new URL(link.getAttribute("href")!, "http://x").searchParams;

  /** The fixture backend, with the page a jump asks for answered by its number. */
  function jumpingApi(call: ApiCall): unknown {
    const page = call.url.searchParams.get("page");
    if (call.url.pathname === "/api/mails" && page) {
      return { ...filteredPage, page: Number(page), prev_cursor: "back", next_cursor: "on" };
    }
    return fixtureApi(call);
  }

  it("numbers the pages, jumps by number and by the field, all in the URL", async () => {
    const { router, calls } = renderApp(filteredPath, jumpingApi);
    const nav = await screen.findByRole("navigation", { name: "Seiten" });
    expect(within(nav).getByText("1–12 von 1.207")).toBeTruthy();
    expect(within(nav).getByRole("link", { name: "Seite 1" }).getAttribute("aria-current")).toBe(
      "page",
    );
    // 1.207 mails, 50 a page: 25 pages, the last one by its number.
    const last = within(nav).getByRole("link", { name: "Seite 25" });
    expect(query(last).get("page")).toBe("25");
    expect(within(nav).getByRole("link", { name: "Letzte Seite »" }).getAttribute("href")).toBe(
      last.getAttribute("href"),
    );

    fireEvent.change(within(nav).getByRole("spinbutton", { name: "Seite" }), {
      target: { value: "13" },
    });
    fireEvent.click(within(nav).getByRole("button", { name: "Los" }));
    expect(search(router.state.location).get("page")).toBe("13");
    expect(search(router.state.location).has("cursor")).toBe(false);
    expect((await screen.findAllByText("601–612 von 1.207")).length).toBeGreaterThan(0);
    expect(mailCalls(calls).at(-1)!.url.searchParams.get("page")).toBe("13");
    expect(screen.getByRole("link", { name: "Seite 13" }).getAttribute("aria-current")).toBe(
      "page",
    );
    // The steps go on by cursor from there and keep the number.
    const back = query(await screen.findByRole("link", { name: "‹ Zurück" }));
    expect([back.get("cursor"), back.get("page")]).toEqual(["back", "12"]);
    const on = query(screen.getByRole("link", { name: "Weiter ›" }));
    expect([on.get("cursor"), on.get("page")]).toEqual(["on", "14"]);

    // Another page size starts again at the first page.
    fireEvent.change(screen.getByRole("combobox", { name: "Pro Seite" }), {
      target: { value: "100" },
    });
    expect(search(router.state.location).get("limit")).toBe("100");
    expect(search(router.state.location).has("page")).toBe(false);
    await waitFor(() => expect(mailCalls(calls).at(-1)!.url.searchParams.get("limit")).toBe("100"));
    expect(mailCalls(calls).at(-1)!.url.searchParams.has("page")).toBe(false);
  });

  it("goes back to the first page when a filter changes, at the same page size", async () => {
    const { router } = renderApp(`${filteredPath}&limit=25&page=7`, jumpingApi);
    expect((await screen.findAllByText("151–162 von 1.207")).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByRole("combobox", { name: "Sortierung" }), {
      target: { value: "date_asc" },
    });
    const now = search(router.state.location);
    expect([now.get("sort"), now.get("limit"), now.has("page")]).toEqual(["date_asc", "25", false]);
  });

  it("reaches the last of more than 10.000 mails without a number", async () => {
    const { router, calls } = renderApp("/mails", (call) => {
      if (call.url.pathname === "/api/mails/summary") {
        return { ...summaryAll, total: 10000, exact: false };
      }
      if (call.url.pathname === "/api/mails" && call.url.searchParams.get("last") === "true") {
        return { ...mailPage, page: null, prev_cursor: "before-last", next_cursor: null };
      }
      return fixtureApi(call);
    });
    const nav = await screen.findByRole("navigation", { name: "Seiten" });
    expect(within(nav).getByText("1–12 von mehr als 10.000")).toBeTruthy();
    // The pages the lower bound fills are numbered, and the list goes on after them.
    expect(within(nav).getByRole("link", { name: "Seite 200" })).toBeTruthy();
    expect(nav.textContent).toContain("200…");
    fireEvent.click(within(nav).getByRole("link", { name: "Letzte Seite »" }));
    expect(router.state.location.search).toBe("?page=last");
    expect((await screen.findAllByText("die letzten 12 von mehr als 10.000")).length).toBe(2);
    expect(mailCalls(calls).at(-1)!.url.search).toBe("?last=true");
    expect((await screen.findByRole("link", { name: "‹ Zurück" })).getAttribute("href")).toBe(
      "/mails?cursor=before-last",
    );
    expect(screen.queryByRole("link", { name: "Letzte Seite »" })).toBeNull();
  });

  it("offers the first and the last page when a jump took too long", async () => {
    renderApp(`${filteredPath}&page=4000`, (call) =>
      call.url.pathname === "/api/mails" && call.url.searchParams.get("page") === "4000"
        ? Response.json(
            { detail: { code: "page_too_far", message: "not within the count budget" } },
            { status: 400 },
          )
        : fixtureApi(call),
    );
    expect(await screen.findByText("Diese Seite ist zu weit entfernt.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Erste Seite" }).getAttribute("href")).toBe(
      filteredPath,
    );
    expect(screen.getByRole("link", { name: "Letzte Seite" }).getAttribute("href")).toBe(
      `${filteredPath}&page=last`,
    );
  });
});
