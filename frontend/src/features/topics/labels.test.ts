import { describe, expect, it } from "vitest";

import type { TopicTerm } from "../../api/types";
import { themes, topicState, topicStateNever } from "../../test/fixtures";
import {
  formatRatio,
  formatShare,
  periodName,
  stateText,
  termFigures,
  themesOf,
  themeText,
} from "./labels";

// Intl puts a no-break space before "%".
const plain = (text: string | null) => text?.replace(/\u00a0/g, " ");

const spende: TopicTerm = {
  term: "spend",
  label: "Spende",
  mails: 37,
  share: 37 / 412,
  rest_share: 0.004,
  ratio: 37 / 412 / 0.004,
  score: 120.4,
  themes: ["spenden"],
};

describe("topic texts", () => {
  it("names months, quarters and years", () => {
    expect(periodName("2025-10-01", "month")).toBe("Oktober 2025");
    expect(periodName("2025-10-01", "quarter")).toBe("4. Quartal 2025");
    expect(periodName("2025-01-01", "quarter")).toBe("1. Quartal 2025");
    expect(periodName("2025-01-01", "year")).toBe("2025");
  });

  it("gives shares in whole percent, below one percent by their first digit", () => {
    expect(plain(formatShare(37 / 412))).toBe("9 %");
    expect(plain(formatShare(0.651))).toBe("65 %");
    expect(plain(formatShare(1))).toBe("100 %");
    expect(plain(formatShare(0.004))).toBe("0,4 %");
    expect(plain(formatShare(0.00031))).toBe("0,03 %");
    expect(plain(formatShare(0))).toBe("0 %");
  });

  it("says how much more often, or that no other mail holds the term", () => {
    expect(formatRatio(22.45)).toBe("22-mal so häufig");
    expect(formatRatio(2.46)).toBe("2,5-mal so häufig");
    expect(formatRatio(3)).toBe("3-mal so häufig");
    expect(formatRatio(1234.4)).toBe("1.234-mal so häufig");
    expect(formatRatio(null)).toBe("nur hier");
  });

  it("tells the figures of a term as a reader can retell them", () => {
    expect(plain(termFigures(spende, 412))).toBe(
      "37 von 412 Mails (9 %) · im übrigen Archiv 0,4 % · 22-mal so häufig",
    );
    expect(plain(termFigures({ ...spende, rest_share: 0, ratio: null }, 412))).toBe(
      "37 von 412 Mails (9 %) · im übrigen Archiv 0 % · nur hier",
    );
    expect(plain(termFigures(spende, 48_210, true))).toBe(
      "etwa 37 von 48.210 Mails (9 %) · im übrigen Archiv 0,4 % · 22-mal so häufig",
    );
    expect(plain(termFigures(spende, null))).toBe(
      "37 Mails (9 %) · im übrigen Archiv 0,4 % · 22-mal so häufig",
    );
  });

  it("names the research themes of a term", () => {
    expect(themesOf(["spenden"], themes).map((theme) => theme.name)).toEqual(["Spendenaffären"]);
    expect(themesOf(["spenden"], undefined)).toEqual([]);
    expect(themeText(themesOf(["spenden"], themes))).toBe(" · Recherchethema: Spendenaffären");
    expect(themeText(themesOf(["gewalt", "spenden"], themes))).toBe(
      " · Recherchethemen: Spendenaffären, Gewalt",
    );
    expect(themeText([])).toBe("");
  });

  it("says when and over how many mails the topics were computed", () => {
    expect(stateText(topicState)).toBe(
      "Berechnet am 21.10.2026, 14:05 über 398.112 Mails. Neue Mails kommen beim nächsten Import dazu.",
    );
    expect(stateText(topicStateNever)).toBeNull();
  });
});
