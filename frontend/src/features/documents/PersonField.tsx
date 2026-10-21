import { useId, useState, type KeyboardEvent } from "react";

import { usePerson } from "../../api/queries";
import type { PersonSummary } from "../../api/types";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { useDebounced } from "../../lib/useDebounced";
import { usePersonSearch } from "../graph/personSearch";
import { personLabel } from "../persons/labels";
import styles from "./DocumentFilterColumn.module.css";
import type { DocumentPersonRole } from "./urlState";

const ROLE_OPTIONS: [DocumentPersonRole | "", string][] = [
  ["", "gesendet oder empfangen"],
  ["sent", "gesendet"],
  ["received", "empfangen"],
];

/** The person filter (D74): a search over the person list, as the map's Zentrum field has, that
 *  picks one person, and the role it took. */
export function PersonField({
  person,
  role,
  onChange,
}: {
  person: number | null;
  role: DocumentPersonRole | null;
  onChange: (person: number | null, role: DocumentPersonRole | null) => void;
}) {
  const [picked, setPicked] = useState<PersonSummary | null>(null);
  return (
    <fieldset className={styles.group}>
      <legend className={styles.legend}>Person</legend>
      {person === null ? (
        <PersonSearch
          onPick={(chosen) => {
            setPicked(chosen);
            onChange(chosen.id, role);
          }}
        />
      ) : (
        <SelectedPerson
          id={person}
          known={picked?.id === person ? picked : null}
          role={role}
          onChange={onChange}
        />
      )}
    </fieldset>
  );
}

/** The chosen person as a chip, named by its profile (which also names a person that came with a
 *  link), and its role. */
function SelectedPerson({
  id,
  known,
  role,
  onChange,
}: {
  id: number;
  known: PersonSummary | null;
  role: DocumentPersonRole | null;
  onChange: (person: number | null, role: DocumentPersonRole | null) => void;
}) {
  const profile = usePerson(id);
  const shown = profile.data ?? known;
  const name = shown ? personLabel(shown) : `Person #${id}`;
  return (
    <>
      <span className={styles.chip}>
        <span className={styles.chipText} title={shown?.email}>
          {name}
        </span>
        <button
          type="button"
          className={styles.chipRemove}
          aria-label={`Person entfernen: ${name}`}
          onClick={() => onChange(null, null)}
        >
          ×
        </button>
      </span>
      <select
        aria-label="Rolle der Person"
        className={styles.select}
        value={role ?? ""}
        onChange={(event) =>
          onChange(id, (event.target.value || null) as DocumentPersonRole | null)
        }
      >
        {ROLE_OPTIONS.map(([value, label]) => (
          <option key={value} value={value}>
            {label}
          </option>
        ))}
      </select>
    </>
  );
}

/** "Person suchen …": the persons whose name or address contain the text, most mails first. */
function PersonSearch({ onPick }: { onPick: (person: PersonSummary) => void }) {
  const listId = useId();
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const q = useDebounced(text.trim(), 250);
  const search = usePersonSearch(q);
  const results = search.data?.items ?? [];
  const showList = open && text.trim() !== "";

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      setOpen(true);
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((current) =>
        Math.min(Math.max(current + step, 0), Math.max(results.length - 1, 0)),
      );
    } else if (event.key === "Enter" && showList && results[active]) {
      event.preventDefault();
      onPick(results[active]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className={styles.combo}>
      <input
        type="text"
        role="combobox"
        aria-label="Person suchen"
        className={styles.input}
        placeholder="Name oder Adresse …"
        autoComplete="off"
        spellCheck={false}
        aria-expanded={showList}
        aria-controls={listId}
        aria-activedescendant={showList && results[active] ? `${listId}-${active}` : undefined}
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={onKeyDown}
      />
      {showList && (
        // Clicks must not blur the input before they pick.
        <div className={styles.results} onMouseDown={(event) => event.preventDefault()}>
          {search.isError ? (
            <p className={styles.resultNote}>Die Suche ist fehlgeschlagen.</p>
          ) : search.isPending || q !== text.trim() ? (
            <p className={styles.resultNote}>
              <Spinner label="Personen werden gesucht" /> Suche …
            </p>
          ) : results.length === 0 ? (
            <p className={styles.resultNote}>Keine Person gefunden.</p>
          ) : (
            <ul id={listId} role="listbox" aria-label="Personen" className={styles.resultList}>
              {results.map((candidate, index) => (
                <li
                  key={candidate.id}
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={index === active}
                  className={cx(styles.result, index === active && styles.resultActive)}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => onPick(candidate)}
                >
                  <span className={styles.resultName}>{personLabel(candidate)}</span>
                  <span className={styles.resultMeta}>
                    <span className="mono">{candidate.email}</span>
                    <span>{formatNumber(candidate.figures.mails)} Mails</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
