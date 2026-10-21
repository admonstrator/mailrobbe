import type { MouseEvent } from "react";
import { Link, useNavigate } from "react-router";

import type { DocumentListItem, DocumentTextStatus } from "../../api/types";
import { PersonLink } from "../../components/PersonLink";
import { cx } from "../../lib/cx";
import { formatBytes, formatDate, formatDateTime } from "../../lib/format";
import styles from "./DocumentTable.module.css";
import { highlightParts } from "../../lib/highlight";
import { KindIcon } from "./KindIcon";
import {
  documentName,
  KIND_LABELS,
  mailsText,
  otherNamesText,
  pagesText,
  statusNote,
} from "./labels";
import { documentPath } from "./urlState";

/** The tone of a status label: scans and locked files stand out a little, failures more. */
const STATUS_TONES: Partial<Record<DocumentTextStatus, string>> = {
  scanned: styles.notable,
  encrypted: styles.notable,
  failed: styles.problem,
  timeout: styles.problem,
  unreadable: styles.problem,
};

/** text with the search words marked. */
export function Highlighted({ text, terms }: { text: string; terms: string[] }) {
  return (
    <>
      {highlightParts(text, terms).map((part, index) =>
        part.mark ? <mark key={index}>{part.text}</mark> : part.text,
      )}
    </>
  );
}

/** The quiet label of a text status that says something (not for plain text). */
export function StatusLabel({ status }: { status: DocumentTextStatus }) {
  const note = statusNote(status);
  if (!note) return null;
  return <span className={cx(styles.status, STATUS_TONES[status])}>{note}</span>;
}

/** One page of the document list. Each row opens the document; the name is the real link, so
 *  middle-click and "open in new tab" work. */
export function DocumentTable({
  items,
  terms,
  stale,
}: {
  items: DocumentListItem[];
  /** The search words to mark in the snippets. */
  terms: string[];
  stale: boolean;
}) {
  const navigate = useNavigate();

  function openRow(event: MouseEvent<HTMLTableRowElement>, id: number) {
    const target = event.target as HTMLElement;
    if (target.closest("a, button, input, label") || window.getSelection()?.toString()) return;
    void navigate(documentPath(id));
  }

  return (
    <div className={styles.scroll}>
      <table className={cx(styles.table, stale && styles.stale)}>
        <thead>
          <tr>
            <th className={styles.iconCol}>
              <span className="sr-only">Art</span>
            </th>
            <th>Dokument</th>
            <th>Art</th>
            <th className={styles.num}>Größe</th>
            <th className={styles.num}>Mails</th>
            <th>Erstmals</th>
            <th>Zuletzt</th>
            <th>Zuerst gesendet von</th>
          </tr>
        </thead>
        <tbody>
          {items.map((doc) => (
            <tr key={doc.id} onClick={(event) => openRow(event, doc.id)}>
              <td className={styles.icon}>
                <KindIcon kind={doc.kind} />
              </td>
              <td className={styles.document}>
                <span className={styles.title}>
                  <Link
                    to={documentPath(doc.id)}
                    className={cx(styles.name, !doc.name && styles.muted)}
                  >
                    {documentName(doc.name)}
                  </Link>
                  {doc.names > 1 && (
                    <span
                      className={styles.names}
                      title={`Unter ${doc.names} verschiedenen Dateinamen verschickt`}
                    >
                      {otherNamesText(doc.names)}
                    </span>
                  )}
                  <StatusLabel status={doc.text_status} />
                </span>
                {doc.snippet && (
                  <span className={styles.snippet}>
                    <Highlighted text={doc.snippet} terms={terms} />
                  </span>
                )}
              </td>
              <td className={styles.kind}>
                {doc.kind ? KIND_LABELS[doc.kind] : <span className={styles.muted}>–</span>}
                {doc.pages !== null && <span className={styles.pages}>{pagesText(doc.pages)}</span>}
              </td>
              <td className={cx(styles.num, styles.size)}>{formatBytes(doc.size)}</td>
              <td className={cx(styles.num, styles.mails)}>{mailsText(doc.mails)}</td>
              <td className={styles.date}>
                {doc.first_date ? (
                  <span title={formatDateTime(doc.first_date)}>{formatDate(doc.first_date)}</span>
                ) : (
                  "–"
                )}
              </td>
              <td className={styles.date}>
                {doc.last_date ? (
                  <span title={formatDateTime(doc.last_date)}>{formatDate(doc.last_date)}</span>
                ) : (
                  "–"
                )}
              </td>
              <td className={styles.sender}>
                {doc.first_sender ? (
                  <PersonLink person={doc.first_sender} className={styles.person} />
                ) : (
                  <span className={styles.muted}>(unbekannt)</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
