// German texts about documents (D70 to D77): kinds, text statuses and what they mean, sorts, and
// the small counts the screens put beside a document; protection and containers (D230 to D239).

import type {
  DocumentKind,
  DocumentMembersStatus,
  DocumentMemberStatus,
  DocumentProtection,
  DocumentSort,
  DocumentTextStatus,
  PasswordTier,
} from "../../api/types";
import { formatNumber } from "../../lib/format";

/** Every kind, in the order of the filter column. */
export const DOCUMENT_KINDS: readonly DocumentKind[] = [
  "pdf",
  "document",
  "spreadsheet",
  "presentation",
  "text",
  "email",
  "image",
  "archive",
  "media",
  "other",
];

export const KIND_LABELS: Record<DocumentKind, string> = {
  pdf: "PDF",
  document: "Textdokument",
  spreadsheet: "Tabelle",
  presentation: "Präsentation",
  text: "Text",
  email: "Mail",
  image: "Bild",
  archive: "Archiv",
  media: "Audio/Video",
  other: "Sonstige",
};

/** Every text status, in the order of the filter column and the dashboard. */
export const TEXT_STATUSES: readonly DocumentTextStatus[] = [
  "text",
  "scanned",
  "encrypted",
  "failed",
  "timeout",
  "too_large",
  "unreadable",
  "empty",
  "unsupported",
  "pending",
];

/** Short labels, as the list rows and the dashboard show them. */
export const TEXT_STATUS_LABELS: Record<DocumentTextStatus, string> = {
  pending: "Ausstehend",
  text: "Mit Text",
  empty: "Ohne Text",
  scanned: "Gescannt",
  encrypted: "Verschlüsselt",
  unsupported: "Nicht unterstützt",
  too_large: "Zu groß",
  failed: "Fehler",
  timeout: "Zeitüberschreitung",
  unreadable: "Nicht lesbar",
};

/** The filter column's labels: a scan says that it has no text. */
export const TEXT_STATUS_FILTER_LABELS: Record<DocumentTextStatus, string> = {
  ...TEXT_STATUS_LABELS,
  scanned: "Gescannt (ohne Text)",
};

/** Why a scan is not found by words, beside the filter and above a list of scans. */
export const SCANNED_HINT =
  "Gescannte PDFs haben noch keine Textebene und werden von der Volltextsuche nicht gefunden; eine spätere Texterkennung (OCR) liest sie.";

/** What the text status of a document means, in plain German, for its page. */
export const TEXT_STATUS_TEXTS: Record<DocumentTextStatus, string> = {
  pending:
    "Der Text ist noch nicht ausgelesen. Das geschieht beim nächsten Import in der Phase „Anhänge auswerten“.",
  text: "Der Text ist ausgelesen; die Volltextsuche findet das Dokument über seine Wörter.",
  empty: "Das Format wird gelesen, die Datei enthält aber keinen Text.",
  scanned:
    "Ein gescanntes PDF: Die Seiten sind Bilder ohne Textebene. Die Volltextsuche findet es deshalb nicht, nur über den Dateinamen; eine spätere Texterkennung (OCR) kann es lesen.",
  encrypted:
    "Die Datei ist mit einem Kennwort geschützt. Ohne das Kennwort lässt sich ihr Text nicht lesen.",
  unsupported:
    "Aus diesem Format liest Mailrobbe keinen Text (etwa Bilder, Audio, Video oder alte Office-Formate). Gefunden wird es über den Dateinamen.",
  too_large:
    "Die Datei ist größer als das Limit der Textauswertung und wurde nicht gelesen (MAILROBBE_ATTACHMENT_TEXT_MAX_SIZE).",
  failed: "Der Text ließ sich nicht auslesen: Die Datei ist beschädigt oder unlesbar.",
  timeout:
    "Das Auslesen dauerte zu lange und wurde abgebrochen. Der bis dahin gelesene Text ist gespeichert und durchsuchbar.",
  unreadable:
    "Die MBOX-Datei dieses Anhangs fehlt oder hat sich geändert. Der nächste Import versucht es erneut.",
};

/** Statuses with a stored text to show (D72: a timeout keeps what it read). */
export function hasStoredText(status: DocumentTextStatus): boolean {
  return status === "text" || status === "timeout";
}

/** The quiet label of a list row or an attachment; null where the text was read as usual. */
export function statusNote(status: DocumentTextStatus | null): string | null {
  return status === null || status === "text" ? null : TEXT_STATUS_LABELS[status];
}

export const SORT_LABELS: Record<DocumentSort, string> = {
  recent: "Neueste zuerst",
  oldest: "Älteste zuerst",
  mails: "Meiste Mails",
  size: "Größte zuerst",
};

/** "in 1 Mail", "in 6 Mails" */
export function mailsText(mails: number): string {
  return `in ${formatNumber(mails)} ${mails === 1 ? "Mail" : "Mails"}`;
}

/** "1 Seite", "14 Seiten" */
export function pagesText(pages: number): string {
  return `${formatNumber(pages)} ${pages === 1 ? "Seite" : "Seiten"}`;
}

/** "+2 Namen" for a document sent under three file names. */
export function otherNamesText(names: number): string {
  const others = names - 1;
  return `+${formatNumber(others)} ${others === 1 ? "Name" : "Namen"}`;
}

/** A document's name, or a placeholder when it was always sent without one. */
export function documentName(name: string | null): string {
  return name || "(ohne Dateinamen)";
}

/** The kind of an attachment from its declared MIME type, for attachments without a document
 *  yet; the document's kind (decided by the backend from the content) wins once it exists. */
export function kindFromMimeType(mimeType: string): DocumentKind {
  const type = mimeType.toLowerCase();
  if (type === "application/pdf") return "pdf";
  if (/spreadsheet|excel|csv/.test(type)) return "spreadsheet";
  if (/presentation|powerpoint/.test(type)) return "presentation";
  if (/word|opendocument\.text|rtf/.test(type)) return "document";
  if (type === "message/rfc822") return "email";
  if (type.startsWith("image/")) return "image";
  if (/^(audio|video)\//.test(type)) return "media";
  if (/zip|compressed|tar|rar|7z/.test(type)) return "archive";
  if (type.startsWith("text/")) return "text";
  return "other";
}

// Protected and packed attachments (D230 to D239) -----------------------------------------------

/** Both protections, in the order of the filter column. */
export const PROTECTIONS: readonly DocumentProtection[] = ["locked", "open"];

/** The filter column's labels, under the heading "Verschlüsselt". */
export const PROTECTION_FILTER_LABELS: Record<DocumentProtection, string> = {
  locked: "Kennwort unbekannt",
  open: "geöffnet",
};

/** What the mark of a protected document says beside its name. */
export const PROTECTION_TITLES: Record<DocumentProtection, string> = {
  locked: "Verschlüsselt, das Kennwort ist nicht bekannt",
  open: "Verschlüsselt, mit einem gefundenen Kennwort geöffnet",
};

/** The short label of a protected attachment or container entry. */
export const PROTECTION_NOTES: Record<DocumentProtection, string> = {
  locked: "Kennwort unbekannt",
  open: "Geöffnet",
};

/** The mark of a document found inside a container (D231), and its title. */
export const CONTAINED_NOTE = "ausgepackt";
export const CONTAINED_TITLE = "Aus einem Archiv oder einer angehängten Mail ausgepackt";

/** What became of one entry of a container (D231). */
export const MEMBER_STATUS_LABELS: Record<DocumentMemberStatus, string> = {
  document: "Dokument",
  locked: "Kennwort unbekannt",
  too_large: "Zu groß",
  too_many: "Zu viele Einträge",
  failed: "Fehler",
};

/** How the unpacking of a container stands, for its card on the document page; null when there
 *  is nothing to say. opened: it was opened with a password (D236). */
export function membersStatusText(
  status: DocumentMembersStatus | null,
  opened: boolean,
): string | null {
  switch (status) {
    case null:
      return opened
        ? "Mit dem Kennwort geöffnet; der nächste Import packt den Inhalt aus."
        : "Noch nicht ausgepackt. Das geschieht beim nächsten Import.";
    case "done":
      return null;
    case "locked":
      return "Einträge brauchen ein Kennwort, das noch nicht bekannt ist; was sich ohne lesen ließ, ist ausgepackt.";
    case "too_deep":
      return "Die Datei steckt selbst in einem Archiv oder einer angehängten Mail. Mailrobbe packt nur zwei Ebenen aus; ihr Inhalt bleibt verpackt.";
    case "unsupported":
      return "Dieses Format packt Mailrobbe nicht aus (etwa RAR, tar oder gzip), nur ZIP, 7z und angehängte Mails.";
    case "failed":
      return "Das Auspacken ist fehlgeschlagen.";
    case "unreadable":
      return "Die MBOX-Datei fehlt oder hat sich geändert. Der nächste Import versucht es erneut.";
  }
}

/** The short note under a container among a mail's attachments; null when it is unpacked. */
export function membersStatusNote(status: DocumentMembersStatus | null): string | null {
  switch (status) {
    case null:
      return "Noch nicht ausgepackt, das geschieht beim nächsten Import.";
    case "done":
      return null;
    case "locked":
      return "Einträge brauchen ein Kennwort, das noch nicht bekannt ist.";
    case "too_deep":
      return "Nicht ausgepackt: steckt in einem anderen Archiv.";
    case "unsupported":
      return "Dieses Format wird nicht ausgepackt.";
    case "failed":
      return "Das Auspacken ist fehlgeschlagen.";
    case "unreadable":
      return "Nicht lesbar: Die MBOX-Datei fehlt oder hat sich geändert.";
  }
}

/** Where the password that opened a document came from (D235), nearest first; those typed in
 *  by hand name the editor (D237). */
export function passwordOrigin(tier: PasswordTier, editor: string | null): string {
  const by = editor ? ` von ${editor}` : " (ohne Namen)";
  switch (tier) {
    case "manual":
      return `Von Hand eingegeben${by} und an allen verschlüsselten Dateien probiert`;
    case "typed":
      return `Auf dieser Seite eingegeben${by}`;
    case "mail":
      return "Gefunden in derselben Mail";
    case "thread":
      return "Gefunden in einer Mail desselben Verlaufs";
    case "contacts":
      return "Gefunden in einer Mail zwischen denselben Personen, bis 30 Tage davor oder danach";
    case "attachments":
      return "Gefunden im Text eines Anhangs aus demselben Verlauf oder zwischen denselben Personen";
    case "opened":
      return "Hat schon eine andere Datei geöffnet";
    case "archive":
      return "Gefunden anderswo im Archiv";
  }
}
