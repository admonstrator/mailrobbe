import { useImportErrors } from "../../api/queries";
import type { ImportErrorItem } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { Spinner } from "../../components/Spinner";
import { formatDateTime, formatNumber } from "../../lib/format";
import styles from "./ErrorLog.module.css";
import { ERROR_KIND_TEXTS } from "./labels";

/** Errors the card lists; "Alle" opens the rest. */
const NEWEST = 5;

/** One entry: time, "file @ offset", the German kind and the importer's English message. */
export function ErrorEntry({
  error,
  withDate = false,
}: {
  error: ImportErrorItem;
  withDate?: boolean;
}) {
  const when = formatDateTime(error.created_at, true);
  return (
    <li className={styles.entry}>
      <time dateTime={error.created_at} title={when} className={styles.time}>
        {withDate ? when : when.slice(-8)}
      </time>
      <div className={styles.text}>
        <span>
          {error.path && (
            <span className={styles.where}>
              {error.byte_offset === null
                ? error.path
                : `${error.path} @ ${formatNumber(error.byte_offset)}`}
            </span>
          )}
          {error.path && ": "}
          {ERROR_KIND_TEXTS[error.kind]}
        </span>
        <span className={styles.message}>{error.message}</span>
      </div>
    </li>
  );
}

/** "Fehlerprotokoll": the newest import errors, polled while a run is alive. */
export function ErrorLog({ alive, onShowAll }: { alive: boolean; onShowAll: () => void }) {
  const errors = useImportErrors({ limit: NEWEST }, alive);
  return (
    <Card variant="side" aria-labelledby="import-errors-title">
      <div className={styles.head}>
        <CardTitle id="import-errors-title">Fehlerprotokoll</CardTitle>
        {errors.data && errors.data.total > 0 && (
          <Button variant="link" size="xs" className={styles.all} onClick={onShowAll}>
            {`Alle ${formatNumber(errors.data.total)}`}
          </Button>
        )}
      </div>
      {errors.isPending ? (
        <Spinner label="Fehlerprotokoll wird geladen" />
      ) : errors.isError ? (
        <p className={styles.note}>Das Fehlerprotokoll konnte nicht geladen werden.</p>
      ) : errors.data.items.length === 0 ? (
        <p className={styles.note}>Der Import hat keine Fehler gemeldet.</p>
      ) : (
        <ol className={styles.list}>
          {errors.data.items.map((error) => (
            <ErrorEntry key={error.id} error={error} />
          ))}
        </ol>
      )}
    </Card>
  );
}
