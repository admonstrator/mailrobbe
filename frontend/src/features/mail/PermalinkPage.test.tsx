import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mailDetail } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const failing = (status: number, code: string) => (call: ApiCall) =>
  call.url.pathname.startsWith("/api/permalink/")
    ? Response.json({ detail: { code, message: "permalink" } }, { status })
    : fixtureApi(call);

describe("permalink", () => {
  it("opens the mail with this content in place of the permalink", async () => {
    const { router, calls } = renderApp("/m/3F9C2A1B8E7D6C5F");
    await waitFor(() => expect(router.state.location.pathname).toBe(`/mails/${mailDetail.id}`));
    expect(router.state.historyAction).toBe("REPLACE");
    expect(calls.map((call) => call.url.pathname)).toContain("/api/permalink/3f9c2a1b8e7d6c5f");
    expect(await screen.findByRole("heading", { name: mailDetail.subject! })).toBeTruthy();
  });

  it("says when no mail of the archive has this content", async () => {
    renderApp("/m/3f9c2a1b8e7d6c5f", failing(404, "not_found"));
    expect(await screen.findByText("Keine Mail mit diesem Inhalt im Archiv.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Zur Mailliste" }).getAttribute("href")).toBe("/mails");
  });

  it("says that a short link fits several mails and how many digits it had", async () => {
    renderApp("/m/3f9c2a1b8e7d", failing(409, "ambiguous_permalink"));
    expect(await screen.findByText("Der Link ist zu kurz.")).toBeTruthy();
    expect(screen.getByText(/Er nennt nur 12 Ziffern \(3f9c2a1b8e7d\)/)).toBeTruthy();
  });

  it("explains a link that is no permalink", async () => {
    renderApp("/m/xyz", failing(400, "invalid_filter"));
    expect(await screen.findByText("Das ist kein gültiger Permalink.")).toBeTruthy();
  });
});
