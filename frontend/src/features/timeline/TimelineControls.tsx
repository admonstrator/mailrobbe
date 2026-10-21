import { useId, useState, type FormEvent } from "react";

import {
  MAX_TIMELINE_BUCKETS,
  MAX_TIMELINE_SERIES,
  MAX_TIMELINE_TERMS,
  type PersonSummary,
  type Timeline,
  type TimelineBucket,
  type TimelineSplit,
} from "../../api/types";
import { Button } from "../../components/Button";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { BUCKET_LABELS, BUCKET_PLURALS, SPLIT_LABELS } from "./labels";
import { PersonPicker } from "./PersonPicker";
import styles from "./TimelineControls.module.css";
import { TIMELINE_BUCKETS, TIMELINE_SPLITS, type TimelineState } from "./urlState";

/** One choice of several as a row of buttons, the pressed one highlighted. */
function Segments<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: [T, string][];
  value: T;
  onChange: (value: T) => void;
}) {
  const labelId = useId();
  return (
    <div className={styles.control}>
      <span id={labelId} className={styles.label}>
        {label}
      </span>
      <div role="group" aria-labelledby={labelId} className={styles.segments}>
        {options.map(([key, text]) => (
          <button
            key={key}
            type="button"
            aria-pressed={key === value}
            className={cx(styles.segment, key === value && styles.active)}
            onClick={() => onChange(key)}
          >
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}

/** What the unit control says about the unit shown: chosen by the span, or coarsened (D91). */
function bucketHint(state: TimelineState, timeline: Timeline | undefined): string | null {
  if (!timeline) return null;
  const shown = BUCKET_PLURALS[timeline.bucket];
  if (timeline.coarsened) {
    const finer = state.bucket ? `nach ${BUCKET_PLURALS[state.bucket]}` : "feiner";
    return `Angezeigt nach ${shown}: ${finer} wären es mehr als ${formatNumber(MAX_TIMELINE_BUCKETS)} Balken.`;
  }
  return state.bucket === null ? `Automatisch gewählt: nach ${shown}.` : null;
}

/** Zeiteinheit and Aufschlüsseln, and below them what the split shows: the chosen persons or
 *  threads (else the six with the most matches), or the search strings. */
export function TimelineControls({
  state,
  onChange,
  timeline,
  seriesName,
  onPickPerson,
}: {
  state: TimelineState;
  onChange: (next: TimelineState) => void;
  timeline: Timeline | undefined;
  /** The name of a chosen person or thread. */
  seriesName: (id: number) => string;
  onPickPerson: (person: PersonSummary) => void;
}) {
  const hint = bucketHint(state, timeline);
  const ids = state.split_id;
  const setIds = (split_id: number[]) => onChange({ ...state, split_id });
  return (
    <div className={styles.controls}>
      <div className={styles.row}>
        <Segments<TimelineBucket | "auto">
          label="Zeiteinheit"
          options={[
            ["auto", "Automatisch"],
            ...TIMELINE_BUCKETS.map((key): [TimelineBucket, string] => [key, BUCKET_LABELS[key]]),
          ]}
          value={state.bucket ?? "auto"}
          onChange={(bucket) => onChange({ ...state, bucket: bucket === "auto" ? null : bucket })}
        />
        <Segments<TimelineSplit>
          label="Aufschlüsseln"
          options={TIMELINE_SPLITS.map((key) => [key, SPLIT_LABELS[key]])}
          value={state.split}
          onChange={(split) => {
            // Ids and terms belong to their split: person ids are no thread ids.
            if (split !== state.split) onChange({ ...state, split, split_id: [], term: [] });
          }}
        />
      </div>
      {hint && (
        <p className={cx(styles.hint, timeline?.coarsened && styles.coarsened)} role="status">
          {hint}
        </p>
      )}

      {state.split === "person" && (
        <div className={styles.detail}>
          {ids.length === 0 ? (
            <p className={styles.hint}>
              Ohne Auswahl: die sechs Personen mit den meisten Treffern, ohne Verteiler und
              Automaten.
            </p>
          ) : (
            <SeriesChips
              ids={ids}
              name={seriesName}
              noun="Person"
              onChange={setIds}
              onReset={() => setIds([])}
            />
          )}
          <PersonPicker
            chosen={ids}
            disabled={ids.length >= MAX_TIMELINE_SERIES}
            onPick={(person) => {
              onPickPerson(person);
              setIds([...ids, person.id]);
            }}
          />
        </div>
      )}
      {state.split === "thread" && (
        <div className={styles.detail}>
          {ids.length === 0 ? (
            <p className={styles.hint}>
              Die sechs Threads mit den meisten Treffern, benannt nach dem Betreff ihrer ersten
              Mail.
            </p>
          ) : (
            <SeriesChips
              ids={ids}
              name={seriesName}
              noun="Thread"
              onChange={setIds}
              onReset={() => setIds([])}
            />
          )}
        </div>
      )}
      {state.split === "term" && (
        <TermField terms={state.term} onChange={(term) => onChange({ ...state, term })} />
      )}
    </div>
  );
}

function SeriesChips({
  ids,
  name,
  noun,
  onChange,
  onReset,
}: {
  ids: number[];
  name: (id: number) => string;
  noun: string;
  onChange: (ids: number[]) => void;
  onReset: () => void;
}) {
  return (
    <div className={styles.chipRow}>
      <ul
        className={styles.chips}
        aria-label={noun === "Person" ? "Gewählte Personen" : "Gewählte Threads"}
      >
        {ids.map((id) => (
          <li key={id} className={styles.chip}>
            <span className={styles.chipText}>{name(id)}</span>
            <button
              type="button"
              className={styles.chipRemove}
              aria-label={`${noun} entfernen: ${name(id)}`}
              onClick={() => onChange(ids.filter((other) => other !== id))}
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <Button variant="link" size="sm" onClick={onReset}>
        Wieder die sechs häufigsten
      </Button>
    </div>
  );
}

/** Search strings to compare, each a lane of its own; Enter or "Hinzufügen" adds one. */
function TermField({ terms, onChange }: { terms: string[]; onChange: (terms: string[]) => void }) {
  const inputId = useId();
  const [text, setText] = useState("");
  const full = terms.length >= MAX_TIMELINE_TERMS;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const term = text.trim();
    if (!term || full) return;
    if (!terms.includes(term)) onChange([...terms, term]);
    setText("");
  }

  return (
    <div className={styles.detail}>
      {terms.length > 0 && (
        <ul className={styles.chips} aria-label="Suchbegriffe">
          {terms.map((term) => (
            <li key={term} className={styles.chip}>
              <span className={cx("mono", styles.chipText)}>{term}</span>
              <button
                type="button"
                className={styles.chipRemove}
                aria-label={`Suchbegriff entfernen: ${term}`}
                onClick={() => onChange(terms.filter((other) => other !== term))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <form className={styles.termForm} onSubmit={onSubmit}>
        <label htmlFor={inputId} className="sr-only">
          Suchbegriff
        </label>
        <input
          id={inputId}
          type="text"
          className={styles.input}
          placeholder={full ? "Höchstens sechs Suchbegriffe" : "Suchbegriff hinzufügen …"}
          autoComplete="off"
          spellCheck={false}
          disabled={full}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <Button type="submit" size="sm" disabled={full || !text.trim()}>
          Hinzufügen
        </Button>
      </form>
      <p className={styles.hint}>
        Jeder Suchbegriff bekommt eine eigene Zeile, bis zu sechs. Es gilt die Suchsyntax der
        Mailliste, etwa <code className={styles.example}>Spende</code>,{" "}
        <code className={styles.example}>"schwarze Kasse"</code> oder{" "}
        <code className={styles.example}>from:kasse@</code>.
      </p>
    </div>
  );
}
