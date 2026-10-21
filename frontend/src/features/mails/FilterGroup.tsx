import { useState, type ReactNode } from "react";

import { cx } from "../../lib/cx";
import styles from "./FilterGroup.module.css";

const STORAGE_KEY = "mailrobbe.filter-groups";

function loadFolded(): string[] {
  try {
    const folded: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
    return Array.isArray(folded) ? folded.filter((id) => typeof id === "string") : [];
  } catch {
    return []; // storage blocked or unreadable: all open
  }
}

function saveFolded(id: string, folded: boolean): void {
  try {
    const others = loadFolded().filter((other) => other !== id);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(folded ? [...others, id] : others));
  } catch {
    // storage blocked: the choice lasts until reload
  }
}

/** A group of a filter column whose heading folds it away, remembered in this browser by its id.
 *  Folded, a group with a filter set says so beside its heading, so no filter hides in it. */
export function FilterGroup({
  id,
  title,
  active = false,
  className,
  children,
}: {
  id: string;
  title: string;
  active?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(() => !loadFolded().includes(id));
  return (
    <fieldset className={cx(styles.group, className)}>
      <legend className={styles.legend}>
        <button
          type="button"
          className={styles.toggle}
          aria-expanded={open}
          onClick={() => {
            setOpen(!open);
            saveFolded(id, open);
          }}
        >
          {title}
          {!open && active && <span className={styles.active}> · aktiv</span>}
          <span className={styles.chevron} aria-hidden="true" />
        </button>
      </legend>
      {open && children}
    </fieldset>
  );
}
