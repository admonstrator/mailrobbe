import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AiSummaryView } from "../../api/types";
import { aiSummaryNone, mailDetail, mailItems } from "../../test/fixtures";
import { openInsights, rowOf, rows } from "../../test/mailList";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const previewOf = (location: { search: string }) =>
  new URLSearchParams(location.search).get("vorschau");

const panel = () => screen.getByRole("complementary", { name: "Vorschau" });

describe("the preview beside the mail list (D335)", () => {
  it("opens from a row's subject and from elsewhere in the row, with the id in the URL", async () => {
    const { router } = renderApp("/mails?has_attachment=true");
    await rows();
    expect(screen.queryByRole("complementary", { name: "Vorschau" })).toBeNull();

    fireEvent.click(screen.getByRole("link", { name: mailItems[0].subject! }));
    expect(router.state.location.pathname).toBe("/mails");
    expect(previewOf(router.state.location)).toBe(String(mailItems[0].id));
    expect(
      await within(panel()).findByRole("heading", { name: mailDetail.subject!, level: 2 }),
    ).toBeTruthy();
    expect(rowOf(mailItems[0].subject!).getAttribute("aria-current")).toBe("true");
    expect(within(panel()).getByRole("link", { name: "Ganz öffnen" }).getAttribute("href")).toBe(
      `/mails/${mailItems[0].id}?has_attachment=true`,
    );
    expect(
      within(panel()).getByRole("link", { name: "In neuem Fenster öffnen" }).getAttribute("target"),
    ).toBe("_blank");

    // A click elsewhere in another row shows that mail instead.
    fireEvent.click(rowOf(mailItems[2].subject!));
    expect(previewOf(router.state.location)).toBe(String(mailItems[2].id));
    expect(screen.getAllByRole("complementary", { name: "Vorschau" })).toHaveLength(1);
  });

  it("keeps the default of a click with a modifier, which opens the detail elsewhere", async () => {
    const { router } = renderApp("/mails");
    await rows();
    const link = screen.getByRole("link", { name: mailItems[0].subject! });
    const event = new MouseEvent("click", { bubbles: true, cancelable: true, ctrlKey: true });
    link.dispatchEvent(event);
    expect(previewOf(router.state.location)).toBeNull();
  });

  it("opens straight from the URL and closes by Esc and by its cross", async () => {
    const { router } = renderApp(`/mails?vorschau=${mailDetail.id}`);
    expect(
      await within(panel()).findByRole("heading", { name: mailDetail.subject!, level: 2 }),
    ).toBeTruthy();
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => expect(previewOf(router.state.location)).toBeNull());
    expect(screen.queryByRole("complementary", { name: "Vorschau" })).toBeNull();

    await router.navigate(`/mails?vorschau=${mailDetail.id}`);
    fireEvent.click(
      await within(await screen.findByRole("complementary", { name: "Vorschau" })).findByRole(
        "button",
        { name: "Schließen" },
      ),
    );
    await waitFor(() => expect(previewOf(router.state.location)).toBeNull());
  });

  it("and the panel Einblicke exclude each other", async () => {
    const { router } = renderApp(`/mails?vorschau=${mailDetail.id}`);
    await within(panel()).findByRole("heading", { name: mailDetail.subject!, level: 2 });
    await openInsights();
    expect(previewOf(router.state.location)).toBeNull();
    expect(screen.queryByRole("complementary", { name: "Vorschau" })).toBeNull();

    fireEvent.click(screen.getByRole("link", { name: mailItems[1].subject! }));
    expect(await screen.findByRole("complementary", { name: "Vorschau" })).toBeTruthy();
    expect(screen.queryByRole("complementary", { name: "Einblicke" })).toBeNull();
  });
});

describe("the AI summary in the preview (D345, D352)", () => {
  it("offers the light blue block, which starts the summary and then shows it running", async () => {
    const running: AiSummaryView = {
      ...aiSummaryNone,
      task: {
        id: 9,
        status: "running",
        parts_done: 0,
        parts_total: 1,
        queued_at: new Date().toISOString(),
        started_at: new Date().toISOString(),
      },
    };
    let view: AiSummaryView = aiSummaryNone;
    const posts: unknown[] = [];
    renderApp(`/mails?vorschau=${mailDetail.id}`, (call: ApiCall) => {
      if (call.url.pathname === "/api/ai/summary") return view;
      if (call.url.pathname === "/api/ai/tasks" && call.method === "POST") {
        posts.push(call.body);
        view = running;
        return { queued: 1, raised: 0, unreadable: 0, logos: 0, run: "started", short: 0 };
      }
      return fixtureApi(call);
    });
    const offer = await within(
      await screen.findByRole("complementary", { name: "Vorschau" }),
    ).findByRole("button", { name: "KI-Zusammenfassung erstellen" });
    fireEvent.click(offer);
    expect(await within(panel()).findByText(/KI rechnet seit 0:0\d Min\./)).toBeTruthy();
    expect(within(panel()).getByRole("status").textContent).toContain(
      "KI-Zusammenfassung wird erstellt",
    );
    expect(posts).toEqual([
      { kind: "summarize", mail_ids: [mailDetail.id], single: true, start: true },
    ]);
  });
});
