import { useEffect, useRef } from "react";

import styles from "./FilterColumn.module.css";

// The parts that the filter columns of other pages share with the mail list's filter bar.

function isDay(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(value));
}

/** A date input that changes the filter only for complete days: while the year is being typed
 *  the browser reports days such as 0002-01-01, which lie outside the archive's range and wait
 *  for the field to lose focus. */
export function DateField({
  id,
  label,
  value,
  min,
  max,
  onCommit,
}: {
  id: string;
  label: string;
  value: string | null;
  min: string | undefined;
  max: string | undefined;
  onCommit: (day: string | null) => void;
}) {
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (input.current && document.activeElement !== input.current) {
      input.current.value = value ?? "";
    }
  }, [value]);

  const inRange = (day: string) => (!min || day >= min) && (!max || day <= max);

  return (
    <div className={styles.dateField}>
      <label htmlFor={id} className={styles.dateLabel}>
        {label}
      </label>
      <input
        ref={input}
        id={id}
        type="date"
        className={styles.input}
        defaultValue={value ?? ""}
        min={min}
        max={max}
        onChange={(event) => {
          const day = event.target.value;
          if (day === (value ?? "")) return;
          if (day === "") onCommit(null);
          else if (isDay(day) && inRange(day)) onCommit(day);
        }}
        onBlur={(event) => {
          const day = event.target.value;
          if (day === (value ?? "")) return;
          if (day === "") onCommit(null);
          else if (isDay(day)) onCommit(day);
          else event.target.value = value ?? "";
        }}
      />
    </div>
  );
}
