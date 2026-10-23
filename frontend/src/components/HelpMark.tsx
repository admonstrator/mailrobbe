import { cx } from "../lib/cx";
import styles from "./HelpMark.module.css";

/** A small "?" beside a heading whose tooltip explains it (D334): explanations stand behind it
 *  instead of on the page. Focusable, so the keyboard reaches the text too. */
export function HelpMark({ text, className }: { text: string; className?: string }) {
  return (
    <span
      className={cx(styles.mark, className)}
      title={text}
      aria-label={text}
      role="img"
      tabIndex={0}
    >
      ?
    </span>
  );
}
