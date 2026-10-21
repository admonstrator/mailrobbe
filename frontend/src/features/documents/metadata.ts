// What a file says about itself (D167), as the card "Metadaten" of the document page shows it:
// the groups, a German label for every stable key the backend writes
// (attachments/metadata/model.py), and how the values read. Values are shown as found; dates
// with a time zone in the browser's local time, dates without one as they stand in the file.

import type { DocumentMetadata, DocumentMetadataStatus, MetadataValue } from "../../api/types";
import { formatDateTime, formatNumber } from "../../lib/format";

export type MetadataGroup =
  "camera" | "capture" | "place" | "author" | "program" | "dates" | "document" | "other";

/** The groups in the order of the card. */
export const METADATA_GROUPS: readonly MetadataGroup[] = [
  "camera",
  "capture",
  "place",
  "author",
  "program",
  "dates",
  "document",
  "other",
];

export const GROUP_LABELS: Record<MetadataGroup, string> = {
  camera: "Kamera",
  capture: "Aufnahme",
  place: "Ort",
  author: "Autor",
  program: "Programm",
  dates: "Daten",
  document: "Dokument",
  other: "Weitere Angaben",
};

/** Where in the file a field stands, as the card tags it. */
export const SOURCE_LABELS: Record<string, string> = {
  exif: "EXIF",
  gps: "GPS",
  xmp: "XMP",
  png: "PNG",
  pdf: "PDF",
  pdf_custom: "PDF",
  office: "Office",
  odf: "ODF",
};

type ValueKind = "text" | "date" | "number" | "minutes" | "metres";

/** [source, key, group, label, kind]: every known field, in the card's order within a group. */
type Known = [source: string, key: string, group: MetadataGroup, label: string, kind?: ValueKind];

const KNOWN: readonly Known[] = [
  ["exif", "make", "camera", "Hersteller"],
  ["exif", "model", "camera", "Modell"],
  ["exif", "body_serial_number", "camera", "Seriennummer"],
  ["exif", "camera_owner_name", "camera", "Besitzer"],
  ["exif", "lens_make", "camera", "Objektivhersteller"],
  ["exif", "lens_model", "camera", "Objektiv"],
  ["exif", "lens_serial_number", "camera", "Objektiv-Seriennummer"],
  ["exif", "datetime_original", "capture", "Aufgenommen", "date"],
  ["exif", "datetime_digitized", "capture", "Digitalisiert", "date"],
  ["exif", "datetime", "capture", "Zuletzt geändert", "date"],
  ["exif", "image_description", "capture", "Bildbeschreibung"],
  ["exif", "user_comment", "capture", "Kommentar"],
  ["exif", "image_unique_id", "capture", "Bild-ID"],
  ["gps", "altitude", "place", "Höhe", "metres"],
  ["gps", "timestamp", "place", "GPS-Zeit", "date"],
  ["exif", "artist", "author", "Fotograf/Autor"],
  ["exif", "xp_author", "author", "Autor (Windows)"],
  ["exif", "copyright", "author", "Urheberrecht"],
  ["pdf", "author", "author", "Autor"],
  ["xmp", "creator", "author", "Urheber"],
  ["xmp", "rights", "author", "Rechte"],
  ["office", "creator", "author", "Erstellt von"],
  ["office", "last_modified_by", "author", "Zuletzt geändert von"],
  ["office", "company", "author", "Firma"],
  ["office", "manager", "author", "Vorgesetzter"],
  ["odf", "initial_creator", "author", "Erstellt von"],
  ["odf", "creator", "author", "Zuletzt gespeichert von"],
  ["odf", "printed_by", "author", "Gedruckt von"],
  ["png", "Author", "author", "Autor"],
  ["png", "Copyright", "author", "Urheberrecht"],
  ["exif", "software", "program", "Software"],
  ["exif", "host_computer", "program", "Rechner"],
  ["pdf", "creator", "program", "Erstellt mit"],
  ["pdf", "producer", "program", "PDF erzeugt mit"],
  ["xmp", "creator_tool", "program", "Erstellt mit"],
  ["xmp", "producer", "program", "PDF erzeugt mit"],
  ["xmp", "history_agents", "program", "Bearbeitet mit"],
  ["xmp", "history_events", "program", "Bearbeitungsschritte", "number"],
  ["office", "application", "program", "Anwendung"],
  ["office", "app_version", "program", "Version"],
  ["odf", "generator", "program", "Erstellt mit"],
  ["png", "Software", "program", "Software"],
  ["pdf", "creation_date", "dates", "Erstellt", "date"],
  ["pdf", "mod_date", "dates", "Geändert", "date"],
  ["xmp", "create_date", "dates", "Erstellt", "date"],
  ["xmp", "modify_date", "dates", "Geändert", "date"],
  ["xmp", "metadata_date", "dates", "Metadaten geändert", "date"],
  ["office", "created", "dates", "Erstellt", "date"],
  ["office", "modified", "dates", "Geändert", "date"],
  ["office", "last_printed", "dates", "Zuletzt gedruckt", "date"],
  ["office", "total_time", "dates", "Bearbeitungszeit", "minutes"],
  ["odf", "creation_date", "dates", "Erstellt", "date"],
  ["odf", "date", "dates", "Zuletzt gespeichert", "date"],
  ["odf", "print_date", "dates", "Zuletzt gedruckt", "date"],
  ["odf", "editing_duration", "dates", "Bearbeitungszeit"],
  ["odf", "editing_cycles", "dates", "Bearbeitungen", "number"],
  ["png", "Creation Time", "dates", "Erstellt"],
  ["png", "tIME", "dates", "Zuletzt geändert", "date"],
  ["pdf", "title", "document", "Titel"],
  ["xmp", "title", "document", "Titel"],
  ["office", "title", "document", "Titel"],
  ["odf", "title", "document", "Titel"],
  ["exif", "xp_title", "document", "Titel (Windows)"],
  ["png", "Title", "document", "Titel"],
  ["pdf", "subject", "document", "Betreff"],
  ["office", "subject", "document", "Betreff"],
  ["odf", "subject", "document", "Betreff"],
  ["exif", "xp_subject", "document", "Betreff (Windows)"],
  ["pdf", "keywords", "document", "Stichwörter"],
  ["xmp", "keywords", "document", "Stichwörter"],
  ["xmp", "subject", "document", "Stichwörter"],
  ["office", "keywords", "document", "Stichwörter"],
  ["odf", "keywords", "document", "Stichwörter"],
  ["exif", "xp_keywords", "document", "Stichwörter (Windows)"],
  ["xmp", "description", "document", "Beschreibung"],
  ["office", "description", "document", "Beschreibung"],
  ["odf", "description", "document", "Beschreibung"],
  ["png", "Description", "document", "Beschreibung"],
  ["exif", "xp_comment", "document", "Kommentar (Windows)"],
  ["png", "Comment", "document", "Kommentar"],
  ["office", "category", "document", "Kategorie"],
  ["office", "content_status", "document", "Status"],
  ["office", "template", "document", "Vorlage"],
  ["odf", "template", "document", "Vorlage"],
  ["odf", "template_location", "document", "Ort der Vorlage"],
  ["office", "revision", "document", "Revision", "number"],
  ["office", "pages", "document", "Seiten", "number"],
  ["office", "words", "document", "Wörter", "number"],
  ["office", "characters", "document", "Zeichen", "number"],
  ["office", "slides", "document", "Folien", "number"],
  ["office", "notes", "document", "Notizen", "number"],
  ["office", "hidden_slides", "document", "Ausgeblendete Folien", "number"],
  ["office", "comments", "document", "Kommentare", "number"],
  ["office", "comment_authors", "document", "Kommentare von"],
  ["office", "tracked_changes", "document", "Nachverfolgte Änderungen", "number"],
  ["office", "change_authors", "document", "Änderungen von"],
  ["pdf", "version", "document", "PDF-Version"],
  ["pdf", "revisions", "document", "Fassungen (Revisionen)", "number"],
  ["pdf", "embedded_files", "document", "Eingebettete Dateien", "number"],
  ["pdf", "embedded_file_names", "document", "Namen eingebetteter Dateien"],
  ["pdf", "trapped", "document", "Überfüllung (Trapped)"],
  ["xmp", "document_id", "document", "Dokument-ID"],
  ["xmp", "original_document_id", "document", "Ursprüngliche Dokument-ID"],
  ["xmp", "instance_id", "document", "Instanz-ID"],
];

const KNOWN_BY_KEY = new Map(KNOWN.map((known, index) => [`${known[0]}.${known[1]}`, index]));

export interface MetadataRow {
  id: string; // "exif.make"
  group: MetadataGroup;
  label: string;
  source: string; // "EXIF"
  value: string; // as shown
  title?: string; // the value as it stands in the file, where the card shows another form
}

export interface Coordinates {
  latitude: number;
  longitude: number;
}

const ISO = /^(\d{4})(?:-(\d{2})(?:-(\d{2})(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?)?)?$/;
const ZONE = /(?:Z|[+-]\d{2}:\d{2})$/;

/** A date as the card shows it: with a zone in local time, without one as the file gives it
 *  (marked so), and a text that is no ISO date as found. */
export function metadataDate(value: string): { text: string; title?: string } {
  if (ZONE.test(value) && !Number.isNaN(Date.parse(value))) {
    return { text: formatDateTime(value, true), title: `in der Datei: ${value}` };
  }
  const parts = ISO.exec(value);
  if (!parts) return { text: value };
  const [, year, month, day, hour, minute, second] = parts;
  const date = [day, month, year].filter(Boolean).join(".");
  if (!hour) return { text: date };
  return {
    text: `${date} ${hour}:${minute}${second ? `:${second}` : ""} (ohne Zeitzone)`,
    title: `in der Datei: ${value}; ohne Zeitzone, also nicht umgerechnet`,
  };
}

function shown(value: MetadataValue, kind: ValueKind): { text: string; title?: string } {
  if (Array.isArray(value)) return { text: value.join(", ") };
  if (typeof value === "number") {
    const number = kind === "metres" ? value.toLocaleString("de-DE") : formatNumber(value);
    if (kind === "minutes") return { text: `${number} ${value === 1 ? "Minute" : "Minuten"}` };
    return { text: kind === "metres" ? `${number} m` : number };
  }
  return kind === "date" ? metadataDate(value) : { text: value };
}

/** The coordinates of the GPS fields, when the file gives both. */
export function coordinates(metadata: DocumentMetadata): Coordinates | null {
  const { latitude, longitude } = metadata.fields.gps ?? {};
  if (typeof latitude !== "number" || typeof longitude !== "number") return null;
  return { latitude, longitude };
}

/** The place on OpenStreetMap, opened by the reader's choice; the app itself loads no map. */
export function openStreetMapUrl({ latitude, longitude }: Coordinates): string {
  return `https://www.openstreetmap.org/?mlat=${latitude}&mlon=${longitude}#map=16/${latitude}/${longitude}`;
}

/** Every field of the file as a row: the known ones in the card's order, then the others (the
 *  file's own names in pdf_custom and png, keys a later reader adds) under "Weitere Angaben".
 *  Latitude and longitude are the card's "Ort" row, not rows of their own. */
export function metadataRows(metadata: DocumentMetadata): MetadataRow[] {
  const rows: [order: number, row: MetadataRow][] = [];
  for (const [source, values] of Object.entries(metadata.fields)) {
    for (const [key, value] of Object.entries(values)) {
      if (source === "gps" && (key === "latitude" || key === "longitude")) continue;
      const index = KNOWN_BY_KEY.get(`${source}.${key}`);
      const known = index === undefined ? undefined : KNOWN[index];
      const { text, title } = shown(value, known?.[4] ?? "text");
      rows.push([
        index ?? KNOWN.length + rows.length,
        {
          id: `${source}.${key}`,
          group: known?.[2] ?? "other",
          label: known?.[3] ?? key,
          source: SOURCE_LABELS[source] ?? source,
          value: text,
          title,
        },
      ]);
    }
  }
  return rows.sort((a, b) => a[0] - b[0]).map(([, row]) => row);
}

/** The line the card shows instead of fields, per status; found has its fields. */
export const METADATA_STATUS_TEXTS: Record<Exclude<DocumentMetadataStatus, "found">, string> = {
  pending: "Noch nicht gelesen: beim nächsten Import-Lauf unter Import.",
  empty: "Die Datei enthält keine Metadaten.",
  unsupported: "Aus diesem Format liest Mailrobbe keine Metadaten.",
  too_large:
    "Die Datei ist größer als das Limit der Auswertung und wurde nicht gelesen (MAILROBBE_ATTACHMENT_TEXT_MAX_SIZE).",
  failed: "Die Metadaten ließen sich nicht lesen: Die Datei ist beschädigt oder verschlüsselt.",
};
