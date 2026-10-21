import { useState } from "react";

import { useImportErrorPages, type ImportErrorFilters } from "../../api/queries";
import type { ImportErrorKind, MboxFileInfo } from "../../api/types";
import { Button } from "../../components/Button";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { Dialog } from "../persons/Dialog";
import styles from "./ErrorDialog.module.css";
import { ErrorEntry } from "./ErrorLog";
import { ERROR_KIND_TEXTS } from "./labels";

const KINDS = Object.keys(ERROR_KIND_TEXTS) as ImportErrorKind[];

/** Every import error, newest first, by kind and file, a page at a time. */
export function ErrorDialog({
  initial,
  files,
  onClose,
}: {
  initial: ImportErrorFilters;
  files: MboxFileInfo[];
  onClose: () => void;
}) {
  const [filters, setFilters] = useState(initial);
  const pages = useImportErrorPages(filters);
  const first = pages.data?.pages[0];
  const items = pages.data?.pages.flatMap((page) => page.items) ?? [];
  const kinds = first?.kinds ?? {};
  const all = Object.values(kinds).reduce((sum, count) => sum + (count ?? 0), 0);
  const errorFiles = files.filter((file) => file.error_count > 0 || file.id === filters.mbox_file);

  return (
    <Dialog title="Fehlerprotokoll" onClose={onClose}>
      <div className={styles.filters}>
        <div className={styles.field}>
          <label htmlFor="import-error-kind">Art</label>
          <select
            id="import-error-kind"
            value={filters.kind ?? ""}
            onChange={(event) =>
              setFilters({
                ...filters,
                kind: (event.target.value || undefined) as ImportErrorKind | undefined,
              })
            }
          >
            <option value="">{`Alle Arten (${formatNumber(all)})`}</option>
            {KINDS.filter((kind) => kinds[kind] || kind === filters.kind).map((kind) => (
              <option key={kind} value={kind}>
                {`${ERROR_KIND_TEXTS[kind]} (${formatNumber(kinds[kind] ?? 0)})`}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.field}>
          <label htmlFor="import-error-file">Datei</label>
          <select
            id="import-error-file"
            value={filters.mbox_file ?? ""}
            onChange={(event) =>
              setFilters({
                ...filters,
                mbox_file: event.target.value ? Number(event.target.value) : undefined,
              })
            }
          >
            <option value="">Alle Dateien</option>
            {errorFiles.map((file) => (
              <option key={file.id} value={file.id}>
                {`${file.path} (${formatNumber(file.error_count)})`}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className={cx(styles.scroll, pages.isPlaceholderData && styles.stale)}>
        {pages.isPending && <Spinner label="Fehler werden geladen" />}
        {pages.isError && <p className={styles.note}>Die Fehler konnten nicht geladen werden.</p>}
        {first && items.length === 0 && <p className={styles.note}>Keine Fehler.</p>}
        {items.length > 0 && (
          <ol className={styles.list}>
            {items.map((error) => (
              <ErrorEntry key={error.id} error={error} withDate />
            ))}
          </ol>
        )}
      </div>
      <div className={styles.foot}>
        <span className={styles.count}>
          {first && `${formatNumber(items.length)} von ${formatNumber(first.total)} Fehlern`}
        </span>
        {pages.hasNextPage && (
          <Button onClick={() => void pages.fetchNextPage()} disabled={pages.isFetchingNextPage}>
            Weitere laden
          </Button>
        )}
        <Button variant="primary" onClick={onClose}>
          Schließen
        </Button>
      </div>
    </Dialog>
  );
}
