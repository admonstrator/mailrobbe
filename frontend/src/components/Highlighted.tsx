import { highlightParts, type TextPart } from "../lib/highlight";
import styles from "./Highlighted.module.css";

/** The search words of a mail list's query (D79): typed words and phrases, and German stems; with
 *  whole_word the words only where they stand as whole words, no stems (D173). */
export interface SearchMarks {
  words: string[];
  stems: string[];
  whole_word?: boolean;
}

/** text cut into parts, the search words of marks marked as the search found them. */
export function markWords(text: string, marks: SearchMarks | undefined): TextPart[] {
  return highlightParts(text, marks?.words ?? [], marks?.stems ?? [], {
    wholeWord: marks?.whole_word,
  });
}

/** Text parts with the marked ones in <mark>. */
export function MarkedParts({ parts }: { parts: TextPart[] }) {
  return parts.map((part, index) =>
    part.mark ? (
      <mark key={index} className={styles.mark}>
        {part.text}
      </mark>
    ) : (
      part.text
    ),
  );
}

/** text with the search words marked; as it is without marks. */
export function Highlighted({ text, marks }: { text: string; marks: SearchMarks | undefined }) {
  if (!marks) return text;
  return <MarkedParts parts={markWords(text, marks)} />;
}
