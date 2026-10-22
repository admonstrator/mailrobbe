// German texts for DKIM statuses and reason codes (enums.py DkimStatus, DkimReason), and for
// the origin of a signature's key (KeyOrigin, KeyLookupSource; D100, D101).

import type {
  DkimKey,
  DkimReason,
  DkimStatus,
  KeyEvidenceInfo,
  KeyLookupSource,
  KeyOrigin,
} from "../api/types";
import { formatDate } from "./format";

/** Filter order of the list's DKIM checkboxes. */
export const DKIM_KEYS: readonly DkimKey[] = [
  "pass",
  "consistent",
  "fail",
  "no_key",
  "unsigned",
  "temp_error",
  "unchecked",
];

/** Labels in the filter column. */
export const DKIM_FILTER_LABELS: Record<DkimKey, string> = {
  pass: "Gültig",
  consistent: "Signatur stimmig",
  fail: "Ungültig",
  no_key: "Schlüssel nicht abrufbar",
  unsigned: "Nicht signiert",
  temp_error: "DNS-Fehler",
  unchecked: "Nicht geprüft",
};

/** Labels of the badge in the detail view and the tooltip of the list's dots. */
export const DKIM_STATUS_LABELS: Record<DkimKey, string> = {
  pass: "DKIM gültig",
  consistent: "Signatur stimmig",
  fail: "DKIM ungültig",
  no_key: "Schlüssel nicht abrufbar",
  unsigned: "Nicht signiert",
  temp_error: "DNS-Fehler",
  unchecked: "Nicht geprüft",
};

export const DKIM_REASON_TEXTS: Record<DkimReason, string> = {
  body_hash_mismatch: "Body nach dem Signieren verändert",
  signature_mismatch: "Signatur passt nicht (Header verändert oder anderer Schlüssel)",
  signature_malformed: "Signatur fehlerhaft aufgebaut",
  unsupported_algorithm: "Algorithmus nicht unterstützt",
  from_not_signed: "From-Header nicht signiert",
  key_malformed: "Schlüssel im DNS unbrauchbar",
  key_too_short: "Schlüssel zu kurz (unter 1024 Bit)",
  message_malformed: "Kopfzeilen nicht lesbar",
  key_not_found: "Schlüssel nicht im DNS (Selector gelöscht)",
  key_revoked: "Schlüssel widerrufen (leeres p=)",
  key_mismatch: "Vorhandene Schlüssel passen nicht",
  dns_timeout: "DNS-Zeitüberschreitung",
  dns_offline: "Offline-Modus, Schlüssel nicht im Cache",
};

/** The filter and count key of a mail's status; null means not checked yet. */
export function dkimKey(status: DkimStatus | null): DkimKey {
  return status ?? "unchecked";
}

/** Strongest first, as the backend ranks them (D100). */
export const KEY_ORIGINS: readonly KeyOrigin[] = ["dns", "observed", "documented", "reconstructed"];

/** The badge of a key's origin, beside a signature's status. */
export const KEY_ORIGIN_LABELS: Record<KeyOrigin, string> = {
  dns: "DNS",
  observed: "im DNS beobachtet",
  documented: "dokumentiert",
  reconstructed: "rekonstruiert",
};

/** What each origin shows, in one sentence: the badge's tooltip. */
export const KEY_ORIGIN_TEXTS: Record<KeyOrigin, string> = {
  dns: "Mailrobbe hat diesen Schlüssel selbst im DNS der Domain abgefragt, heute oder früher; einmal gesehen bleibt er gespeichert.",
  observed: "Ein Dritter hat diesen Schlüssel im DNS der Domain gesehen.",
  documented: "Ein Dokument enthält diesen Schlüssel: ein Fund im Archiv oder ein Beleg von Hand.",
  reconstructed:
    "Aus Signaturen berechnet: Die Signaturen stammen vom selben privaten Schlüssel, an die Domain bindet ihn das nicht.",
};

/** Where a key was looked for and found: per lookup and per piece of evidence. */
export const KEY_SOURCE_LABELS: Record<KeyLookupSource, string> = {
  reconstruction: "Rekonstruktion",
  archive_text: "Fund im Archiv",
  manual: "Von Hand eingetragen",
  zkemail: "ZK-Email-Archiv",
  dns: "DNS",
};

/** What happened at a piece of evidence's asked_at, per source. */
export const KEY_SOURCE_VERBS: Record<KeyLookupSource, string> = {
  reconstruction: "berechnet",
  archive_text: "gefunden",
  manual: "eingetragen",
  zkemail: "abgefragt",
  dns: "abgefragt",
};

/** The source's own times, apart from when Mailrobbe asked (D101): "laut Quelle 01.03.2024 bis
 *  30.09.2025"; null when it names none. */
export function evidenceTimes(from: string | null, to: string | null): string | null {
  if (from && to) return `laut Quelle ${formatDate(from)} bis ${formatDate(to)}`;
  if (from) return `laut Quelle ab ${formatDate(from)}`;
  return to ? `laut Quelle bis ${formatDate(to)}` : null;
}

/** One piece of evidence in one line: "ZK-Email-Archiv · abgefragt 21.10.2026 · laut Quelle
 *  01.03.2024 bis 30.09.2025". */
export function evidenceLine(evidence: KeyEvidenceInfo): string {
  const used = evidence.signatures.length;
  if (evidence.source === "dns") {
    // Mailrobbe's own DNS answers: when it saw the key there, first and last (D106)
    const from = evidence.observed_from ?? evidence.asked_at;
    const to = evidence.observed_to ?? from;
    const seen =
      formatDate(from) === formatDate(to)
        ? `im DNS gesehen am ${formatDate(from)}`
        : `im DNS gesehen ${formatDate(from)} bis ${formatDate(to)}`;
    return [KEY_SOURCE_LABELS.dns, seen, evidence.reference && `unter ${evidence.reference}`]
      .filter(Boolean)
      .join(" · ");
  }
  return [
    KEY_SOURCE_LABELS[evidence.source],
    `${KEY_SOURCE_VERBS[evidence.source]} ${formatDate(evidence.asked_at)}`,
    evidence.editor && `von ${evidence.editor}`,
    evidenceTimes(evidence.observed_from, evidence.observed_to),
    used > 0 && `aus ${used} ${used === 1 ? "Signatur" : "Signaturen"}`,
    evidence.reference && `Beleg: ${evidence.reference}`,
  ]
    .filter(Boolean)
    .join(" · ");
}

/** The plain sentence for a signature that only a reconstructed key verifies (D100). */
export const CONSISTENT_TEXT =
  "Die Signatur passt zu einem aus Signaturen berechneten Schlüssel. Das zeigt, dass diese Mails mit demselben privaten Schlüssel signiert wurden, nicht, dass die Domain ihn veröffentlicht hat.";

/** A signature's key name as the API names selectors: "<selector>._domainkey.<domain>" in
 *  lower case; null without both parts. */
export function keyName(selector: string | null, domain: string | null): string | null {
  return selector && domain ? `${selector}._domainkey.${domain}`.toLowerCase() : null;
}

/** The page of a key name: its keys with their evidence, the lookups, its mails. */
export function selectorPath(name: string): string {
  return `/import/selektoren/${encodeURIComponent(name)}`;
}
