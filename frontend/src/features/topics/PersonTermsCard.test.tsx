import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { annaProfile, topicStateNever, topicTerms } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const termCalls = (calls: ApiCall[]) =>
  calls.filter((call) => call.url.pathname === "/api/topics/terms");

/** The fixture backend with the terms' answer replaced. */
function withTerms(answer: unknown) {
  return (call: ApiCall) => (call.url.pathname === "/api/topics/terms" ? answer : fixtureApi(call));
}

async function card(): Promise<HTMLElement> {
  return (await screen.findByRole("heading", { name: "Auffällige Begriffe" })).closest("section")!;
}

describe("profile card of a person's terms", () => {
  it("lists the terms of the person's sent mails, each opening their mails", async () => {
    const { calls } = renderApp("/personen/11");
    const terms = await within(await card()).findByRole("list", {
      name: "Auffällige Begriffe der gesendeten Mails",
    });
    expect(termCalls(calls).map((call) => call.url.search)).toEqual([
      "?person=11&person_role=sent&limit=12",
    ]);
    const links = within(terms).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Rahmenvertrag 212",
      "Wartung 180",
      "Umspannwerk 95",
      "Spende 40",
      "Kassenprüfung 4",
    ]);
    expect(links[1].getAttribute("href")).toBe(
      "/mails?q=Wartung&hide_duplicates=true&person=11&person_role=sent",
    );
    expect(
      within(await card())
        .getByRole("link", { name: "Alle Begriffe" })
        .getAttribute("href"),
    ).toBe("/themen?view=selection&person=11&person_role=sent");
    // In the overview beside the contacts, above the signals.
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings.indexOf("Auffällige Begriffe")).toBe(
      headings.indexOf("Mit wem am meisten") + 1,
    );
    expect(
      within(await card())
        .getByRole("img")
        .getAttribute("title"),
    ).toBe("In den gesendeten Mails, verglichen mit dem übrigen Archiv");
  });

  it("says quietly that the next import computes the terms", async () => {
    renderApp(
      "/personen/11",
      withTerms({ ...topicTerms, state: topicStateNever, mails: null, terms: [], common: [] }),
    );
    const found = await card();
    expect(
      await within(found).findByText(/Die Begriffe werden beim nächsten Import berechnet\./),
    ).toBeTruthy();
    expect(within(found).getByRole("link", { name: "Zum Import" }).getAttribute("href")).toBe(
      "/import",
    );
  });

  it("says quietly when no word stands out", async () => {
    renderApp("/personen/11", withTerms({ ...topicTerms, terms: [] }));
    expect(
      await within(await card()).findByText(
        "Kein Wort ist in den gesendeten Mails mindestens doppelt so häufig wie im übrigen Archiv.",
      ),
    ).toBeTruthy();
  });

  it("is left out for a person who sent nothing", async () => {
    const quiet = { ...annaProfile, figures: { ...annaProfile.figures!, sent: 0 } };
    const { calls } = renderApp("/personen/11", (call) =>
      call.url.pathname === "/api/persons/11" ? quiet : fixtureApi(call),
    );
    await screen.findByRole("heading", { name: "Anna Keller", level: 1 });
    expect(screen.queryByRole("heading", { name: "Auffällige Begriffe" })).toBeNull();
    expect(termCalls(calls)).toHaveLength(0);
  });
});
