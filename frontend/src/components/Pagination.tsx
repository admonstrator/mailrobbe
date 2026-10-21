import type { ReactNode } from "react";
import { Link } from "react-router";

import { buttonClass } from "./Button";
import styles from "./Pagination.module.css";

/** Range text with Zurück/Weiter links (D19: no page numbers); null means there is no such page. */
export function Pagination({
  range,
  prev,
  next,
}: {
  range: ReactNode;
  prev: string | null;
  next: string | null;
}) {
  const step = (to: string | null, label: string) =>
    to === null ? (
      <span className={buttonClass("default", "sm")} aria-disabled="true">
        {label}
      </span>
    ) : (
      <Link to={to} className={buttonClass("default", "sm")}>
        {label}
      </Link>
    );
  return (
    <nav className={styles.pagination} aria-label="Seiten">
      <span>{range}</span>
      <div className={styles.steps}>
        {step(prev, "‹ Zurück")}
        {step(next, "Weiter ›")}
      </div>
    </nav>
  );
}
