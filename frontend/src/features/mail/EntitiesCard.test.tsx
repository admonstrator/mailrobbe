import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { fixtureApi, openFolds, renderApp } from "../../test/render";

async function entitiesCard(): Promise<HTMLElement> {
  const heading = await screen.findByRole("heading", { name: /^Erkannt in dieser Mail/ });
  return heading.closest("section")!;
}

describe("entities of one mail", () => {
  it("are grouped by kind, mentions in text and attachments together", async () => {
    openFolds("mail.entities");
    const { calls } = renderApp("/mails/184221");
    const card = await entitiesCard();
    await within(card).findByRole("link", { name: "12.500,00 EUR" });
    expect(within(card).getByRole("heading", { level: 2 }).textContent).toBe(
      "Erkannt in dieser Mail (15)",
    );
    expect(calls.filter((call) => call.url.pathname === "/api/mails/184221/entities")).toHaveLength(
      1,
    );

    // The first 12 entries, by kind group and kind.
    expect(
      within(card)
        .getAllByRole("heading", { level: 3 })
        .map((heading) => heading.textContent),
    ).toEqual([
      "Beträge",
      "Konten",
      "Organisationen",
      "Personen",
      "Orte",
      "Telefon",
      "E-Mail",
      "Web",
    ]);

    const amount = within(card).getByRole("link", { name: "12.500,00 EUR" }).closest("li")!;
    expect(within(amount).getByRole("link", { name: "12.500,00 EUR" }).getAttribute("href")).toBe(
      "/entitaeten/312",
    );
    // Occurrences add up, contexts join, the attachment is named.
    expect(within(amount).getByText("3×")).toBeTruthy();
    expect(within(amount).getByText("Bargeld")).toBeTruthy();
    expect(within(amount).getByText("Spende")).toBeTruthy();
    expect(amount.textContent).toContain("auch im Anhang Rahmenvereinbarung_2026_final.pdf");
    expect(
      within(amount)
        .getByRole("link", { name: "Rahmenvereinbarung_2026_final.pdf" })
        .getAttribute("href"),
    ).toBe("/anhaenge/5101");
    expect(
      within(amount).getByRole("link", { name: "Mails mit 12.500,00 EUR" }).getAttribute("href"),
    ).toBe("/mails?entity=312");

    // Only in the attachment: "im Anhang".
    const iban = within(card)
      .getByRole("link", { name: "DE89 3704 0044 0532 0130 00" })
      .closest("li")!;
    expect(iban.textContent).toContain("im Anhang Rahmenvereinbarung_2026_final.pdf");
    expect(iban.textContent).not.toContain("auch im Anhang");
    // Once mentioned: no count.
    const place = within(card).getByRole("link", { name: "Köln" }).closest("li")!;
    expect(within(place).queryByText(/×$/)).toBeNull();
  });

  it("show the first 12 and all on request", async () => {
    openFolds("mail.entities");
    renderApp("/mails/184221");
    const card = await entitiesCard();
    await within(card).findByRole("link", { name: "12.500,00 EUR" });
    expect(within(card).queryByRole("link", { name: "Barspende" })).toBeNull();
    fireEvent.click(within(card).getByRole("button", { name: "alle 15 zeigen" }));
    const term = within(card).getByRole("link", { name: "Barspende" }).closest("li")!;
    expect(term.textContent).toContain("im Anhang Rahmenvereinbarung_2026_final.pdf");
    expect(within(card).getAllByRole("heading", { level: 3 }).at(-1)!.textContent).toBe(
      "Themenbegriffe",
    );
    expect(within(card).getByRole("button", { name: "Weniger zeigen" })).toBeTruthy();
  });

  it("say when nothing was found", async () => {
    openFolds("mail.entities");
    renderApp("/mails/184221", (call) =>
      call.url.pathname === "/api/mails/184221/entities" ? [] : fixtureApi(call),
    );
    const card = await entitiesCard();
    expect(await within(card).findByText("Nichts erkannt.")).toBeTruthy();
  });
});
