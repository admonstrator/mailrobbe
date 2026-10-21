import type { MouseEvent } from "react";
import { Link, useNavigate } from "react-router";

import type { EntityListItem, EntityRef, ThemeInfo } from "../../api/types";
import { cx } from "../../lib/cx";
import { formatDate, formatNumber } from "../../lib/format";
import { ColorChip } from "../research/ColorChip";
import { EntityIcon } from "./EntityIcon";
import styles from "./EntityTable.module.css";
import { countryName, countryOf, KIND_LABELS, themeOf } from "./labels";
import { entityMailsHref, entityPath } from "./urlState";

/** What the label alone does not say: a term's theme, the country of an IBAN or a phone number,
 *  that a place is a country. */
export function EntityExtras({
  entity,
  themes,
}: {
  entity: EntityRef;
  themes: ThemeInfo[] | undefined;
}) {
  const theme = themeOf(entity, themes);
  const country = countryOf(entity);
  return (
    <>
      {theme && <ColorChip color={theme.color}>{theme.name}</ColorChip>}
      {country && (
        <span className={styles.badge} title={countryName(country)}>
          {country}
        </span>
      )}
      {entity.kind === "place" && entity.detail === "country" && (
        <span className={styles.badge}>Land</span>
      )}
    </>
  );
}

/** "03.02.2014 – 18.10.2026", one day once, "–" without dated mails. */
export function periodText(first: string | null, last: string | null): string {
  if (!first || !last) return "–";
  const [from, to] = [formatDate(first), formatDate(last)];
  return from === to ? from : `${from} – ${to}`;
}

/** One page of the entity list. Each row opens the entity; the label is the real link, so
 *  middle-click and "open in new tab" work. */
export function EntityTable({
  items,
  themes,
  showKind,
  stale,
}: {
  items: EntityListItem[];
  themes: ThemeInfo[] | undefined;
  /** The "Alle" tab mixes kinds and names each. */
  showKind: boolean;
  stale: boolean;
}) {
  const navigate = useNavigate();

  function openRow(event: MouseEvent<HTMLTableRowElement>, id: number) {
    const target = event.target as HTMLElement;
    if (target.closest("a, button, input, label") || window.getSelection()?.toString()) return;
    void navigate(entityPath(id));
  }

  return (
    <div className={styles.scroll}>
      <table className={cx(styles.table, stale && styles.stale)}>
        <thead>
          <tr>
            <th className={styles.iconCol} aria-hidden="true" />
            <th>Entität</th>
            {showKind && <th>Art</th>}
            <th className={styles.num}>Mails</th>
            <th className={styles.num}>Dokumente</th>
            <th>Zeitraum</th>
            <th>
              <span className="sr-only">Mailliste</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((entity) => (
            <tr key={entity.id} onClick={(event) => openRow(event, entity.id)}>
              <td className={styles.icon}>
                <EntityIcon kind={entity.kind} size={16} labelled={!showKind} />
              </td>
              <td className={styles.entity}>
                <span className={styles.title}>
                  <Link to={entityPath(entity.id)} className={styles.label}>
                    {entity.label}
                  </Link>
                  <EntityExtras entity={entity} themes={themes} />
                </span>
              </td>
              {showKind && <td className={styles.kind}>{KIND_LABELS[entity.kind].one}</td>}
              <td className={cx(styles.num, styles.mails)}>{formatNumber(entity.mails)}</td>
              <td className={cx(styles.num, styles.muted)}>
                {entity.documents > 0 ? formatNumber(entity.documents) : "–"}
              </td>
              <td className={styles.period}>{periodText(entity.first_date, entity.last_date)}</td>
              <td className={styles.open}>
                <Link
                  to={entityMailsHref([entity.id])}
                  aria-label={`Mails mit ${entity.label}`}
                  title="In der Mailliste zeigen"
                >
                  Mails
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
