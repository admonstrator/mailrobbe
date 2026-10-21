import { useId, useState } from "react";
import { Link } from "react-router";

import { attachmentContentUrl } from "../../api/client";
import type { AttachmentHit, AttachmentInfo, DocumentKind, MetadataSummary } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { Highlighted, type SearchMarks } from "../../components/Highlighted";
import { cx } from "../../lib/cx";
import { formatBytes, formatDate, formatNumber } from "../../lib/format";
import { KindIcon } from "../documents/KindIcon";
import { kindFromMimeType, pagesText, statusNote } from "../documents/labels";
import { documentPath } from "../documents/urlState";
import { PreviewOverlay } from "../preview/PreviewOverlay";
import styles from "./AttachmentsCard.module.css";
import { attachmentElementId } from "./SearchHitsCard";

/** Attachments listed before "alle n anzeigen"; those holding a search word are always listed. */
export const ATTACHMENTS_SHOWN = 8;

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

/** What the file says about itself, in one line (D167): "Autor Peter Hofmann · Microsoft Word ·
 *  08.10.2026", "Kamera Canon EOS 80D · mit Ortsangabe"; fields it lacks left out. */
export function metadataLine(metadata: MetadataSummary, kind: DocumentKind | null): string | null {
  const parts = [
    metadata.author && `Autor ${metadata.author}`,
    metadata.modified_by && `geändert von ${metadata.modified_by}`,
    metadata.device && `${kind === "image" ? "Kamera" : "Gerät"} ${metadata.device}`,
    metadata.software,
    metadata.created && formatDate(metadata.created),
    metadata.gps && "mit Ortsangabe",
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

/** The attachments in the side column (D18, D75, D166): metadata, the download read from the
 *  MBOX file (D76), the preview over the page (D120, D165), and the document each one is, with
 *  the other mails that carry it; those holding a search word of the mail list's query marked,
 *  with the place (D79). A long list shows its first ATTACHMENTS_SHOWN. */
export function AttachmentsCard({
  attachments,
  hits = [],
  marks,
}: {
  attachments: AttachmentInfo[];
  hits?: AttachmentHit[];
  marks?: SearchMarks;
}) {
  const titleId = useId();
  const [all, setAll] = useState(false);
  // One preview at a time, over the page.
  const [open, setOpen] = useState<AttachmentInfo | null>(null);
  const hitById = new Map(hits.map((hit) => [hit.attachment_id, hit]));
  const shown = all
    ? attachments
    : attachments.filter(
        (attachment, index) => index < ATTACHMENTS_SHOWN || hitById.has(attachment.id),
      );

  return (
    <Card variant="side" aria-labelledby={titleId}>
      <CardTitle variant="caps" id={titleId}>
        Anhänge ({formatNumber(attachments.length)})
      </CardTitle>
      <ul className={styles.list}>
        {shown.map((attachment) => {
          const kind = attachment.kind ?? kindFromMimeType(attachment.mime_type);
          const note = statusNote(attachment.text_status);
          const name = attachment.filename || "(ohne Namen)";
          const hit = hitById.get(attachment.id);
          const described = attachment.metadata && metadataLine(attachment.metadata, kind);
          return (
            <li
              key={attachment.id}
              id={attachmentElementId(attachment.id)}
              className={cx(styles.item, hit && styles.hit)}
            >
              <KindIcon kind={kind} labelled />
              <span className={styles.text}>
                <span className={styles.name} title={name}>
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
                {described && (
                  <span className={styles.described} title="Was die Datei über sich sagt">
                    {described}
                  </span>
                )}
                {hit && <span className={styles.hitText}>{hitText(hit, marks)}</span>}
                <span className={styles.links}>
                  <a
                    href={attachmentContentUrl(attachment.id)}
                    download
                    aria-label={`${name} herunterladen`}
                  >
                    Herunterladen
                  </a>
                  {attachment.preview ? (
                    <button
                      type="button"
                      className={styles.open}
                      aria-haspopup="dialog"
                      onClick={() => setOpen(attachment)}
                    >
                      Vorschau
                    </button>
                  ) : (
                    <span className={styles.downloadOnly}>nur Download</span>
                  )}
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
            </li>
          );
        })}
      </ul>
      {shown.length < attachments.length && (
        <Button variant="link" size="xs" className={styles.more} onClick={() => setAll(true)}>
          {`alle ${formatNumber(attachments.length)} anzeigen`}
        </Button>
      )}
      {open?.preview && (
        <PreviewOverlay
          attachmentId={open.id}
          kind={open.preview}
          name={open.filename || "(ohne Namen)"}
          onClose={() => setOpen(null)}
        />
      )}
    </Card>
  );
}
