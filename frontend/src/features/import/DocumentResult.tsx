import { Link } from "react-router";

import type { DocumentTextStatus, ImportSummary } from "../../api/types";
import { Card, CardTitle } from "../../components/Card";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { TEXT_STATUS_FILTER_LABELS, TEXT_STATUSES } from "../documents/labels";
import { DEFAULT_DOCUMENT_LIST_STATE, documentListHref } from "../documents/urlState";
import styles from "./DocumentResult.module.css";

const statusHref = (status: DocumentTextStatus) =>
  documentListHref({ ...DEFAULT_DOCUMENT_LIST_STATE, text_status: [status] });

/** The text extraction of the attachments so far (D72): documents by text status, live, each
 *  leading to the document list of that status (the scans are the work list of a later OCR). */
export function DocumentResult({ summary }: { summary: ImportSummary }) {
  const counts = summary.documents;
  const shown = TEXT_STATUSES.filter((status) => (counts[status] ?? 0) > 0);
  const total = shown.reduce((sum, status) => sum + counts[status], 0);
  const share = (status: DocumentTextStatus) => counts[status] / total;
  const pending = counts.pending ?? 0;

  return (
    <Card variant="side" className={styles.card} aria-labelledby="import-documents-title">
      <CardTitle id="import-documents-title">Anhänge ausgewertet</CardTitle>
      {total === 0 ? (
        <p className={styles.none}>
          {summary.attachments > 0
            ? `Die ${formatNumber(summary.attachments)} Anhänge werden beim nächsten Import ausgewertet: Gleiche Dateien werden zu Dokumenten zusammengefasst und ihr Text wird gelesen.`
            : "Noch keine Anhänge im Archiv."}
        </p>
      ) : (
        <>
          <div
            className={styles.bar}
            role="img"
            aria-label={`Anteile: ${shown
              .map(
                (status) =>
                  `${Math.round(share(status) * 100)} % ${TEXT_STATUS_FILTER_LABELS[status]}`,
              )
              .join(", ")}`}
          >
            {shown.map((status) => (
              <span
                key={status}
                className={styles[status]}
                style={{ width: `${share(status) * 100}%` }}
              />
            ))}
          </div>
          <ul className={styles.legend}>
            {shown.map((status) => (
              <li key={status} className={styles.entry}>
                <span className={cx(styles.dot, styles[status])} aria-hidden="true" />
                <Link to={statusHref(status)} className={styles.label}>
                  {TEXT_STATUS_FILTER_LABELS[status]}
                </Link>
                <strong className={styles.count}>{formatNumber(counts[status])}</strong>
              </li>
            ))}
          </ul>
          <p className={styles.note}>
            {`${formatNumber(total)} ${total === 1 ? "Dokument" : "verschiedene Dokumente"} aus ${formatNumber(summary.attachments)} Anhängen.`}
            {pending > 0 && " Ausstehende liest der nächste Import."}
          </p>
        </>
      )}
    </Card>
  );
}
