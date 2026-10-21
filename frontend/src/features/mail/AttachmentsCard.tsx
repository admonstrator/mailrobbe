import { Link } from "react-router";

import { attachmentContentUrl } from "../../api/client";
import type { AttachmentInfo } from "../../api/types";
import { Card, CardTitle } from "../../components/Card";
import { formatBytes, formatNumber } from "../../lib/format";
import { KindIcon } from "../documents/KindIcon";
import { kindFromMimeType, pagesText, statusNote } from "../documents/labels";
import { documentPath } from "../documents/urlState";
import { PreviewPanel, PreviewToggle } from "../preview/AttachmentPanel";
import styles from "./AttachmentsCard.module.css";

/** "auch in 5 weiteren Mails" when the document travels in others too, else "Zum Dokument". */
function documentLinkText(mails: number | null): string {
  const others = (mails ?? 1) - 1;
  if (others <= 0) return "Zum Dokument";
  return others === 1
    ? "auch in 1 weiteren Mail"
    : `auch in ${formatNumber(others)} weiteren Mails`;
}

/** The attachments (D18, D75): metadata, the download read from the MBOX file (D76), and the
 *  document each one is, with the other mails that carry it. */
export function AttachmentsCard({ attachments }: { attachments: AttachmentInfo[] }) {
  return (
    <Card className={styles.card}>
      <CardTitle>Anhänge ({formatNumber(attachments.length)})</CardTitle>
      <ul className={styles.list}>
        {attachments.map((attachment) => {
          const kind = attachment.kind ?? kindFromMimeType(attachment.mime_type);
          const note = statusNote(attachment.text_status);
          const name = attachment.filename || "(ohne Namen)";
          return (
            <li key={attachment.id} className={styles.item}>
              <KindIcon kind={kind} labelled />
              <span className={styles.text}>
                <span className={styles.name}>{name}</span>
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
