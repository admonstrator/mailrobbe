import { type ReactNode, useId } from "react";

import { SparklesIcon } from "../../components/icons";
import { cx } from "../../lib/cx";
import styles from "./AiBox.module.css";

/** The light blue block of a summary (D352): "KI-Zusammenfassung erstellen" with the sparkles where
 *  an element has none yet, the whole block one button; after a failed try "erneut versuchen". */
export function SummarizeBox({
  failed = false,
  hint = "Zwei bis vier Sätze, vom Sprachmodell, kann irren",
  disabled,
  title,
  onClick,
}: {
  failed?: boolean;
  hint?: string;
  disabled?: boolean;
  title?: string;
  onClick: () => void;
}) {
  const label = failed ? "KI-Zusammenfassung erneut versuchen" : "KI-Zusammenfassung erstellen";
  const hintId = useId();
  return (
    <button
      type="button"
      className={cx(styles.box, styles.button)}
      aria-label={label}
      aria-describedby={hintId}
      disabled={disabled}
      title={title}
      onClick={onClick}
    >
      <Sparkles />
      <span className={styles.lines}>
        <span className={styles.heading}>{label}</span>
        <span id={hintId} className={cx(styles.hint, failed && styles.failed)}>
          {failed ? "Der letzte Versuch ist fehlgeschlagen." : hint}
        </span>
      </span>
    </button>
  );
}

/** The same block while the model works or once the summary is there (D352). */
export function AiBox({
  heading,
  note,
  busy = false,
  children,
}: {
  heading: string;
  note?: string;
  busy?: boolean;
  children: ReactNode;
}) {
  return (
    <div className={styles.box} role={busy ? "status" : undefined}>
      <Sparkles />
      <div className={styles.lines}>
        <span className={styles.heading}>
          {heading} {note && <span className={styles.note}>{note}</span>}
        </span>
        {children}
      </div>
    </div>
  );
}

/** A bar that moves while the model works (D345). */
export function AiBar() {
  return (
    <span className={styles.bar} aria-hidden="true">
      <span />
    </span>
  );
}

function Sparkles() {
  return (
    <span className={styles.icon}>
      <SparklesIcon size={20} strokeWidth={1.8} />
    </span>
  );
}
