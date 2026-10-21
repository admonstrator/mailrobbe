import { describe, expect, it } from "vitest";

import { highlightParts, highlightTerms } from "./highlight";

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

  it("leaves text without terms whole", () => {
    expect(highlightParts("Protokoll", [])).toEqual([{ text: "Protokoll", mark: false }]);
    expect(highlightParts("Protokoll", ["Spende"])).toEqual([{ text: "Protokoll", mark: false }]);
  });
});
