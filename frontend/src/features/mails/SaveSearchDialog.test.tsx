import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SavedSearchCreate } from "../../api/types";
import { searches } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

function api(call: ApiCall): unknown {
  if (call.method === "POST" && call.url.pathname === "/api/searches") {
    return Response.json(
      { ...searches[1], ...(call.body as SavedSearchCreate), id: 8 },
      { status: 201 },
    );
  }
  return fixtureApi(call);
}

describe("saving a search", () => {
  it("stores the list's query without cursor and page, in an Akte if chosen", async () => {
    const { calls, router } = renderApp(
      "/mails?q=Vertrag&review=relevant&tag=2&sort=date_asc&cursor=abc&page=2",
      api,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Suche speichern" }));
    const dialog = screen.getByRole("dialog", { name: "Suche speichern" });
    expect(within(dialog).getByLabelText("Name")).toHaveProperty("value", "Vertrag");
    const akte = within(dialog).getByLabelText("Akte (optional)");
    await within(akte).findByRole("option", { name: "Story Nordstahl" });
    fireEvent.change(akte, { target: { value: "1" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Speichern" }));

    const saved = await screen.findByRole("dialog", { name: "Suche gespeichert" });
    expect(
      within(saved).getByText(
        "„Vertrag“ steht in der Akte „Story Nordstahl“ und sucht bei jedem Öffnen neu.",
      ),
    ).toBeTruthy();
    const post = calls.find((call) => call.url.pathname === "/api/searches")!;
    expect(post.body).toEqual({
      name: "Vertrag",
      query: "q=Vertrag&review=relevant&tag=2&sort=date_asc",
      collection_id: 1,
    });
    fireEvent.click(within(saved).getByRole("link", { name: "In Akten ansehen" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/akten/1"));
  });

  it("names a search without text after its filters and needs no Akte", async () => {
    const { calls } = renderApp("/mails?review=relevant&has_note=true", api);
    fireEvent.click(await screen.findByRole("button", { name: "Suche speichern" }));
    const dialog = screen.getByRole("dialog", { name: "Suche speichern" });
    expect(within(dialog).getByLabelText("Name")).toHaveProperty(
      "value",
      "Mit Notiz · Status: Relevant",
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Speichern" }));
    const saved = await screen.findByRole("dialog", { name: "Suche gespeichert" });
    expect(within(saved).getByRole("link", { name: "In Akten ansehen" }).getAttribute("href")).toBe(
      "/akten",
    );
    expect(calls.find((call) => call.url.pathname === "/api/searches")!.body).toEqual({
      name: "Mit Notiz · Status: Relevant",
      query: "review=relevant&has_note=true",
      collection_id: null,
    });
  });

  it("is offered only for a filtered list", async () => {
    renderApp("/mails");
    await screen.findAllByRole("row");
    expect(screen.queryByRole("button", { name: "Suche speichern" })).toBeNull();
  });
});
