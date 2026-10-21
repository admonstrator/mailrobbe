import type { PersonFigures } from "../../api/types";
import { cx } from "../../lib/cx";
import { formatDate, formatIsoDay, formatNumber, formatPercent } from "../../lib/format";
import styles from "./ProfileTiles.module.css";

interface Tile {
  label: string;
  value: string;
  sub?: string;
  pass?: boolean;
}

/** "2016" big and "11.03.2016" small, in the browser's time zone. */
function dateTile(label: string, iso: string | null): Tile {
  if (!iso) return { label, value: "–" };
  return { label, value: formatIsoDay(iso).slice(0, 4), sub: formatDate(iso) };
}

/** The six figures of a person (D29). */
export function ProfileTiles({ figures }: { figures: PersonFigures }) {
  const ratio = figures.dkim_pass_ratio;
  const tiles: Tile[] = [
    { label: "Gesendet", value: formatNumber(figures.sent) },
    { label: "Empfangen (An/Cc)", value: formatNumber(figures.received) },
    { label: "Kontakte", value: formatNumber(figures.contacts) },
    ratio === null
      ? { label: "DKIM gültig (gesendet)", value: "–", sub: "keine geprüfte Mail gesendet" }
      : { label: "DKIM gültig (gesendet)", value: formatPercent(ratio), pass: true },
    dateTile("Erste Mail", figures.first_date),
    dateTile("Letzte Mail", figures.last_date),
  ];
  return (
    <ul className={styles.tiles} aria-label="Kennzahlen">
      {tiles.map((tile) => (
        <li key={tile.label} className={styles.tile}>
          <span className={styles.label}>{tile.label}</span>
          <span className={cx(styles.value, tile.pass && styles.pass)}>{tile.value}</span>
          {tile.sub && <span className={styles.sub}>{tile.sub}</span>}
        </li>
      ))}
    </ul>
  );
}
