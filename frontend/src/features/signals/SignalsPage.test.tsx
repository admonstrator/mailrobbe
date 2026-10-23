import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SignalOverview } from "../../api/types";
import {
  signalOverview,
  signalOverviewAttachments,
  signalOverviewNever,
} from "../../test/fixtures";
import { fixtureApi, renderApp, type ApiCall } from "../../test/render";

function withOverview(answer: SignalOverview | Response) {
  return (call: ApiCall) => (call.url.pathname === "/api/signals" ? answer : fixtureApi(call));
}

/** When the signals were computed, and the notices about it. */
const status = () => screen.getByRole("region", { name: "Stand" });

function card(name: string): HTMLElement {
  return screen.getByRole("heading", { name, level: 2 }).closest("section")!;
}

/** A signal's entry on the overview by its name. */
function entry(name: string): HTMLElement {
  return screen.getByRole("heading", { name, level: 3 }).closest("li")!;
}

const href = (element: HTMLElement, name: string) =>
  within(element).getByRole("link", { name }).getAttribute("href");

/** The page once its figures are there. */
async function loaded(path = "/auffaelligkeiten", api = fixtureApi) {
  const rendered = renderApp(path, api);
  await screen.findByRole("heading", { name: "Regeln", level: 2 });
  return rendered;
}

describe("signal overview", () => {
  it("is a screen of its own in the navigation, explaining signals and how to search", async () => {
    const { calls } = await loaded();
    expect(screen.getByRole("heading", { name: "Signale", level: 1 })).toBeTruthy();
    expect(document.title).toBe("Signale · Mailrobbe");
    const nav = screen.getByRole("navigation", { name: "Hauptnavigation" });
    const links = within(nav)
      .getAllByRole("link")
      .map((link) => link.textContent);
    expect(links.slice(6, 9)).toEqual(["Orte", "Signale", "Entitäten"]);
    expect(within(nav).getByRole("link", { name: "Signale" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(card("Was Signale sind").textContent).toContain(
      "Signale bewerten nichts und beweisen nichts.",
    );
    expect(card("So suchen Sie damit").textContent).toContain("Warum fällt diese Mail auf");
    expect(
      within(screen.getByRole("list", { name: "Kennzahlen" }))
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "409.880 Mails ohne Duplikate",
      expect.stringMatching(/Signale mit Treffern$/),
      "3 Verstummte Personen",
    ]);
    expect(calls.filter((call) => call.url.pathname === "/api/signals")).toHaveLength(1);
  });

  it("shows the settings and when the signals were computed", async () => {
    await loaded();
    expect(status().textContent).toBe(
      "Berechnet beim Import am 20.10.2026 03:14, über 409.880 Mails ohne Duplikate.",
    );
    const settings = card("Regeln");
    const values = Object.fromEntries(
      within(settings)
        .getAllByRole("term")
        .map((term) => [term.textContent, term.nextElementSibling?.textContent]),
    );
    expect(values).toEqual({
      "Interne Domains": "nordlicht-gmbh.example",
      Zeitzone: "Europe/Berlin",
      "Private Mailanbieter": "78 Domains",
      Nachts: "22 bis 6 Uhr",
      "Viele Empfänger": "ab 25 Adressen",
      Weiterleitung: "Fwd: Fw: WG: TR: RV: ENC: Doorst: VS: VB:",
    });
    // where the rules are set, behind the "?"
    const help = within(settings).getByRole("img").getAttribute("aria-label");
    expect(help).toContain("themes.toml unter [signals]");
    expect(help).toContain("„Import starten“");
    expect(href(settings, "Einstellungen")).toBe("/einstellungen");
    expect(within(status()).queryByRole("link", { name: "Zum Import" })).toBeNull();
    expect(status().textContent).not.toContain("anderen Regeln");
  });

  it("lists the signals by group with rule, figures, links and senders", async () => {
    await loaded();
    const titles = screen
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent);
    expect(titles).toEqual([
      "Was Signale sind",
      "So suchen Sie damit",
      "Adressen",
      "Empfänger und Weiterleitungen",
      "Uhrzeit",
      "Wortfelder",
      "Personen",
      "Regeln",
    ]);
    expect(
      within(card("Adressen"))
        .getAllByRole("heading", { level: 3 })
        .map((heading) => heading.textContent),
    ).toEqual([
      "Private Adresse",
      "Von intern an privat",
      "Von privat an intern",
      "Private Zweitadresse",
    ]);

    const night = entry("Nachts");
    expect(night.id).toBe("signal-night");
    expect(night.textContent).toContain("Gesendet zwischen 22 und 6 Uhr (Europe/Berlin).");
    expect(night.textContent).toContain("15.873 Mails · 3,9\u00a0%");
    expect(night.textContent).toContain("von 1.902 Personen gesendet");
    expect(href(night, "Mails mit Nachts")).toBe("/mails?signal=night");
    expect(href(night, "Zeitachse von Nachts")).toBe("/zeitachse?signal=night");
    expect(card("Uhrzeit").textContent).toContain("Ortszeit Europe/Berlin");

    // At most five senders, each with the profile and those mails.
    const privateEntry = entry("Private Adresse");
    expect(within(privateEntry).getByText("Am häufigsten von")).toBeTruthy();
    expect(href(privateEntry, "Anna Keller")).toBe("/personen/11");
    expect(href(privateEntry, "412 Mails von Anna Keller mit Private Adresse")).toBe(
      "/mails?person=11&person_role=sent&signal=private",
    );
    expect(within(privateEntry).getAllByRole("listitem")).toHaveLength(5);
  });

  it("lists the word fields by theme, with the rule once and the way to the Akten", async () => {
    await loaded();
    const wording = card("Wortfelder");
    expect(
      within(wording)
        .getAllByRole("heading", { level: 3 })
        .map((heading) => heading.textContent),
    ).toEqual(["Spendenaffären", "Gewalt"]);
    expect(wording.textContent?.match(/Ein Begriff aus dem Wortfeld/g)).toHaveLength(1);
    expect(href(wording, "Die Wortfelder stehen unter Akten › Themen.")).toBe("/akten?tab=themen");
    const donations = entry("Spendenaffären");
    expect(href(donations, "Mails mit Wortfeld Spendenaffären")).toBe(
      "/mails?signal=term%3Aspenden",
    );
    expect(href(donations, "Anna Keller")).toBe("/personen/11");
    // Without senders, no sender line.
    expect(within(entry("Gewalt")).queryByText("Am häufigsten von")).toBeNull();
    expect(within(entry("Gewalt")).queryByRole("listitem")).toBeNull();
  });

  it("shows the signals of concealment in a group of their own (D238)", async () => {
    await loaded("/auffaelligkeiten", withOverview(signalOverviewAttachments));
    const titles = screen
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent);
    expect(titles.slice(2)).toEqual([
      "Adressen",
      "Empfänger und Weiterleitungen",
      "Uhrzeit",
      "Anhänge",
      "Wortfelder",
      "Personen",
      "Regeln",
    ]);
    const attachments = card("Anhänge");
    expect(
      within(attachments)
        .getAllByRole("heading", { level: 3 })
        .map((heading) => heading.textContent),
    ).toEqual(["Verschlüsselter Anhang", "Kennwort separat geschickt", "Verschlüsselte Mail"]);
    const encrypted = entry("Verschlüsselter Anhang");
    expect(encrypted.textContent).toContain("Ein Anhang braucht ein Kennwort");
    expect(encrypted.textContent).toContain("412 Mails");
    expect(href(encrypted, "Mails mit Verschlüsselter Anhang")).toBe(
      "/mails?signal=encrypted_attachment",
    );
    expect(href(entry("Verschlüsselte Mail"), "Zeitachse von Verschlüsselte Mail")).toBe(
      "/zeitachse?signal=encrypted_mail",
    );
    // Where the passwords and what they opened stand.
    expect(href(attachments, "„Verschlüsselt“")).toBe(
      "/anhaenge?protection=locked&protection=open",
    );
  });

  it("lists the persons fallen silent with profile and timeline", async () => {
    await loaded("/auffaelligkeiten", withOverview({ ...signalOverview, silent_count: 7 }));
    const persons = card("Personen");
    expect(persons.textContent).toContain("Seit mindestens drei Monaten bis zum Ende des Archivs");
    const rows = within(within(persons).getByRole("list", { name: "Verstummte Personen" }))
      .getAllByRole("listitem")
      .map((row) => row.textContent);
    expect(rows[0]).toBe(
      "Lukas Vogtverstummt seit Juli 2025214 Mails in den sechs Monaten davorZeitachse",
    );
    expect(rows).toHaveLength(3);
    expect(href(persons, "Lukas Vogt")).toBe("/personen/14");
    expect(href(persons, "Zeitachse von Lukas Vogt")).toBe("/zeitachse?person=14");
    expect(persons.textContent).toContain(
      "Gezeigt: 3 von 7 Personen, die mit den meisten Mails davor zuerst.",
    );
  });

  it("says what is missing before the first signals phase and without internal domains", async () => {
    await loaded("/auffaelligkeiten", withOverview(signalOverviewNever));
    expect(status().textContent).toContain("Noch nicht berechnet.");
    expect(href(status(), "Zum Import")).toBe("/import");
    expect(screen.queryByRole("list", { name: "Kennzahlen" })).toBeNull();
    const settings = card("Regeln");
    expect(settings.textContent).toContain(
      "Nicht gesetzt: Von intern an privat, Von privat an intern und Private Zweitadresse sind aus, bis die Einstellungen die eigenen Domains der Organisation nennen",
    );
    expect(settings.textContent).toContain(
      "Als Hilfe die Absender-Domains mit den meisten Mails: nordlicht-gmbh.example (88.120), stadtwerke-beispiel.example (41.933)",
    );

    // Signals that are off: greyed with the reason, without figures or links.
    const alias = entry("Private Zweitadresse");
    expect(alias.textContent).toContain("Aus, bis die Einstellungen die eigenen Domains nennen.");
    expect(within(alias).queryByRole("link")).toBeNull();
    expect(entry("Private Adresse").textContent).toContain("noch nicht berechnet");
    expect(card("Personen").textContent).toContain("Noch nicht berechnet.");
  });

  it("warns about a time zone PostgreSQL does not know, and about outdated figures", async () => {
    await loaded(
      "/auffaelligkeiten",
      withOverview({
        ...signalOverview,
        outdated: true,
        settings: {
          ...signalOverview.settings,
          timezone: "Europe/Atlantis",
          timezone_known: false,
        },
      }),
    );
    expect(card("Regeln").textContent).toContain("PostgreSQL kennt diese Zeitzone nicht.");
    expect(status().textContent).toContain(
      "Diese Zahlen entstanden unter anderen Regeln oder Wortfeldern als den jetzigen.",
    );
    expect(href(status(), "Import")).toBe("/import");
  });

  it("keeps the introduction folded until opened, and open on the next visit", async () => {
    await loaded();
    const intro = () =>
      screen.getByText("Was Signale sind und wie Sie damit suchen").closest("details")!;
    expect(intro().open).toBe(false);
    // Folded, the explanation is still there to unfold.
    expect(within(intro()).getByRole("heading", { name: "Was Signale sind" })).toBeTruthy();
    fireEvent.click(screen.getByText("Was Signale sind und wie Sie damit suchen"));
    await waitFor(() => expect(intro().open).toBe(true));
    expect(localStorage.getItem("mailrobbe.signals-intro")).toBe("open");
    cleanup();
    await loaded();
    expect(intro().open).toBe(true);
  });

  it("shows the error with a retry", async () => {
    let fail = true;
    renderApp("/auffaelligkeiten", (call) =>
      call.url.pathname === "/api/signals" && fail
        ? Response.json({ detail: "boom" }, { status: 500 })
        : fixtureApi(call),
    );
    expect(await screen.findByText("Die Signale konnten nicht geladen werden.")).toBeTruthy();
    // The explanation stays readable.
    expect(screen.getByRole("heading", { name: "Was Signale sind" })).toBeTruthy();
    fail = false;
    fireEvent.click(screen.getByRole("button", { name: "Erneut versuchen" }));
    expect(await screen.findByRole("heading", { name: "Regeln" })).toBeTruthy();
  });

  it("scrolls to the signal a facet's link names", async () => {
    // jsdom has no scrolling; the page asks for it where the browser can.
    const original = Element.prototype.scrollIntoView;
    const scrolled: string[] = [];
    Element.prototype.scrollIntoView = function (this: Element) {
      scrolled.push(this.id);
    };
    try {
      await loaded("/auffaelligkeiten#signal-term-spenden");
      await waitFor(() => expect(scrolled).toEqual(["signal-term-spenden"]));
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });
});
