import { useEffect, useId, useRef, useState } from "react";

import { Button } from "../../components/Button";
import { Checkbox } from "../../components/Checkbox";
import { COLUMN_LABELS, type ColumnChoice, type OptionalColumn } from "./columns";
import styles from "./ColumnMenu.module.css";

/** The "Spalten" button with its menu of optional columns. */
export function ColumnMenu({
  columns,
  onChange,
}: {
  columns: ColumnChoice;
  onChange: (column: OptionalColumn, shown: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={root} className={styles.root}>
      <Button size="sm" aria-expanded={open} aria-controls={menuId} onClick={() => setOpen(!open)}>
        Spalten
      </Button>
      {open && (
        <div id={menuId} role="group" aria-label="Spalten" className={styles.menu}>
          {(Object.keys(COLUMN_LABELS) as OptionalColumn[]).map((column) => (
            <Checkbox
              key={column}
              checked={columns[column]}
              onChange={(shown) => onChange(column, shown)}
            >
              {COLUMN_LABELS[column]}
            </Checkbox>
          ))}
        </div>
      )}
    </div>
  );
}
