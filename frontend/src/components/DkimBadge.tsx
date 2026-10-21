import type { DkimKey } from "../api/types";
import { cx } from "../lib/cx";
import { DKIM_STATUS_LABELS } from "../lib/dkim";
import styles from "./Dkim.module.css";
import { AlertIcon, CheckIcon, CrossIcon, MinusIcon } from "./icons";

const ICONS = {
  pass: CheckIcon,
  consistent: CheckIcon,
  fail: CrossIcon,
  no_key: AlertIcon,
  temp_error: AlertIcon,
  unsigned: MinusIcon,
  unchecked: MinusIcon,
} satisfies Record<DkimKey, unknown>;

/** The status pill of the detail view: "DKIM gültig", "DKIM ungültig", ... */
export function DkimBadge({ status }: { status: DkimKey }) {
  const Icon = ICONS[status];
  return (
    <span className={cx(styles.badge, styles[`badge_${status}`])}>
      <Icon size={14} strokeWidth={2.5} />
      {DKIM_STATUS_LABELS[status]}
    </span>
  );
}
