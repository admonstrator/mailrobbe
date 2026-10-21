// Links and German texts of the research screens (D57 to D64).

import { ApiError } from "../../api/client";
import { formatNumber } from "../../lib/format";

/** The mail list with a saved search's query string (D59). */
export function searchHref(query: string): string {
  return query ? `/mails?${query}` : "/mails";
}

/** The mail list searching for a word of a theme's word field; a phrase in quotes. */
export function termHref(term: string): string {
  return `/mails?${new URLSearchParams({ q: /\s/.test(term) ? `"${term}"` : term })}`;
}

export function tagMailsHref(tagId: number): string {
  return `/mails?tag=${tagId}`;
}

export function collectionMailsHref(collectionId: number): string {
  return `/mails?collection=${collectionId}`;
}

/** "1 Mail", "1.024 Mails" */
export function mailCount(n: number): string {
  return `${formatNumber(n)} ${n === 1 ? "Mail" : "Mails"}`;
}

/** Why a write to the research file failed. */
export function researchErrorText(error: Error): string {
  const code = error instanceof ApiError ? error.code : null;
  if (code === "duplicate_name")
    return "Diesen Namen gibt es schon (Groß- und Kleinschreibung zählen nicht).";
  if (code === "not_found") {
    return "Das gibt es so nicht mehr, vermutlich wurde es inzwischen gelöscht. Bitte die Seite neu laden.";
  }
  if (error instanceof ApiError && error.status === 422) {
    return "Die Eingabe passt nicht: Ein Name darf nicht leer und nicht zu lang sein.";
  }
  return "Das hat nicht geklappt: Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.";
}
