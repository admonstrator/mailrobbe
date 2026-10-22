import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BlockInfo, BlockPage, BlockSummary } from "../../api/types";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const NOTICE = "Diese Nachricht ist vertraulich und nur für den Empfänger bestimmt.";

function block(hash: string, sample: string, patch: Partial<BlockInfo> = {}): BlockInfo {
  return {
    hash,
    sample,
    standard: true,
    detected: true,
    override: null,
    pending: false,
    mails: 1234,
    senders: 12,
    first_date: "2019-03-01T09:00:00Z",
    last_date: "2026-10-17T07:12:00Z",
    ...patch,
  };
}

const BLOCKS: BlockInfo[] = [
  block("7198ac121813e610", `> ${NOTICE}\n> Bitte beachten Sie den Rechtshinweis.\n>\n> Rat`),
  block("0123456789abcdef", "Wochenrückblick der Abteilung Recht, jeden Freitag neu", {
    detected: false,
    override: true,
    mails: 40,
    senders: 3,
  }),
  block("fedcba9876543210", "Nordlicht GmbH, Sitz Köln, Amtsgericht Köln HRB 19414", {
    override: false,
    pending: true,
    mails: 31,
    senders: 2,
  }),
];

const SUMMARY: BlockSummary = {
  blocks: 3,
  detected: 2,
  marked: 1,
  dismissed: 1,
  pending: 2,
  mails: 1305,
  waiting: 0,
  min_mails: 25,
  computed_at: "2026-10-22T08:00:00Z",
};

function blocksApi(summary: BlockSummary, items: BlockInfo[]) {
  return (call: ApiCall): unknown => {
    if (call.url.pathname === "/api/blocks/summary") return summary;
    if (call.url.pathname === "/api/blocks") {
      const q = call.url.searchParams.get("q") ?? "";
      const found = items.filter((item) => item.sample.includes(q));
      return { items: found, total: found.length } satisfies BlockPage;
    }
    return fixtureApi(call);
  };
}

const listCalls = (calls: ApiCall[]) =>
  calls
    .filter((call) => call.url.pathname === "/api/blocks")
    .map((call) => call.url.searchParams.toString());

describe("standard block list", () => {
  it("lists the blocks with the figures of the last run and what the next one does", async () => {
    const { calls } = renderApp("/ausgeblendet/bloecke", blocksApi(SUMMARY, BLOCKS));
    // the first visit loads the page's lazy chunk, which takes a while in a busy test run
    const rows = await screen.findAllByRole("row", {}, { timeout: 5000 });
    expect(rows).toHaveLength(4);
    expect(listCalls(calls)).toEqual([""]);

    const figures = screen.getByRole("list", { name: "Zahlen des letzten Laufs" });
    expect(within(figures).getByText("2 erkannt · 1 von Hand")).toBeTruthy();
    expect(within(figures).getByText("ab 25 Mails")).toBeTruthy();
    expect(within(figures).getByText("alle Mails in Absätze zerlegt")).toBeTruthy();
    const note = screen.getByRole("status");
    expect(note.textContent).toContain("2 Entscheidungen wirken beim nächsten Lauf.");
    expect(within(note).getByRole("link", { name: "Zum Import" }).getAttribute("href")).toBe(
      "/import",
    );

    // the first lines without quote markers, leading to the block's page
    const first = within(rows[1]).getByRole("link");
    expect(first.textContent).toBe(`${NOTICE}\nBitte beachten Sie den Rechtshinweis.\nRat`);
    expect(first.getAttribute("href")).toBe("/ausgeblendet/bloecke/7198ac121813e610");
    expect(within(rows[1]).getByText("1.234")).toBeTruthy();
    expect(within(rows[1]).getByText("01.03.2019 – 17.10.2026")).toBeTruthy();
    expect(within(rows[2]).getByText("von Hand")).toBeTruthy();
    expect(within(rows[3]).getByText("wirkt beim nächsten Lauf")).toBeTruthy();
    expect(within(rows[1]).queryByText("wirkt beim nächsten Lauf")).toBeNull();
  });

  it("switches to the blocks taken back, sorts and searches through the URL", async () => {
    const { calls, router } = renderApp("/ausgeblendet/bloecke", blocksApi(SUMMARY, BLOCKS));
    await screen.findAllByRole("row");
    fireEvent.click(screen.getByRole("button", { name: "Zurückgenommen" }));
    await waitFor(() => expect(router.state.location.search).toBe("?state=dismissed"));
    fireEvent.change(screen.getByLabelText("Sortierung"), { target: { value: "recent" } });
    await waitFor(() => expect(router.state.location.search).toBe("?state=dismissed&sort=recent"));
    fireEvent.change(screen.getByLabelText("Block suchen"), { target: { value: "Köln" } });
    await waitFor(() =>
      expect(listCalls(calls)).toEqual([
        "",
        "state=dismissed",
        "state=dismissed&sort=recent",
        "q=K%C3%B6ln&state=dismissed&sort=recent",
      ]),
    );
    expect(await screen.findByText("1 Block gefunden")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Block suchen"), { target: { value: "Spende" } });
    expect(await screen.findByText("Kein Block gefunden")).toBeTruthy();
    expect(screen.getByText("Kein Block enthält „Spende“.")).toBeTruthy();
  });

  it("says when the blocks step has not run yet", async () => {
    const never = { ...SUMMARY, blocks: 0, detected: 0, marked: 0, dismissed: 0, pending: 0 };
    renderApp(
      "/ausgeblendet/bloecke",
      blocksApi({ ...never, mails: 0, waiting: 5000, computed_at: null }, []),
    );
    expect(await screen.findByText("Noch keine Standardblöcke berechnet")).toBeTruthy();
    expect(screen.getByText("5.000 Mails noch nicht zerlegt")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain(
      "5.000 Mails sind noch nicht in Absätze zerlegt.",
    );
  });

  it("says when the last run found none", async () => {
    const none = { ...SUMMARY, blocks: 0, detected: 0, marked: 0, dismissed: 0, pending: 0 };
    renderApp("/ausgeblendet/bloecke", blocksApi(none, []));
    expect(await screen.findByText("Keine Standardblöcke gefunden")).toBeTruthy();
    expect(screen.getByText(/Kein Absatz steht am Ende von mindestens 25 Mails\./)).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("standard block list paging (D193)", () => {
  it("numbers every page and asks by offset at the page size", async () => {
    const many = Array.from({ length: 57 }, (_, index) =>
      block(index.toString(16).padStart(16, "0"), `Rechtshinweis Nummer ${index + 1}`),
    );
    const api = (call: ApiCall): unknown => {
      if (call.url.pathname === "/api/blocks") {
        const offset = Number(call.url.searchParams.get("offset") ?? 0);
        const limit = Number(call.url.searchParams.get("limit") ?? 50);
        return { items: many.slice(offset, offset + limit), total: many.length };
      }
      return blocksApi(SUMMARY, BLOCKS)(call);
    };
    const { calls, router } = renderApp("/ausgeblendet/bloecke?limit=25", api);
    expect(await screen.findByText("1–25 von 57")).toBeTruthy();
    const nav = screen.getByRole("navigation", { name: "Seiten" });
    fireEvent.click(within(nav).getByRole("link", { name: "Seite 3" }));
    await waitFor(() => expect(router.state.location.search).toBe("?page=3&limit=25"));
    expect(await screen.findByText("51–57 von 57")).toBeTruthy();
    expect(listCalls(calls).at(-1)).toBe("offset=50&limit=25");
    expect(screen.getByRole("link", { name: "Seite 3" }).getAttribute("aria-current")).toBe("page");
  });
});
