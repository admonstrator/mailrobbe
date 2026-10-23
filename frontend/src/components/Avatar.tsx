import { cx } from "../lib/cx";
import styles from "./Avatar.module.css";

// Dark enough for white initials; a person keeps their colour everywhere (by id).
const PALETTE = [
  "#1d5bd6",
  "#0f766e",
  "#b45309",
  "#7c3aed",
  "#be185d",
  "#15803d",
  "#0369a1",
  "#475569",
];

/** "Anna Keller" -> "AK", "Dr. Miriam Steiner" -> "MS"; the address when there is no name. */
function initials(name: string | null, email: string): string {
  const words = (name ?? "")
    .split(/\s+/)
    .filter((word) => !word.endsWith(".") && /\p{L}/u.test(word));
  const firstTwo = (text: string) => [...text].slice(0, 2).join("").toUpperCase();
  if (words.length >= 2) {
    return firstTwo(firstLetter(words[0]) + firstLetter(words[words.length - 1]));
  }
  if (words.length === 1) {
    return firstTwo(words[0].replace(/[^\p{L}]/gu, ""));
  }
  return firstTwo(email.replace(/[^\p{L}\p{N}]/gu, ""));
}

function firstLetter(word: string): string {
  return word.match(/\p{L}/u)?.[0] ?? "";
}

/** The initials on the person's colour: "sm" in dense rows, "lg" in a short profile, "xl" the
 *  profile page's large picture (D336). */
export function Avatar({
  personId,
  name,
  email,
  size = "md",
}: {
  personId: number;
  name: string | null;
  email: string;
  size?: "sm" | "md" | "lg" | "xl";
}) {
  return (
    <span
      className={cx(styles.avatar, size !== "md" && styles[size])}
      style={{ background: PALETTE[personId % PALETTE.length] }}
      aria-hidden="true"
    >
      {initials(name, email)}
    </span>
  );
}
