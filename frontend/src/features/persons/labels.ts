// German texts about persons: names, alias counts, why two persons are suggested as one (D30).

import { ApiError } from "../../api/client";
import type { AliasCandidate } from "../../api/types";
import { formatNumber } from "../../lib/format";
import { personName, type Named } from "../../lib/person";

type Reasons = Pick<AliasCandidate, "same_name" | "same_local_part">;

/** "Gleicher Name „anna keller“", "Gleicher Adressteil „a.keller“". */
export function suggestionReasons({ same_name, same_local_part }: Reasons): string[] {
  const reasons: string[] = [];
  if (same_name) reasons.push(`Gleicher Name „${same_name}“`);
  if (same_local_part) reasons.push(`Gleicher Adressteil „${same_local_part}“`);
  return reasons;
}

/** A person's name: the team's label (D157), else the name of the mails, else the address. */
export function personLabel(person: Named): string {
  return personName(person);
}

/** "+2 Aliase": addresses merged into the person. */
export function aliasHint(aliases: number): string {
  return `+${formatNumber(aliases)} ${aliases === 1 ? "Alias" : "Aliase"}`;
}

/** Why a merge, an unmerge or a dismissal failed. */
export function personErrorText(error: Error): string {
  const code = error instanceof ApiError ? error.code : null;
  if (code === "invalid_merge") {
    return "Das geht nicht: Eine Person lässt sich nicht mit sich selbst zusammenführen, und lösen lässt sich nur ein Alias.";
  }
  if (code === "not_found") {
    return "Eine der Personen gibt es so nicht mehr, vermutlich wurde sie inzwischen zusammengeführt. Bitte die Seite neu laden.";
  }
  return "Das hat nicht geklappt: Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.";
}
