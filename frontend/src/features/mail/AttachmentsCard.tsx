import type { AttachmentInfo } from "../../api/types";
import { Card, CardTitle } from "../../components/Card";
import { FileIcon } from "../../components/icons";
import { formatBytes, formatNumber } from "../../lib/format";
import styles from "./AttachmentsCard.module.css";

/** Icon colour by MIME type. */
function kind(mimeType: string): string {
  const type = mimeType.toLowerCase();
  if (type === "application/pdf") return styles.pdf;
  if (/spreadsheet|excel|csv/.test(type)) return styles.sheet;
  if (/^image\/|word|document|^text\//.test(type)) return styles.document;
  if (/zip|compressed|tar|rar|7z/.test(type)) return styles.archive;
  return styles.other;
}

/** Metadata of the attachments (D18); the files themselves stay in the MBOX. */
export function AttachmentsCard({ attachments }: { attachments: AttachmentInfo[] }) {
  return (
    <Card className={styles.card}>
      <CardTitle>Anhänge ({formatNumber(attachments.length)})</CardTitle>
      <ul className={styles.list}>
        {attachments.map((attachment) => (
          <li key={attachment.id} className={styles.item}>
            <FileIcon size={20} className={kind(attachment.mime_type)} />
            <span className={styles.text}>
              <span className={styles.name}>{attachment.filename || "(ohne Namen)"}</span>
              <span className={styles.meta}>
                {attachment.mime_type} · {formatBytes(attachment.size)} ·{" "}
                {attachment.sha256 ? (
                  <span title={attachment.sha256}>SHA-256 {attachment.sha256.slice(0, 4)}…</span>
                ) : (
                  "nicht gehasht (über 50 MB)"
                )}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
