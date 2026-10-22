import { useState } from "react";
import { Link } from "react-router";

import type { DocumentDetail, DocumentMember, DocumentMembers } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { cx } from "../../lib/cx";
import { formatBytes, formatNumber } from "../../lib/format";
import styles from "./ContentsCard.module.css";
import { KindIcon } from "./KindIcon";
import { MEMBER_STATUS_LABELS, membersStatusText, statusNote } from "./labels";
import { ProtectionMark } from "./ProtectionMark";
import { documentPath } from "./urlState";

/** Entries listed before "alle n anzeigen"; a container holds up to 1,000 (D231). */
export const ENTRIES_SHOWN = 50;

/** What a container holds (D231), in its own order: each entry's path, size and what became of
 *  it, the member documents linked; how the unpacking stands and why it failed. An attached
 *  mail's entries are its attachments. */
export function ContentsCard({
  document,
  members,
}: {
  document: DocumentDetail;
  members: DocumentMembers;
}) {
  const [all, setAll] = useState(false);
  const { entries } = members;
  const mail = document.kind === "email";
  const status = membersStatusText(members.status, document.protection === "open");
  const shown = all ? entries : entries.slice(0, ENTRIES_SHOWN);
  const title = mail ? "Anhänge der angehängten Mail" : "Inhalt";

  return (
    <Card aria-labelledby="document-contents-title">
      <CardTitle id="document-contents-title">
        {entries.length > 0 ? `${title} (${formatNumber(entries.length)})` : title}
      </CardTitle>
      {(status || members.error) && (
        <p className={styles.status}>
          {status}
          {members.error && <code className={styles.error}>{members.error}</code>}
        </p>
      )}
      {entries.length > 0 ? (
        <ol className={styles.list}>
          {shown.map((entry) => (
            <Entry key={entry.position} entry={entry} />
          ))}
        </ol>
      ) : (
        members.status === "done" && (
          <p className={styles.status}>
            {mail ? "Die angehängte Mail hat keine Anhänge." : "Das Archiv ist leer."}
          </p>
        )
      )}
      {shown.length < entries.length && (
        <Button variant="link" size="xs" className={styles.more} onClick={() => setAll(true)}>
          {`alle ${formatNumber(entries.length)} anzeigen`}
        </Button>
      )}
    </Card>
  );
}

/** What became of an entry: why it is no document, or how the document stands where that says
 *  something; finalize assigns a new member its document in the next import. */
function entryNote(entry: DocumentMember): string | null {
  if (entry.status !== "document") return MEMBER_STATUS_LABELS[entry.status];
  if (entry.document_id === null) return `${MEMBER_STATUS_LABELS.document} ab dem nächsten Import`;
  return statusNote(entry.text_status);
}

/** One entry: a member document links to its page; the technical reason of a failure on hover. */
function Entry({ entry }: { entry: DocumentMember }) {
  const note = entryNote(entry);
  return (
    <li className={styles.entry}>
      <KindIcon kind={entry.kind} size={16} />
      <span className={styles.path}>
        {entry.document_id !== null ? (
          <Link to={documentPath(entry.document_id)}>{entry.path}</Link>
        ) : (
          entry.path
        )}
      </span>
      <span className={styles.facts}>
        {entry.protection && <ProtectionMark protection={entry.protection} />}
        {note && (
          <span
            className={cx(styles.note, entry.status !== "document" && styles.missing)}
            title={entry.error ?? undefined}
          >
            {note}
          </span>
        )}
        {entry.size !== null && <span className={styles.size}>{formatBytes(entry.size)}</span>}
      </span>
    </li>
  );
}
