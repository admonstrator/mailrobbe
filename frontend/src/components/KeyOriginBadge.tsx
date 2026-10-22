import type { KeyOrigin } from "../api/types";
import { cx } from "../lib/cx";
import { KEY_ORIGIN_LABELS, KEY_ORIGIN_TEXTS } from "../lib/dkim";
import styles from "./KeyOriginBadge.module.css";

/** Where the key a signature rests on comes from (D100): "DNS", "im DNS beobachtet",
 *  "dokumentiert", "rekonstruiert"; the tooltip says what that shows. */
export function KeyOriginBadge({ origin }: { origin: KeyOrigin }) {
  return (
    <span className={cx(styles.badge, styles[origin])} title={KEY_ORIGIN_TEXTS[origin]}>
      {KEY_ORIGIN_LABELS[origin]}
    </span>
  );
}
