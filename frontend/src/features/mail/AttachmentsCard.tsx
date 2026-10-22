import { useState } from "react";
import { Link } from "react-router";

import { attachmentContentUrl } from "../../api/client";
import type { AttachmentHit, AttachmentInfo, DocumentKind, MetadataSummary } from "../../api/types";
import { Button } from "../../components/Button";
import { FoldCard } from "../../components/FoldCard";
import { Highlighted, type SearchMarks } from "../../components/Highlighted";
import { cx } from "../../lib/cx";
import { formatBytes, formatDate, formatNumber } from "../../lib/format";
import { KindIcon } from "../documents/KindIcon";
import {
  KIND_LABELS,
  kindFromMimeType,
  membersStatusNote,
  pagesText,
  PROTECTION_NOTES,
  PROTECTION_TITLES,
  statusNote,
} from "../documents/labels";
import { ProtectionMark } from "../documents/ProtectionMark";
import { documentPath } from "../documents/urlState";
import { photoPosition, PhotoPosition } from "../places/PhotoPosition";
import { PreviewOverlay } from "../preview/PreviewOverlay";
import styles from "./AttachmentsCard.module.css";
import { attachmentElementId } from "./SearchHitsCard";

/** Attachments listed before "alle n anzeigen"; those holding a search word are always listed. */
export const ATTACHMENTS_SHOWN = 8;
/** The same for the documents of a container below it. */
export const MEMBERS_SHOWN = 5;

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
  return hit.in_name && !hit.in_text
    ? "Suchwort im Dateinamen"
    : "Suchwort im Text, in einer anderen Wortform";
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

/** Whether an attachment or one of its members holds a search word. */
function holdsHit(attachment: AttachmentInfo, hitById: Map<number, AttachmentHit>): boolean {
  return hitById.has(attachment.id) || (attachment.members ?? []).some(({ id }) => hitById.has(id));
}

/** The id of the attachment list, which the header's count scrolls to, and its fold. */
export const ATTACHMENTS_CARD_ID = "mail-attachments";
export const ATTACHMENTS_FOLD = "mail.attachments";

/** Folded: the total size and the first names. */
function foldedSummary(attachments: AttachmentInfo[]): string {
  const size = attachments.reduce((sum, attachment) => sum + attachment.size, 0);
  const names = attachments.map((attachment) => attachment.filename || "(ohne Namen)");
  return [formatBytes(size), names.join(", ")].join(" · ");
}

/** The attachments below the mail's text, one row each as a mail program lists them (D18, D75,
 *  D166): kind, name, pages and size, the metadata line of D167, preview over the page (D120,
 *  D165), the download read from the MBOX file (D76) and the document each one is, with the other
 *  mails that carry it; those holding a search word of the mail list's query marked, with the
 *  place (D79). A long list shows its first ATTACHMENTS_SHOWN. Each says whether it needs a
 *  password or was opened with one (D233); a container lists the documents it holds below it
 *  (D231). A photo with a position shows it on a small map (D249), one photo at a time: the
 *  first, or the one chosen. The list folds like every block of the page. */
export function AttachmentsCard({
  attachments,
  hits = [],
  marks,
}: {
  attachments: AttachmentInfo[];
  hits?: AttachmentHit[];
  marks?: SearchMarks;
}) {
  const [all, setAll] = useState(false);
  // One preview at a time, over the page.
  const [open, setOpen] = useState<AttachmentInfo | null>(null);
  const [chosen, setChosen] = useState<number | null>(null);
  const hitById = new Map(hits.map((hit) => [hit.attachment_id, hit]));
  const shown = all
    ? attachments
    : attachments.filter(
        (attachment, index) => index < ATTACHMENTS_SHOWN || holdsHit(attachment, hitById),
      );
  const positioned = shown.filter((attachment) => photoPosition(attachment.metadata));
  const mapped = positioned.find((attachment) => attachment.id === chosen) ?? positioned[0];

  return (
    <FoldCard
      id={ATTACHMENTS_FOLD}
      elementId={ATTACHMENTS_CARD_ID}
      variant="main"
      className={styles.card}
      title={`Anhänge (${formatNumber(attachments.length)})`}
      summary={foldedSummary(attachments)}
    >
      <ul className={styles.list}>
        {shown.map((attachment) => {
          const kind = attachment.kind ?? kindFromMimeType(attachment.mime_type);
          const name = attachment.filename || "(ohne Namen)";
          const hit = hitById.get(attachment.id);
          const described = attachment.metadata && metadataLine(attachment.metadata, kind);
          const preview = attachment.protection !== "locked" && attachment.preview;
          const position = photoPosition(attachment.metadata);
          return (
            <li
              key={attachment.id}
              id={attachmentElementId(attachment.id)}
              className={cx(styles.item, hit && styles.hit)}
            >
              <KindIcon kind={kind} labelled />
              <div className={styles.text}>
                <span className={styles.name} title={name}>
                  <Highlighted text={name} marks={hit?.in_name ? marks : undefined} />
                </span>
                <span className={styles.meta}>
                  <span title={attachment.mime_type}>{KIND_LABELS[kind]}</span>
                  {attachment.pages !== null && ` · ${pagesText(attachment.pages)}`}
                  {` · ${formatBytes(attachment.size)} · `}
                  {attachment.sha256 ? (
                    <span title={attachment.sha256}>SHA-256 {attachment.sha256.slice(0, 4)}…</span>
                  ) : (
                    "nicht gehasht (über 50 MB)"
                  )}
                  <Notes attachment={attachment} />
                </span>
                {described && (
                  <span className={styles.described} title="Was die Datei über sich sagt">
                    {described}
                  </span>
                )}
                {hit && <span className={styles.hitText}>{hitText(hit, marks)}</span>}
                {position && attachment === mapped && (
                  <span className={styles.position}>
                    <PhotoPosition documentId={attachment.document_id} position={position} />
                  </span>
                )}
                <Members
                  container={attachment}
                  kind={kind}
                  name={name}
                  hitById={hitById}
                  marks={marks}
                />
              </div>
              <span className={styles.links}>
                <a
                  href={attachmentContentUrl(attachment.id)}
                  download
                  aria-label={`${name} herunterladen`}
                >
                  Herunterladen
                </a>
                {preview ? (
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
                {position && attachment !== mapped && (
                  <button
                    type="button"
                    className={styles.open}
                    aria-label={`Aufnahmeort von ${name} zeigen`}
                    onClick={() => setChosen(attachment.id)}
                  >
                    Aufnahmeort zeigen
                  </button>
                )}
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
          decrypted={open.protection === "open"}
          onClose={() => setOpen(null)}
        />
      )}
    </FoldCard>
  );
}

/** The quiet labels after the size: the protection (D233), and the text status where it says
 *  more than the protection does and more than the kind already tells. */
function Notes({ attachment }: { attachment: AttachmentInfo }) {
  const { protection } = attachment;
  // "Nicht unterstützt" only says that no text is read from pictures, sound and the like.
  const note =
    (protection && attachment.text_status === "encrypted") ||
    attachment.text_status === "unsupported"
      ? null
      : statusNote(attachment.text_status);
  return (
    <>
      {protection && (
        <span
          className={cx(styles.status, styles.protection)}
          title={PROTECTION_TITLES[protection]}
        >
          <ProtectionMark protection={protection} size={11} decorative />
          {PROTECTION_NOTES[protection]}
        </span>
      )}
      {note && <span className={styles.status}>{note}</span>}
    </>
  );
}

/** The documents a container holds (D231), indented below it in its order, the first
 *  MEMBERS_SHOWN and those holding a search word; and when it is not unpacked (yet), or some of
 *  its entries need a password. A ZIP, 7z or attached mail not unpacked yet has no status. */
function Members({
  container,
  kind,
  name,
  hitById,
  marks,
}: {
  container: AttachmentInfo;
  kind: DocumentKind;
  name: string;
  hitById: Map<number, AttachmentHit>;
  marks?: SearchMarks;
}) {
  const [all, setAll] = useState(false);
  const members = container.members ?? [];
  const status = container.members_status;
  const waiting =
    status === null && members.length === 0 && (kind === "archive" || kind === "email");
  const note =
    status === undefined || (status === null && !waiting) ? null : membersStatusNote(status);
  const shown = all
    ? members
    : members.filter((member, index) => index < MEMBERS_SHOWN || hitById.has(member.id));

  if (!note && members.length === 0) return null;
  return (
    <>
      {note && <span className={styles.membersNote}>{note}</span>}
      {members.length > 0 && (
        <ul className={styles.members} aria-label={`Inhalt von ${name}`}>
          {shown.map((member) => {
            const hit = hitById.get(member.id);
            const path = member.path || member.filename || "(ohne Namen)";
            return (
              <li
                key={member.id}
                id={attachmentElementId(member.id)}
                className={cx(styles.member, hit && styles.hit)}
              >
                <KindIcon kind={member.kind ?? kindFromMimeType(member.mime_type)} size={14} />
                <span className={styles.text}>
                  <span className={styles.memberPath}>
                    {member.document_id !== null ? (
                      <Link to={documentPath(member.document_id)} title={path}>
                        <Highlighted text={path} marks={hit?.in_name ? marks : undefined} />
                      </Link>
                    ) : (
                      path
                    )}
                  </span>
                  <span className={styles.meta}>
                    {formatBytes(member.size)}
                    <Notes attachment={member} />
                  </span>
                  {hit && <span className={styles.hitText}>{hitText(hit, marks)}</span>}
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {shown.length < members.length && (
        <Button variant="link" size="xs" className={styles.more} onClick={() => setAll(true)}>
          {`alle ${formatNumber(members.length)} Einträge anzeigen`}
        </Button>
      )}
    </>
  );
}
