import { useState } from "react";

import { useMetadataValues } from "../../api/queries";
import type { DocumentFilters, MetadataValueCount } from "../../api/types";
import { Button } from "../../components/Button";
import { Checkbox } from "../../components/Checkbox";
import { Spinner } from "../../components/Spinner";
import { useDebounced } from "../../lib/useDebounced";
import styles from "./DocumentFilterColumn.module.css";

/** Values shown before "mehr". */
const SHOWN = 6;

const NAMES = {
  author: { title: "Autor", search: "Autor suchen …", remove: "Autor entfernen" },
  program: { title: "Programm", search: "Programm suchen …", remove: "Programm entfernen" },
};

/** A facet of what the files say about themselves (D167), "Autor" or "Programm": the chosen
 *  values as chips, the most frequent others with their documents, and a search within every
 *  value. The counts are taken without the facet's own selection. */
export function MetadataFacet({
  field,
  selected,
  top,
  filters,
  onChange,
}: {
  field: "author" | "program";
  selected: string[];
  /** The most frequent values (DocumentSummary); undefined while loading, null: out of time. */
  top: MetadataValueCount[] | null | undefined;
  /** The list's filters without this facet's selection, which the search counts within. */
  filters: DocumentFilters;
  onChange: (values: string[]) => void;
}) {
  const names = NAMES[field];
  const [text, setText] = useState("");
  const [expanded, setExpanded] = useState(false);
  const search = useDebounced(text.trim(), 250);
  const searching = text.trim() !== "";
  const found = useMetadataValues({ ...filters, field, search }, search !== "");
  const values = (searching ? found.data?.values : top) ?? [];
  const open = values.filter(({ value }) => !selected.includes(value));
  const shown = searching || expanded ? open : open.slice(0, SHOWN);
  const nothing = top?.length === 0 && selected.length === 0 && !searching;

  const pick = (value: string) => {
    onChange([...selected, value]);
    setText("");
  };

  return (
    <fieldset className={`${styles.group} ${styles.tight}`}>
      <legend className={styles.legend}>{names.title}</legend>
      {selected.map((value) => (
        <span key={value} className={styles.chip}>
          <span className={styles.chipText}>{value}</span>
          <button
            type="button"
            className={styles.chipRemove}
            aria-label={`${names.remove}: ${value}`}
            onClick={() => onChange(selected.filter((other) => other !== value))}
          >
            ×
          </button>
        </span>
      ))}
      {top === null && !searching && (
        <p className={styles.note}>Die Angaben ließen sich nicht rechtzeitig zählen.</p>
      )}
      {nothing ? (
        <p className={styles.note}>Keine Angaben in den Dateien.</p>
      ) : (
        <input
          type="search"
          className={styles.input}
          aria-label={names.search.replace(" …", "")}
          placeholder={names.search}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      )}
      {searching && !found.data && !found.isError ? (
        <p className={styles.resultNote}>
          <Spinner label="Werte werden gesucht" /> Suche …
        </p>
      ) : searching && found.isError ? (
        <p className={styles.note}>Die Suche ist fehlgeschlagen.</p>
      ) : searching && found.data?.values === null ? (
        <p className={styles.note}>Die Suche dauerte zu lange.</p>
      ) : searching && found.data && open.length === 0 ? (
        <p className={styles.note}>Nichts gefunden.</p>
      ) : (
        shown.map(({ value, documents }) => (
          <Checkbox key={value} checked={false} onChange={() => pick(value)} count={documents}>
            {value}
          </Checkbox>
        ))
      )}
      {!searching && open.length > SHOWN && (
        <Button
          variant="link"
          size="xs"
          className={styles.moreValues}
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "weniger" : `alle ${open.length} anzeigen`}
        </Button>
      )}
    </fieldset>
  );
}
