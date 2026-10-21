import { useEffect, useRef } from "react";

import { MIN_HITS_LIMIT, SEARCH_FIELDS, type QueryTerm, type SearchField } from "../../api/types";
import { Checkbox } from "../../components/Checkbox";
import { SEARCH_FIELD_LABELS } from "./chips";
import columnStyles from "./FilterColumn.module.css";
import { canonicalScope, positiveInt, type FilterPatch, type ListState } from "./listState";
import styles from "./SearchOptions.module.css";

/** Query keys of full text words: the free words and those looked for in one place (D172). */
const WORD_KEYS: readonly QueryTerm["key"][] = [
  "text",
  "in_subject",
  "in_body",
  "in_attachment",
  "in_filename",
];

/** The search syntax in short lines (D20, D172, D175). */
const SYNTAX: readonly [string, string][] = [
  ["betreff:Wort", "nur im Betreff"],
  ["text:Wort", "nur im Mailtext"],
  ["anhang:Wort", "nur im Text der Anhänge"],
  ["datei:Wort", "nur in Dateinamen"],
  ["-datei:Entwurf", "Minus schließt aus, auch vor from:, has: usw."],
  ["Wort or Wort", "eines der beiden"],
  ['"genaue Phrase"', "die Wörter in dieser Folge"],
  ["subject:Wort", "Teil des Betreffs, auch mitten im Wort"],
];

/** q has no full text words, as far as its terms are known; false while they are not (a page
 *  loading for a new query). */
function withoutWords(q: string, terms: QueryTerm[] | undefined): boolean {
  if (!q) return true;
  const known = terms?.filter((term) => q.includes(term.raw)) ?? [];
  return known.length > 0 && !known.some((term) => WORD_KEYS.includes(term.key));
}

/** The group "Suche" of the filter column (D177): where q's free words are looked for, whole
 *  words, and how often they must occur at least (D171 to D174), with a short help of the
 *  syntax. All four places ticked is the default; the last ticked one cannot be unticked. */
export function SearchOptions({
  state,
  terms,
  change,
}: {
  state: ListState;
  /** The query terms of the page shown, for the note that the options need words. */
  terms: QueryTerm[] | undefined;
  change: (patch: FilterPatch) => void;
}) {
  const ticked = state.scope.length ? state.scope : SEARCH_FIELDS;
  function toggle(field: SearchField, checked: boolean) {
    change({
      scope: canonicalScope(
        checked ? [...ticked, field] : ticked.filter((other) => other !== field),
      ),
    });
  }

  return (
    <fieldset className={columnStyles.group}>
      <legend className={columnStyles.legend}>Suche</legend>
      {withoutWords(state.q, terms) && (
        <p className={columnStyles.scope}>Wirkt auf die Wörter der Suche oben</p>
      )}
      <div className={columnStyles.sub} role="group" aria-label="Suchen in">
        <span className={columnStyles.subLegend}>Suchen in</span>
        {SEARCH_FIELDS.map((field) => {
          const checked = ticked.includes(field);
          const last = checked && ticked.length === 1;
          return (
            <Checkbox
              key={field}
              checked={checked}
              disabled={last}
              title={last ? "Mindestens ein Ort bleibt ausgewählt" : undefined}
              onChange={(on) => toggle(field, on)}
            >
              {SEARCH_FIELD_LABELS[field]}
            </Checkbox>
          );
        })}
      </div>
      <div>
        <Checkbox checked={state.whole_word} onChange={(whole_word) => change({ whole_word })}>
          Ganzes Wort
        </Checkbox>
        <p className={styles.hint}>
          ohne Wortstamm und Teilwörter, Groß/Klein egal, Umlaute und Akzente zählen
        </p>
      </div>
      <MinHitsField value={state.min_hits} onCommit={(min_hits) => change({ min_hits })} />
      <details className={styles.syntax}>
        <summary className={styles.summary}>Suchsyntax</summary>
        <ul className={styles.syntaxList}>
          {SYNTAX.map(([example, meaning]) => (
            <li key={example}>
              <code className={styles.code}>{example}</code> {meaning}
            </li>
          ))}
        </ul>
      </details>
    </fieldset>
  );
}

/** "Mindestens [n] Treffer": a whole number from 1 to MIN_HITS_LIMIT counts on Enter or when the
 *  field is left, an empty field clears it, anything else leaves the filter as it is. */
function MinHitsField({
  value,
  onCommit,
}: {
  value: number | null;
  onCommit: (value: number | null) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const shown = value === null ? "" : String(value);

  useEffect(() => {
    if (input.current && document.activeElement !== input.current) input.current.value = shown;
  }, [shown]);

  function commit(field: HTMLInputElement) {
    const text = field.value.trim();
    const next = text === "" ? null : positiveInt(text, MIN_HITS_LIMIT);
    if (text !== "" && next === null) {
      field.value = shown; // not a usable number: the filter stays as it is
      return;
    }
    field.value = next === null ? "" : String(next);
    if (next !== value) onCommit(next);
  }

  return (
    <div className={styles.minHits}>
      <label id="filter-min-hits-label" htmlFor="filter-min-hits">
        Mindestens
      </label>
      <input
        ref={input}
        id="filter-min-hits"
        type="text"
        inputMode="numeric"
        autoComplete="off"
        className={`${columnStyles.input} ${styles.minHitsInput}`}
        defaultValue={shown}
        aria-labelledby="filter-min-hits-label filter-min-hits-unit"
        onKeyDown={(event) => {
          if (event.key !== "Enter") return;
          event.preventDefault();
          commit(event.currentTarget);
        }}
        onBlur={(event) => commit(event.currentTarget)}
      />
      <span id="filter-min-hits-unit">Treffer</span>
    </div>
  );
}
