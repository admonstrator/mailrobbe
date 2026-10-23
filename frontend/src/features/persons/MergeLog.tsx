import { useState } from "react";

import { useMergeLog, useUndoMerge, useUndoMergeBatch } from "../../api/queries";
import type { MergeBatchInfo, MergeLogEntry, MergeUndoResult } from "../../api/types";
import { Button } from "../../components/Button";
import { HelpTip } from "../../components/PageHead";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { PersonLink } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatDateTime, formatNumber } from "../../lib/format";
import { mergeCount, personCount, personErrorText } from "./labels";
import styles from "./MergeLog.module.css";

/** "Zuletzt zusammengeführt" (D163): the logged merges, newest first, the runs of "Alle
 *  sicheren zusammenführen" together, each merge and each run with its "Rückgängig". */
export function MergeLog() {
  const log = useMergeLog();
  const undoMerge = useUndoMerge();
  const undoBatch = useUndoMergeBatch();
  const [notice, setNotice] = useState<string | null>(null);
  const failed = undoMerge.error ?? undoBatch.error;
  const busy = undoMerge.isPending || undoBatch.isPending;

  const undone = (result: MergeUndoResult) =>
    setNotice(
      `Rückgängig gemacht: ${mergeCount(result.merges)}, ${personCount(result.persons)} ${
        result.persons === 1 ? "ist" : "sind"
      } wieder eigenständig.`,
    );
  const onUndoMerge = (id: number) => {
    undoBatch.reset();
    undoMerge.mutate(id, { onSuccess: undone });
  };
  const onUndoBatch = (id: number) => {
    undoMerge.reset();
    undoBatch.mutate(id, { onSuccess: undone });
  };

  if (log.isPending) {
    return (
      <div className={styles.loading}>
        <Spinner label="Zusammenführungen werden geladen" />
      </div>
    );
  }
  if (log.isError) {
    return (
      <div>
        <ErrorState
          title="Die Zusammenführungen konnten nicht geladen werden."
          actions={<Button onClick={() => void log.refetch()}>Erneut versuchen</Button>}
        >
          Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
        </ErrorState>
      </div>
    );
  }

  const pages = log.data.pages;
  const batches = new Map(pages.flatMap((page) => page.batches).map((b) => [b.id, b]));
  const groups = runs(pages.flatMap((page) => page.items));
  return (
    <>
      <p className={styles.intro}>
        Rückgängig machen geht hier für jede Zusammenführung seit dem Protokoll.
        <HelpTip text="Auch nach späteren Zusammenführungen. Ältere Zusammenführungen löst man im Profil Adresse für Adresse." />
      </p>
      <p role="status" className={cx(styles.notice, !notice && "sr-only")}>
        {notice}
      </p>
      {failed && (
        <p className={styles.error} role="alert">
          {personErrorText(failed)}
        </p>
      )}
      <div className={styles.card}>
        {groups.length === 0 ? (
          <EmptyState title="Noch nichts zusammengeführt">
            Zusammenführungen erscheinen hier, sobald Personen zusammengeführt werden.
          </EmptyState>
        ) : (
          groups.map(({ batch, items }) => (
            <section key={`${batch}-${items[0].id}`} className={styles.group}>
              {batch !== null && batches.has(batch) && (
                <RunHead
                  batch={batches.get(batch)!}
                  busy={busy}
                  onUndo={() => onUndoBatch(batch)}
                />
              )}
              <ul className={styles.list} aria-label={batch === null ? "Einzeln" : `Lauf ${batch}`}>
                {items.map((entry) => (
                  <MergeRow
                    key={entry.id}
                    entry={entry}
                    busy={busy}
                    onUndo={() => onUndoMerge(entry.id)}
                  />
                ))}
              </ul>
            </section>
          ))
        )}
      </div>
      {log.hasNextPage && (
        <div className={styles.more}>
          <Button onClick={() => void log.fetchNextPage()} disabled={log.isFetchingNextPage}>
            Weitere laden
          </Button>
        </div>
      )}
    </>
  );
}

/** The merges in order, consecutive ones of one run together. */
function runs(items: MergeLogEntry[]): { batch: number | null; items: MergeLogEntry[] }[] {
  const groups: { batch: number | null; items: MergeLogEntry[] }[] = [];
  for (const entry of items) {
    const last = groups.at(-1);
    if (last && last.batch !== null && last.batch === entry.batch_id) last.items.push(entry);
    else groups.push({ batch: entry.batch_id, items: [entry] });
  }
  return groups;
}

function RunHead({
  batch,
  busy,
  onUndo,
}: {
  batch: MergeBatchInfo;
  busy: boolean;
  onUndo: () => void;
}) {
  const open = batch.merges - batch.undone;
  return (
    <div className={styles.run}>
      <div>
        <h3 className={styles.runTitle}>
          „Alle sicheren zusammenführen“ vom {formatDateTime(batch.created_at)}
        </h3>
        <p className={styles.meta}>
          {mergeCount(batch.merges)}
          {batch.undone > 0 && `, davon ${formatNumber(batch.undone)} rückgängig gemacht`}
          {batch.editor && ` · ${batch.editor}`}
        </p>
      </div>
      {open > 0 && (
        <Button size="sm" disabled={busy} onClick={onUndo}>
          Ganzen Lauf rückgängig
        </Button>
      )}
    </div>
  );
}

function MergeRow({
  entry,
  busy,
  onUndo,
}: {
  entry: MergeLogEntry;
  busy: boolean;
  onUndo: () => void;
}) {
  const undone = entry.undone_at !== null;
  return (
    <li className={cx(styles.row, undone && styles.undone)}>
      <div className={styles.what}>
        <p className={styles.moved}>
          {entry.moved.map((person) => person.email).join(", ")}
          <span className={styles.arrow}> in </span>
          <PersonLink person={entry.target} />
        </p>
        <p className={styles.meta}>
          {formatDateTime(entry.created_at)}
          {entry.editor && ` · ${entry.editor}`}
          {undone &&
            ` · rückgängig gemacht am ${formatDateTime(entry.undone_at!)}${
              entry.undone_by ? ` von ${entry.undone_by}` : ""
            }`}
        </p>
      </div>
      {!undone && (
        <Button size="sm" disabled={busy} onClick={onUndo}>
          Rückgängig
        </Button>
      )}
    </li>
  );
}
