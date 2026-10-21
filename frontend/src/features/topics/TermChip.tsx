import { useId, useState, type ReactNode, type SyntheticEvent } from "react";
import { Link } from "react-router";

import type { ThemeInfo } from "../../api/types";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { TAG_PALETTE } from "../../lib/research";
import { themeText } from "./labels";
import styles from "./TermChip.module.css";

// The tip's widest box in pixels; a chip closer than this to the right edge opens it leftwards.
const TIP_WIDTH = 340;

/** A row of terms that wraps. */
export function TermList({ label, children }: { label: string; children: ReactNode }) {
  return (
    <ul className={styles.list} aria-label={label}>
      {children}
    </ul>
  );
}

/** A term as a link to its mails with their number, a dot in the colour of each research theme
 *  it belongs to (a marker, no rating), and its figures in a tip on hover or focus. */
export function TermChip({
  label,
  mails,
  href,
  figures,
  themes,
  muted = false,
}: {
  label: string;
  mails: number;
  href: string;
  /** What the tip says, e.g. "37 von 412 Mails (9 %) · im übrigen Archiv 0,4 % · 22-mal so
   *  häufig"; the themes are added. */
  figures: string;
  themes: ThemeInfo[];
  muted?: boolean;
}) {
  const tipId = useId();
  const [end, setEnd] = useState(false);
  const place = (event: SyntheticEvent<HTMLElement>) =>
    setEnd(event.currentTarget.getBoundingClientRect().left > window.innerWidth - TIP_WIDTH);
  return (
    <li
      className={cx(styles.term, muted && styles.muted, end && styles.end)}
      onPointerEnter={place}
      onFocus={place}
    >
      <Link to={href} className={styles.link} aria-describedby={tipId}>
        {themes.map((theme) => (
          <span
            key={theme.key}
            className={styles.dot}
            style={{ background: TAG_PALETTE[theme.color].text }}
            aria-hidden="true"
          />
        ))}
        <span className={styles.label}>{label}</span>{" "}
        <span className={styles.count}>{formatNumber(mails)}</span>
      </Link>
      <span id={tipId} role="tooltip" className={styles.tip}>
        {figures}
        {themeText(themes)}
      </span>
    </li>
  );
}
