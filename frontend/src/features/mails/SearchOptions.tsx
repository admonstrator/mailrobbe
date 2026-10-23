import { useEffect, useRef } from "react";

import {
  BODY_PARTS,
  MIN_HITS_LIMIT,
  SEARCH_FIELDS,
  type BodyPart,
  type SearchField,
} from "../../api/types";
import { Checkbox } from "../../components/Checkbox";
import { SEARCH_FIELD_LABELS } from "./chips";
import { canonicalScope, positiveInt, type SearchOptions as Options } from "./listState";
import styles from "./SearchOptions.module.css";

/** The operators of the search in short lines, by group (D20, D172, D175, D229, D340, D341). */
const SYNTAX: readonly (readonly [string, readonly (readonly [string, string])[]])[] = [
  [
    "Wörter",
    [
      ["Spende Partei", "beide Wörter, auch gebeugt"],
      ["Spende or Zuwendung", "eines der beiden"],
      ['"finale Fassung"', "genau so geschrieben, auch ein einzelnes Wort"],
      ['"Spende bar"~5', "beide Wörter, höchstens 5 Wörter dazwischen"],
      ["-Entwurf", "ohne dieses Wort"],
      ["betreff:Wort", "nur im Betreff"],
      ["text:Wort", "nur im Mailtext"],
      ["anhang:Wort", "nur im Text der Anhänge"],
      ["datei:Wort", "nur in Dateinamen"],
    ],
  ],
  [
    "Personen und Domains",
    [
      ["from:anna", "Absender: Teil von Adresse oder Name"],
      ["to: cc: bcc:", "ebenso für An, Cc und Bcc"],
      ["recipient:anna", "in An, Cc oder Bcc"],
      ["to:@beispiel.de", "an diese Domain und ihre Subdomains"],
      ["recipient:.ru", "an Adressen auf .ru"],
      ["domain:beispiel.de", "Domain in jeder Rolle, auch domain:.at"],
      ["between:anna,bert", "die eine Seite schrieb, die andere empfing"],
      ["between:anna,.ru", "Anna mit jemandem auf .ru, auch @domain"],
    ],
  ],
  [
    "Weitere",
    [
      ["subject:Wort", "Teil des Betreffs, auch mitten im Wort"],
      ["has:attachment", "mit Anhang"],
      [
        "dkim:fail",
        "DKIM-Ergebnis: pass, consistent, fail, no_key, unsigned, temp_error, unchecked",
      ],
      ["after:2024-01-31", "ab diesem Tag, auch 31.01.2024"],
      ["before:2025-01-01", "vor diesem Tag"],
      ["<id@host>", "Message-ID"],
      ["-from:@beispiel.de", "Minus vor einem Operator schließt aus"],
    ],
  ],
];

export const DEFAULT_SEARCH_OPTIONS: Options = {
  scope: [],
  whole_word: false,
  min_hits: null,
  body_part: "clean",
  include_hidden: false,
};

/** How many of the options differ from the default: the badge of the search menu. */
export function changedOptions(options: Options): number {
  return [
    options.scope.length > 0,
    options.whole_word,
    options.min_hits !== null,
    options.body_part !== "clean",
    options.include_hidden,
  ].filter(Boolean).length;
}

/** The parts of the mail's own text the words are looked for in (D226, D228). */
export const BODY_PART_LABELS: Record<BodyPart, [label: string, hint: string]> = {
  clean: ["Ohne Standardblöcke", "Rechtshinweise und Signaturen, die unter vielen Mails stehen"],
  own: ["Nur selbst Geschriebenes", "auch ohne Zitate, Weiterleitungen und Vorgängermails"],
  full: ["Alles", "Standardblöcke und Zitate eingeschlossen"],
};

/** The search options of the search menu (D177): where q's free words are looked for, whole
 *  words, and how often they must occur at least (D171 to D174). All four places ticked is the
 *  default; the last ticked one cannot be unticked. */
export function SearchOptions({
  options,
  change,
}: {
  options: Options;
  change: (patch: Partial<Options>) => void;
}) {
  const ticked = options.scope.length ? options.scope : SEARCH_FIELDS;
  function toggle(field: SearchField, checked: boolean) {
    change({
      scope: canonicalScope(
        checked ? [...ticked, field] : ticked.filter((other) => other !== field),
      ),
    });
  }

  return (
    <div className={styles.options}>
      <div className={styles.places} role="group" aria-labelledby="search-places-label">
        <span id="search-places-label" className={styles.label}>
          Suchen in
        </span>
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
        <Checkbox checked={options.whole_word} onChange={(whole_word) => change({ whole_word })}>
          Ganzes Wort
        </Checkbox>
        <p className={styles.hint}>
          ohne Wortstamm und Teilwörter, Groß/Klein egal, Umlaute und Akzente zählen
        </p>
      </div>
      <MinHitsField value={options.min_hits} onCommit={(min_hits) => change({ min_hits })} />
      <div className={styles.places} role="radiogroup" aria-labelledby="search-body-part-label">
        <span id="search-body-part-label" className={styles.label}>
          Mailtext durchsuchen
        </span>
        {BODY_PARTS.map((part) => (
          <label key={part} className={styles.radio}>
            <input
              type="radio"
              name="search-body-part"
              checked={options.body_part === part}
              onChange={() => change({ body_part: part })}
            />
            <span>
              {BODY_PART_LABELS[part][0]}
              <span className={styles.radioHint}>{BODY_PART_LABELS[part][1]}</span>
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}

/** The search syntax as a compact list of examples. */
export function SearchSyntax() {
  return (
    <div className={styles.syntaxGroups}>
      {SYNTAX.map(([group, lines]) => (
        <div key={group}>
          <h4 className={styles.syntaxGroup}>{group}</h4>
          <dl className={styles.syntax}>
            {lines.map(([example, meaning]) => (
              <div key={example} className={styles.syntaxLine}>
                <dt>
                  <code className={styles.code}>{example}</code>
                </dt>
                <dd>{meaning}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </div>
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
        className={styles.minHitsInput}
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
