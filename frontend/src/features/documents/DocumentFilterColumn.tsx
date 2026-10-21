import type { DocumentKind, DocumentSummary, DocumentTextStatus, Stats } from "../../api/types";
import { Button } from "../../components/Button";
import { Checkbox } from "../../components/Checkbox";
import { utcDay } from "../../lib/format";
import { DateField } from "../mails/FilterColumn";
import { DebouncedInput } from "./DebouncedInput";
import styles from "./DocumentFilterColumn.module.css";
import { KindIcon } from "./KindIcon";
import { DOCUMENT_KINDS, KIND_LABELS, TEXT_STATUS_FILTER_LABELS, TEXT_STATUSES } from "./labels";
import { PersonField } from "./PersonField";
import {
  withDocumentFilters,
  withoutDocumentFilters,
  type DocumentFilterPatch,
  type DocumentListState,
} from "./urlState";

/** Statuses always offered; the others once documents have them (or a link selects them). */
const MAIN_STATUSES: readonly DocumentTextStatus[] = [
  "text",
  "scanned",
  "encrypted",
  "failed",
  "unsupported",
];

/** Count of one value in a summary group: absent values have none; unknown while loading or when
 *  counting ran out of time. */
function countOf<K extends string>(
  counts: Partial<Record<K, number>> | null | undefined,
  key: K,
): number | undefined {
  return counts ? (counts[key] ?? 0) : undefined;
}

function toggle<T>(values: readonly T[], value: T, checked: boolean, order: readonly T[]): T[] {
  const next = checked ? [...values, value] : values.filter((other) => other !== value);
  return order.filter((item) => next.includes(item));
}

/** The filter column of the document list (D74). Each group of checkboxes is counted without its
 *  own selection, so its other values keep their counts. */
export function DocumentFilterColumn({
  state,
  onChange,
  onName,
  kinds,
  statuses,
  stats,
}: {
  state: DocumentListState;
  onChange: (next: DocumentListState) => void;
  /** The file name filter, typed: replaces the history entry instead of adding one per pause. */
  onName: (name: string) => void;
  kinds: DocumentSummary | undefined;
  statuses: DocumentSummary | undefined;
  stats: Stats | undefined;
}) {
  const change = (patch: DocumentFilterPatch) => onChange(withDocumentFilters(state, patch));
  const shownStatuses = TEXT_STATUSES.filter(
    (status) =>
      MAIN_STATUSES.includes(status) ||
      (statuses?.text_status?.[status] ?? 0) > 0 ||
      state.text_status.includes(status),
  );
  const dayMin = stats?.date_min ? utcDay(stats.date_min) : undefined;
  const dayMax = stats?.date_max ? utcDay(stats.date_max) : undefined;

  return (
    <aside className={styles.column} aria-label="Filter">
      <div className={styles.head}>
        <h2 className={styles.heading}>Filter</h2>
        <Button variant="link" onClick={() => onChange(withoutDocumentFilters(state))}>
          Zurücksetzen
        </Button>
      </div>

      <div className={styles.group}>
        <label htmlFor="document-name" className={styles.legend}>
          Dateiname enthält
        </label>
        <DebouncedInput
          id="document-name"
          type="search"
          className={styles.input}
          placeholder="z. B. protokoll, .xlsx"
          value={state.name}
          onCommit={onName}
        />
      </div>

      <fieldset className={`${styles.group} ${styles.tight}`}>
        <legend className={styles.legend}>Art</legend>
        {DOCUMENT_KINDS.map((kind: DocumentKind) => (
          <Checkbox
            key={kind}
            checked={state.kind.includes(kind)}
            onChange={(checked) =>
              change({ kind: toggle(state.kind, kind, checked, DOCUMENT_KINDS) })
            }
            count={countOf(kinds?.kinds, kind)}
          >
            <KindIcon kind={kind} size={15} />
            {KIND_LABELS[kind]}
          </Checkbox>
        ))}
      </fieldset>

      <fieldset className={`${styles.group} ${styles.tight}`}>
        <legend className={styles.legend}>Textstatus</legend>
        {shownStatuses.map((status) => (
          <div key={status} className={styles.option}>
            <Checkbox
              checked={state.text_status.includes(status)}
              onChange={(checked) =>
                change({
                  text_status: toggle(state.text_status, status, checked, TEXT_STATUSES),
                })
              }
              count={countOf(statuses?.text_status, status)}
            >
              {TEXT_STATUS_FILTER_LABELS[status]}
            </Checkbox>
            {status === "scanned" && (
              <p className={styles.hint}>
                Ohne Textebene: Die Volltextsuche findet sie nicht, bis eine spätere Texterkennung
                (OCR) sie liest.
              </p>
            )}
          </div>
        ))}
      </fieldset>

      <fieldset className={styles.group}>
        <legend className={styles.legend}>Zeitraum</legend>
        <div className={styles.dates}>
          <DateField
            id="document-date-from"
            label="von"
            value={state.date_from}
            min={dayMin}
            max={state.date_to ?? dayMax}
            onCommit={(date_from) => change({ date_from })}
          />
          <DateField
            id="document-date-to"
            label="bis"
            value={state.date_to}
            min={state.date_from ?? dayMin}
            max={dayMax}
            onCommit={(date_to) => change({ date_to })}
          />
        </div>
      </fieldset>

      <PersonField
        person={state.person}
        role={state.person_role}
        onChange={(person, person_role) => change({ person, person_role })}
      />

      <fieldset className={styles.group}>
        <legend className={styles.legend}>Weitere</legend>
        <Checkbox checked={state.shared} onChange={(shared) => change({ shared })}>
          In mehreren Mails
        </Checkbox>
        {((stats?.internal_domains.length ?? 0) > 0 || state.external) && (
          <Checkbox checked={state.external} onChange={(external) => change({ external })}>
            Nur extern ↔ intern
          </Checkbox>
        )}
      </fieldset>
    </aside>
  );
}
