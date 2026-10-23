import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mailDetail, mailItems } from "../../test/fixtures";
import { openInsights, rowOf, rows } from "../../test/mailList";
import { renderApp } from "../../test/render";

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
