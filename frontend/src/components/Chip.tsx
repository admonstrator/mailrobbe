import styles from "./Chip.module.css";

/** An active filter with a button that removes it; color adds a dot, e.g. a tag's colour. */
export function Chip({
  label,
  onRemove,
  color,
}: {
  label: string;
  onRemove: () => void;
  color?: string;
}) {
  return (
    <span className={styles.chip}>
      {color && <span className={styles.dot} style={{ background: color }} aria-hidden="true" />}
      {label}
      <button
        type="button"
        className={styles.remove}
        aria-label={`Filter entfernen: ${label}`}
        onClick={onRemove}
      >
        ×
      </button>
    </span>
  );
}
