import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { themes } from "../../test/fixtures";
import { fixtureApi, renderApp } from "../../test/render";

describe("word fields of the themes", () => {
  it("lead to the mails of a term's entity where there is one, else to the search (D138)", async () => {
    renderApp("/akten?tab=themen", (call) =>
      call.url.pathname === "/api/research/themes"
        ? [{ ...themes[0], terms: ["Spende", "nicht weiterleiten"], term_ids: [302, null] }]
        : fixtureApi(call),
    );
    const words = await screen.findByRole("list", { name: "Wortfeld Spendenaffären" });
    // The entity scan matches the phrase as written; the full text search would drop "nicht".
    expect(within(words).getByRole("link", { name: "Spende" }).getAttribute("href")).toBe(
      "/mails?entity=302",
    );
    expect(
      within(words).getByRole("link", { name: "nicht weiterleiten" }).getAttribute("href"),
    ).toBe("/mails?q=%22nicht+weiterleiten%22");
  });
});
