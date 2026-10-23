import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { cx } from "../lib/cx";
import styles from "./OverflowMenu.module.css";

export interface OverflowItem {
  label: string;
  onSelect: () => void;
  /** Deleting and other final steps: shown in red, and the caller asks before doing it. */
  danger?: boolean;
  disabled?: boolean;
  /** A thin line above this item, to group the menu. */
  separated?: boolean;
}

/** The menu "…" (D334): the rare and the final actions of a view, so the view itself shows one
 *  main button and two or three others. Closes on a choice, Esc and a click outside. */
export function OverflowMenu({
  items,
  label = "Weitere Aktionen",
  icon,
  className,
}: {
  items: OverflowItem[];
  label?: string;
  /** The button's content; three dots by default. */
  icon?: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const area = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
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
    <div ref={area} className={cx(styles.area, className)}>
      <button
        ref={button}
        type="button"
        className={styles.button}
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        onClick={() => setOpen(!open)}
      >
        {icon ?? (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <circle cx="5" cy="12" r="1.7" />
            <circle cx="12" cy="12" r="1.7" />
            <circle cx="19" cy="12" r="1.7" />
          </svg>
        )}
      </button>
      {open && (
        <div id={menuId} role="menu" className={styles.menu}>
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              className={cx(
                styles.item,
                item.danger && styles.danger,
                item.separated && styles.separated,
              )}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
