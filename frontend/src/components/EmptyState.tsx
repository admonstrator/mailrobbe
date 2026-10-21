import type { ReactNode } from "react";

import styles from "./States.module.css";

/** Nothing to show: a title, an optional explanation and actions such as a reset link. */
export function EmptyState({
  title,
  children,
  actions,
}: {
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className={styles.state}>
      <p className={styles.title}>{title}</p>
      {children && <p className={styles.text}>{children}</p>}
      {actions && <div className={styles.actions}>{actions}</div>}
    </div>
  );
}
