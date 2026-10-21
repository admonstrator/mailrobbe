// German names and rules of the signals (D130 to D134): the one place the overview, the facets,
// the chips, the mail detail and the person profile take them from. The names are those of
// signals/model.py LABELS, which the CSV and the export use. Signals rate nothing, so the texts
// say what holds, never what it means.

import { withQuery } from "../../api/client";
import type {
  MailSignalKind,
  SignalGroup,
  SignalKey,
  SignalSettings,
  ThemeInfo,
} from "../../api/types";
import { formatNumber, formatPercent, utcDay } from "../../lib/format";
import { formatBucket } from "../timeline/buckets";

const TERM_PREFIX = "term:";

export const SIGNAL_NAMES: Record<MailSignalKind | "silent", string> = {
  private: "Private Adresse",
  internal_to_private: "Von intern an privat",
  private_to_internal: "Von privat an intern",
  private_alias: "Private Zweitadresse",
  bcc: "Blindkopie (Bcc)",
  many_recipients: "Viele Empfänger",
  forward: "Weiterleitung",
  forward_out: "Weiterleitung nach außen",
  night: "Nachts",
  weekend: "Wochenende",
  silent: "Verstummt",
};

export const GROUP_NAMES: Record<SignalGroup, string> = {
  addresses: "Adressen",
  recipients: "Empfänger und Weiterleitungen",
  time: "Uhrzeit",
  wording: "Wortfelder",
  persons: "Personen",
};

/** The theme key of a term signal ("spenden" of "term:spenden"); null for any other key. */
export function signalTheme(key: string): string | null {
  return key.startsWith(TERM_PREFIX) ? key.slice(TERM_PREFIX.length) : null;
}

/** The German name of a signal; a term signal is "Wortfeld <theme>", with the theme's name from
 *  the API, or its key while the name is not known. */
export function signalName(key: SignalKey | "silent", theme?: string | null): string {
  const themeKey = signalTheme(key);
  if (themeKey !== null) return `Wortfeld ${theme || themeKey}`;
  return SIGNAL_NAMES[key as MailSignalKind | "silent"] ?? key;
}

/** The theme of a term signal among the themes of useThemes(); undefined otherwise. */
export function signalThemeInfo(
  key: string,
  themes: ThemeInfo[] | undefined,
): ThemeInfo | undefined {
  const themeKey = signalTheme(key);
  return themeKey === null ? undefined : themes?.find((theme) => theme.key === themeKey);
}

/** "a, b und c", or with "oder". */
export function joinList(items: string[], last: "und" | "oder" = "und"): string {
  if (items.length < 2) return items.join("");
  return `${items.slice(0, -1).join(", ")} ${last} ${items.at(-1)}`;
}

/** The rule of a signal in one plain sentence (D132 to D134), with the current settings. */
export function signalRule(key: SignalKey | "silent", settings: SignalSettings): string {
  if (signalTheme(key) !== null) {
    return "Ein Begriff aus dem Wortfeld des Themas steht in der Mail oder in einem ihrer Anhänge.";
  }
  const zone = settings.timezone;
  switch (key as MailSignalKind | "silent") {
    case "private":
      return `Der Absender oder ein Empfänger hat eine Adresse bei einem privaten Mailanbieter (Liste mit ${formatNumber(settings.private_domains)} Domains).`;
    case "internal_to_private":
      return "Ein interner Absender schreibt an eine private Adresse, in An, Cc oder Bcc.";
    case "private_to_internal":
      return "Eine private Adresse schreibt an einen internen Empfänger, in An, Cc oder Bcc.";
    case "private_alias":
      return "Eine private Adresse gehört zu einer Person, die auch eine interne Adresse hat (zusammengeführt oder als Alias-Vorschlag).";
    case "bcc":
      return "Ein Empfänger steht in Bcc; das zeigt nur die Kopie des Absenders.";
    case "many_recipients":
      return `An mindestens ${formatNumber(settings.many_recipients)} verschiedene Adressen in An, Cc und Bcc zusammen.`;
    case "forward":
      return `Der Betreff beginnt mit ${joinList(
        settings.forward_prefixes.map((prefix) => `${prefix}:`),
        "oder",
      )}, auch hinter Listen-Tags und Re: oder AW:, oder eine Mail hängt als Anhang an.`;
    case "forward_out":
      return settings.internal_domains.length > 0
        ? "Eine Weiterleitung an eine private Adresse, oder von intern an eine Adresse außerhalb der internen Domains."
        : "Eine Weiterleitung an eine private Adresse.";
    case "night":
      return `Gesendet zwischen ${settings.night_from} und ${settings.night_to} Uhr (${zone}).`;
    case "weekend":
      return `Gesendet an einem Samstag oder Sonntag (${zone}).`;
    case "silent":
      return "Seit mindestens drei Monaten bis zum Ende des Archivs keine Mail, davor Mails in mindestens drei von sechs Monaten, zusammen mindestens fünf.";
  }
  return key;
}

/** Why a signal is off: the three that compare with the internal domains (D131). */
export const UNAVAILABLE_TEXT = "Aus, bis MAILROBBE_INTERNAL_DOMAINS die eigenen Domains nennt.";

/** "0,3 %"; "unter 0,1 %" for a share above nothing that would round to nothing. */
export function percentText(share: number): string {
  return share > 0 && share < 0.0005 ? `unter ${formatPercent(0.001)}` : formatPercent(share);
}

/** part's share of base as percentText; null without base. */
export function shareText(part: number, base: number): string | null {
  return base > 0 ? percentText(part / base) : null;
}

/** "März 2025" for the first day (UTC) of a person's first month without mail. */
export function silentMonth(since: string): string {
  return formatBucket(utcDay(since), "month");
}

const WEEKDAYS = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];

/** "Sa, 18.10.2026 23:41" for "2026-10-18T23:41:07+02:00": the time as the string says it, in
 *  the zone of its own offset, not the browser's. The string itself where it is no such time. */
export function formatLocalTime(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
  if (!match) return iso;
  const [, year, month, day, hour, minute] = match;
  const weekday = WEEKDAYS[new Date(Date.UTC(+year, +month - 1, +day)).getUTCDay()];
  return `${weekday}, ${day}.${month}.${year} ${hour}:${minute}`;
}

/** The mail list with each of these signals (D136), plus other filters as the list writes them. */
export function signalMailsHref(
  key: SignalKey,
  filters: { person?: number[]; person_role?: "sent" } = {},
): string {
  return withQuery("/mails", { ...filters, signal: [key] });
}

/** The mails a person sent with the signal: its profile's figure behind the link. */
export function personSignalHref(personId: number, key: SignalKey): string {
  return signalMailsHref(key, { person: [personId], person_role: "sent" });
}

/** The id of a signal's entry on the overview, for links to its rule: "signal-term-spenden". */
export function signalAnchor(key: SignalKey | "silent"): string {
  return `signal-${key.replace(":", "-")}`;
}

/** The timeline of the mails with the signal. */
export function signalTimelineHref(key: SignalKey): string {
  return withQuery("/zeitachse", { signal: [key] });
}
