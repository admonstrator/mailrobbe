import { useState } from "react";

import type { ImportStatus, MboxFileInfo, MboxStatus } from "../../api/types";
import { Button } from "../../components/Button";
import { cx } from "../../lib/cx";
import { formatBytes, formatNumber } from "../../lib/format";
import styles from "./FileTable.module.css";
import { FILE_FILTER_LABELS, FILE_STATUS_LABELS } from "./labels";
import { FILE_GROUPS, fileRows, type FileFilter, type FileRow as Row } from "./model";
import { HelpTip } from "../../components/PageHead";

const FILTERS: readonly FileFilter[] = ["all", ...FILE_GROUPS];

/** "Läuft · W3" while a worker has the file. */
function statusText(file: MboxFileInfo): string {
  const label = FILE_STATUS_LABELS[file.status];
  return file.status === "running" && file.worker_id !== null
    ? `${label} · W${file.worker_id}`
    : label;
}

/** "46 weitere fertig" or "Fertige einklappen", for the done and the waiting files. */
function toggleText(row: Exclude<Row, { type: "file" }>): string {
  const done = row.status === "done";
  if (row.type === "less") return done ? "Fertige einklappen" : "Wartende einklappen";
  return `${formatNumber(row.hidden)} weitere ${done ? "fertig" : "warten"}`;
}

/** The MBOX files with their progress over the byte offset (SPEC 5.5); the error count opens
 *  the error log for the file. */
export function FileTable({
  status,
  onShowErrors,
}: {
  status: ImportStatus;
  onShowErrors: (file: MboxFileInfo) => void;
}) {
  const [filter, setFilter] = useState<FileFilter>("all");
  const [expanded, setExpanded] = useState<ReadonlySet<MboxStatus>>(new Set());
  const { totals } = status;
  const counts: Record<FileFilter, number> = {
    all: totals.files,
    done: totals.done,
    running: totals.running,
    paused: totals.paused,
    error: totals.error,
    pending: totals.pending,
  };
  const rows = fileRows(status.files, filter, expanded);

  return (
    <section className={styles.card} aria-labelledby="import-files-title">
      <div className={styles.head}>
        <h2 id="import-files-title" className={styles.title}>
          MBOX-Dateien
        </h2>
        <HelpTip text="Fortschritt pro Datei über Byte-Offset, Wiederaufnahme nach Abbruch möglich" />
        <label htmlFor="import-file-status" className={styles.filterLabel}>
          Status
        </label>
        <select
          id="import-file-status"
          className={styles.filter}
          value={filter}
          onChange={(event) => setFilter(event.target.value as FileFilter)}
        >
          {FILTERS.filter((key) => key === "all" || key === filter || counts[key] > 0).map(
            (key) => (
              <option key={key} value={key}>
                {`${FILE_FILTER_LABELS[key]} ${formatNumber(counts[key])}`}
              </option>
            ),
          )}
        </select>
      </div>
      <div className={styles.scroll}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Datei</th>
              <th className={styles.size}>Größe</th>
              <th className={styles.mails}>Mails</th>
              <th className={styles.progress}>Fortschritt</th>
              <th className={styles.status}>Status</th>
              <th className={styles.errors}>Fehler</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) =>
              row.type === "file" ? (
                <FileRow key={row.file.id} file={row.file} onShowErrors={onShowErrors} />
              ) : (
                <tr key={`${row.type}-${row.status}`} className={styles.toggle}>
                  <td className={styles.path}>{row.type === "more" && "…"}</td>
                  <td colSpan={3} />
                  <td colSpan={2}>
                    <Button
                      variant="link"
                      size="xs"
                      className={styles.toggleButton}
                      aria-expanded={row.type === "less"}
                      onClick={() =>
                        setExpanded((groups) => {
                          const next = new Set(groups);
                          if (row.type === "more") next.add(row.status);
                          else next.delete(row.status);
                          return next;
                        })
                      }
                    >
                      {toggleText(row)}
                    </Button>
                  </td>
                </tr>
              ),
            )}
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className={styles.none}>
                  Keine Datei mit diesem Status.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function FileRow({
  file,
  onShowErrors,
}: {
  file: MboxFileInfo;
  onShowErrors: (file: MboxFileInfo) => void;
}) {
  const untouched = file.status === "pending" && file.bytes_done === 0;
  const ratio = file.size_bytes > 0 ? Math.min(1, file.bytes_done / file.size_bytes) : 0;
  const percent = Math.floor(ratio * 100);
  return (
    <tr>
      <td className={styles.path}>{file.path}</td>
      <td>{formatBytes(file.size_bytes)}</td>
      <td>{untouched ? "–" : formatNumber(file.mails_parsed)}</td>
      <td>
        <div
          className={styles.track}
          role="progressbar"
          aria-label={`Fortschritt ${file.path}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          title={`${percent} % · ${formatBytes(file.bytes_done)} von ${formatBytes(file.size_bytes)}`}
        >
          <span
            className={cx(styles.fill, styles[`fill_${file.status}`])}
            style={{ width: `${ratio * 100}%` }}
          />
        </div>
      </td>
      <td className={cx(styles.state, styles[`state_${file.status}`])}>{statusText(file)}</td>
      <td>
        {untouched ? (
          "–"
        ) : file.error_count > 0 ? (
          <Button
            variant="link"
            size="xs"
            className={styles.errorLink}
            aria-label={`${formatNumber(file.error_count)} Fehler in ${file.path} anzeigen`}
            onClick={() => onShowErrors(file)}
          >
            {formatNumber(file.error_count)}
          </Button>
        ) : (
          "0"
        )}
      </td>
    </tr>
  );
}
