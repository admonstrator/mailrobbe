import styles from "./States.module.css";

/** A small busy indicator; label is read out instead of the animation. */
export function Spinner({ label = "Wird geladen" }: { label?: string }) {
  return <span className={styles.spinner} role="status" aria-label={label} />;
}
