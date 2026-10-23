import type { ReactNode } from "react";

import { HelpIcon } from "./icons";
import { cx } from "../lib/cx";
import styles from "./PageHead.module.css";

/** The head of a system page (D334): the title with an optional state badge, at most one muted
 *  line below it, the actions at the right (one primary, two or three others, the menu "…"). */
export function PageHead({
  title,
  badge,
  sub,
  help,
  actions,
  titleId,
}: {
  title: ReactNode;
  badge?: ReactNode;
  sub?: ReactNode;
  /** An explanation behind a "?" with a tooltip. */
  help?: string;
  actions?: ReactNode;
  titleId?: string;
}) {
  return (
    <div className={styles.head}>
      <div className={styles.text}>
        <div className={styles.titleRow}>
          <h1 id={titleId} className={styles.title}>
            {title}
          </h1>
          {badge}
          {help && <HelpTip text={help} />}
        </div>
        {sub && <div className={styles.sub}>{sub}</div>}
      </div>
      {actions && <div className={styles.actions}>{actions}</div>}
    </div>
  );
}

export type BadgeTone = "accent" | "warning" | "done" | "error" | "quiet";

/** A small rounded state beside a title: "Läuft · Schritt 7 von 15". */
export function StateBadge({ tone, children }: { tone: BadgeTone; children: ReactNode }) {
  return <span className={cx(styles.badge, styles[tone])}>{children}</span>;
}

/** A "?" whose tooltip holds an explanation that used to stand on the page (D334). */
export function HelpTip({ text }: { text: string }) {
  return (
    <span className={styles.help} title={text} aria-label={text} role="img" tabIndex={0}>
      <HelpIcon size={16} />
    </span>
  );
}

export interface Figure {
  label: ReactNode;
  value: ReactNode;
  /** A tooltip with the details. */
  title?: string;
  /** A warning colour, as for errors. */
  warn?: boolean;
  /** A second muted line, a link or a share. */
  sub?: ReactNode;
}

/** Figures as a row of numbers (D334), not tiles. */
export function Figures({ items, label }: { items: Figure[]; label: string }) {
  return (
    <ul className={styles.figures} aria-label={label}>
      {items.map((item, index) => (
        <li key={index} className={styles.figure} title={item.title}>
          <span className={cx(styles.value, item.warn && styles.warn)}>{item.value}</span>{" "}
          <span className={styles.label}>{item.label}</span>
          {item.sub && <span className={styles.figureSub}>{item.sub}</span>}
        </li>
      ))}
    </ul>
  );
}
