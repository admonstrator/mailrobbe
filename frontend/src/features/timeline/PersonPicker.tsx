import { useId, useState, type KeyboardEvent } from "react";

import type { PersonSummary } from "../../api/types";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { useDebounced } from "../../lib/useDebounced";
import { usePersonSearch } from "../graph/personSearch";
import { personLabel } from "../persons/labels";
import styles from "./TimelineControls.module.css";

/** "Person hinzufügen …": the person list's search (as the map's Zentrum field has) that picks
 *  one more person for the split; persons already chosen are not offered. */
export function PersonPicker({
  chosen,
  disabled,
  onPick,
}: {
  chosen: number[];
  disabled: boolean;
  onPick: (person: PersonSummary) => void;
}) {
  const listId = useId();
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const q = useDebounced(text.trim(), 250);
  const search = usePersonSearch(q);
  const results = (search.data?.items ?? []).filter((person) => !chosen.includes(person.id));
  const showList = open && text.trim() !== "";

  function pick(person: PersonSummary) {
    onPick(person);
    setText("");
    setActive(0);
  }

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
      pick(results[active]);
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className={styles.combo}>
      <input
        type="text"
        role="combobox"
        aria-label="Person hinzufügen"
        className={styles.input}
        placeholder={disabled ? "Höchstens zwölf Personen" : "Person hinzufügen …"}
        autoComplete="off"
        spellCheck={false}
        disabled={disabled}
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
              {results.map((person, index) => (
                <li
                  key={person.id}
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={index === active}
                  className={cx(styles.result, index === active && styles.resultActive)}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => pick(person)}
                >
                  <span className={styles.resultName}>{personLabel(person)}</span>
                  <span className={styles.resultMeta}>
                    <span className="mono">{person.email}</span>
                    <span>{formatNumber(person.figures.mails)} Mails</span>
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
