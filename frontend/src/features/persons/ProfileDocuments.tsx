import { Link } from "react-router";

import { useDocumentPage } from "../../api/queries";
import { Button, buttonClass } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { PersonLink } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { formatBytes, formatDate, formatNumber } from "../../lib/format";
import { KindIcon } from "../documents/KindIcon";
import { KIND_LABELS } from "../documents/labels";
import { documentPath } from "../documents/urlState";
import styles from "./ProfileDocuments.module.css";

// Documents the tab lists; the attachment list has the rest.
const PROFILE_DOCUMENTS = 25;

/** The person's attachments in the attachment list (D75). */
export function personDocumentsHref(personId: number): string {
  return `/anhaenge?person=${personId}`;
}

/** The profile's tab Anhänge (D336): the newest documents of the person's mails, each leading to
 *  its page, and the whole list in the attachment screen. */
export function ProfileDocuments({ personId }: { personId: number }) {
  const page = useDocumentPage({ person: personId, limit: PROFILE_DOCUMENTS });
  const all = (
    <Link to={personDocumentsHref(personId)} className={buttonClass()}>
      In der Anhangsliste öffnen
    </Link>
  );

  if (page.isPending) {
    return (
      <div className={styles.loading}>
        <Spinner label="Anhänge werden geladen" />
      </div>
    );
  }
  if (page.isError) {
    return (
      <p className={styles.note} role="alert">
        Die Anhänge konnten nicht geladen werden.{" "}
        <Button variant="link" size="xs" onClick={() => void page.refetch()}>
          Erneut versuchen
        </Button>
      </p>
    );
  }
  const { items } = page.data;
  if (items.length === 0) {
    return (
      <EmptyState title="Keine Anhänge">
        Die Mails dieser Person tragen keine Anhänge, oder der Import hat sie noch nicht
        ausgewertet.
      </EmptyState>
    );
  }
  return (
    <div className={styles.documents}>
      <ul className={styles.list} aria-label="Anhänge der Person">
        {items.map((doc) => {
          const date = doc.first_date;
          return (
            <li key={doc.id} className={styles.row}>
              <span className={styles.icon}>
                <KindIcon kind={doc.kind} size={18} />
              </span>
              <div className={styles.what}>
                <Link to={documentPath(doc.id)} className={styles.name}>
                  {doc.name ?? "(ohne Namen)"}
                </Link>
                <span className={styles.info}>
                  {[
                    doc.kind ? KIND_LABELS[doc.kind] : null,
                    formatBytes(doc.size),
                    doc.pages ? `${formatNumber(doc.pages)} S.` : null,
                    `${formatNumber(doc.mails)} ${doc.mails === 1 ? "Mail" : "Mails"}`,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  {doc.first_sender && (
                    <>
                      {" · zuerst von "}
                      <PersonLink person={doc.first_sender} />
                    </>
                  )}
                </span>
              </div>
              <span className={styles.date}>{date ? formatDate(date) : "–"}</span>
            </li>
          );
        })}
      </ul>
      <div className={styles.foot}>
        {page.data.next_cursor && (
          <span className={styles.note}>{`Die ersten ${formatNumber(items.length)}.`}</span>
        )}
        {all}
      </div>
    </div>
  );
}
