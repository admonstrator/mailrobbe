import type { ReactNode } from "react";
import { Link } from "react-router";

import type { ImportSummary } from "../../api/types";
import {
  formatBytes,
  formatDateTime,
  formatNumber,
  formatPercent,
  formatRelative,
} from "../../lib/format";
import styles from "./ArchiveTiles.module.css";

interface Tile {
  label: string;
  value: string;
  sub: ReactNode;
  title?: string;
}

/** "heute 03:12", else "gestern", "vor 3 Tagen". */
function since(iso: string, now = new Date()): string {
  const relative = formatRelative(iso, now);
  return relative === "heute" ? `heute ${formatDateTime(iso).slice(-5)}` : relative;
}

/** The five archive figures of SPEC 5.5: sizes and DNS cache live, the rest from global_stats. */
export function ArchiveTiles({ summary }: { summary: ImportSummary }) {
  const { dns_cache, dns_hit_ratio, open_suggestions, edge_table } = summary;
  const suggestions =
    open_suggestions === 0
      ? "keine Alias-Vorschläge offen"
      : `${formatNumber(open_suggestions)} ${open_suggestions === 1 ? "Alias-Vorschlag" : "Alias-Vorschläge"} offen`;
  const tiles: Tile[] = [
    {
      label: "DB-Größe (Metadaten + Index)",
      value: formatBytes(summary.db_size_bytes),
      sub:
        summary.raw_size_bytes > 0 &&
        `ca. ${formatPercent(summary.db_size_bytes / summary.raw_size_bytes)} der Rohdaten`,
    },
    {
      label: "Volltextindex",
      value: formatBytes(summary.fulltext_index_bytes),
      sub: "Betreff + Textteil",
    },
    {
      label: "DNS-Cache",
      value: formatNumber(dns_cache.found),
      sub:
        dns_hit_ratio === null
          ? "Selector-Einträge"
          : `Selector-Einträge · ${formatPercent(dns_hit_ratio)} Cache-Treffer`,
      title: `${formatNumber(dns_cache.found)} Schlüssel gefunden, ${formatNumber(dns_cache.not_found)} nicht gefunden, ${formatNumber(dns_cache.temp_error)} DNS-Fehler`,
    },
    {
      label: "Personen erkannt",
      value: formatNumber(summary.persons),
      sub:
        open_suggestions > 0 ? (
          <Link to="/personen?tab=vorschlaege">{suggestions}</Link>
        ) : (
          suggestions
        ),
    },
    {
      label: "Kantentabelle",
      value: formatNumber(edge_table.pairs),
      sub: edge_table.refreshed_at
        ? `Personenpaare · aktualisiert ${since(edge_table.refreshed_at)}`
        : "Personenpaare · noch nicht berechnet",
      title: edge_table.refreshed_at
        ? `Aktualisiert ${formatDateTime(edge_table.refreshed_at)}`
        : undefined,
    },
  ];
  return (
    <ul className={styles.tiles} aria-label="Kennzahlen des Archivs">
      {tiles.map((tile) => (
        <li key={tile.label} className={styles.tile} title={tile.title}>
          <span className={styles.label}>{tile.label}</span>
          <span className={styles.value}>{tile.value}</span>
          {tile.sub && <span className={styles.sub}>{tile.sub}</span>}
        </li>
      ))}
    </ul>
  );
}
