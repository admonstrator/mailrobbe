import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mailItems, mailPage } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

describe("mail list and attachments", () => {
  it("marks a mail found through the text of an attachment", async () => {
    renderApp("/mails?q=Spende", (call: ApiCall) =>
      call.url.pathname === "/api/mails"
        ? {
            ...mailPage,
            items: [{ ...mailItems[0], attachment_match: true }, mailItems[2]],
            query_terms: [{ key: "text", value: "Spende", raw: "Spende" }],
          }
        : fixtureApi(call),
    );
    const mark = await screen.findByText("im Anhang");
    expect(mark.getAttribute("title")).toBe("Suchbegriff steht im Text eines Anhangs");
    const row = mark.closest("tr")!;
    expect(within(row).getByRole("img", { name: "Anhang" })).toBeTruthy();
    expect(within(row).getByText(/Vertragsentwurf Rahmenvereinbarung 2026/)).toBeTruthy();
    expect(screen.getAllByText("im Anhang")).toHaveLength(1);
  });

  it("shows the document filter as a chip named by the document", async () => {
    const { router, calls } = renderApp("/mails?document=5101&sort=date_asc");
    const chip = await screen.findByRole("button", {
      name: "Filter entfernen: Dokument: Rahmenvereinbarung_2026_final.pdf",
    });
    const page = calls.find((call) => call.url.pathname === "/api/mails")!;
    expect(page.url.searchParams.get("document")).toBe("5101");
    const summary = calls.find((call) => call.url.pathname === "/api/mails/summary")!;
    expect(summary.url.searchParams.get("document")).toBe("5101");
    expect(screen.getByRole("link", { name: "Export CSV" }).getAttribute("href")).toBe(
      "/api/mails/export.csv?document=5101&sort=date_asc",
    );

    fireEvent.click(chip);
    expect(router.state.location.search).toBe("?sort=date_asc");
    await waitFor(() => expect(screen.queryByRole("button", { name: /Dokument:/ })).toBeNull());
  });

  it("names the chip by number while the document is unknown", async () => {
    renderApp("/mails?document=777");
    expect(
      await screen.findByRole("button", { name: "Filter entfernen: Dokument: #777" }),
    ).toBeTruthy();
  });
});
