import { useEffect, useRef, type ReactNode } from "react";

import { cx } from "../lib/cx";
import { CrossIcon } from "./icons";
import styles from "./SidePanel.module.css";

/** A panel at the right of a page's content (D334): a quick look without leaving the list, such
 *  as a mail's preview or the facets of a list. It sits beside the content, sticks below the
 *  header and scrolls on its own; Esc and the cross close it. `actions` stand left of the cross
 *  ("Ganz öffnen", "In neuem Fenster"). */
export function SidePanel({
  label,
  title,
  actions,
  onClose,
  width,
  className,
  children,
}: {
  /** The accessible name of the panel. */
  label: string;
  /** A visible heading in the panel's bar; without it only the actions stand there. */
  title?: ReactNode;
  actions?: ReactNode;
  onClose: () => void;
  /** CSS width, default --panel-width. */
  width?: string;
  className?: string;
  children: ReactNode;
}) {
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("dialog, [role=dialog], [role=menu]")) return;
      close.current();
    };
    document.addEventListener("keydown", escape);
    return () => document.removeEventListener("keydown", escape);
  }, []);
  return (
    <aside
      aria-label={label}
      className={cx(styles.panel, className)}
      style={width ? { width, flexBasis: width } : undefined}
    >
      <div className={styles.bar}>
        {title && <h2 className={styles.title}>{title}</h2>}
        <div className={styles.actions}>{actions}</div>
        <button
          type="button"
          className={styles.close}
          aria-label="Schließen"
          title="Schließen (Esc)"
          onClick={onClose}
        >
          <CrossIcon size={18} />
        </button>
      </div>
      <div className={styles.body}>{children}</div>
    </aside>
  );
}
