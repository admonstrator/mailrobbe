import { fireEvent, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MailSignals } from "../../api/types";
import { mailSignals, mailSignalsAttachments, mailSignalsForward } from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

async function signalsCard(): Promise<HTMLElement> {
  const heading = await screen.findByRole("heading", { name: "Warum fällt diese Mail auf" });
  return heading.closest("section")!;
}

function withSignals(answer: MailSignals | Response) {
  return (call: ApiCall) =>
    call.url.pathname === "/api/mails/184221/signals" ? answer : fixtureApi(call);
}

/** An entry of the card by its signal's name. */
function entry(card: HTMLElement, name: string): HTMLElement {
  return within(card).getByText(name, { selector: "span" }).closest("li")!;
}

describe("why a mail shows signals", () => {
  it("lists its signals in the response's order, each with what makes it hold", async () => {
    const { calls } = renderApp("/mails/184221");
    const card = await signalsCard();
    await within(card).findByText("Private Adresse");
    expect(calls.filter((call) => call.url.pathname === "/api/mails/184221/signals")).toHaveLength(
      1,
    );
    const names = within(card)
      .getAllByRole("listitem")
      .map((item) => item.firstElementChild?.firstElementChild?.textContent);
    expect(names).toEqual([
      "Private Adresse",
      "Von intern an privat",
      "Private Zweitadresse",
      "Blindkopie (Bcc)",
      "Wochenende",
      "Wortfeld Spendenaffären",
    ]);

    // The persons concerned, with the address the signal is about.
    const internal = entry(card, "Von intern an privat");
    const persons = within(internal).getAllByRole("link", { name: "Anna Keller" });
    expect(persons.map((link) => link.getAttribute("href"))).toEqual([
      "/personen/11",
      "/personen/22",
    ]);
    expect(internal.textContent).toContain(
      "Anna Keller (anna.keller@nordlicht-gmbh.example), Anna Keller (annakeller78@mail.example)",
    );
    expect(entry(card, "Blindkopie (Bcc)").textContent).toContain(
      "in Bcc: Anna Keller (annakeller78@mail.example)",
    );

    // The local time with its own offset, and the zone.
    expect(entry(card, "Wochenende").textContent).toContain("So, 18.10.2026 14:32 (Europe/Berlin)");

    // The terms found, each leading to its mails.
    const wording = entry(card, "Wortfeld Spendenaffären");
    expect(within(wording).getByRole("link", { name: "Spende" }).getAttribute("href")).toBe(
      "/mails?entity=302",
    );
    expect(within(wording).getByRole("link", { name: "Barspende" }).getAttribute("href")).toBe(
      "/mails?entity=301",
    );

    // Each signal leads to the mails with it.
    expect(
      within(card).getByRole("link", { name: "Mails mit Wochenende" }).getAttribute("href"),
    ).toBe("/mails?signal=weekend");
    expect(
      within(card)
        .getByRole("link", { name: "Mails mit Wortfeld Spendenaffären" })
        .getAttribute("href"),
    ).toBe("/mails?signal=term%3Aspenden");
    expect(within(card).getByText(/sie bewerten nichts/)).toBeTruthy();
    expect(within(card).getByRole("link", { name: "einfachen Regeln" }).getAttribute("href")).toBe(
      "/auffaelligkeiten",
    );
  });

  it("shows recipients, forwards and the hour of another zone as they are", async () => {
    renderApp("/mails/184221", withSignals(mailSignalsForward));
    const card = await signalsCard();
    await within(card).findByText("Viele Empfänger");
    expect(entry(card, "Viele Empfänger").textContent).toContain("31 Empfänger");
    const forward = entry(card, "Weiterleitung");
    expect(forward.textContent).toContain("Betreff mit „WG:“");
    expect(forward.textContent).toContain("Mail im Anhang: Angebot.eml");
    const out = entry(card, "Weiterleitung nach außen");
    expect(out.textContent).toContain("Betreff mit „Fwd:“");
    expect(out.textContent).toContain("Mail im Anhang (ohne Dateinamen)");
    expect(out.textContent).toContain("an Thomas Weber (t.weber@post.example)");
    // 23:41 in New York, not 05:41 in the browser's Berlin.
    expect(entry(card, "Nachts").textContent).toContain("Di, 04.11.2025 23:41 (America/New_York)");
  });

  it("links the documents of the signals of concealment (D238)", async () => {
    renderApp("/mails/184221", withSignals(mailSignalsAttachments));
    const card = await signalsCard();
    await within(card).findByText("Verschlüsselter Anhang");
    const encrypted = entry(card, "Verschlüsselter Anhang");
    expect(
      within(encrypted).getByRole("link", { name: "Spendenliste_2019.xlsx" }).getAttribute("href"),
    ).toBe("/anhaenge/5104");
    const separate = entry(card, "Kennwort separat geschickt");
    expect(separate.textContent).toContain("öffnete Angebot_Nordstahl.pdf, (ohne Dateinamen)");
    expect(
      within(separate)
        .getAllByRole("link")
        .slice(1)
        .map((link) => link.getAttribute("href")),
    ).toEqual(["/anhaenge/5110", "/anhaenge/5106"]);
  });

  it("says when no signal holds", async () => {
    renderApp("/mails/184221", withSignals({ ...mailSignals, signals: [] }));
    const card = await signalsCard();
    expect(await within(card).findByText("Keine Signale.")).toBeTruthy();
    expect(within(card).queryByText(/bewerten nichts/)).toBeNull();
  });

  it("says that the next import computes them while no signals phase ran", async () => {
    renderApp("/mails/184221", withSignals({ ...mailSignals, signals: [], computed_at: null }));
    const card = await signalsCard();
    expect(
      await within(card).findByText("Signale werden beim nächsten Import berechnet."),
    ).toBeTruthy();
    expect(within(card).queryByText("Keine Signale.")).toBeNull();
  });

  it("offers a retry when they cannot be loaded", async () => {
    let fail = true;
    renderApp("/mails/184221", (call) =>
      call.url.pathname === "/api/mails/184221/signals" && fail
        ? Response.json({ detail: "boom" }, { status: 500 })
        : fixtureApi(call),
    );
    const card = await signalsCard();
    expect(await within(card).findByText("Konnte nicht geladen werden.")).toBeTruthy();
    fail = false;
    fireEvent.click(within(card).getByRole("button", { name: "Erneut versuchen" }));
    expect(await within(card).findByText("Private Adresse")).toBeTruthy();
  });

  it("sits in the side column right after the research card and the attachments", async () => {
    renderApp("/mails/184221");
    await signalsCard();
    const side = screen.getByRole("complementary", { name: "Zur Mail" });
    const titles = within(side)
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent);
    expect(titles.slice(0, 3)).toEqual(["Recherche", "Anhänge (2)", "Warum fällt diese Mail auf"]);
  });
});
