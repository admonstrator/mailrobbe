import { describe, expect, it } from "vitest";

import { highlightParts, highlightTerms, markCount } from "./highlight";

describe("highlightTerms", () => {
  it("takes words and quoted phrases, without OR and negations", () => {
    expect(highlightTerms('Spende "Konto DE89" or Vorstand -intern -"nicht hier" OR')).toEqual([
      "Spende",
      "Konto DE89",
      "Vorstand",
    ]);
  });

  it("drops punctuation around words, empty phrases and repeats", () => {
    expect(highlightTerms('(Spende), "" Spende! 12.500,00 „Zahlung“')).toEqual([
      "Spende",
      "12.500,00",
      "Zahlung",
    ]);
    expect(highlightTerms("   ")).toEqual([]);
  });

  it("takes an unclosed phrase as typed so far", () => {
    expect(highlightTerms('"Konto DE')).toEqual(["Konto DE"]);
  });
});

describe("highlightParts", () => {
  it("marks every occurrence in any case", () => {
    expect(highlightParts("Die Spende, weitere SPENDEN.", ["spende"])).toEqual([
      { text: "Die ", mark: false },
      { text: "Spende", mark: true },
      { text: ", weitere ", mark: false },
      { text: "SPENDE", mark: true },
      { text: "N.", mark: false },
    ]);
  });

  it("prefers the longer term and escapes regular expression characters", () => {
    expect(highlightParts("Konto DE89 (neu)", ["Konto", "Konto DE89", "(neu)"])).toEqual([
      { text: "Konto DE89", mark: true },
      { text: " ", mark: false },
      { text: "(neu)", mark: true },
    ]);
  });

  it("marks the words a German stem begins, umlauts and ß folded as PostgreSQL writes them", () => {
    const parts = highlightParts(
      "Die Spendenquittungen, Übersicht und Straße.",
      [],
      ["spendenquitt", "ubersicht", "strass"],
    );
    expect(parts.filter((part) => part.mark).map((part) => part.text)).toEqual([
      "Spendenquittungen",
      "Übersicht",
      "Straße",
    ]);
    expect(markCount(parts)).toBe(3);
  });

  it("takes a short stem only as a whole word and merges overlapping marks", () => {
    expect(highlightParts("EU und Europa", [], ["eu"]).filter((part) => part.mark)).toEqual([
      { text: "EU", mark: true },
    ]);
    expect(highlightParts("Großspenden", ["spende"], ["grossspend"])).toEqual([
      { text: "Großspenden", mark: true },
    ]);
  });

  describe("with whole words (D173)", () => {
    const marked = (text: string, terms: string[], stems: string[] = []) =>
      highlightParts(text, terms, stems, { wholeWord: true })
        .filter((part) => part.mark)
        .map((part) => part.text);

    it("marks a word only where letters and digits do not go on, in any case", () => {
      expect(marked("Neger, NEGER und neger. Negern, Negers, Neger2, 2Neger", ["Neger"])).toEqual([
        "Neger",
        "NEGER",
        "neger",
      ]);
    });

    it("leaves umlauts and accents as written and uses no stems", () => {
      expect(marked("Uberfremdung und Überfremdung", ["Überfremdung"])).toEqual(["Überfremdung"]);
      expect(marked("négère, negere und Neger", ["negere"], ["neg"])).toEqual(["negere"]);
    });

    it("takes _ . - and spaces as the end of a word, as in file names", () => {
      expect(marked("Scan_NEG_2019-03.pdf, NEG-Liste, NEGATIV, Bericht.NEG", ["NEG"])).toEqual([
        "NEG",
        "NEG",
        "NEG",
      ]);
    });

    it("lets anything but letters and digits stand between a phrase's words", () => {
      expect(marked("Konto-DE89, Konto  DE89 und KontoDE89, Konto DE890", ["Konto DE89"])).toEqual([
        "Konto-DE89",
        "Konto  DE89",
      ]);
      expect(marked("(neu) und neu", ["(neu)"])).toEqual(["(neu)"]);
    });

    it("prefers the longer term where both stand", () => {
      expect(
        highlightParts("Konto DE89 Konto", ["Konto", "Konto DE89"], [], { wholeWord: true }),
      ).toEqual([
        { text: "Konto DE89", mark: true },
        { text: " ", mark: false },
        { text: "Konto", mark: true },
      ]);
    });
  });

  it("leaves text without terms whole", () => {
    expect(highlightParts("Protokoll", [])).toEqual([{ text: "Protokoll", mark: false }]);
    expect(highlightParts("Protokoll", ["Spende"])).toEqual([{ text: "Protokoll", mark: false }]);
  });
});
