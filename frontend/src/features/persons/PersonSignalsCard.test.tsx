import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PersonSignals } from "../../api/types";
import { personSignals } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const TITLE = "Signale gesendeter Mails";

async function signalsCard(): Promise<HTMLElement> {
  return (await screen.findByRole("heading", { name: TITLE })).closest("section")!;
}

function withSignals(answer: PersonSignals | Response) {
  return (call: ApiCall) =>
    call.url.pathname === "/api/persons/11/signals" ? answer : fixtureApi(call);
}

/** The cells of a table row by its signal's name. */
function row(card: HTMLElement, name: string): string[] {
  const header = within(card).getByRole("rowheader", { name });
  return [...header.closest("tr")!.children].map((cell) => cell.textContent ?? "");
}

describe("signals of a person's sent mails", () => {
  it("count each signal, its share of the sent mails beside the archive's, and link them", async () => {
    const { calls } = renderApp("/personen/11");
    const card = await signalsCard();
    await within(card).findByRole("table");
    expect(calls.filter((call) => call.url.pathname === "/api/persons/11/signals")).toHaveLength(1);
    expect(within(card).getByText("3.412 Mails gesendet, ohne Duplikate")).toBeTruthy();
    expect(
      within(card)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Signal", "Mails", "Anteil", "Im Archiv"]);
    expect(row(card, "Private Adresse")).toEqual([
      "Private Adresse",
      "412",
      "12,1\u00a0%",
      "4,5\u00a0%",
    ]);
    expect(row(card, "Nachts")).toEqual(["Nachts", "96", "2,8\u00a0%", "3,9\u00a0%"]);
    expect(row(card, "Wortfeld Spendenaffären")).toEqual([
      "Wortfeld Spendenaffären",
      "41",
      "1,2\u00a0%",
      "0,5\u00a0%",
    ]);
    expect(
      within(card)
        .getByRole("link", { name: "412 Mails mit Private Adresse" })
        .getAttribute("href"),
    ).toBe("/mails?person=11&person_role=sent&signal=private");
    expect(
      within(card)
        .getByRole("link", { name: "41 Mails mit Wortfeld Spendenaffären" })
        .getAttribute("href"),
    ).toBe("/mails?person=11&person_role=sent&signal=term%3Aspenden");
    expect(within(card).queryByText(/Verstummt/)).toBeNull();
  });

  it("say since when the person fell silent, with the timeline", async () => {
    renderApp(
      "/personen/11",
      withSignals({ ...personSignals, silent_since: "2025-07-01T00:00:00Z", silent_mails: 48 }),
    );
    const card = await signalsCard();
    const line = await within(card).findByText(/^Verstummt seit/);
    expect(line.textContent).toBe(
      "Verstummt seit Juli 2025, davor 48 Mails in sechs Monaten. Zeitachse",
    );
    expect(within(line).getByRole("link", { name: "Zeitachse" }).getAttribute("href")).toBe(
      "/zeitachse?person=11",
    );
  });

  it("show the silence alone when no sent mail has a signal", async () => {
    renderApp(
      "/personen/11",
      withSignals({
        sent: 0,
        signals: [],
        silent_since: "2025-07-01T00:00:00Z",
        silent_mails: 1,
      }),
    );
    const card = await signalsCard();
    expect(
      await within(card).findByText(/^Verstummt seit Juli 2025, davor 1 Mail in sechs Monaten/),
    ).toBeTruthy();
    expect(within(card).queryByRole("table")).toBeNull();
  });

  it("step aside when there is nothing to say", async () => {
    const { calls } = renderApp(
      "/personen/11",
      withSignals({ sent: 12, signals: [], silent_since: null, silent_mails: null }),
    );
    await screen.findByRole("heading", { name: "Anna Keller", level: 1 });
    await waitFor(() =>
      expect(calls.some((call) => call.url.pathname === "/api/persons/11/signals")).toBe(true),
    );
    await waitFor(() => expect(screen.queryByRole("heading", { name: TITLE })).toBeNull());
  });

  it("offer a retry when they cannot be loaded", async () => {
    let fail = true;
    renderApp("/personen/11", (call) =>
      call.url.pathname === "/api/persons/11/signals" && fail
        ? Response.json({ detail: "boom" }, { status: 500 })
        : fixtureApi(call),
    );
    const card = await signalsCard();
    expect(await within(card).findByText("Die Signale konnten nicht geladen werden.")).toBeTruthy();
    fail = false;
    fireEvent.click(within(card).getByRole("button", { name: "Erneut versuchen" }));
    expect(await within(card).findByRole("table")).toBeTruthy();
  });

  it("ask for the root when the profile was opened by an alias", async () => {
    const { calls } = renderApp("/personen/21");
    await signalsCard();
    await waitFor(() =>
      expect(
        calls.filter((call) => call.url.pathname.endsWith("/signals")).map((c) => c.url.pathname),
      ).toEqual(["/api/persons/11/signals"]),
    );
  });
});
