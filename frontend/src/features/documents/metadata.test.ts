import { describe, expect, it } from "vitest";

import type { DocumentMetadata } from "../../api/types";
import { formatDateTime } from "../../lib/format";
import { documentDetail, imageDocument } from "../../test/fixtures";
import { coordinates, metadataDate, metadataRows, openStreetMapUrl } from "./metadata";

const found = (fields: DocumentMetadata["fields"]): DocumentMetadata => ({
  status: "found",
  error: null,
  fields,
  summary: null,
});

describe("metadata of a file", () => {
  it("shows dates with a zone in local time and dates without one as found", () => {
    expect(metadataDate("2026-10-08T17:40:12+02:00")).toEqual({
      text: formatDateTime("2026-10-08T15:40:12Z", true),
      title: "in der Datei: 2026-10-08T17:40:12+02:00",
    });
    expect(metadataDate("2026-10-02T14:31:07").text).toBe("02.10.2026 14:31:07 (ohne Zeitzone)");
    expect(metadataDate("2026-10-02T14:31").text).toBe("02.10.2026 14:31 (ohne Zeitzone)");
    expect(metadataDate("2024-05-06")).toEqual({ text: "06.05.2024" });
    expect(metadataDate("2024")).toEqual({ text: "2024" });
    expect(metadataDate("0000:00:00 00:00:00")).toEqual({ text: "0000:00:00 00:00:00" });
  });

  it("puts every field in its group, known ones in order, the file's own names last", () => {
    const rows = metadataRows(documentDetail.metadata);
    expect(rows.map((row) => [row.group, row.label, row.source, row.value])).toEqual([
      ["author", "Autor", "PDF", "Peter Hofmann"],
      ["author", "Urheber", "XMP", "Peter Hofmann"],
      ["program", "Erstellt mit", "PDF", "Microsoft Word für Microsoft 365"],
      ["program", "PDF erzeugt mit", "PDF", "Microsoft Word für Microsoft 365"],
      ["program", "Erstellt mit", "XMP", "Microsoft Word für Microsoft 365"],
      [
        "program",
        "Bearbeitet mit",
        "XMP",
        "Microsoft Word für Microsoft 365, Adobe Acrobat Pro 24.1",
      ],
      ["program", "Bearbeitungsschritte", "XMP", "2"],
      ["dates", "Erstellt", "PDF", formatDateTime("2026-10-08T15:40:12Z", true)],
      ["dates", "Geändert", "PDF", formatDateTime("2026-10-09T06:02:51Z", true)],
      ["document", "Titel", "PDF", "Rahmenvereinbarung 2026"],
      ["document", "PDF-Version", "PDF", "1.7"],
      ["document", "Fassungen (Revisionen)", "PDF", "3"],
      ["document", "Dokument-ID", "XMP", "uuid:7D4E1F0C-1B6C-4D6E-9F2A-3C5B7A9E0D11"],
      ["other", "Abteilung", "PDF", "Einkauf"],
    ]);
  });

  it("reads numbers with their units and leaves the coordinates to the place row", () => {
    const rows = metadataRows(
      found({
        gps: { latitude: -33.8666667, longitude: -70.5, altitude: -12.25 },
        office: { total_time: 95, pages: 1200 },
        png: { "Creation Time": "Sat, 02 Nov 2023 14:05:09" },
      }),
    );
    expect(rows.map((row) => [row.label, row.value])).toEqual([
      ["Höhe", "-12,25 m"],
      ["Bearbeitungszeit", "95 Minuten"],
      ["Erstellt", "Sat, 02 Nov 2023 14:05:09"],
      ["Seiten", "1.200"],
    ]);
  });

  it("links the place on OpenStreetMap", () => {
    const place = coordinates(imageDocument.metadata);
    expect(place).toEqual({ latitude: 53.5438333, longitude: 9.9661667 });
    expect(openStreetMapUrl(place!)).toBe(
      "https://www.openstreetmap.org/?mlat=53.5438333&mlon=9.9661667#map=16/53.5438333/9.9661667",
    );
    expect(coordinates(found({ gps: { latitude: 1 } }))).toBeNull();
    expect(coordinates(documentDetail.metadata)).toBeNull();
  });
});
