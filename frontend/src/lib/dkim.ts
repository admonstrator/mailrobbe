// German texts for DKIM statuses and reason codes (enums.py DkimStatus, DkimReason).

import type { DkimKey, DkimReason, DkimStatus } from "../api/types";

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
