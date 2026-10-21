// German texts about persons: names, alias counts, why two persons are suggested as one (D30,
// D160) and what merging and undoing did (D162, D163).

import { ApiError } from "../../api/client";
import type { AliasCandidate, SuggestionReason } from "../../api/types";
import { formatNumber } from "../../lib/format";

type Reasons = Pick<AliasCandidate, "same_name" | "same_local_part">;

/** "Gleicher Name „anna keller“", "Gleicher Adressteil „a.keller“". */
export function suggestionReasons({ same_name, same_local_part }: Reasons): string[] {
  const reasons: string[] = [];
  if (same_name) reasons.push(`Gleicher Name „${same_name}“`);
  if (same_local_part) reasons.push(`Gleicher Adressteil „${same_local_part}“`);
  return reasons;
}

/** Why a suggestion was made, as the list says it: sicher or unsicher, and the signs. */
export const REASON_TEXTS: Record<SuggestionReason, string> = {
  name_and_local_part: "Sicher: gleicher Name und gleicher Adressteil",
  name_fits_addresses: "Sicher: Name passt zu beiden Adressen, gleiche Organisation",
  name: "Unsicher: nur der gleiche Name",
  local_part: "Unsicher: nur der gleiche Adressteil",
};

/** A person's name, or the address when it has none. */
export function personLabel(person: { name: string | null; email: string }): string {
  return person.name || person.email;
}

/** "+2 Aliase": addresses merged into the person. */
export function aliasHint(aliases: number): string {
  return `+${formatNumber(aliases)} ${aliases === 1 ? "Alias" : "Aliase"}`;
}

/** "1 Person", "312 Personen". */
export function personCount(persons: number): string {
  return `${formatNumber(persons)} ${persons === 1 ? "Person" : "Personen"}`;
}

/** "1 Zusammenführung", "290 Zusammenführungen". */
export function mergeCount(merges: number): string {
  return `${formatNumber(merges)} ${merges === 1 ? "Zusammenführung" : "Zusammenführungen"}`;
}

/** Why a merge, an undo, an unmerge or a dismissal failed. */
export function personErrorText(error: Error): string {
  const code = error instanceof ApiError ? error.code : null;
  if (code === "invalid_merge") {
    return "Das geht nicht: Eine Person lässt sich nicht mit sich selbst zusammenführen, und lösen lässt sich nur ein Alias.";
  }
  if (code === "not_found") {
    return "Eine der Personen gibt es so nicht mehr, vermutlich wurde sie inzwischen zusammengeführt. Bitte die Seite neu laden.";
  }
  if (code === "merge_undone") {
    return "Das ist schon rückgängig gemacht. Bitte die Seite neu laden.";
  }
  return "Das hat nicht geklappt: Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.";
}
