import { highlightParts, type TextPart } from "../lib/highlight";
import styles from "./Highlighted.module.css";

/** The search words of a mail list's query (D79): typed words and phrases, and German stems. */
export interface SearchMarks {
  words: string[];
  stems: string[];
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
  return <MarkedParts parts={highlightParts(text, marks.words, marks.stems)} />;
}
