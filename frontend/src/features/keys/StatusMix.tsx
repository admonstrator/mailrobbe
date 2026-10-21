import type { DkimStatus } from "../../api/types";
import { DkimDot } from "../../components/DkimDot";
import { DKIM_KEYS, DKIM_STATUS_LABELS } from "../../lib/dkim";
import { formatNumber } from "../../lib/format";
import styles from "./StatusMix.module.css";

/** A key name's signatures by status, in the order of the list's filter; with labels the
 *  status's name stands beside its dot. */
export function StatusMix({
  statuses,
  labels = false,
}: {
  statuses: Partial<Record<DkimStatus, number>>;
  labels?: boolean;
}) {
  const shown = DKIM_KEYS.filter(
    (key): key is DkimStatus => key !== "unchecked" && (statuses[key] ?? 0) > 0,
  );
  return (
    <span className={styles.mix}>
      {shown.map((status) => (
        <span key={status} className={styles.part}>
          <DkimDot status={status} decorative={labels} />
          {labels && <span className={styles.label}>{DKIM_STATUS_LABELS[status]}</span>}
          <span className={styles.count}>{formatNumber(statuses[status] ?? 0)}</span>
        </span>
      ))}
    </span>
  );
}
