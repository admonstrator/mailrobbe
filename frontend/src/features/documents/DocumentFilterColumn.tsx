import type { DocumentKind, DocumentSummary, DocumentTextStatus, Stats } from "../../api/types";
import { Button } from "../../components/Button";
import { Checkbox } from "../../components/Checkbox";
import { utcDay } from "../../lib/format";
import { DateField } from "../mails/FilterColumn";
import { FilterGroup } from "../mails/FilterGroup";
import { DebouncedInput } from "./DebouncedInput";
import styles from "./DocumentFilterColumn.module.css";
import { KindIcon } from "./KindIcon";
import {
  DOCUMENT_KINDS,
  KIND_LABELS,
  PROTECTION_FILTER_LABELS,
  PROTECTIONS,
  TEXT_ORIGIN_LABELS,
  TEXT_ORIGINS,
  TEXT_STATUS_FILTER_LABELS,
  TEXT_STATUSES,
} from "./labels";
import { MetadataFacet } from "./MetadataFacet";
import { PersonField } from "./PersonField";
import { ProtectionMark } from "./ProtectionMark";
import {
  facetFilters,
  toDocumentFilters,
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
  protections,
  authors,
  programs,
  stats,
}: {
  state: DocumentListState;
  onChange: (next: DocumentListState) => void;
  /** The file name filter, typed: replaces the history entry instead of adding one per pause. */
  onName: (name: string) => void;
  kinds: DocumentSummary | undefined;
  statuses: DocumentSummary | undefined;
  protections: DocumentSummary | undefined;
  /** The summaries the facets "Autor" and "Programm" count with (D167). */
  authors: DocumentSummary | undefined;
  programs: DocumentSummary | undefined;
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
  const filters = toDocumentFilters(state);

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

      <FilterGroup id="documents.kind" title="Art" active={state.kind.length > 0}>
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
      </FilterGroup>

      <FilterGroup id="documents.status" title="Textstatus" active={state.text_status.length > 0}>
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
                Ohne Textebene: Die Volltextsuche findet sie erst, wenn die Texterkennung (Seite
                „KI“) sie gelesen hat.
              </p>
            )}
          </div>
        ))}
      </FilterGroup>

      <FilterGroup id="documents.origin" title="Textquelle" active={state.text_origin.length > 0}>
        {TEXT_ORIGINS.map((origin) => (
          <Checkbox
            key={origin}
            checked={state.text_origin.includes(origin)}
            onChange={(checked) =>
              change({ text_origin: toggle(state.text_origin, origin, checked, TEXT_ORIGINS) })
            }
          >
            {TEXT_ORIGIN_LABELS[origin]}
          </Checkbox>
        ))}
      </FilterGroup>

      <FilterGroup
        id="documents.protection"
        title="Verschlüsselt"
        active={state.protection.length > 0}
      >
        {PROTECTIONS.map((protection) => (
          <Checkbox
            key={protection}
            checked={state.protection.includes(protection)}
            onChange={(checked) =>
              change({ protection: toggle(state.protection, protection, checked, PROTECTIONS) })
            }
            count={countOf(protections?.protection, protection)}
          >
            <ProtectionMark protection={protection} decorative />
            {PROTECTION_FILTER_LABELS[protection]}
          </Checkbox>
        ))}
      </FilterGroup>

      <MetadataFacet
        field="author"
        selected={state.author}
        top={authors?.authors}
        filters={facetFilters(filters, "author")}
        onChange={(author) => change({ author })}
      />

      <MetadataFacet
        field="program"
        selected={state.program}
        top={programs?.programs}
        filters={facetFilters(filters, "program")}
        onChange={(program) => change({ program })}
      />

      <FilterGroup
        id="documents.date"
        title="Zeitraum"
        active={state.date_from !== null || state.date_to !== null}
      >
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
      </FilterGroup>

      <PersonField
        person={state.person}
        role={state.person_role}
        onChange={(person, person_role) => change({ person, person_role })}
      />

      <FilterGroup id="documents.more" title="Weitere" active={state.shared || state.external}>
        <Checkbox checked={state.shared} onChange={(shared) => change({ shared })}>
          In mehreren Mails
        </Checkbox>
        {((stats?.internal_domains.length ?? 0) > 0 || state.external) && (
          <Checkbox checked={state.external} onChange={(external) => change({ external })}>
            Nur extern ↔ intern
          </Checkbox>
        )}
      </FilterGroup>
    </aside>
  );
}
