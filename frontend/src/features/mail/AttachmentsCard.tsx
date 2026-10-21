import { Link } from "react-router";

import { attachmentContentUrl } from "../../api/client";
import type { AttachmentHit, AttachmentInfo } from "../../api/types";
import { Card, CardTitle } from "../../components/Card";
import { Highlighted, type SearchMarks } from "../../components/Highlighted";
import { cx } from "../../lib/cx";
import { formatBytes, formatNumber } from "../../lib/format";
import { KindIcon } from "../documents/KindIcon";
import { kindFromMimeType, pagesText, statusNote } from "../documents/labels";
import { documentPath } from "../documents/urlState";
import { PreviewPanel, PreviewToggle } from "../preview/AttachmentPanel";
import styles from "./AttachmentsCard.module.css";
import { attachmentElementId } from "./SearchHitsCard";

/** "auch in 5 weiteren Mails" when the document travels in others too, else "Zum Dokument". */
function documentLinkText(mails: number | null): string {
  const others = (mails ?? 1) - 1;
  if (others <= 0) return "Zum Dokument";
  return others === 1
    ? "auch in 1 weiteren Mail"
    : `auch in ${formatNumber(others)} weiteren Mails`;
}

/** Where an attachment holds a search word (D79): the text around it, or the name. */
function hitText(hit: AttachmentHit, marks: SearchMarks | undefined) {
  if (hit.snippet !== null) return <Highlighted text={`…${hit.snippet}…`} marks={marks} />;
  return hit.in_name ? "Suchwort im Dateinamen" : "Suchwort im Text, in einer anderen Wortform";
}

/** The attachments (D18, D75): metadata, the download read from the MBOX file (D76), and the
 *  document each one is, with the other mails that carry it; those holding a search word of
 *  the mail list's query marked, with the place (D79). */
export function AttachmentsCard({
  attachments,
  hits = [],
  marks,
}: {
  attachments: AttachmentInfo[];
  hits?: AttachmentHit[];
  marks?: SearchMarks;
}) {
  const hitById = new Map(hits.map((hit) => [hit.attachment_id, hit]));
  return (
    <Card className={styles.card}>
      <CardTitle>Anhänge ({formatNumber(attachments.length)})</CardTitle>
      <ul className={styles.list}>
        {attachments.map((attachment) => {
          const kind = attachment.kind ?? kindFromMimeType(attachment.mime_type);
          const note = statusNote(attachment.text_status);
          const name = attachment.filename || "(ohne Namen)";
          const hit = hitById.get(attachment.id);
          return (
            <li
              key={attachment.id}
              id={attachmentElementId(attachment.id)}
              className={cx(styles.item, hit && styles.hit)}
            >
              <KindIcon kind={kind} labelled />
              <span className={styles.text}>
                <span className={styles.name}>
                  <Highlighted text={name} marks={hit?.in_name ? marks : undefined} />
                </span>
                <span className={styles.meta}>
                  <span className={styles.mime} title={attachment.mime_type}>
                    {attachment.mime_type}
                  </span>
                  {attachment.pages !== null && ` · ${pagesText(attachment.pages)}`}
                  {` · ${formatBytes(attachment.size)} · `}
                  {attachment.sha256 ? (
                    <span title={attachment.sha256}>SHA-256 {attachment.sha256.slice(0, 4)}…</span>
                  ) : (
                    "nicht gehasht (über 50 MB)"
                  )}
                  {note && <span className={styles.status}>{note}</span>}
                </span>
                {hit && <span className={styles.hitText}>{hitText(hit, marks)}</span>}
                <span className={styles.links}>
                  <a
                    href={attachmentContentUrl(attachment.id)}
                    download
                    aria-label={`${name} herunterladen`}
                  >
                    Herunterladen
                  </a>
                  <PreviewToggle attachment={attachment} />
                  {attachment.document_id !== null && (
                    <Link
                      to={documentPath(attachment.document_id)}
                      title="Wer hat dieses Dokument wann an wen geschickt"
                    >
                      {documentLinkText(attachment.document_mails)}
                    </Link>
                  )}
                </span>
              </span>
              <PreviewPanel attachment={attachment} name={name} />
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
