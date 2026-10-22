// German texts of the hide rules (D221 to D223): a rule's criteria in words, the start of a
// subject for a new rule, and why a write failed.

import { ApiError } from "../../api/client";
import type { HideRuleFields, MailResearch, PersonRef } from "../../api/types";
import { personName } from "../../lib/person";

/** The criteria as the page and the dialog name them, with the person a rule names. */
export interface RuleCriteria extends HideRuleFields {
  person?: PersonRef | null;
}

/** Each criterion in words, in the order of the dialog's fields. */
export function criteriaParts(rule: RuleCriteria): string[] {
  const parts: string[] = [];
  if (rule.person_id != null) {
    parts.push(
      rule.person
        ? `Person ${personName(rule.person)} mit allen Adressen`
        : `Person #${rule.person_id} (nicht mehr im Archiv)`,
    );
  }
  if (rule.sender) parts.push(`Absender ${rule.sender}`);
  if (rule.domain) parts.push(`Domain ${rule.domain}`);
  if (rule.list_id) parts.push(`Verteiler ${rule.list_id}`);
  if (rule.automated) parts.push("automatisch versendet");
  if (rule.subject) {
    parts.push(
      rule.subject_match === "starts"
        ? `Betreff beginnt mit „${rule.subject}“`
        : `Betreff enthält „${rule.subject}“`,
    );
  }
  return parts;
}

/** "Verteiler newsletter.example · Betreff beginnt mit „Wochenrückblick“" */
export function describeRule(rule: RuleCriteria): string {
  return criteriaParts(rule).join(" · ") || "ohne Angaben";
}

/** At least one criterion is named (D221); the name alone is none. */
export function hasCriterion(rule: HideRuleFields): boolean {
  return Boolean(
    rule.sender ||
    rule.person_id != null ||
    rule.domain ||
    rule.list_id ||
    rule.automated ||
    rule.subject,
  );
}

// Reply and forward prefixes, also repeated and with a counter: "Re: AW[2]: Fwd: WG:".
const PREFIXES = /^(\s*(re|aw|antw|fwd?|wg|wtr|sv|tr)(\[\d+\])?\s*:)+\s*/i;
const START_LIMIT = 60;

/** The start of a subject for "Mails wie diese": without reply and forward prefixes, and up to
 *  the first digit, where newsletters number their issues ("Wochenrückblick 12" gives
 *  "Wochenrückblick"); at most START_LIMIT characters, cut at a word. */
export function subjectStart(subject: string | null): string {
  const bare = (subject ?? "").replace(PREFIXES, "").trim();
  const beforeNumber = (bare.split(/\d/, 1)[0] ?? "").replace(/[\s#(:,.–—-]+$/, "");
  const start = beforeNumber.length >= 3 ? beforeNumber : bare;
  if (start.length <= START_LIMIT) return start;
  const cut = start.slice(0, START_LIMIT);
  const word = cut.lastIndexOf(" ");
  return (word > 0 ? cut.slice(0, word) : cut).trim();
}

/** Why the team keeps a mail visible although a rule matches it (D203), from its research
 *  data: "in einer Akte liegt und eine Notiz hat". Empty when nothing keeps it. */
export function keptReasons(research: MailResearch): string[] {
  const reasons: string[] = [];
  const akten = research.collections;
  if (akten.length === 1) reasons.push(`in der Akte „${akten[0]?.name ?? ""}“ liegt`);
  else if (akten.length > 1) reasons.push(`in ${akten.length} Akten liegt`);
  if (research.notes.length > 0) {
    reasons.push(research.notes.length === 1 ? "eine Notiz hat" : "Notizen hat");
  }
  if (research.mark.flagged) reasons.push("ein Lesezeichen trägt");
  if (research.mark.review === "relevant") reasons.push("als „relevant“ markiert ist");
  return reasons;
}

/** "a", "a und b", "a, b und c" */
export function joinGerman(parts: string[]): string {
  if (parts.length < 2) return parts.join("");
  return `${parts.slice(0, -1).join(", ")} und ${parts[parts.length - 1]}`;
}

/** Why a write of a rule failed. */
export function hidingErrorText(error: Error): string {
  const code = error instanceof ApiError ? error.code : null;
  if (code === "invalid_rule") {
    return "So geht die Regel nicht: Sie braucht mindestens eine Angabe, und eine genannte Person muss es im Archiv noch geben.";
  }
  if (code === "not_found") {
    return "Diese Regel gibt es nicht mehr, vermutlich wurde sie inzwischen gelöscht. Bitte die Seite neu laden.";
  }
  return "Das hat nicht geklappt: Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.";
}
