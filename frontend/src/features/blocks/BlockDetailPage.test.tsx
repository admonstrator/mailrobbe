import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BlockDetail, BlockInfo, BlockOverrideUpdate } from "../../api/types";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const HASH = "7198ac121813e610";
const LAZY = { timeout: 5000 };
const SAMPLE =
  "Diese Nachricht ist vertraulich und nur für den Empfänger bestimmt.\n\n" +
  "Nordlicht GmbH · Rechtshinweis: Sitz Köln, Amtsgericht Köln HRB 19414";

const BLOCK: BlockInfo = {
  hash: HASH,
  sample: SAMPLE,
  standard: true,
  detected: true,
  override: null,
  pending: false,
  mails: 1234,
  senders: 3,
  first_date: "2019-03-01T09:00:00Z",
  last_date: "2026-10-17T07:12:00Z",
};

const DETAIL: BlockDetail = {
  block: BLOCK,
  senders: [
    { person: { person_id: 11, email: "anna@nordlicht.example", name: "Anna Keller" }, mails: 800 },
    { person: { person_id: 12, email: "j.brandt@nordlicht.example", name: null }, mails: 434 },
  ],
  domains: [{ domain: "nordlicht.example", mails: 1234 }],
};

/** The block's endpoints with the choice applied as api/blocks.py does: a choice equal to
 *  detection removes the team's choice. */
function blockApi() {
  let block = BLOCK;
  return (call: ApiCall): unknown => {
    if (call.url.pathname === `/api/blocks/${HASH}/override` && call.method === "PUT") {
      const { standard } = call.body as BlockOverrideUpdate;
      const override = standard === block.detected ? null : standard;
      block = { ...block, override, pending: (override ?? block.detected) !== block.standard };
      return block;
    }
    if (call.url.pathname === `/api/blocks/${HASH}`) return { ...DETAIL, block };
    if (call.url.pathname.startsWith("/api/blocks/")) {
      return Response.json(
        { detail: { code: "not_found", message: "no standard block" } },
        { status: 404 },
      );
    }
    return fixtureApi(call);
  };
}

describe("standard block page", () => {
  it("shows the whole sample, its figures, senders and domains, and leads to its mails", async () => {
    renderApp(`/ausgeblendet/bloecke/${HASH}`, blockApi());
    // the first visit loads the page's lazy chunk, which takes a while in a busy test run
    const heading = await screen.findByRole("heading", { name: "Standardblock" }, LAZY);
    expect(heading).toBeTruthy();
    expect(screen.getByText(/^Erkannt: steht am Ende vieler Mails/)).toBeTruthy();
    expect(screen.getByText(/Nordlicht GmbH · Rechtshinweis/).textContent).toBe(SAMPLE);

    const mails = screen.getByRole("link", { name: "Mails mit diesem Block (1.234)" });
    expect(mails.getAttribute("href")).toBe(`/mails?block=${HASH}`);
    const figures = screen.getByRole("list", { name: "Zahlen des Blocks" });
    expect(within(figures).getByText("01.03.2019")).toBeTruthy();
    expect(within(figures).getByText("17.10.2026")).toBeTruthy();

    const senders = screen.getByRole("region", { name: "Absender (3)" });
    expect(
      within(senders)
        .getAllByRole("link")
        .map((link) => [link.textContent, link.getAttribute("href")]),
    ).toEqual([
      ["Anna Keller", "/personen/11"],
      ["j.brandt@nordlicht.example", "/personen/12"],
    ]);
    expect(within(senders).getByText("Die 2 mit den meisten Mails.")).toBeTruthy();
    const domains = screen.getByRole("region", { name: "Domains der Absender" });
    const domain = within(domains).getByRole("link", { name: "nordlicht.example" });
    expect(domain.getAttribute("href")).toBe(
      `/mails?sender_domain=nordlicht.example&block=${HASH}`,
    );
  });

  it("takes a block back and offers it again; the choice waits for the next run", async () => {
    localStorage.setItem("mailrobbe.editor", "Lena Vogt");
    const { calls } = renderApp(`/ausgeblendet/bloecke/${HASH}`, blockApi());
    expect(await screen.findByText(/Eine Änderung wirkt beim nächsten Lauf/)).toBeTruthy();
    expect(screen.getByText(/^Entscheidungen werden gespeichert als/).textContent).toBe(
      "Entscheidungen werden gespeichert als Lena Vogt. Namen ändern",
    );
    fireEvent.click(screen.getByRole("button", { name: "Kein Standardblock" }));

    const note = await screen.findByRole("status");
    expect(note.textContent).toBe("Kein Standardblock · wirkt beim nächsten Lauf. Zum Import");
    fireEvent.click(screen.getByRole("button", { name: "Wieder als Standardblock" }));
    expect(await screen.findByRole("button", { name: "Kein Standardblock" })).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();

    const put = calls.filter((call) => call.method === "PUT");
    expect(put.map((call) => call.body)).toEqual([{ standard: false }, { standard: true }]);
    expect(put[0].headers.get("X-Mailrobbe-Editor")).toBe("Lena%20Vogt");
  });

  it("asks for the editor's name before the first choice", async () => {
    const { calls } = renderApp(`/ausgeblendet/bloecke/${HASH}`, blockApi());
    fireEvent.click(await screen.findByRole("button", { name: "Kein Standardblock" }));
    const dialog = screen.getByRole("dialog", { name: "Name für Notizen und Änderungen" });
    expect(calls.some((call) => call.method === "PUT")).toBe(false);
    fireEvent.click(within(dialog).getByRole("button", { name: "Abbrechen" }));
    // saved all the same, without a name
    await waitFor(() => expect(calls.filter((call) => call.method === "PUT")).toHaveLength(1));
    expect(calls.find((call) => call.method === "PUT")?.headers.has("X-Mailrobbe-Editor")).toBe(
      false,
    );
  });

  it("says when no block has the hash", async () => {
    renderApp("/ausgeblendet/bloecke/0000000000000000", blockApi());
    expect(await screen.findByText("Diesen Standardblock gibt es nicht")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Alle Standardblöcke" }).getAttribute("href")).toBe(
      "/ausgeblendet/bloecke",
    );
  });

  it("says so for a hash that cannot be one, without asking the server", async () => {
    const { calls } = renderApp("/ausgeblendet/bloecke/zz", blockApi());
    expect(await screen.findByText("Diesen Standardblock gibt es nicht")).toBeTruthy();
    expect(calls.some((call) => call.url.pathname.startsWith("/api/blocks"))).toBe(false);
  });
});
