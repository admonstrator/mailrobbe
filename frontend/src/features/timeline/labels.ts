// German texts of the timeline: units, splits, roles, a bar's tooltip and the rules of the
// marks (D93), told as simply as the rules are.

import type {
  ParticipationRole,
  PersonKind,
  TimelineBucket,
  TimelineSeries,
  TimelineSplit,
} from "../../api/types";
import { formatNumber } from "../../lib/format";
import { formatBucket } from "./buckets";

export const BUCKET_LABELS: Record<TimelineBucket, string> = {
  day: "Tag",
  week: "Woche",
  month: "Monat",
};

/** "nach Tagen", "nach Wochen", "nach Monaten". */
export const BUCKET_PLURALS: Record<TimelineBucket, string> = {
  day: "Tagen",
  week: "Wochen",
  month: "Monaten",
};

export const SPLIT_LABELS: Record<TimelineSplit, string> = {
  none: "Gesamt",
  person: "Personen",
  thread: "Threads",
  term: "Suchbegriffe",
};

/** A person's role in its first mail. */
export const ROLE_LABELS: Record<ParticipationRole, string> = {
  from: "schrieb",
  to: "erhielt",
  cc: "in Cc",
  bcc: "in Bcc",
};

export const KIND_LABELS: Record<PersonKind, string> = { list: "Verteiler", automated: "Automat" };

export const NO_SUBJECT = "(ohne Betreff)";

/** "1 Mail", "4.300 Mails". */
export function mailsText(count: number): string {
  return `${formatNumber(count)} ${count === 1 ? "Mail" : "Mails"}`;
}

/** "1 Person", "12 Personen". */
export function personsText(count: number): string {
  return `${formatNumber(count)} ${count === 1 ? "Person" : "Personen"}`;
}

/** The name of a series' lane: the person, the thread's subject or the search string. */
export function seriesName(series: TimelineSeries): string {
  if (series.person) return series.person.name || series.person.email;
  if (series.thread_id !== null) return series.label || NO_SUBJECT;
  return series.term ?? series.label ?? "";
}

/** A bar's tooltip: "März 2024: 4.300 Mails · üblich etwa 1.216" for a marked bucket, with the
 *  moving mean it was compared with. */
export function bucketText(
  series: TimelineSeries,
  index: number,
  start: string,
  bucket: TimelineBucket,
): string {
  const text = `${formatBucket(start, bucket)}: ${mailsText(series.counts[index] ?? 0)}`;
  const mark = series.outliers.find((outlier) => outlier.index === index);
  return mark ? `${text} · üblich etwa ${formatNumber(Math.round(mark.expected))}` : text;
}

/** The comparison window of the marks per unit (D93). */
const WINDOWS: Record<TimelineBucket, string> = {
  day: "mit demselben Wochentag der vier Wochen davor",
  week: "mit den acht Wochen davor",
  month: "mit den sechs Monaten davor",
};

const SILENCE: Record<TimelineBucket, string> = {
  day: "mindestens 21 Tage",
  week: "mindestens 6 Wochen",
  month: "mindestens 3 Monate",
};

export interface MarkRules {
  compare: string;
  high: string;
  low: string;
  silent: string;
}

/** The rules of the marks for the unit shown, in plain words. */
export function markRules(bucket: TimelineBucket): MarkRules {
  return {
    compare: `Jeder Balken wird ${WINDOWS[bucket]} verglichen, genauer mit deren Durchschnitt (dem gleitenden Mittelwert); ohne so viel Vorlauf bekommt er kein Zeichen.`,
    high: "mindestens dreimal so viele Mails wie der Durchschnitt und mindestens fünf mehr.",
    low: "höchstens ein Drittel des Durchschnitts, wenn dieser bei mindestens fünf Mails liegt.",
    silent: `ab da keine Mail mehr bis zum Ende des Archivs oder des Zeitraums, ${SILENCE[bucket]} lang, nachdem davor regelmäßig Mails kamen (in mindestens der Hälfte der Balken, zusammen mindestens fünf).`,
  };
}
