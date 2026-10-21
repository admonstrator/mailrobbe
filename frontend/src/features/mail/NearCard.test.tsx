import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mailDetailNear } from "../../test/fixtures";
import { fixtureApi, renderApp } from "../../test/render";

const listQuery = new URLSearchParams({ q: "subject:Vertrag" }).toString();

describe("near duplicates card", () => {
  it("lists the other mails of the group with their people, duplicates marked", async () => {
    renderApp(`/mails/184221?${listQuery}`, (call) =>
      call.url.pathname === "/api/mails/184221" ? mailDetailNear : fixtureApi(call),
    );
    const heading = await screen.findByRole("heading", { name: "5 nahezu gleiche Mails" });
    const card = within(heading.closest("section")!);

    const items = within(card.getByRole("list")).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      "18.10.2026 14:30Anna Keller an Dr. Miriam Steiner",
      "18.10.2026 14:30DoppeltAnna Keller an Dr. Miriam Steiner",
      "18.10.2026 14:31Anna Keller an Lukas Vogt, Peter Hofmann, Thomas Weber +1",
    ]);
    // The mails open with the list around the open mail, the persons link to their profiles.
    expect(
      within(items[2])
        .getAllByRole("link")
        .map((link) => link.getAttribute("href")),
    ).toEqual([
      `/mails/184184?${listQuery}`,
      "/personen/11",
      "/personen/14",
      "/personen/15",
      "/personen/18",
    ]);
    expect(within(items[1]).getByText("Doppelt").title).toBe("Exaktes Duplikat einer anderen Mail");
    // Five with this one: one more than listed.
    expect(card.getByText("… und 1 weitere")).toBeTruthy();
    expect(card.getByRole("link", { name: "Alle in der Mailliste" }).getAttribute("href")).toBe(
      "/mails?near_group=184180",
    );
  });

  it("stays away for a mail in no group", async () => {
    renderApp("/mails/184221");
    await screen.findByRole("heading", { name: "Thread (4 Mails)" });
    expect(screen.queryByRole("heading", { name: /nahezu gleiche/ })).toBeNull();
  });
});
