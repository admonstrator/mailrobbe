import { useImportErrors, type ImportErrorFilters } from "../../api/queries";
import type { ImportErrorItem, ImportErrorKind } from "../../api/types";
import { Button } from "../../components/Button";
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

/** The tab "Fehler": the import errors grouped by their cause, each group opening its errors,
 *  and the newest errors as the log, polled while a run is alive. */
export function ErrorLog({
  alive,
  onShow,
}: {
  alive: boolean;
  onShow: (filters: ImportErrorFilters) => void;
}) {
  const errors = useImportErrors({ limit: NEWEST }, alive);
  if (errors.isPending) return <Spinner label="Fehlerprotokoll wird geladen" />;
  if (errors.isError) {
    return <p className={styles.note}>Das Fehlerprotokoll konnte nicht geladen werden.</p>;
  }
  if (errors.data.items.length === 0) {
    return <p className={styles.note}>Der Import hat keine Fehler gemeldet.</p>;
  }
  const kinds = (Object.entries(errors.data.kinds) as [ImportErrorKind, number][]).sort(
    ([, a], [, b]) => b - a,
  );
  return (
    <div className={styles.tab}>
      <section aria-labelledby="import-error-kinds" className={styles.section}>
        <div className={styles.head}>
          <h2 id="import-error-kinds" className={styles.title}>
            Nach Ursache
          </h2>
          <Button variant="link" size="sm" className={styles.all} onClick={() => onShow({})}>
            {`Alle ${formatNumber(errors.data.total)}`}
          </Button>
        </div>
        <ul className={styles.kinds}>
          {kinds.map(([kind, count]) => (
            <li key={kind}>
              <button type="button" className={styles.kind} onClick={() => onShow({ kind })}>
                <span className={styles.kindText}>{ERROR_KIND_TEXTS[kind]}</span>
                <span className={styles.kindCount}>{formatNumber(count)}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="import-errors-title" className={styles.section}>
        <h2 id="import-errors-title" className={styles.title}>
          Fehlerprotokoll
        </h2>
        <ol className={styles.list}>
          {errors.data.items.map((error) => (
            <ErrorEntry key={error.id} error={error} />
          ))}
        </ol>
      </section>
    </div>
  );
}
