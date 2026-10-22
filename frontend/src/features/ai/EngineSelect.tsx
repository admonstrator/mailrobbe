import type { OcrEngineChoice } from "../../api/types";
import { ENGINE_HINTS, ENGINE_LABELS } from "./labels";
import styles from "./EngineSelect.module.css";

/** The engine choices at hand: without a usable vision model, Tesseract only (D182). */
export function engineChoices(vision: boolean): OcrEngineChoice[] {
  return vision ? ["auto", "tesseract", "vision"] : ["tesseract"];
}

/** The engine of a selection or a run, with what the chosen one does below it. */
export function EngineSelect({
  id,
  value,
  vision,
  onChange,
  label = "Verfahren",
}: {
  id: string;
  value: OcrEngineChoice;
  /** A vision model is configured and allowed. */
  vision: boolean;
  onChange: (engine: OcrEngineChoice) => void;
  label?: string;
}) {
  const choices = engineChoices(vision);
  const shown = choices.includes(value) ? value : choices[0];
  return (
    <div className={styles.field}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      <select
        id={id}
        className={styles.select}
        value={shown}
        onChange={(event) => onChange(event.target.value as OcrEngineChoice)}
      >
        {choices.map((choice) => (
          <option key={choice} value={choice}>
            {ENGINE_LABELS[choice]}
          </option>
        ))}
      </select>
      <span className={styles.hint}>{ENGINE_HINTS[shown]}</span>
    </div>
  );
}
