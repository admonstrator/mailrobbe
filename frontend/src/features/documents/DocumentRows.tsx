import type { MouseEvent } from "react";
import { Link } from "react-router";

import type { DocumentListItem, DocumentTextStatus } from "../../api/types";
import { PersonLink } from "../../components/PersonLink";
import { cx } from "../../lib/cx";
import { formatBytes, formatDate } from "../../lib/format";
import { highlightParts } from "../../lib/highlight";
import { formatListDate } from "../../lib/listDate";
import styles from "./DocumentRows.module.css";
import { KindIcon } from "./KindIcon";
import {
  documentName,
  KIND_LABELS,
  mailsText,
  otherNamesText,
  pagesText,
  statusNote,
} from "./labels";
import { MachineMark } from "./MachineMark";
import { ContainedMark, ProtectionMark } from "./ProtectionMark";
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

/** "PDF · 14 Seiten · 168 KB" */
function metaText(doc: DocumentListItem): string {
  return [
    doc.kind ? KIND_LABELS[doc.kind] : "Art unbekannt",
    doc.pages !== null && pagesText(doc.pages),
    formatBytes(doc.size),
  ]
    .filter(Boolean)
    .join(" · ");
}

/** "Erstmals 28.09.2026, zuletzt 18.10.2026" */
function datesTitle(doc: DocumentListItem): string | undefined {
  if (!doc.first_date || !doc.last_date) return undefined;
  return `Erstmals ${formatDate(doc.first_date)}, zuletzt ${formatDate(doc.last_date)}`;
}

/** One page of the document list as rows (D335): icon, name with its marks, the snippet of a
 *  search or kind and size, the mails, who sent it first and when it was last sent. A click
 *  opens the document beside the list (onOpen); the name is the real link to its page, so
 *  middle click, Ctrl-click and "open in new tab" still work. narrow: a panel stands beside. */
export function DocumentRows({
  items,
  terms,
  stale,
  openId,
  onOpen,
  narrow,
}: {
  items: DocumentListItem[];
  /** The search words to mark in the snippets. */
  terms: string[];
  stale: boolean;
  openId: number | null;
  onOpen: (id: number) => void;
  narrow: boolean;
}) {
  function openRow(event: MouseEvent<HTMLLIElement>, id: number) {
    const target = event.target as HTMLElement;
    if (target.closest("a, button, input, label") || window.getSelection()?.toString()) return;
    onOpen(id);
  }

  function openName(event: MouseEvent<HTMLAnchorElement>, id: number) {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey)
      return;
    event.preventDefault();
    onOpen(id);
  }

  return (
    <ul
      className={cx(styles.rows, stale && styles.stale, narrow && styles.narrow)}
      aria-label="Anhänge"
    >
      {items.map((doc) => (
        <li
          key={doc.id}
          data-document-row=""
          className={cx(styles.row, doc.id === openId && styles.open)}
          aria-current={doc.id === openId ? "true" : undefined}
          onClick={(event) => openRow(event, doc.id)}
        >
          <span className={styles.icon}>
            <KindIcon kind={doc.kind} size={20} />
          </span>
          <div className={styles.main}>
            <span className={styles.title}>
              <Link
                to={documentPath(doc.id)}
                className={cx(styles.name, !doc.name && styles.muted)}
                onClick={(event) => openName(event, doc.id)}
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
              {doc.protection && <ProtectionMark protection={doc.protection} />}
              {doc.contained && <ContainedMark />}
              {doc.text_origin && doc.text_origin !== "extracted" && (
                <MachineMark short transcript={doc.text_origin === "transcript"} />
              )}
              <StatusLabel status={doc.text_status} />
            </span>
            <span className={styles.second}>
              {doc.snippet ? (
                <span className={styles.snippet}>
                  <Highlighted text={doc.snippet} terms={terms} />
                </span>
              ) : (
                <span className={styles.meta}>{metaText(doc)}</span>
              )}
            </span>
          </div>
          <span className={styles.mails}>{mailsText(doc.mails)}</span>
          <span className={styles.sender}>
            {doc.first_sender ? (
              <PersonLink person={doc.first_sender} className={styles.person} />
            ) : (
              <span className={styles.muted}>(unbekannt)</span>
            )}
          </span>
          <span className={styles.date} title={datesTitle(doc)}>
            {doc.last_date ? formatListDate(doc.last_date) : "–"}
          </span>
        </li>
      ))}
    </ul>
  );
}
