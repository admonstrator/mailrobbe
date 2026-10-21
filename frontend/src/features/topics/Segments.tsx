import { useId } from "react";

import { cx } from "../../lib/cx";
import styles from "./Segments.module.css";

/** One choice of several as a row of buttons, the pressed one highlighted, as the timeline's
 *  controls look. */
export function Segments<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: [T, string][];
  value: T;
  onChange: (value: T) => void;
}) {
  const labelId = useId();
  return (
    <div className={styles.control}>
      <span id={labelId} className={styles.label}>
        {label}
      </span>
      <div role="group" aria-labelledby={labelId} className={styles.segments}>
        {options.map(([key, text]) => (
          <button
            key={key}
            type="button"
            aria-pressed={key === value}
            className={cx(styles.segment, key === value && styles.active)}
            onClick={() => key !== value && onChange(key)}
          >
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}
