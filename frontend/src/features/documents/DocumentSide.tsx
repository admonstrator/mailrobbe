import { Link } from "react-router";

import { DOCUMENT_NAMES_LIMIT, type DocumentDetail, type PersonCount } from "../../api/types";
import { Card, CardTitle } from "../../components/Card";
import { personPath } from "../../components/PersonLink";
import { formatNumber } from "../../lib/format";
import { personLabel } from "../persons/labels";
import { AttachmentPreview } from "../preview/AttachmentPreview";
import styles from "./DocumentSide.module.css";
import { documentName } from "./labels";

/** A raster image (D76), shown as the mail detail shows it. */
export function DocumentPreview({ document }: { document: DocumentDetail }) {
  return (
    <Card variant="side" aria-labelledby="document-preview-title">
      <CardTitle id="document-preview-title" variant="caps">
        Vorschau
      </CardTitle>
      <div className={styles.preview}>
        <AttachmentPreview
          attachmentId={document.attachment_id}
          kind="image"
          name={documentName(document.name)}
        />
      </div>
    </Card>
  );
}

/** The file names it was sent under, most used first. */
export function DocumentNames({ document }: { document: DocumentDetail }) {
  const { names } = document;
  return (
    <Card variant="side" aria-labelledby="document-names-title">
      <CardTitle id="document-names-title" variant="caps">
        {names.length === 1 ? "Dateiname" : `Dateinamen (${formatNumber(names.length)})`}
      </CardTitle>
      {names.length === 0 ? (
        <p className={styles.empty}>Immer ohne Dateinamen verschickt.</p>
      ) : (
        <ul className={styles.list}>
          {names.map(({ name, attachments }) => (
            <li key={name} className={styles.row}>
              <span className={styles.name}>{name}</span>
              <span
                className={styles.count}
                title={`${formatNumber(attachments)} ${attachments === 1 ? "Anhang" : "Anhänge"} mit diesem Namen`}
              >
                {`${formatNumber(attachments)}×`}
              </span>
            </li>
          ))}
        </ul>
      )}
      {names.length >= DOCUMENT_NAMES_LIMIT && (
        <p className={styles.more}>{`Die ${DOCUMENT_NAMES_LIMIT} häufigsten Namen.`}</p>
      )}
    </Card>
  );
}

/** The senders or the recipients who had it most (root persons), each with its mails. */
export function DocumentPersons({
  id,
  title,
  persons,
  total,
  empty,
}: {
  id: string;
  title: string;
  persons: PersonCount[];
  total: number;
  empty: string;
}) {
  const rest = total - persons.length;
  return (
    <Card variant="side" aria-labelledby={id}>
      <CardTitle id={id} variant="caps">
        {`${title} (${formatNumber(total)})`}
      </CardTitle>
      {persons.length === 0 ? (
        <p className={styles.empty}>{empty}</p>
      ) : (
        <ul className={styles.list}>
          {persons.map(({ person, mails }) => (
            <li key={person.person_id} className={styles.row}>
              <Link
                to={personPath(person.person_id)}
                className={styles.person}
                title={person.email}
              >
                {personLabel(person)}
              </Link>
              <span
                className={styles.count}
                title={`${formatNumber(mails)} ${mails === 1 ? "Mail" : "Mails"} mit diesem Dokument`}
              >
                {formatNumber(mails)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {rest > 0 && <p className={styles.more}>{`und ${formatNumber(rest)} weitere`}</p>}
    </Card>
  );
}
