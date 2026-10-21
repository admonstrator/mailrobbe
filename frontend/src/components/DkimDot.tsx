import type { DkimKey } from "../api/types";
import { cx } from "../lib/cx";
import { DKIM_STATUS_LABELS } from "../lib/dkim";
import styles from "./Dkim.module.css";

/** The DKIM traffic light: a coloured dot with the German label as tooltip and for screen
 *  readers; decorative when it sits next to that label anyway. */
export function DkimDot({
  status,
  size = 10,
  decorative = false,
}: {
  status: DkimKey;
  size?: number;
  decorative?: boolean;
}) {
  const label = DKIM_STATUS_LABELS[status];
  return (
    <span
      className={cx(styles.dot, styles[status])}
      style={{ width: size, height: size }}
      {...(decorative
        ? { "aria-hidden": true }
        : { role: "img", "aria-label": label, title: label })}
    />
  );
}
