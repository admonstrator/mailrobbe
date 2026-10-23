import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { calendarEvent, mailDetail, mailItems, mailPage } from "../../test/fixtures";
import { openFilter, rowOf } from "../../test/mailList";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

describe("mail list and calendar invitations", () => {
  it("marks calendar mails beside the subject with their kind", async () => {
    renderApp("/mails", (call: ApiCall) =>
      call.url.pathname === "/api/mails"
        ? {
            ...mailPage,
            items: [
              { ...mailItems[0], event: "request" },
              { ...mailItems[1], event: "cancel" },
              mailItems[2],
            ],
          }
        : fixtureApi(call),
    );
    const invitation = await screen.findByRole("img", { name: "Termin: Einladung" });
    expect(invitation.querySelector("title")?.textContent).toBe("Termin: Einladung");
    expect(invitation.closest("li")).toBe(rowOf(mailItems[0].subject!));
    const cancel = screen.getByRole("img", { name: "Termin: Absage" });
    expect(cancel.closest("li")).toBe(rowOf(mailItems[1].subject!));
    expect(screen.getAllByRole("img", { name: /^Termin:/ })).toHaveLength(2);
  });

  it("filters by kind in the popover Termine with the archive's counts", async () => {
    const { router, calls } = renderApp("/mails");
    const group = await openFilter("Termine");
    expect(
      within(group)
        .getAllByRole("checkbox")
        .map((box) => box.closest("label")!.textContent),
    ).toEqual(["Einladung312", "Antwort148", "Absage21"]);

    fireEvent.click(within(group).getByRole("checkbox", { name: /Absage/ }));
    fireEvent.click(within(group).getByRole("checkbox", { name: /Einladung/ }));
    await waitFor(() => expect(router.state.location.search).toBe("?event=request&event=cancel"));
    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.url.pathname === "/api/mails" &&
            call.url.searchParams.getAll("event").join() === "request,cancel",
        ),
      ).toBe(true),
    );
    const chip = await screen.findByRole("button", {
      name: "Filter entfernen: Termine: Einladung, Absage",
    });
    fireEvent.click(chip);
    await waitFor(() => expect(router.state.location.search).toBe(""));
  });

  it("names the chip of one event by its summary", async () => {
    const uid = calendarEvent.uid!;
    const { router, calls } = renderApp(
      `/mails?event_uid=${encodeURIComponent(uid)}`,
      (call: ApiCall) =>
        call.url.pathname === "/api/mails/184236"
          ? { ...mailDetail, id: 184236, events: [{ ...calendarEvent, kind: "reply" }] }
          : fixtureApi(call),
    );
    const chip = await screen.findByRole("button", {
      name: "Filter entfernen: Termin: Abstimmung Rahmenvereinbarung 2026",
    });
    const page = calls.find((call) => call.url.pathname === "/api/mails")!;
    expect(page.url.searchParams.get("event_uid")).toBe(uid);
    expect(screen.getAllByRole("img", { name: "Termin: Antwort" })).toHaveLength(2);
    fireEvent.click(chip);
    await waitFor(() => expect(router.state.location.search).toBe(""));
  });

  it("calls the chip of an event it cannot name a Termin", async () => {
    renderApp("/mails?event_uid=unknown%40x.example", (call: ApiCall) =>
      call.url.pathname === "/api/mails" ? { ...mailPage, items: [] } : fixtureApi(call),
    );
    expect(
      await screen.findByRole("button", { name: "Filter entfernen: Ein Termin" }),
    ).toBeTruthy();
  });
});
