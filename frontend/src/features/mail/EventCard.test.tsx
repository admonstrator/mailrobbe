import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CalendarAttendee, CalendarEventInfo, MailDetail } from "../../api/types";
import { calendarEvent, mailDetail } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";
import { eventTime, recurrenceText } from "./EventCard";

function withEvents(events: CalendarEventInfo[]) {
  const detail: MailDetail = { ...mailDetail, events };
  return (call: ApiCall) =>
    call.url.pathname === `/api/mails/${mailDetail.id}` ? detail : fixtureApi(call);
}

async function eventCard(title = "Termin"): Promise<HTMLElement> {
  return (await screen.findByRole("heading", { name: title, level: 2 })).closest("section")!;
}

/** The value beside a label of the card's facts. */
function fact(scope: HTMLElement, label: string): HTMLElement {
  return within(scope).getByText(label, { selector: "dt" }).nextElementSibling as HTMLElement;
}

const answer = (scope: HTMLElement, name: string) =>
  within(scope).getByText(name).closest("li")!.textContent;

describe("calendar events of a mail", () => {
  it("show an invitation above the text with time, place, recurrence, people and answers", async () => {
    const { calls } = renderApp(`/mails/${mailDetail.id}`, withEvents([calendarEvent]));
    const card = await eventCard();

    // In the main column, after the DKIM box and before the text.
    const dkim = screen.getByRole("heading", { name: "DKIM-Prüfung" }).closest("section")!;
    expect(dkim.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const body = screen.getByRole("tab", { name: "Text" }).closest("section")!;
    expect(card.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    expect(within(card).getByText("Einladung")).toBeTruthy();
    expect(within(card).getByText("Abstimmung Rahmenvereinbarung 2026")).toBeTruthy();
    expect(within(card).queryByRole("note")).toBeNull();
    // Written in a Windows zone that is Berlin's: no second time.
    expect(fact(card, "Wann").textContent).toBe(
      "Di, 27.10.2026, 10:00–11:30 (W. Europe Standard Time)",
    );
    expect(fact(card, "Wo").textContent).toBe("Besprechungsraum 3, Hafenstraße 12");
    const rule = fact(card, "Wiederholung");
    expect(rule.textContent).toBe("wöchentlich am Di, 6-mal");
    expect(rule.getAttribute("title")).toBe("FREQ=WEEKLY;BYDAY=TU;COUNT=6");

    const organizer = fact(card, "Organisiert von");
    expect(within(organizer).getByRole("link", { name: "Anna Keller" }).getAttribute("href")).toBe(
      "/personen/11",
    );
    const attendees = fact(card, "Teilnehmende");
    expect(
      within(attendees)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "Jonas Brandt <j.brandt@stadtwerke-beispiel.example>zugesagt",
      "Dr. Miriam Steiner <steiner@kanzlei-muster.example> (optional)vorläufig",
      "Besprechungsraum 3 <raum.3@nordlicht-gmbh.example> (zur Information)offen",
    ]);
    expect(within(attendees).getByRole("link", { name: "Jonas Brandt" }).getAttribute("href")).toBe(
      "/personen/12",
    );
    expect(within(attendees).queryByRole("link", { name: "Besprechungsraum 3" })).toBeNull();

    const description = within(card).getByText("Beschreibung").closest("details")!;
    expect(description.open).toBe(false);
    expect(description.textContent).toContain("1. Haftung");

    // The other mails of the UID, without this one, and the list of them all.
    const others = within(card)
      .getByRole("heading", { name: "Weitere Mails zu diesem Termin" })
      .closest("div")!;
    await within(others).findByRole("link", { name: /^Angenommen:/ });
    expect(
      within(others)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "AntwortAngenommen: Abstimmung Rahmenvereinbarung 2026Jonas Brandt · 21.10.2026",
      "AntwortMit Vorbehalt angenommen: Abstimmung Rahmenvereinbarung 2026Dr. Miriam Steiner · 20.10.2026",
    ]);
    expect(
      within(others)
        .getByRole("link", { name: /^Angenommen:/ })
        .getAttribute("href"),
    ).toBe("/mails/184236");
    const page = calls.find((call) => call.url.searchParams.has("event_uid"))!;
    expect(page.url.searchParams.get("event_uid")).toBe(calendarEvent.uid);
    const all = within(others).getByRole("link", {
      name: "Alle 3 Mails zu diesem Termin in der Mailliste",
    });
    expect(all.getAttribute("href")).toBe(
      `/mails?event_uid=${encodeURIComponent(calendarEvent.uid!)}`,
    );
  });

  it("show an answer with the time in Berlin when it was written in UTC", async () => {
    const reply: CalendarEventInfo = {
      ...calendarEvent,
      kind: "reply",
      method: "REPLY",
      starts_local: "2026-11-03T13:00:00",
      ends_local: "2026-11-03T14:00:00",
      time_zone: "UTC",
      starts_at: "2026-11-03T13:00:00Z",
      ends_at: "2026-11-03T14:00:00Z",
      recurrence: null,
      description: null,
      attendees: [calendarEvent.attendees[0]],
      uid_mails: 1,
    };
    renderApp(`/mails/${mailDetail.id}`, withEvents([reply]));
    const card = await eventCard();
    expect(within(card).getByText("Antwort")).toBeTruthy();
    expect(fact(card, "Wann").textContent).toBe(
      "Di, 03.11.2026, 13:00–14:00 (UTC)in Berlin: Di, 03.11.2026, 14:00–15:00",
    );
    expect(answer(fact(card, "Antwort von"), "Jonas Brandt")).toBe(
      "Jonas Brandt <j.brandt@stadtwerke-beispiel.example>zugesagt",
    );
    expect(within(card).queryByText("Wiederholung")).toBeNull();
    expect(within(card).queryByText("Beschreibung")).toBeNull();
    // The only mail of its UID: nothing more to link.
    expect(within(card).queryByText("Weitere Mails zu diesem Termin")).toBeNull();
  });

  it("mark a cancellation and show all-day events by their days", async () => {
    const cancel: CalendarEventInfo = {
      ...calendarEvent,
      id: 902,
      kind: "cancel",
      method: "CANCEL",
      status: "CANCELLED",
      sequence: 1,
      summary: "Verbandstag Nord",
      starts_local: "2026-06-04T00:00:00",
      ends_local: "2026-06-06T00:00:00",
      time_zone: null,
      starts_at: null,
      ends_at: null,
      all_day: true,
      recurrence: "FREQ=MONTHLY;BYDAY=1TH",
      uid_mails: 0,
      uid: null,
    };
    const floating: CalendarEventInfo = {
      ...calendarEvent,
      id: 903,
      sequence: 2,
      summary: "Telefonat",
      starts_local: "2026-06-10T09:00:00",
      ends_local: null,
      time_zone: null,
      starts_at: null,
      ends_at: null,
      recurrence: null,
      organizer: null,
      attendees: [],
      uid_mails: 1,
    };
    renderApp(`/mails/${mailDetail.id}`, withEvents([cancel, floating]));
    const card = await eventCard("Termine (2)");
    const [first, second] = within(card).getAllByRole("article");
    expect(within(first).getByText("Absage")).toBeTruthy();
    expect(within(first).getByRole("note").textContent).toBe(
      "Abgesagt: Dieser Termin wurde abgesagt.",
    );
    expect(fact(first, "Wann").textContent).toBe("Do, 04.06.2026 – Fr, 05.06.2026 (ganztägig)");
    // A rule that is not simple stays as written.
    expect(fact(first, "Wiederholung").textContent).toBe("FREQ=MONTHLY;BYDAY=1TH");
    expect(within(first).queryByText(/^geändert/)).toBeNull();

    expect(within(second).getByText("Einladung")).toBeTruthy();
    expect(within(second).getByText("geändert (Fassung 3)").getAttribute("title")).toBe(
      "SEQUENCE:2",
    );
    expect(within(second).queryByRole("note")).toBeNull();
    expect(fact(second, "Wann").textContent).toBe("Mi, 10.06.2026, 09:00 (ohne Zeitzone)");
    expect(within(second).queryByText("Organisiert von")).toBeNull();
    expect(within(second).queryByText("Teilnehmende")).toBeNull();
  });

  it("fold attendees beyond the first twelve", async () => {
    const many: CalendarAttendee[] = Array.from({ length: 15 }, (_, index) => ({
      email: `person${index + 1}@verband.example`,
      name: null,
      role: null,
      partstat: null,
      person: null,
    }));
    renderApp(`/mails/${mailDetail.id}`, withEvents([{ ...calendarEvent, attendees: many }]));
    const attendees = fact(await eventCard(), "Teilnehmende");
    const more = within(attendees).getByText("und 3 weitere").closest("details")!;
    expect(more.open).toBe(false);
    expect(within(more).getAllByRole("listitem")).toHaveLength(3);
    expect(within(attendees).getAllByRole("listitem")).toHaveLength(15);
    expect(within(attendees).getByText("person1@verband.example")).toBeTruthy();
  });

  it("are not shown for a mail without events", async () => {
    renderApp(`/mails/${mailDetail.id}`);
    await screen.findByRole("heading", { name: "DKIM-Prüfung" });
    expect(screen.queryByRole("heading", { name: "Termin" })).toBeNull();
  });
});

describe("event times and rules in words", () => {
  it("say a simple rule in words and keep any other as written", () => {
    expect(recurrenceText("FREQ=WEEKLY")).toBe("wöchentlich");
    expect(recurrenceText("FREQ=DAILY;INTERVAL=1")).toBe("täglich");
    expect(recurrenceText("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH")).toBe("alle 2 Wochen am Mo, Do");
    expect(recurrenceText("FREQ=MONTHLY;BYMONTHDAY=4;COUNT=6")).toBe("monatlich am 4., 6-mal");
    expect(recurrenceText("freq=yearly;until=20301231T225959Z")).toBe("jährlich, bis 31.12.2030");
    expect(recurrenceText("FREQ=WEEKLY;WKST=MO;BYDAY=FR")).toBe("wöchentlich am Fr");
    for (const rule of [
      "FREQ=MONTHLY;BYDAY=-1FR",
      "FREQ=WEEKLY;BYSETPOS=1",
      "FREQ=HOURLY",
      "FREQ=DAILY;INTERVAL=0",
      "",
    ]) {
      expect(recurrenceText(rule)).toBe(rule);
    }
  });

  it("write a time across midnight with both days and know Berlin's summer time", () => {
    const night: CalendarEventInfo = {
      ...calendarEvent,
      starts_local: "2026-07-01T22:30:00",
      ends_local: "2026-07-02T01:00:00",
      time_zone: "America/New_York",
      starts_at: "2026-07-02T02:30:00Z",
      ends_at: "2026-07-02T05:00:00Z",
    };
    expect(eventTime(night)).toEqual({
      written: "Mi, 01.07.2026, 22:30 – Do, 02.07.2026, 01:00",
      zone: "America/New_York",
      berlin: "Do, 02.07.2026, 04:30–07:00",
    });
    expect(eventTime({ ...night, starts_local: null })).toBeNull();
    const day = { ...night, all_day: true, starts_local: "2026-07-01T00:00:00", ends_local: null };
    expect(eventTime(day)).toEqual({ written: "Mi, 01.07.2026", zone: null, berlin: null });
  });
});
