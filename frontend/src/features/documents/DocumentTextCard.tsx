import { useState } from "react";

import { useDocumentText } from "../../api/queries";
import type { DocumentDetail } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { ErrorState } from "../../components/ErrorState";
import { Spinner } from "../../components/Spinner";
import { formatNumber } from "../../lib/format";
import { OcrBar } from "./DocumentOcr";
import styles from "./DocumentTextCard.module.css";
import { hasStoredText } from "./labels";

/** The extracted text, up to 400,000 characters (D72): loaded and drawn only once opened, so the
 *  page stays light; spreadsheets keep their rows, so it is shown as stored, monospaced. A text
 *  an AI run recognised says so with its engine, date and pages (D189); a document OCR can read
 *  without a text gets the card for "Text erkennen" alone. */
export function DocumentTextCard({ document }: { document: DocumentDetail }) {
  const [open, setOpen] = useState(false);
  const stored = hasStoredText(document.text_status);
  const text = useDocumentText(document.id, open && stored);
  const truncated = text.data?.truncated ?? document.text_truncated;
  const title = !stored
    ? "Texterkennung"
    : document.text_origin === "ocr"
      ? "Erkannter Text"
      : "Ausgelesener Text";

  return (
    <Card className={styles.card} aria-labelledby="document-text-title">
      <div className={styles.head}>
        <CardTitle id="document-text-title">{title}</CardTitle>
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
        {stored && (
          <Button
            size="sm"
            className={styles.toggle}
            aria-expanded={open}
            aria-controls="document-text"
            onClick={() => setOpen(!open)}
          >
            {open ? "Text ausblenden" : "Text anzeigen"}
          </Button>
        )}
      </div>
      <OcrBar document={document} />
      {open && stored && (
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
