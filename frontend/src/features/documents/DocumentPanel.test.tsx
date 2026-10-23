import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp } from "../../test/render";

const NAME = "Rahmenvereinbarung_2026_final.pdf";

const previewOf = (location: { search: string }) =>
  new URLSearchParams(location.search).get("vorschau");

const panel = () => screen.getByRole("complementary", { name: "Vorschau" });

describe("the document beside the list (D335)", () => {
  it("opens from a row's name with the id in the URL, keeping the filters", async () => {
    const { router } = renderApp("/anhaenge?kind=pdf");
    fireEvent.click(await screen.findByRole("link", { name: NAME }, { timeout: 3000 }));
    expect(router.state.location.pathname).toBe("/anhaenge");
    expect(router.state.location.search).toBe("?kind=pdf&vorschau=5101");

    expect(await within(panel()).findByRole("heading", { name: NAME, level: 2 })).toBeTruthy();
    expect(
      screen.getByRole("link", { name: NAME }).closest("li")!.getAttribute("aria-current"),
    ).toBe("true");
    expect(within(panel()).getByText("PDF · 14 Seiten · 168 KB")).toBeTruthy();
    expect(
      within(panel())
        .getByRole("link", { name: "Vertrag Nordstahl: Änderungswünsche Einkauf" })
        .getAttribute("href"),
    ).toBe("/mails/183644");
    expect(within(panel()).getByRole("link", { name: "Ganz öffnen" }).getAttribute("href")).toBe(
      "/anhaenge/5101",
    );
    expect(
      within(panel()).getByRole("link", { name: "In neuem Fenster öffnen" }).getAttribute("target"),
    ).toBe("_blank");
    expect(within(panel()).getByRole("link", { name: "Herunterladen" }).getAttribute("href")).toBe(
      "/api/attachments/901/content",
    );
    expect(within(panel()).getByText("Keine Vorschau im Browser, nur Download.")).toBeTruthy();

    // A filter changed beside it keeps the document open.
    fireEvent.click(screen.getByRole("button", { name: "Zurücksetzen" }));
    expect(previewOf(router.state.location)).toBe("5101");
  });

  it("opens from elsewhere in a row, and a click with a modifier keeps the link's default", async () => {
    const { router } = renderApp("/anhaenge");
    const link = await screen.findByRole("link", { name: NAME });
    link.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, ctrlKey: true }));
    expect(previewOf(router.state.location)).toBeNull();
    fireEvent.click(link.closest("li")!);
    expect(previewOf(router.state.location)).toBe("5101");
  });

  it("opens straight from the URL and closes by Esc and by its cross", async () => {
    const { router } = renderApp("/anhaenge?vorschau=5101");
    await within(panel()).findByRole("heading", { name: NAME, level: 2 });
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() => expect(previewOf(router.state.location)).toBeNull());
    expect(screen.queryByRole("complementary", { name: "Vorschau" })).toBeNull();

    await router.navigate("/anhaenge?vorschau=5101");
    fireEvent.click(
      within(await screen.findByRole("complementary", { name: "Vorschau" })).getByRole("button", {
        name: "Schließen",
      }),
    );
    await waitFor(() => expect(previewOf(router.state.location)).toBeNull());
  });

  it("says so when the document cannot be loaded", async () => {
    renderApp("/anhaenge?vorschau=9999");
    expect(
      await within(panel()).findByText("Das Dokument konnte nicht geladen werden."),
    ).toBeTruthy();
  });
});
