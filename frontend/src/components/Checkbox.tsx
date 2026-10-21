import type { ReactNode } from "react";

import { formatNumber } from "../lib/format";
import styles from "./Checkbox.module.css";

/** A checkbox row of the filter column: box, label, and an optional counter on the right. */
export function Checkbox({
  checked,
  onChange,
  count,
  children,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  count?: number;
  children: ReactNode;
}) {
  return (
    <label className={styles.row}>
      <input
        type="checkbox"
        className={styles.box}
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className={styles.label}>{children}</span>
      {count !== undefined && <span className={styles.count}>{formatNumber(count)}</span>}
    </label>
  );
}
