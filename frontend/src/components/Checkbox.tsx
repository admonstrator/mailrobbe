import type { ReactNode } from "react";

import { cx } from "../lib/cx";
import { formatNumber } from "../lib/format";
import styles from "./Checkbox.module.css";

/** A checkbox row of the filter column: box, label, and an optional counter on the right. A
 *  disabled box says why in its title. */
export function Checkbox({
  checked,
  onChange,
  count,
  disabled,
  title,
  children,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  count?: number;
  disabled?: boolean;
  title?: string;
  children: ReactNode;
}) {
  return (
    <label className={cx(styles.row, disabled && styles.disabled)} title={title}>
      <input
        type="checkbox"
        className={styles.box}
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className={styles.label}>{children}</span>
      {count !== undefined && <span className={styles.count}>{formatNumber(count)}</span>}
    </label>
  );
}
