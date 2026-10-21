import type { ReactNode } from "react";

import { cx } from "../lib/cx";
import styles from "./States.module.css";

/** Something went wrong: a German title, details, and a way out (retry, reset, back). */
export function ErrorState({
  title,
  children,
  actions,
}: {
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className={cx(styles.state, styles.error)} role="alert">
      <p className={styles.title}>{title}</p>
      {children && <p className={styles.text}>{children}</p>}
      {actions && <div className={styles.actions}>{actions}</div>}
    </div>
  );
}
