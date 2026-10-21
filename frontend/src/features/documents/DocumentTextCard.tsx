import { useState } from "react";

import { useDocumentText } from "../../api/queries";
import type { DocumentDetail } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { ErrorState } from "../../components/ErrorState";
import { Spinner } from "../../components/Spinner";
import { formatNumber } from "../../lib/format";
import styles from "./DocumentTextCard.module.css";

/** The extracted text, up to 400,000 characters (D72): loaded and drawn only once opened, so the
 *  page stays light; spreadsheets keep their rows, so it is shown as stored, monospaced. */
export function DocumentTextCard({ document }: { document: DocumentDetail }) {
  const [open, setOpen] = useState(false);
  const text = useDocumentText(document.id, open);
  const truncated = text.data?.truncated ?? document.text_truncated;

  return (
    <Card className={styles.card} aria-labelledby="document-text-title">
      <div className={styles.head}>
        <CardTitle id="document-text-title">Ausgelesener Text</CardTitle>
        {truncated && (
          <span
            className={styles.truncated}
            title={
              document.text_status === "timeout"
                ? "Das Auslesen wurde beim Zeitlimit abgebrochen."
                : "Gespeichert sind die ersten 400.000 Zeichen."
            }
          >
            gekürzt
          </span>
        )}
        {open && text.data && (
          <span className={styles.length}>{`${formatNumber(text.data.text.length)} Zeichen`}</span>
        )}
        <Button
          size="sm"
          className={styles.toggle}
          aria-expanded={open}
          aria-controls="document-text"
          onClick={() => setOpen(!open)}
        >
          {open ? "Text ausblenden" : "Text anzeigen"}
        </Button>
      </div>
      {open && (
        <div id="document-text">
          {text.isPending ? (
            <div className={styles.loading}>
              <Spinner label="Text wird geladen" />
            </div>
          ) : text.isError ? (
            <ErrorState
              title="Der Text konnte nicht geladen werden."
              actions={<Button onClick={() => void text.refetch()}>Erneut versuchen</Button>}
            >
              Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
            </ErrorState>
          ) : text.data.text === "" ? (
            <p className={styles.empty}>Zu diesem Dokument ist kein Text gespeichert.</p>
          ) : (
            <pre className={styles.text} tabIndex={0} aria-label="Ausgelesener Text">
              {text.data.text}
            </pre>
          )}
        </div>
      )}
    </Card>
  );
}
