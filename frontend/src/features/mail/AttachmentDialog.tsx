import { Fragment, type ReactNode } from "react";
import { Link } from "react-router";

import { useDocument } from "../../api/queries";
import type {
  AiSummaryResult,
  AttachmentInfo,
  DocumentDetail,
  MailDetail,
  ParticipationRole,
  PersonRef,
} from "../../api/types";
import type { SearchMarks } from "../../components/Highlighted";
import { PersonLink } from "../../components/PersonLink";
import {
  formatBytes,
  formatClock,
  formatDate,
  formatDateTime,
  formatDateTimeLong,
  formatNumber,
} from "../../lib/format";
import { DocumentSummary, SummaryBlock } from "../ai/SummaryCard";
import { KIND_LABELS, kindFromMimeType } from "../documents/labels";
import { documentPath } from "../documents/urlState";
import { DEFAULT_LIST_STATE, listSearch } from "../mails/listState";
import { photoPosition, PhotoPosition } from "../places/PhotoPosition";
import { PreviewOverlay } from "../preview/PreviewOverlay";
import styles from "./AttachmentDialog.module.css";
import { AiButton, Notes, shownOrder } from "./AttachmentsCard";

/** Senders and recipients of a document named in the side column before "und n weitere". */
const PEOPLE_SHOWN = 3;

const ROLE_LABELS = { from: "Von", to: "An", cc: "Cc", bcc: "Bcc" } as const;

/** One attachment of a mail over the page (D331): its preview as before (D120 to D123, D165,
 *  D296), with the arrows to the mail's other attachments, and beside it what the page knows
 *  about it: the summary of its document with tags and hints, who sent it to whom and when, the
 *  other mails of the archive carrying it, and what the file says about itself (D167). A member
 *  of a container opens without the arrows. Every attachment opens, one the browser cannot show
 *  with a note in place of the preview. */
export function AttachmentDialog({
  mail,
  attachment,
  summaries,
  marks,
  onOpen,
}: {
  mail: MailDetail;
  attachment: AttachmentInfo;
  summaries: ReadonlyMap<number, AiSummaryResult>;
  marks?: SearchMarks;
  /** Another attachment, or null on closing. */
  onOpen: (attachment: AttachmentInfo | null) => void;
}) {
  const list = shownOrder(mail.attachments);
  const index = list.findIndex(({ id }) => id === attachment.id);
  const step = (by: number) => onOpen(list[(index + by + list.length) % list.length]);
  const nav =
    index >= 0 && list.length > 1
      ? {
          position: `Anhang ${formatNumber(index + 1)} von ${formatNumber(list.length)}`,
          onPrev: () => step(-1),
          onNext: () => step(1),
        }
      : undefined;
  const locked = attachment.protection === "locked";
  const summary =
    attachment.document_id === null ? undefined : summaries.get(attachment.document_id);
  return (
    <PreviewOverlay
      // a fresh dialog for every attachment: its zoom, player and picture start anew
      key={attachment.id}
      attachmentId={attachment.id}
      kind={locked ? null : attachment.preview}
      locked={locked}
      name={attachment.filename || "(ohne Namen)"}
      decrypted={attachment.protection === "open"}
      // the lines of its transcript below the player, the search words marked (D296)
      transcriptOf={
        attachment.transcript === "transcribed" || attachment.transcript === "no_text"
          ? attachment.document_id
          : null
      }
      shareable={attachment.transcript === "transcribed"}
      marks={marks}
      nav={nav}
      aside={<AttachmentFacts mail={mail} attachment={attachment} summary={summary} />}
      onClose={() => onOpen(null)}
    />
  );
}

/** The side column: KI-Zusammenfassung, Versand, Datei. */
function AttachmentFacts({
  mail,
  attachment,
  summary,
}: {
  mail: MailDetail;
  attachment: AttachmentInfo;
  summary?: AiSummaryResult;
}) {
  const documentId = attachment.document_id;
  const document = useDocument(documentId ?? 0, documentId !== null);
  const kind = attachment.kind ?? kindFromMimeType(attachment.mime_type);
  const name = attachment.filename || "(ohne Namen)";
  const metadata = attachment.metadata;
  const position = photoPosition(metadata);
  const told =
    metadata && (metadata.software || metadata.author || metadata.modified_by || metadata.device);
  const byRole = (role: ParticipationRole) => mail.participants.filter((p) => p.role === role);

  return (
    <div className={styles.facts}>
      <section className={styles.section}>
        <h3 className={styles.heading}>KI-Zusammenfassung</h3>
        {summary ? (
          <SummaryBlock result={summary} mailId={mail.id} />
        ) : documentId === null ? (
          <p className={styles.note}>Noch keine Zusammenfassung.</p>
        ) : (
          <>
            <DocumentSummary
              documentId={documentId}
              mailId={mail.id}
              recognizable={
                attachment.ocr === "readable" || attachment.transcript === "transcribable"
              }
            />
            {(attachment.ocr === "readable" || attachment.transcript === "transcribable") && (
              <span className={styles.actions}>
                {attachment.ocr === "readable" && (
                  <AiButton documentId={documentId} name={name} kind="ocr" />
                )}
                {attachment.transcript === "transcribable" && (
                  <AiButton documentId={documentId} name={name} kind="transcribe" />
                )}
              </span>
            )}
          </>
        )}
      </section>

      <section className={styles.section}>
        <h3 className={styles.heading}>Versand</h3>
        <dl className={styles.list}>
          {(["from", "to", "cc", "bcc"] as const).map((role) => {
            const people = byRole(role);
            if (people.length === 0 && role !== "from") return null;
            return (
              <Fact key={role} label={ROLE_LABELS[role]}>
                <People people={people} total={people.length} />
              </Fact>
            );
          })}
          <Fact label="Gesendet">
            {mail.date ? formatDateTimeLong(mail.date) : "Datum unbekannt"}
          </Fact>
          {attachment.path && <Fact label="Pfad im Archiv">{attachment.path}</Fact>}
        </dl>
        {document.data && <Travels document={document.data} />}
      </section>

      <section className={styles.section}>
        <h3 className={styles.heading}>Datei</h3>
        <dl className={styles.list}>
          <Fact label="Art">
            <span title={attachment.mime_type}>{KIND_LABELS[kind]}</span>
          </Fact>
          {metadata?.software && <Fact label="Programm">{metadata.software}</Fact>}
          {metadata?.author && <Fact label="Autor">{metadata.author}</Fact>}
          {metadata?.modified_by && <Fact label="Geändert von">{metadata.modified_by}</Fact>}
          {metadata?.device && (
            <Fact label={kind === "image" ? "Kamera" : "Gerät"}>{metadata.device}</Fact>
          )}
          {metadata?.created && (
            <Fact label={kind === "image" ? "Aufgenommen" : "Erstellt"}>
              {formatDateTime(metadata.created)}
            </Fact>
          )}
          {attachment.pages !== null && (
            <Fact label="Seiten">{formatNumber(attachment.pages)}</Fact>
          )}
          {typeof attachment.duration === "number" && (
            <Fact label="Länge">{formatClock(attachment.duration)}</Fact>
          )}
          <Fact label="Größe">{formatBytes(attachment.size)}</Fact>
          <Fact label="SHA-256">
            {attachment.sha256 ? (
              <span title={attachment.sha256}>{`${attachment.sha256.slice(0, 12)}…`}</span>
            ) : (
              "nicht gehasht (über 50 MB)"
            )}
          </Fact>
        </dl>
        {!told && (
          <p className={styles.note}>Die Datei nennt weder Programm noch Autor noch Gerät.</p>
        )}
        <p className={styles.notes}>
          <Notes attachment={attachment} />
        </p>
        {position && <PhotoPosition documentId={documentId} position={position} />}
        {documentId !== null && (
          <Link to={documentPath(documentId)} className={styles.more}>
            Zur Dokumentseite
          </Link>
        )}
      </section>
    </div>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className={styles.label}>{label}</dt>
      <dd className={styles.value}>{children}</dd>
    </>
  );
}

/** "Anna Keller, Peter Hofmann und 4 weitere", the names linking to the profiles. */
function People({
  people,
  total,
  counts,
}: {
  people: PersonRef[];
  total: number;
  counts?: number[];
}) {
  if (people.length === 0) return <span className={styles.muted}>–</span>;
  const shown = people.slice(0, PEOPLE_SHOWN);
  const rest = total - shown.length;
  return (
    <>
      {shown.map((person, index) => (
        <Fragment key={person.person_id}>
          {index > 0 && ", "}
          <PersonLink person={person} />
          {counts && <span className={styles.muted}>{` (${formatNumber(counts[index])})`}</span>}
        </Fragment>
      ))}
      {rest > 0 && ` und ${formatNumber(rest)} weitere`}
    </>
  );
}

/** Where else the document travels in the archive: the mails carrying it, the first of them, who
 *  sent it and who got it (D75). */
function Travels({ document }: { document: DocumentDetail }) {
  if (document.mails <= 1) return <p className={styles.note}>Im Archiv nur in dieser Mail.</p>;
  return (
    <>
      <p className={styles.note}>
        {`Im Archiv in ${formatNumber(document.mails)} Mails`}
        {document.first_date && `, zuerst am ${formatDate(document.first_date)}`}
        {document.first_mail?.sender && (
          <>
            {" von "}
            <PersonLink person={document.first_mail.sender} />
          </>
        )}
      </p>
      <dl className={styles.list}>
        <Fact label="Geschickt von">
          <People
            people={document.senders.map(({ person }) => person)}
            counts={document.senders.map(({ mails }) => mails)}
            total={document.sender_count}
          />
        </Fact>
        <Fact label="Bekommen">
          <People
            people={document.recipients.map(({ person }) => person)}
            counts={document.recipients.map(({ mails }) => mails)}
            total={document.recipient_count}
          />
        </Fact>
      </dl>
      <Link
        to={`/mails?${listSearch({ ...DEFAULT_LIST_STATE, document: document.id })}`}
        className={styles.more}
      >
        {`Alle ${formatNumber(document.mails)} Mails zeigen`}
      </Link>
    </>
  );
}
