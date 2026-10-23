import type { ReactNode } from "react";
import { Link } from "react-router";

import { cx } from "../lib/cx";
import styles from "./FigureRow.module.css";

export interface Figure {
  label: string;
  value: ReactNode;
  /** The figure's explanation, as a tooltip. */
  title?: string;
  /** Where the figure leads, e.g. the mail list of what it counts. */
  href?: string;
}

/** The figures of a view as one row of numbers (D334): the value large, its label quiet below,
 *  instead of tiles. */
export function FigureRow({
  figures,
  label = "Kennzahlen",
  className,
}: {
  figures: Figure[];
  label?: string;
  className?: string;
}) {
  return (
    <ul className={cx(styles.figures, className)} aria-label={label}>
      {figures.map((figure) => (
        <li key={figure.label} className={styles.figure} title={figure.title}>
          {figure.href ? (
            <Link to={figure.href} className={cx(styles.value, styles.link)}>
              {figure.value}
            </Link>
          ) : (
            <span className={styles.value}>{figure.value}</span>
          )}
          <span className={styles.label}>{figure.label}</span>
        </li>
      ))}
    </ul>
  );
}
