import type { DocumentProtection } from "../../api/types";
import { cx } from "../../lib/cx";
import { CONTAINED_NOTE, CONTAINED_TITLE, PROTECTION_TITLES } from "./labels";
import styles from "./ProtectionMark.module.css";

/** The lock of a protected document (D233): closed while the password is unknown, open once one
 *  was found. An image named by what it means, the same words on hover; decorative where a label
 *  beside it says it. */
export function ProtectionMark({
  protection,
  size = 14,
  decorative = false,
}: {
  protection: DocumentProtection;
  size?: number;
  decorative?: boolean;
}) {
  const title = PROTECTION_TITLES[protection];
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cx(styles.lock, styles[protection])}
      {...(decorative ? { "aria-hidden": true } : { role: "img", "aria-label": title })}
    >
      {!decorative && <title>{title}</title>}
      <rect x="5" y="11" width="14" height="10" rx="2" />
      <path d={protection === "locked" ? "M8 11V7a4 4 0 0 1 8 0v4" : "M8 11V7a4 4 0 0 1 7.7-1.5"} />
    </svg>
  );
}

/** The small mark of a document found inside a container (D231). */
export function ContainedMark() {
  return (
    <span className={styles.contained} title={CONTAINED_TITLE}>
      {CONTAINED_NOTE}
    </span>
  );
}
