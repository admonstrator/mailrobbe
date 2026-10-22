import { useId, type ReactNode, type Ref } from "react";

import { cx } from "../lib/cx";
import { useFold } from "../lib/folds";
import { Card } from "./Card";
import styles from "./FoldCard.module.css";

/** A card whose heading folds it to one line, remembered in this browser per `id` (lib/folds).
 *  Folded, `summary` stands beside the heading; `actions` stay in reach either way. "main" has
 *  the plain heading of the main column, "side" the small uppercase one of the side column. */
export function FoldCard({
  id,
  title,
  summary,
  actions,
  variant = "side",
  defaultOpen = true,
  className,
  elementId,
  ref,
  children,
}: {
  id: string;
  title: ReactNode;
  summary?: ReactNode;
  actions?: ReactNode;
  variant?: "main" | "side";
  defaultOpen?: boolean;
  className?: string;
  /** The section's id, for links and scrolling to it. */
  elementId?: string;
  ref?: Ref<HTMLElement>;
  children: ReactNode;
}) {
  const [open, setOpen] = useFold(id, defaultOpen);
  const titleId = useId();
  const bodyId = useId();
  return (
    <Card
      ref={ref}
      id={elementId}
      variant={variant}
      className={cx(styles.card, className)}
      aria-labelledby={titleId}
    >
      <div className={styles.head}>
        <FoldHeading
          id={titleId}
          variant={variant}
          open={open}
          controls={open ? bodyId : undefined}
          onToggle={() => setOpen(!open)}
        >
          {title}
        </FoldHeading>
        {!open && summary && <span className={styles.summary}>{summary}</span>}
        {actions && <span className={styles.actions}>{actions}</span>}
      </div>
      {open && (
        <div id={bodyId} className={styles.body}>
          {children}
        </div>
      )}
    </Card>
  );
}

/** The heading of a folding card: a button with a chevron, for cards that fold on their own. */
export function FoldHeading({
  id,
  variant = "side",
  open,
  controls,
  onToggle,
  children,
}: {
  id?: string;
  variant?: "main" | "side";
  open: boolean;
  controls?: string;
  onToggle: () => void;
  children: ReactNode;
}) {
  return (
    <h2 id={id} className={cx(styles.title, styles[variant])}>
      <button
        type="button"
        className={styles.toggle}
        aria-expanded={open}
        aria-controls={controls}
        onClick={onToggle}
      >
        <span className={styles.chevron} aria-hidden="true" />
        {children}
      </button>
    </h2>
  );
}
