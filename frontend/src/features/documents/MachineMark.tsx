import styles from "./MachineMark.module.css";

export const MACHINE_NOTE = "maschinell erkannt";
export const MACHINE_TITLE =
  "Der Text wurde maschinell aus den Seitenbildern erkannt (KI-Seite), nicht aus der Datei gelesen; er kann Lesefehler enthalten.";

/** The small mark of a text an AI run recognised (D189), wherever it shows: the document list,
 *  the hit lines of the mail list and the mail detail. */
export function MachineMark({ short = false }: { short?: boolean }) {
  return (
    <span className={styles.mark} title={MACHINE_TITLE}>
      {short ? "erkannt" : MACHINE_NOTE}
    </span>
  );
}
