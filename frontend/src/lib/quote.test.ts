import { describe, expect, it } from "vitest";

import { splitQuoted } from "./quote";

const lines = (...rows: string[]) => rows.join("\n");

describe("splitQuoted", () => {
  it("leaves a mail without quotes alone", () => {
    expect(splitQuoted(lines("Hallo,", "", "kurze Frage.", "", "Gruß"))).toBeNull();
    expect(splitQuoted("")).toBeNull();
  });

  it("splits off the attribution and the trailing quote block", () => {
    const text = lines(
      "Hallo Frau Keller,",
      "",
      "passt so.",
      "",
      "Am 17.10.2026 um 09:05 schrieb Jonas Brandt <j.brandt@stadtwerke-beispiel.example>:",
      "> Hallo,",
      ">",
      "> anbei der Entwurf.",
      "",
      "",
    );
    expect(splitQuoted(text)).toEqual({
      body: lines("Hallo Frau Keller,", "", "passt so."),
      quoted: lines(
        "Am 17.10.2026 um 09:05 schrieb Jonas Brandt <j.brandt@stadtwerke-beispiel.example>:",
        "> Hallo,",
        ">",
        "> anbei der Entwurf.",
      ),
      quotedLines: 4,
    });
  });

  it("recognises an attribution a mail client wrapped onto two lines", () => {
    const text = lines(
      "Danke!",
      "",
      "On Fri, Oct 17, 2026 at 9:05 AM Jonas Brandt",
      "<j.brandt@stadtwerke-beispiel.example> wrote:",
      "",
      "> Hi",
    );
    expect(splitQuoted(text)?.body).toBe("Danke!");
    expect(splitQuoted(text)?.quotedLines).toBe(4);
  });

  it("takes a quote block without attribution", () => {
    const text = lines("Siehe unten.", "> alte Nachricht", "> zweite Zeile");
    expect(splitQuoted(text)).toEqual({
      body: "Siehe unten.",
      quoted: lines("> alte Nachricht", "> zweite Zeile"),
      quotedLines: 2,
    });
  });

  it("keeps inline answers between quotes in the body", () => {
    const text = lines(
      "> Frage eins?",
      "Antwort eins.",
      "> Frage zwei?",
      "Antwort zwei.",
      "",
      "> Gruß",
      "> Jonas",
    );
    expect(splitQuoted(text)).toEqual({
      body: lines("> Frage eins?", "Antwort eins.", "> Frage zwei?", "Antwort zwei."),
      quoted: lines("> Gruß", "> Jonas"),
      quotedLines: 2,
    });
  });

  it("does not collapse quotes that are followed by the mail's own text", () => {
    const text = lines("Hallo,", "> Frage?", "Antwort darunter.");
    expect(splitQuoted(text)).toBeNull();
  });

  it("takes everything after an Outlook separator", () => {
    const text = lines(
      "Bitte prüfen.",
      "",
      "-----Ursprüngliche Nachricht-----",
      "Von: Jonas Brandt",
      "Gesendet: Freitag, 17. Oktober 2026 09:05",
      "Betreff: Vertrag",
      "",
      "Text ohne Zitatzeichen",
    );
    expect(splitQuoted(text)?.body).toBe("Bitte prüfen.");
    expect(splitQuoted(text)?.quotedLines).toBe(6);
    expect(splitQuoted(lines("Ok.", "-----Original Message-----", "From: x"))?.quotedLines).toBe(2);
  });

  it("takes an Outlook header block without separator", () => {
    const text = lines(
      "Ok, danke.",
      "",
      "Von: Jonas Brandt <j.brandt@stadtwerke-beispiel.example>",
      "Gesendet: Freitag, 17. Oktober 2026 09:05",
      "An: Anna Keller",
      "",
      "Hallo Anna",
    );
    expect(splitQuoted(text)?.body).toBe("Ok, danke.");
    expect(splitQuoted(text)?.quotedLines).toBe(5);
    expect(splitQuoted(lines("Von: Anna", "bis morgen", "", "Gruß"))).toBeNull();
  });

  it("does not split a mail that is all quote", () => {
    expect(splitQuoted(lines("Am 1.1.2026 schrieb X:", "> alt"))).toBeNull();
    expect(splitQuoted(lines("> nur", "> Zitat"))).toBeNull();
  });

  it("handles CRLF line ends", () => {
    expect(splitQuoted("Ja.\r\n> Frage?\r\n")?.body).toBe("Ja.");
  });
});
