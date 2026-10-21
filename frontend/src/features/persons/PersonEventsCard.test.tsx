import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PersonEvents } from "../../api/types";
import { personEvents } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

const EVENTS = "/api/persons/11/events";

async function eventsCard(): Promise<HTMLElement> {
  return (await screen.findByRole("heading", { name: "Termine" })).closest("section")!;
}

function withEvents(answer: PersonEvents | Response) {
  return (call: ApiCall) => (call.url.pathname === EVENTS ? answer : fixtureApi(call));
}

/** The cells of the row whose event has this summary. */
function row(card: HTMLElement, summary: string): string[] {
  const link = within(card).getByRole("link", { name: summary });
  return [...link.closest("tr")!.children].map((cell) => cell.textContent ?? "");
}

describe("events of a person", () => {
  it("list each event with its date, its mail, and who organised it or the answer", async () => {
    const { calls } = renderApp("/personen/11");
    const card = await eventsCard();
    expect(calls.filter((call) => call.url.pathname === EVENTS)).toHaveLength(1);
    expect(within(card).getByText("3 Termine")).toBeTruthy();
    expect(
      within(card)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Wann", "Termin", "Beteiligung"]);
    expect(row(card, "Abstimmung Rahmenvereinbarung 2026")).toEqual([
      "Di, 27.10.2026, 10:00",
      "Abstimmung Rahmenvereinbarung 2026",
      "organisiert",
    ]);
    // Written in UTC, dated in Berlin; cancelled, after Anna had accepted.
    expect(row(card, "Jahresgespräch Stadtwerke")).toEqual([
      "Di, 15.09.2026, 15:00",
      "Jahresgespräch StadtwerkeAbsage",
      "zugesagt, eingeladen von Jonas Brandt",
    ]);
    expect(row(card, "Verbandstag Nord")).toEqual([
      "Do, 04.06.2026",
      "Verbandstag Nord",
      "eingeladen von Verband Nord",
    ]);

    const mail = within(card).getByRole("link", { name: "Jahresgespräch Stadtwerke" });
    expect(mail.getAttribute("href")).toBe("/mails/183950");
    expect(mail.getAttribute("title")).toBe("Abgesagt: Jahresgespräch Stadtwerke");
    expect(within(card).getByRole("link", { name: "Jonas Brandt" }).getAttribute("href")).toBe(
      "/personen/12",
    );
    expect(
      within(card)
        .getByRole("link", { name: "Alle Einladungen in der Mailliste" })
        .getAttribute("href"),
    ).toBe("/mails?person=11&event=request&event=reply&event=cancel");
  });

  it("say how many are listed when there are more", async () => {
    renderApp("/personen/11", withEvents({ ...personEvents, total: 73 }));
    const card = await eventsCard();
    expect(within(card).getByText("73 Termine, die 3 neuesten")).toBeTruthy();
  });

  it("are hidden for a person without events", async () => {
    renderApp("/personen/11", withEvents({ items: [], total: 0 }));
    await screen.findByRole("heading", { name: "Signale gesendeter Mails" });
    await screen.findByRole("heading", { name: "Anna Keller", level: 1 });
    expect(screen.queryByRole("heading", { name: "Termine" })).toBeNull();
  });

  it("offer to load them again after an error", async () => {
    let fail = true;
    renderApp("/personen/11", (call) =>
      call.url.pathname === EVENTS && fail
        ? Response.json({ detail: { code: "x", message: "down" } }, { status: 500 })
        : fixtureApi(call),
    );
    const card = await eventsCard();
    expect(within(card).getByRole("alert").textContent).toContain(
      "Die Termine konnten nicht geladen werden.",
    );
    fail = false;
    fireEvent.click(within(card).getByRole("button", { name: "Erneut versuchen" }));
    expect(await within(card).findByText("3 Termine")).toBeTruthy();
  });
});
