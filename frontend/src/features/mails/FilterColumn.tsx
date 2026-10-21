import { useEffect, useRef, useState } from "react";

import {
  EVENT_KEYS,
  type DkimKey,
  type MboxFileInfo,
  type ResearchOverview,
  type Stats,
} from "../../api/types";
import { Button } from "../../components/Button";
import { Checkbox } from "../../components/Checkbox";
import { DkimDot } from "../../components/DkimDot";
import { DKIM_FILTER_LABELS, DKIM_KEYS } from "../../lib/dkim";
import { formatNumber, utcDay } from "../../lib/format";
import { parseAmount } from "../entities/amount";
import { CONTEXT_LABELS, ENTITY_CONTEXTS } from "../entities/labels";
import { EVENT_LABELS } from "./chips";
import { DomainDialog } from "./DomainDialog";
import styles from "./FilterColumn.module.css";
import { withFilters, withoutSidebarFilters, type FilterPatch, type ListState } from "./listState";
import { ResearchFilters } from "./ResearchFilters";

const ALWAYS_SHOWN: readonly DkimKey[] = ["pass", "fail", "no_key", "unsigned"];
const TOP_DOMAINS = 5;

/** The filter column of the mail list (SPEC 5.1, D21). */
export function FilterColumn({
  state,
  onChange,
  stats,
  mboxFiles,
  research,
}: {
  state: ListState;
  onChange: (next: ListState) => void;
  stats: Stats | undefined;
  mboxFiles: MboxFileInfo[] | undefined;
  research: ResearchOverview | undefined;
}) {
  const [domainDialog, setDomainDialog] = useState(false);
  const change = (patch: FilterPatch) => onChange(withFilters(state, patch));

  // DKIM: all boxes checked and none checked both mean "no DKIM filter".
  const dkimShown = DKIM_KEYS.filter(
    (key) => ALWAYS_SHOWN.includes(key) || (stats?.dkim[key] ?? 0) > 0 || state.dkim.includes(key),
  );
  const dkimChecked = (key: DkimKey) => state.dkim.length === 0 || state.dkim.includes(key);
  function toggleDkim(key: DkimKey, checked: boolean) {
    const current = state.dkim.length ? state.dkim : dkimShown;
    const next = checked ? [...current, key] : current.filter((other) => other !== key);
    const all = dkimShown.every((other) => next.includes(other));
    change({ dkim: all ? [] : DKIM_KEYS.filter((other) => next.includes(other)) });
  }

  const topDomains = stats?.sender_domains.slice(0, TOP_DOMAINS) ?? [];
  const otherSelected = state.sender_domain.filter(
    (domain) => !topDomains.some((top) => top.domain === domain),
  );
  function toggleDomain(domain: string, checked: boolean) {
    change({
      sender_domain: checked
        ? [...state.sender_domain, domain]
        : state.sender_domain.filter((other) => other !== domain),
    });
  }

  const dayMin = stats?.date_min ? utcDay(stats.date_min) : undefined;
  const dayMax = stats?.date_max ? utcDay(stats.date_max) : undefined;
  const fileCount = stats?.mbox_files ?? mboxFiles?.length;

  return (
    <aside className={styles.column} aria-label="Filter">
      <div className={styles.head}>
        <h2 className={styles.heading}>Filter</h2>
        <Button variant="link" onClick={() => onChange(withoutSidebarFilters(state))}>
          Zurücksetzen
        </Button>
      </div>

      <fieldset className={styles.group}>
        <legend className={styles.legend}>Zeitraum</legend>
        <div className={styles.dates}>
          <DateField
            id="filter-date-from"
            label="von"
            value={state.date_from}
            min={dayMin}
            max={state.date_to ?? dayMax}
            onCommit={(date_from) => change({ date_from })}
          />
          <DateField
            id="filter-date-to"
            label="bis"
            value={state.date_to}
            min={state.date_from ?? dayMin}
            max={dayMax}
            onCommit={(date_to) => change({ date_to })}
          />
        </div>
      </fieldset>

      <fieldset className={styles.group}>
        <legend className={styles.legend}>DKIM-Status</legend>
        {dkimShown.map((key) => (
          <Checkbox
            key={key}
            checked={dkimChecked(key)}
            onChange={(checked) => toggleDkim(key, checked)}
            count={stats?.dkim[key]}
          >
            <DkimDot status={key} decorative />
            {DKIM_FILTER_LABELS[key]}
          </Checkbox>
        ))}
      </fieldset>

      <fieldset className={`${styles.group} ${styles.tight}`}>
        <legend className={styles.legend}>Absender-Domain</legend>
        {topDomains.map(({ domain, mails }) => (
          <Checkbox
            key={domain}
            checked={state.sender_domain.includes(domain)}
            onChange={(checked) => toggleDomain(domain, checked)}
            count={mails}
          >
            {domain}
          </Checkbox>
        ))}
        {otherSelected.map((domain) => (
          <Checkbox key={domain} checked onChange={(checked) => toggleDomain(domain, checked)}>
            {domain}
          </Checkbox>
        ))}
        {stats && stats.sender_domain_count > 0 && (
          <button type="button" className={styles.more} onClick={() => setDomainDialog(true)}>
            Alle {formatNumber(stats.sender_domain_count)} Domains …
          </button>
        )}
      </fieldset>

      <AmountFilters state={state} change={change} />

      <ResearchFilters state={state} change={change} research={research} />

      <fieldset className={styles.group}>
        <legend className={styles.legend}>Weitere</legend>
        <Checkbox
          checked={state.has_attachment}
          onChange={(has_attachment) => change({ has_attachment })}
        >
          Mit Anhang
        </Checkbox>
        <Checkbox checked={state.in_thread} onChange={(in_thread) => change({ in_thread })}>
          Teil eines Threads
        </Checkbox>
        {((stats?.internal_domains.length ?? 0) > 0 || state.external) && (
          <Checkbox checked={state.external} onChange={(external) => change({ external })}>
            Nur extern ↔ intern
          </Checkbox>
        )}
        <Checkbox
          checked={state.hide_duplicates}
          onChange={(hide_duplicates) => change({ hide_duplicates })}
        >
          Doppelte ausblenden
        </Checkbox>
        {((stats?.near?.groups ?? 0) > 0 || state.collapse_near) && (
          <Checkbox
            checked={state.collapse_near}
            onChange={(collapse_near) => change({ collapse_near })}
          >
            Dubletten zusammenfassen
          </Checkbox>
        )}
      </fieldset>

      <EventFilters state={state} change={change} stats={stats} />

      <div className={styles.group}>
        <label htmlFor="filter-mbox" className={styles.legend}>
          MBOX-Datei
        </label>
        <select
          id="filter-mbox"
          className={styles.select}
          value={state.mbox_file ?? ""}
          onChange={(event) =>
            change({ mbox_file: event.target.value ? Number(event.target.value) : null })
          }
        >
          <option value="">
            {fileCount === undefined ? "Alle Dateien" : `Alle ${formatNumber(fileCount)} Dateien`}
          </option>
          {state.mbox_file !== null && !mboxFiles?.some((file) => file.id === state.mbox_file) && (
            <option value={state.mbox_file}>Datei #{state.mbox_file}</option>
          )}
          {mboxFiles?.map((file) => (
            <option key={file.id} value={file.id}>
              {file.path}
            </option>
          ))}
        </select>
      </div>

      {domainDialog && (
        <DomainDialog
          selected={state.sender_domain}
          onToggle={toggleDomain}
          onClose={() => setDomainDialog(false)}
        />
      )}
    </aside>
  );
}

function isDay(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value));
}

/** A date input that changes the filter only for complete days: while the year is being typed
 *  the browser reports days such as 0002-01-01, which lie outside the archive's range and wait
 *  for the field to lose focus. */
export function DateField({
  id,
  label,
  value,
  min,
  max,
  onCommit,
}: {
  id: string;
  label: string;
  value: string | null;
  min: string | undefined;
  max: string | undefined;
  onCommit: (day: string | null) => void;
}) {
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (input.current && document.activeElement !== input.current) {
      input.current.value = value ?? "";
    }
  }, [value]);

  const inRange = (day: string) => (!min || day >= min) && (!max || day <= max);

  return (
    <div className={styles.dateField}>
      <label htmlFor={id} className={styles.dateLabel}>
        {label}
      </label>
      <input
        ref={input}
        id={id}
        type="date"
        className={styles.input}
        defaultValue={value ?? ""}
        min={min}
        max={max}
        onChange={(event) => {
          const day = event.target.value;
          if (day === (value ?? "")) return;
          if (day === "") onCommit(null);
          else if (isDay(day) && inRange(day)) onCommit(day);
        }}
        onBlur={(event) => {
          const day = event.target.value;
          if (day === (value ?? "")) return;
          if (day === "") onCommit(null);
          else if (isDay(day)) onCommit(day);
          else event.target.value = value ?? "";
        }}
      />
    </div>
  );
}

/** The amounts mentioned in a mail or its attachments (D86): at least a value, in any currency
 *  (no conversion), and the contexts such an amount stands next to. The value counts on Enter
 *  or when the field is left; German notation such as 10.000 is read, an empty field clears it. */
function AmountFilters({
  state,
  change,
}: {
  state: ListState;
  change: (patch: FilterPatch) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const shown = state.amount_min === null ? "" : formatNumber(state.amount_min);

  useEffect(() => {
    if (input.current && document.activeElement !== input.current) input.current.value = shown;
  }, [shown]);

  function commit(field: HTMLInputElement) {
    const value = parseAmount(field.value);
    if (value === undefined) {
      field.value = shown; // not an amount: the filter stays as it is
      return;
    }
    field.value = value === null ? "" : formatNumber(value);
    if (value !== state.amount_min) change({ amount_min: value });
  }

  return (
    <fieldset className={styles.group}>
      <legend className={styles.legend}>Beträge</legend>
      <p className={styles.scope}>In Text oder Anhang erwähnt, jede Währung</p>
      <div className={styles.amount}>
        <label htmlFor="filter-amount-min" className={styles.dateLabel}>
          ab
        </label>
        <input
          ref={input}
          id="filter-amount-min"
          type="text"
          inputMode="decimal"
          autoComplete="off"
          className={styles.input}
          defaultValue={shown}
          placeholder="z. B. 10.000"
          onKeyDown={(event) => {
            if (event.key !== "Enter") return;
            event.preventDefault();
            commit(event.currentTarget);
          }}
          onBlur={(event) => commit(event.currentTarget)}
        />
      </div>
      <div className={styles.sub} role="group" aria-label="Im Zusammenhang mit">
        <span className={styles.subLegend}>Im Zusammenhang mit</span>
        {ENTITY_CONTEXTS.map((key) => (
          <Checkbox
            key={key}
            checked={state.amount_context.includes(key)}
            onChange={(checked) =>
              change({
                amount_context: ENTITY_CONTEXTS.filter((other) =>
                  other === key ? checked : state.amount_context.includes(other),
                ),
              })
            }
          >
            {CONTEXT_LABELS[key]}
          </Checkbox>
        ))}
      </div>
    </fieldset>
  );
}

/** Calendar mails (D155), shown once the archive holds any. */
function EventFilters({
  state,
  change,
  stats,
}: {
  state: ListState;
  change: (patch: FilterPatch) => void;
  stats: Stats | undefined;
}) {
  const shown = EVENT_KEYS.filter(
    (key) => (stats?.events[key] ?? 0) > 0 || state.event.includes(key),
  );
  if (shown.length === 0) return null;
  function toggle(key: (typeof EVENT_KEYS)[number], checked: boolean) {
    const next = checked ? [...state.event, key] : state.event.filter((other) => other !== key);
    change({ event: EVENT_KEYS.filter((other) => next.includes(other)) });
  }
  return (
    <fieldset className={styles.group}>
      <legend className={styles.legend}>Termine</legend>
      {shown.map((key) => (
        <Checkbox
          key={key}
          checked={state.event.includes(key)}
          onChange={(checked) => toggle(key, checked)}
          count={stats?.events[key]}
        >
          {EVENT_LABELS[key]}
        </Checkbox>
      ))}
    </fieldset>
  );
}
