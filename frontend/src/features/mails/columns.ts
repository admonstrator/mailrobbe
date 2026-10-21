import { useState } from "react";

/** Columns the "Spalten" menu shows or hides; DKIM, Von, Betreff and Datum are always there. */
export type OptionalColumn = "to" | "attachment" | "size" | "mbox";
export type ColumnChoice = Record<OptionalColumn, boolean>;

export const COLUMN_LABELS: Record<OptionalColumn, string> = {
  to: "An",
  attachment: "Anhang",
  size: "Größe",
  mbox: "MBOX-Datei",
};

const DEFAULT_COLUMNS: ColumnChoice = { to: true, attachment: true, size: false, mbox: false };
const STORAGE_KEY = "mailrobbe.columns";

function load(): ColumnChoice {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
    if (Array.isArray(stored)) {
      const visible = new Set(stored);
      return {
        to: visible.has("to"),
        attachment: visible.has("attachment"),
        size: visible.has("size"),
        mbox: visible.has("mbox"),
      };
    }
  } catch {
    // storage blocked or garbage: the defaults
  }
  return DEFAULT_COLUMNS;
}

function save(columns: ColumnChoice): void {
  try {
    const visible = Object.entries(columns).flatMap(([column, shown]) => (shown ? [column] : []));
    localStorage.setItem(STORAGE_KEY, JSON.stringify(visible));
  } catch {
    // storage blocked: the choice lasts until reload
  }
}

/** The optional columns shown, remembered in this browser. */
export function useColumns(): [ColumnChoice, (column: OptionalColumn, shown: boolean) => void] {
  const [columns, setColumns] = useState(load);
  function setColumn(column: OptionalColumn, shown: boolean) {
    const next = { ...columns, [column]: shown };
    setColumns(next);
    save(next);
  }
  return [columns, setColumn];
}
