import styles from "./MachineMark.module.css";

export const MACHINE_NOTE = "maschinell erkannt";
export const MACHINE_TITLE =
  "Der Text wurde maschinell aus den Seitenbildern erkannt (KI-Seite), nicht aus der Datei gelesen; er kann Lesefehler enthalten.";
export const TRANSCRIPT_NOTE = "maschinell transkribiert";
export const TRANSCRIPT_TITLE =
  "Der Text wurde maschinell aus dem Ton der Aufnahme transkribiert (KI-Seite), nicht aus der Datei gelesen; er kann Hörfehler enthalten.";

/** The small mark of a text an AI run made (D189, D296), wherever it shows: the document list,
 *  the hit lines of the mail list and the mail detail, the document page. A transcript says
 *  that it was heard from the sound, a recognised text that it was read from page images. */
export function MachineMark({
  short = false,
  transcript = false,
}: {
  short?: boolean;
  transcript?: boolean;
}) {
  if (transcript) {
    return (
      <span className={styles.mark} title={TRANSCRIPT_TITLE}>
        {short ? "transkribiert" : TRANSCRIPT_NOTE}
      </span>
    );
  }
  return (
    <span className={styles.mark} title={MACHINE_TITLE}>
      {short ? "erkannt" : MACHINE_NOTE}
    </span>
  );
}
