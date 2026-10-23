import type { ReactNode } from "react";
import { Link } from "react-router";

import { PageBackIcon, PageOnIcon } from "../../components/icons";
import type { PaginationProps } from "../../components/Pagination";
import { cx } from "../../lib/cx";
import styles from "./CompactPager.module.css";

/** The pager in a list's toolbar (D335): "1–50 von 686" and the two steps of the full
 *  Pagination at the list's foot (D193), which keeps the page jump. */
export function CompactPager({ paging }: { paging: PaginationProps }) {
  return (
    <nav className={styles.pager} aria-label="Seite">
      <span className={styles.range}>{paging.range}</span>
      <Step to={paging.prev} label="Vorige Seite">
        <PageBackIcon size={18} />
      </Step>
      <Step to={paging.next} label="Nächste Seite">
        <PageOnIcon size={18} />
      </Step>
    </nav>
  );
}

/** A step of the pager: a link, or a quiet disabled one where there is no page. */
function Step({ to, label, children }: { to: string | null; label: string; children: ReactNode }) {
  return to === null ? (
    <span className={cx(styles.step, styles.disabled)} aria-disabled="true" aria-label={label}>
      {children}
    </span>
  ) : (
    <Link to={to} className={styles.step} aria-label={label} title={label}>
      {children}
    </Link>
  );
}
