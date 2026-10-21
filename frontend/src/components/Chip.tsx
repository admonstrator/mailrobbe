import styles from "./Chip.module.css";

/** An active filter with a button that removes it. */
export function Chip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className={styles.chip}>
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
