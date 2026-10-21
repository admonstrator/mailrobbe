import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mailPage, stats, summaryAll } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

// "Signatur stimmig" (D100) where the mail list shows statuses: the filter, the summary tiles and
// the dots of the rows.

function api(call: ApiCall): unknown {
  switch (call.url.pathname) {
    case "/api/stats":
      return { ...stats, dkim: { ...stats.dkim, consistent: 5_336 } };
    case "/api/mails/summary":
      return { ...summaryAll, dkim: { ...summaryAll.dkim!, consistent: 120 } };
    case "/api/mails": {
      const [first, ...rest] = mailPage.items;
      return { ...mailPage, items: [{ ...first, dkim_status: "consistent" }, ...rest] };
    }
    default:
      return fixtureApi(call);
  }
}

function tile(label: string): HTMLElement {
  return within(screen.getByRole("main")).getByText(label, { selector: "span" }).parentElement!;
}

describe("consistent in the mail list", () => {
  it("counts consistent mails as signed but not as valid", async () => {
    renderApp("/mails", api);
    const { pass, fail, no_key, temp_error } = summaryAll.dkim!;
    const signed = pass + 120 + fail + no_key + temp_error;
    await waitFor(() =>
      expect(
        within(tile("DKIM gültig")).getByText(
          `von ${signed.toLocaleString("de-DE")} signierten, 120 stimmig`,
        ),
      ).toBeTruthy(),
    );
    expect(tile("DKIM gültig").getAttribute("title")).toMatch(
      /^Gültig: Der Schlüssel steht heute im DNS/,
    );
  });

  it("filters by it and marks its rows with a ring", async () => {
    const { router } = renderApp("/mails", api);
    const box = await screen.findByRole("checkbox", { name: /Signatur stimmig/ });
    expect(box.closest("label")!.textContent).toBe("Signatur stimmig5.336");
    expect(screen.getAllByRole("img", { name: "Signatur stimmig" }).length).toBeGreaterThan(0);

    fireEvent.click(box);
    const search = new URLSearchParams(router.state.location.search);
    expect(search.getAll("dkim")).toEqual(["pass", "fail", "no_key", "unsigned"]);
  });
});
