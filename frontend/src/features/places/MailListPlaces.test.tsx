import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderApp } from "../../test/render";

const search = (router: { state: { location: { search: string } } }) =>
  decodeURIComponent(router.state.location.search);

describe("the mail list and the page Orte (D247, D248)", () => {
  it("opens the page Orte with the list's filters (Auf der Karte)", async () => {
    renderApp("/mails?q=Spende&has_attachment=true&sort=date_asc");
    const link = await screen.findByRole("link", { name: "Auf der Karte" });
    expect(link.getAttribute("href")).toBe("/orte?q=Spende&has_attachment=true");
  });

  it("shows the photos of a map's view as a chip that can be removed", async () => {
    const { calls, router } = renderApp("/mails?q=Spende&photo_area=5.9,47.3,15.1,55.1");
    const remove = await screen.findByRole("button", {
      name: "Filter entfernen: Fotos im Kartenausschnitt",
    });
    const listCalls = () => calls.filter((call) => call.url.pathname === "/api/mails");
    await waitFor(() => expect(listCalls().length).toBeGreaterThan(0));
    expect(listCalls()[0].url.searchParams.get("photo_area")).toBe("5.9,47.3,15.1,55.1");
    fireEvent.click(remove);
    await waitFor(() => expect(search(router)).toBe("?q=Spende"));
    expect(screen.queryByRole("button", { name: /Fotos im Kartenausschnitt/ })).toBeNull();
  });
});
