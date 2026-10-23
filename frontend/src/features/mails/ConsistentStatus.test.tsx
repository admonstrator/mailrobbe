import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mailPage, stats, summaryAll } from "../../test/fixtures";
import { figures, openFilter } from "../../test/mailList";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

// "Signatur stimmig" (D100) where the mail list shows statuses: the filter, the line of figures and
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

describe("consistent in the mail list", () => {
  it("counts consistent mails as signed but not as valid", async () => {
    renderApp("/mails", api);
    const { pass, fail, no_key, temp_error } = summaryAll.dkim!;
    const signed = pass + 120 + fail + no_key + temp_error;
    const valid = await within(figures()).findByText("DKIM gültig", { exact: false });
    expect(valid.getAttribute("title")).toMatch(
      new RegExp(
        `^von ${signed.toLocaleString("de-DE").replace(".", "\\.")} signierten, 120 stimmig\\. Gültig: Der Schlüssel steht heute im DNS`,
      ),
    );
  });

  it("filters by it and marks its rows with a ring", async () => {
    const { router } = renderApp("/mails", api);
    const box = await within(await openFilter("DKIM")).findByRole("checkbox", {
      name: /Signatur stimmig/,
    });
    expect(box.closest("label")!.textContent).toBe("Signatur stimmig5.336");
    expect(screen.getAllByRole("img", { name: "Signatur stimmig" }).length).toBeGreaterThan(0);

    fireEvent.click(box);
    const search = new URLSearchParams(router.state.location.search);
    expect(search.getAll("dkim")).toEqual(["pass", "fail", "no_key", "unsigned"]);
  });
});
