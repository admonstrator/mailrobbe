import type { ReactNode } from "react";

import type { AttachmentHit, AttachmentInfo, MailHits } from "../../api/types";
import { Card } from "../../components/Card";
import { formatNumber } from "../../lib/format";
import { MachineMark } from "../documents/MachineMark";
import styles from "./SearchHitsCard.module.css";

/** The element id of an attachment in AttachmentsCard, which a hit scrolls to. */
export function attachmentElementId(id: number): string {
  return `anhang-${id}`;
}

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "center" });
}

/** " (3)": how often the words occur in a place (D176), when the backend counted them. */
const times = (count: number | undefined) => (count ? ` (${formatNumber(count)})` : "");

/** Where the mail list's search words occur in this mail (D79, D176): its subject, its own text,
 *  the text of which attachments and which file names, each place with how often the words occur
 *  there when they were counted. The text and the attachments are jumps to the place. */
export function SearchHitsCard({
  hits,
  attachments,
  onShowText,
}: {
  hits: MailHits;
  attachments: AttachmentInfo[];
  onShowText: () => void;
}) {
  // A container's documents are attachments of the mail too (D231), listed below it.
  const names = new Map(
    attachments
      .flatMap((a) => [a, ...(a.members ?? [])])
      .map((a) => [a.id, a.path || a.filename || "(ohne Namen)"]),
  );
  const words = hits.words.map((word) => `„${word}“`).join(", ");

  /** "im Anhang Protokoll.txt (2)", "in den Anhängen a.pdf, b.pdf (5)": each name a jump. */
  const attachmentPlace = (
    key: string,
    [one, many]: [string, string],
    found: AttachmentHit[],
    count: number | undefined,
  ) => (
    <span key={key}>
      {found.length === 1 ? one : many}{" "}
      {found.map((hit, index) => (
        <span key={hit.attachment_id}>
          {index > 0 && ", "}
          <button
            type="button"
            className={styles.place}
            onClick={() => scrollTo(attachmentElementId(hit.attachment_id))}
          >
            {names.get(hit.attachment_id) ?? `#${hit.attachment_id}`}
          </button>
          {key === "text" && hit.machine && (
            <>
              {" "}
              <MachineMark />
            </>
          )}
        </span>
      ))}
      {times(count)}
    </span>
  );

  const counts = hits.counts;
  const places: ReactNode[] = [];
  if (hits.in_subject) {
    places.push(<span key="subject">im Betreff{times(counts?.subject)}</span>);
  }
  // in_mail without in_subject: the mail's own text (a backend before D176 tells no more)
  if (hits.in_body || (hits.in_mail && !hits.in_subject)) {
    places.push(
      <button key="body" type="button" className={styles.place} onClick={onShowText}>
        im Text{times(counts?.body)}
      </button>,
    );
  }
  // An attachment is listed because its text or its name holds a word.
  const inText = hits.attachments.filter((hit) => hit.in_text || !hit.in_name);
  const inName = hits.attachments.filter((hit) => hit.in_name);
  if (inText.length > 0) {
    places.push(
      attachmentPlace("text", ["im Anhang", "in den Anhängen"], inText, counts?.attachment),
    );
  }
  if (inName.length > 0) {
    places.push(
      attachmentPlace("name", ["im Dateinamen", "in den Dateinamen"], inName, counts?.filename),
    );
  }

  return (
    <Card variant="side" className={styles.card} aria-label="Suchtreffer">
      <p className={styles.line}>
        <span className={styles.label}>
          Suchtreffer{words && ` für ${words}`}
          {hits.whole_word && (hits.words.length > 1 ? " als ganze Wörter" : " als ganzes Wort")}:
        </span>{" "}
        {places.length > 0 ? (
          places.map((place, index) => (
            <span key={index}>
              {index > 0 && <span className={styles.separator}> · </span>}
              {place}
            </span>
          ))
        ) : (
          <span className={styles.none}>Die Suchwörter kommen in dieser Mail nicht vor.</span>
        )}
      </p>
    </Card>
  );
}
