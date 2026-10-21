import type { AttachmentInfo, MailHits } from "../../api/types";
import { Card } from "../../components/Card";
import styles from "./SearchHitsCard.module.css";

/** The element id of an attachment in AttachmentsCard, which a hit scrolls to. */
export function attachmentElementId(id: number): string {
  return `anhang-${id}`;
}

function scrollTo(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "center" });
}

/** Where the mail list's search words occur in this mail (D79): its own text, and which
 *  attachments, by their text or their file name. */
export function SearchHitsCard({
  hits,
  attachments,
  onShowText,
}: {
  hits: MailHits;
  attachments: AttachmentInfo[];
  onShowText: () => void;
}) {
  const names = new Map(attachments.map((a) => [a.id, a.filename || "(ohne Namen)"]));
  const words = hits.words.map((word) => `„${word}“`).join(", ");
  const places = [
    ...(hits.in_mail
      ? [
          <button key="mail" type="button" className={styles.place} onClick={onShowText}>
            im Text der Mail
          </button>,
        ]
      : []),
    ...hits.attachments.map((hit) => (
      <button
        key={hit.attachment_id}
        type="button"
        className={styles.place}
        onClick={() => scrollTo(attachmentElementId(hit.attachment_id))}
      >
        im Anhang {names.get(hit.attachment_id) ?? `#${hit.attachment_id}`}
        {hit.in_name && hit.snippet === null && " (Dateiname)"}
      </button>
    )),
  ];
  return (
    <Card variant="side" className={styles.card} aria-label="Suchtreffer">
      <p className={styles.line}>
        <span className={styles.label}>Suchtreffer{words && ` für ${words}`}:</span>{" "}
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
