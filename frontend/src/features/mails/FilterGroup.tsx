import {
  createContext,
  useContext,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { ChevronDownIcon } from "../../components/icons";
import { cx } from "../../lib/cx";
import styles from "./FilterGroup.module.css";

const STORAGE_KEY = "mailrobbe.filter-groups";

/** Inside a bar of filter chips (D335) every FilterGroup is a chip that opens its controls in a
 *  popover; elsewhere it is a group of a filter column that folds by its heading. */
export const FilterBarContext = createContext(false);

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

/** A group of filters. In a filter column its heading folds it away, remembered in this browser
 *  by its id; folded, a group with a filter set says so beside its heading, so no filter hides in
 *  it. In a filter bar (FilterBarContext) it is a chip named `chip` (else `title`) that opens the
 *  same controls below it. */
export function FilterGroup({
  id,
  title,
  chip,
  active = false,
  className,
  children,
}: {
  id: string;
  title: string;
  chip?: string;
  active?: boolean;
  className?: string;
  children: ReactNode;
}) {
  const bar = useContext(FilterBarContext);
  if (bar) {
    return (
      <FilterPopover label={chip ?? title} active={active}>
        {children}
      </FilterPopover>
    );
  }
  return (
    <FoldingGroup id={id} title={title} active={active} className={className}>
      {children}
    </FoldingGroup>
  );
}

function FoldingGroup({
  id,
  title,
  active,
  className,
  children,
}: {
  id: string;
  title: string;
  active: boolean;
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

/** A chip of a filter bar and the popover under it with the group's controls: a change applies
 *  at once, Esc, a click outside or "Fertig" close it. An active chip (a filter of the group is
 *  set) is drawn in the accent colour. Groups nested in the popover fold as in a column. */
export function FilterPopover({
  label,
  active = false,
  dashed = false,
  icon,
  children,
}: {
  label: string;
  active?: boolean;
  /** The quiet chip "Weitere Filter". */
  dashed?: boolean;
  icon?: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const area = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const popover = useRef<HTMLDivElement>(null);
  const popoverId = useId();

  useEffect(() => {
    if (!open) return;
    popover.current?.querySelector<HTMLElement>("input, select, button")?.focus();
    const outside = (event: PointerEvent) => {
      if (!area.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setOpen(false);
      button.current?.focus();
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div ref={area} className={styles.chipArea}>
      <button
        ref={button}
        type="button"
        className={cx(styles.chip, active && styles.chipActive, dashed && styles.chipDashed)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={open ? popoverId : undefined}
        aria-label={active ? `${label} (aktiv)` : undefined}
        onClick={() => setOpen(!open)}
      >
        {icon}
        {label}
        {!dashed && <ChevronDownIcon size={14} />}
      </button>
      {open && (
        <div
          ref={popover}
          id={popoverId}
          role="dialog"
          aria-label={label}
          className={styles.popover}
        >
          <FilterBarContext value={false}>
            <div className={styles.controls}>{children}</div>
          </FilterBarContext>
          <div className={styles.popoverFoot}>
            <button
              type="button"
              className={styles.done}
              onClick={() => {
                setOpen(false);
                button.current?.focus();
              }}
            >
              Fertig
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
