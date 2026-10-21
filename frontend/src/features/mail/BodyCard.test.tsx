import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MailText, TextSegment } from "../../api/types";
import type { SearchMarks } from "../../components/Highlighted";
import { fixtureApi, renderElement } from "../../test/render";
import { BodyCard } from "./BodyCard";

// Texts with the segments quotes.split_text gives them (tests/test_quotes.py has the rule).
const REPLY =
  "Hallo Jonas,\n\npasst so, ich schicke den Vertrag morgen.\n\n-- \nAnna Keller\n" +
  "Nordlicht GmbH\n\nAm 17.10.2026 um 09:12 schrieb Jonas Brandt:\n> Hallo Anna,\n" +
  "> anbei der Entwurf mit der Haftungsklausel.\n> Gruß Jonas\n";
const REPLY_SEGMENTS: TextSegment[] = [
  { kind: "text", start: 0, end: 57, lines: 2, folded: false },
  { kind: "signature", start: 57, end: 89, lines: 3, folded: true },
  { kind: "quote", start: 89, end: 206, lines: 4, folded: true },
];
const INLINE =
  "Hallo Peter,\n\n> Können wir den Termin auf Donnerstag legen?\nJa, Donnerstag 10 Uhr passt.\n" +
  "\n> Und bringst du die Unterlagen mit?\nMache ich.\n\nGruß Anna\n";
const INLINE_SEGMENTS: TextSegment[] = [
  { kind: "text", start: 0, end: 14, lines: 1, folded: false },
  { kind: "quote", start: 14, end: 60, lines: 1, folded: false },
  { kind: "text", start: 60, end: 90, lines: 1, folded: false },
  { kind: "quote", start: 90, end: 127, lines: 1, folded: false },
  { kind: "text", start: 127, end: 149, lines: 2, folded: false },
];
const FORWARD =
  "---------- Forwarded message ---------\nVon: Jonas Brandt <j.brandt@stadtwerke.example>\n" +
  "Date: Fr., 17. Okt. 2026 um 09:12\nSubject: Rechnung\nTo: <anna@nordlicht.example>\n\n" +
  "Bitte überweisen Sie den Betrag bis Monatsende.\n";
const EMOJI =
  "Danke \u{1F44D}, das passt.\n\nAm 17.10.2026 um 09:12 schrieb Jonas Brandt:\n" +
  "> Ist die Haftung so in Ordnung?\n";

function showText(text: string, segments: TextSegment[], marks?: SearchMarks) {
  const body: MailText = {
    text,
    truncated: false,
    source: "text/plain",
    has_html: false,
    segments,
  };
  renderElement(<BodyCard mailId={7} tab="text" onTab={() => {}} marks={marks} />, (call) =>
    call.url.pathname === "/api/mails/7/body" ? body : fixtureApi(call),
  );
}

describe("body card, text view", () => {
  it("folds the history and the signature, each with its line count", async () => {
    showText(REPLY, REPLY_SEGMENTS);
    expect(await screen.findByText(/passt so, ich schicke den Vertrag morgen\./)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Signatur einblenden (3 Zeilen)" })).toBeTruthy();
    const quote = screen.getByRole("button", { name: "Zitat einblenden (4 Zeilen)" });
    expect(quote.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText(/Nordlicht GmbH/)).toBeNull();
    expect(screen.queryByText(/anbei der Entwurf/)).toBeNull();

    fireEvent.click(quote);
    expect(screen.getByText(/anbei der Entwurf/).textContent).toBe(
      "Am 17.10.2026 um 09:12 schrieb Jonas Brandt:\n> Hallo Anna,\n" +
        "> anbei der Entwurf mit der Haftungsklausel.\n> Gruß Jonas",
    );
    expect(quote.textContent).toBe("Zitat ausblenden (4 Zeilen)");
    expect(quote.getAttribute("aria-expanded")).toBe("true");
    expect(screen.queryByText(/Nordlicht GmbH/)).toBeNull();

    fireEvent.click(quote);
    expect(screen.queryByText(/anbei der Entwurf/)).toBeNull();
  });

  it("opens a folded part that holds a search word, and closes it on request", async () => {
    showText(REPLY, REPLY_SEGMENTS, { words: ["Haftung"], stems: [] });
    expect(await screen.findByText("1 Fundstelle markiert")).toBeTruthy();
    const quote = screen.getByRole("button", { name: "Zitat ausblenden (4 Zeilen, 1 Fundstelle)" });
    expect(screen.getByText("Haftung").tagName).toBe("MARK");
    // The signature holds no hit and stays folded.
    expect(screen.getByRole("button", { name: "Signatur einblenden (3 Zeilen)" })).toBeTruthy();

    fireEvent.click(quote);
    expect(quote.textContent).toBe("Zitat einblenden (4 Zeilen, 1 Fundstelle)");
    expect(screen.queryByText("Haftung")).toBeNull();
    expect(screen.getByText("1 Fundstelle markiert")).toBeTruthy();
  });

  it("shows short quotes between the own words in place, without a toggle", async () => {
    showText(INLINE, INLINE_SEGMENTS);
    const text = await screen.findByText(/Ja, Donnerstag 10 Uhr passt\./);
    expect(text.textContent).toBe(INLINE.trimEnd());
    expect(screen.queryByRole("button")).toBeNull();
    // the quoted lines muted in place, the answers as written
    expect(screen.getByText("> Können wir den Termin auf Donnerstag legen?").tagName).toBe("SPAN");
    expect(text.tagName).toBe("DIV");
  });

  it("opens a forward that is the whole text", async () => {
    showText(FORWARD, [{ kind: "forward", start: 0, end: 217, lines: 6, folded: false }]);
    // shown as the content it is, not muted
    expect((await screen.findByText(/Bitte überweisen Sie den Betrag/)).tagName).toBe("DIV");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("counts the server's offsets in characters, an emoji as one", async () => {
    showText(EMOJI, [
      { kind: "text", start: 0, end: 21, lines: 1, folded: false },
      { kind: "quote", start: 21, end: 99, lines: 2, folded: true },
    ]);
    expect((await screen.findByText(/Danke/)).textContent).toBe("Danke \u{1F44D}, das passt.");
    fireEvent.click(screen.getByRole("button", { name: "Zitat einblenden (2 Zeilen)" }));
    expect(screen.getByText(/Ist die Haftung/).textContent).toBe(
      "Am 17.10.2026 um 09:12 schrieb Jonas Brandt:\n> Ist die Haftung so in Ordnung?",
    );
  });

  it("shows a text without segments as it is", async () => {
    showText("Nur eine Zeile.\n", []);
    expect((await screen.findByText(/Nur eine Zeile/)).textContent).toBe("Nur eine Zeile.");
    expect(screen.queryByRole("button")).toBeNull();
  });
});
