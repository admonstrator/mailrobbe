// German texts of the topics (D142, D148): period names, the figures of a term as a reader can
// retell them, and the state of the last computation. The profile card uses them too, so the
// module stays small.

import type { ThemeInfo, TopicState, TopicTerm, TopicUnit } from "../../api/types";
import { formatDateTime, formatNumber } from "../../lib/format";
import { formatBucket } from "../timeline/buckets";

/** "Oktober 2025", "4. Quartal 2025", "2025" for the first day of a period. */
export function periodName(start: string, unit: TopicUnit): string {
  const [year, month] = start.split("-").map(Number);
  if (unit === "month") return formatBucket(start, "month");
  if (unit === "quarter") return `${Math.floor((month - 1) / 3) + 1}. Quartal ${year}`;
  return String(year);
}

/** "Monate", "Quartale", "Jahre". */
export const UNIT_PLURALS: Record<TopicUnit, string> = {
  month: "Monate",
  quarter: "Quartale",
  year: "Jahre",
};

export const UNIT_LABELS: Record<TopicUnit, string> = {
  month: "Monat",
  quarter: "Quartal",
  year: "Jahr",
};

/** "1 Mail", "412 Mails". */
export function mailsText(count: number): string {
  return `${formatNumber(count)} ${count === 1 ? "Mail" : "Mails"}`;
}

const wholePercent = new Intl.NumberFormat("de-DE", {
  style: "percent",
  maximumFractionDigits: 0,
});
const smallPercent = new Intl.NumberFormat("de-DE", {
  style: "percent",
  maximumSignificantDigits: 1,
});

/** A share as a reader takes it in: "9 %", "65 %"; below one percent its first digit, "0,4 %",
 *  "0,03 %"; "0 %" for none. */
export function formatShare(fraction: number): string {
  return fraction > 0 && fraction < 0.01
    ? smallPercent.format(fraction)
    : wholePercent.format(Math.max(0, fraction));
}

const smallRatio = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 });

/** "22-mal so häufig", "2,5-mal so häufig"; "nur hier" when no other mail holds the term. */
export function formatRatio(ratio: number | null): string {
  if (ratio === null) return "nur hier";
  const times = ratio < 10 ? smallRatio.format(ratio) : formatNumber(Math.round(ratio));
  return `${times}-mal so häufig`;
}

/** The research themes a term belongs to, in the order of themes.toml. */
export function themesOf(keys: string[], themes: ThemeInfo[] | undefined): ThemeInfo[] {
  return keys.length === 0 ? [] : (themes ?? []).filter((theme) => keys.includes(theme.key));
}

/** " · Recherchethema: Spendenaffären", or "" for a term of no theme. */
export function themeText(themes: ThemeInfo[]): string {
  if (themes.length === 0) return "";
  const names = themes.map((theme) => theme.name).join(", ");
  return ` · ${themes.length === 1 ? "Recherchethema" : "Recherchethemen"}: ${names}`;
}

/** The figures of a term in its scope (D142): "37 von 412 Mails (9 %) · im übrigen Archiv
 *  0,4 % · 22-mal so häufig". scope null: the scope's mails were not counted in time; estimated:
 *  counted over a sample (D144). */
export function termFigures(term: TopicTerm, scope: number | null, estimated = false): string {
  const about = estimated ? "etwa " : "";
  const mails =
    scope === null
      ? `${about}${mailsText(term.mails)}`
      : `${about}${formatNumber(term.mails)} von ${mailsText(scope)}`;
  return `${mails} (${formatShare(term.share)}) · im übrigen Archiv ${formatShare(term.rest_share)} · ${formatRatio(term.ratio)}`;
}

/** "Berechnet am 21.10.2026, 14:05 über 398.112 Mails. Neue Mails kommen beim nächsten Import
 *  dazu." for a computation; null before the first. */
export function stateText(state: TopicState): string | null {
  if (state.computed_at === null) return null;
  const [day, time] = formatDateTime(state.computed_at).split(" ");
  return `Berechnet am ${day}, ${time} über ${mailsText(state.mails)}. Neue Mails kommen beim nächsten Import dazu.`;
}
