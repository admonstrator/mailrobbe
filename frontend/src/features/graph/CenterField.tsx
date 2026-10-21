import { useId, useState, type KeyboardEvent } from "react";

import { ApiError } from "../../api/client";
import type { Graph, PersonSummary } from "../../api/types";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { useDebounced } from "../../lib/useDebounced";
import { nodeLabel } from "./elements";
import styles from "./GraphSidebar.module.css";
import { usePersonSearch } from "./personSearch";

/** The centers of the ego network as chips, and "Person hinzufügen …" with a person search.
 *  Chips are named from the drawn graph, an earlier one or the search result picked, else by
 *  id (a refused excerpt has no graph). */
export function CenterField({
  ids,
  graph,
  onChange,
}: {
  ids: number[];
  graph: Graph | undefined;
  onChange: (ids: number[]) => void;
}) {
  const listId = useId();
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [known, setKnown] = useState<Map<number, string>>(new Map());
  const [seen, setSeen] = useState<Graph | undefined>(undefined);
  if (graph && graph !== seen) {
    setSeen(graph);
    const next = new Map(known);
    for (const node of graph.nodes) if (node.center) next.set(node.id, nodeLabel(node));
    setKnown(next);
  }
  const q = useDebounced(text.trim(), 250);
  const search = usePersonSearch(q);
  const results = (search.data?.items ?? []).filter((person) => !ids.includes(person.id));
  const showList = open && text.trim() !== "";

  function name(id: number): string {
    const node = graph?.nodes.find((candidate) => candidate.id === id);
    return node ? nodeLabel(node) : (known.get(id) ?? `#${id}`);
  }

  function pick(person: PersonSummary) {
    setKnown(new Map(known).set(person.id, nodeLabel(person)));
    onChange([...ids, person.id]);
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

  const unavailable = search.error instanceof ApiError && search.error.status === 404;

  return (
    <div className={styles.group}>
      <label htmlFor="graph-center" className={styles.label}>
        Zentrum
      </label>
      {ids.length > 0 && (
        <ul className={styles.chips}>
          {ids.map((id) => (
            <li key={id} className={styles.chip}>
              {name(id)}
              <button
                type="button"
                className={styles.chipRemove}
                aria-label={`Zentrum entfernen: ${name(id)}`}
                onClick={() => onChange(ids.filter((other) => other !== id))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className={styles.combo}>
        <input
          id="graph-center"
          type="text"
          role="combobox"
          className={styles.text}
          placeholder="Person hinzufügen …"
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
            {unavailable ? (
              <p className={styles.resultNote}>
                Die Personensuche ist noch nicht verfügbar. Personen kommen über „Im Graphen zeigen“
                in einer Mail ins Zentrum.
              </p>
            ) : search.isError ? (
              <p className={styles.resultNote}>Die Suche ist fehlgeschlagen.</p>
            ) : search.isPending || q !== text.trim() ? (
              <p className={styles.resultNote}>
                <Spinner label="Personen werden gesucht" /> Suche …
              </p>
            ) : results.length === 0 ? (
              <p className={styles.resultNote}>Keine Person gefunden.</p>
            ) : null}
            {!unavailable && results.length > 0 && (
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
                    <span className={styles.resultName}>{person.name || person.email}</span>
                    <span className={styles.resultMeta}>
                      <span className={cx("mono", styles.resultEmail)}>{person.email}</span>
                      <span className={styles.resultCount}>
                        {formatNumber(person.figures.mails)} Mails
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
