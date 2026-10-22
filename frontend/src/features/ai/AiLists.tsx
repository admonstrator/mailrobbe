import { useState } from "react";
import { Link } from "react-router";

import {
  useAiResults,
  useAiSendLog,
  useAiTaskAction,
  useAiTasks,
  useDiscardAi,
} from "../../api/queries";
import type {
  AiDocumentRef,
  AiResultItem,
  AiResultState,
  AiStatus,
  AiTaskItem,
  AiTaskStatus,
} from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import {
  formatBytes,
  formatClock,
  formatDateTime,
  formatElapsed,
  formatNumber,
} from "../../lib/format";
import { Dialog } from "../persons/Dialog";
import styles from "./AiPage.module.css";
import {
  aiErrorText,
  ENGINE_LABELS,
  engineName,
  pageNumbers,
  queueCounts,
  RESULT_STATE_LABELS,
  TASK_KIND_LABELS,
  TASK_STATUS_LABELS,
  TASK_STATUSES,
  transcriberName,
} from "./labels";

/** "2 von 3 Seiten", "3 Seiten", or "–" when nothing is known. */
function pagesAmount(read: number, total: number | null): string {
  if (total !== null) return `${formatNumber(read)} von ${formatNumber(total)} Seiten`;
  return read > 0 ? `${formatNumber(read)} ${read === 1 ? "Seite" : "Seiten"}` : "–";
}

/** A recording's part read of its length (D293): "1:05 von 3:12", "3:12", or "–". */
function secondsAmount(read: number | null | undefined, length: number | null | undefined): string {
  if (read && length && read < length - 1) return `${formatClock(read)} von ${formatClock(length)}`;
  if (length) return formatClock(length);
  return read ? formatClock(read) : "–";
}

function DocumentCell({ document }: { document: AiDocumentRef | null }) {
  if (!document) return <span className={styles.muted}>gelöscht</span>;
  return (
    <Link to={`/anhaenge/${document.id}`} className={styles.docLink}>
      {document.name || "ohne Namen"}
    </Link>
  );
}

/** A filter button of a list; none pressed shows everything. */
function Toggle({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      className={cx(styles.toggle, active && styles.toggleOn)}
      aria-pressed={active}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

function LoadMore({
  hasNext,
  fetching,
  onMore,
}: {
  hasNext: boolean;
  fetching: boolean;
  onMore: () => void;
}) {
  if (!hasNext) return null;
  return (
    <div className={styles.more}>
      <Button size="sm" disabled={fetching} onClick={onMore}>
        {fetching ? "Wird geladen …" : "Mehr laden"}
      </Button>
    </div>
  );
}

// Queue -----------------------------------------------------------------------------------------

/** The tasks (D186): by status, with retry and cancel one by one or all at once. */
export function QueueCard({ status, alive }: { status: AiStatus; alive: boolean }) {
  const [filter, setFilter] = useState<AiTaskStatus[]>([]);
  const tasks = useAiTasks({ status: filter }, alive);
  const retry = useAiTaskAction("retry");
  const cancel = useAiTaskAction("cancel");
  // Text recognition and transcription share the queue (D295).
  const counts = queueCounts(status.queue);
  const transcriber = transcriberName(status.transcription?.model ?? null);
  const items = tasks.data?.pages.flatMap((page) => page.items) ?? [];
  const error = retry.error ?? cancel.error;
  const toggle = (value: AiTaskStatus) =>
    setFilter(filter.includes(value) ? filter.filter((s) => s !== value) : [...filter, value]);

  return (
    <Card aria-labelledby="ai-queue-title">
      <div className={styles.cardHead}>
        <CardTitle id="ai-queue-title">Warteschlange</CardTitle>
        <div className={styles.headActions}>
          {counts.failed > 0 && (
            <Button
              size="sm"
              disabled={retry.isPending}
              onClick={() => retry.mutate({ all: true })}
            >
              {`Alle fehlgeschlagenen erneut (${formatNumber(counts.failed)})`}
            </Button>
          )}
          {counts.waiting > 0 && (
            <Button
              size="sm"
              variant="link"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate({ all: true })}
            >
              {`Alle vorgemerkten abbrechen (${formatNumber(counts.waiting)})`}
            </Button>
          )}
        </div>
      </div>
      <div className={styles.chips} role="group" aria-label="Nach Status filtern">
        {TASK_STATUSES.map((value) => (
          <Toggle key={value} active={filter.includes(value)} onClick={() => toggle(value)}>
            {`${TASK_STATUS_LABELS[value]} ${formatNumber(counts[value])}`}
          </Toggle>
        ))}
      </div>
      {error && (
        <p className={styles.warning} role="alert">
          {aiErrorText(error)}
        </p>
      )}
      {tasks.isPending ? (
        <div className={styles.listLoading}>
          <Spinner label="Warteschlange wird geladen" />
        </div>
      ) : tasks.isError ? (
        <p className={styles.warning}>Die Warteschlange konnte nicht geladen werden.</p>
      ) : items.length === 0 ? (
        <EmptyState
          title={
            filter.length ? "Keine Aufträge mit diesem Status." : "Die Warteschlange ist leer."
          }
        >
          Vorgemerkt wird oben in den Arbeitslisten, in der Anhangsliste oder auf der Seite eines
          Dokuments.
        </EmptyState>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Dokument</th>
                <th>Status</th>
                <th>Verfahren</th>
                <th className={styles.num}>Umfang</th>
                <th>Vorgemerkt</th>
                <th>
                  <span className="sr-only">Aktionen</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  transcriber={transcriber}
                  busy={retry.isPending || cancel.isPending}
                  onRetry={() => retry.mutate({ ids: [task.id] })}
                  onCancel={() => cancel.mutate({ ids: [task.id] })}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <LoadMore
        hasNext={Boolean(tasks.hasNextPage)}
        fetching={tasks.isFetchingNextPage}
        onMore={() => void tasks.fetchNextPage()}
      />
    </Card>
  );
}

/** A task: its document, status, kind and engine, how much of it is read (pages, or a
 *  recording's seconds of its length), when and by whom it was queued. */
function TaskRow({
  task,
  transcriber,
  busy,
  onRetry,
  onCancel,
}: {
  task: AiTaskItem;
  transcriber: string;
  busy: boolean;
  onRetry: () => void;
  onCancel: () => void;
}) {
  const transcribe = task.kind === "transcribe";
  const amount = transcribe
    ? secondsAmount(task.seconds_read, task.document?.duration)
    : pagesAmount(task.pages_read, task.pages_total);
  return (
    <tr>
      <td>
        <DocumentCell document={task.document} />
        {task.priority > 0 && <span className={styles.tag}>zuerst</span>}
        {task.error && <span className={styles.technical}>{task.error}</span>}
      </td>
      <td>
        <span className={cx(styles.state, styles[`state_${task.status}`])}>
          {TASK_STATUS_LABELS[task.status]}
        </span>
        {task.attempts > 1 && (
          <span className={styles.muted}>{` · ${formatNumber(task.attempts)} Versuche`}</span>
        )}
      </td>
      <td>
        {transcribe ? transcriber : ENGINE_LABELS[task.engine]}
        <span className={styles.sub}>{TASK_KIND_LABELS[task.kind]}</span>
      </td>
      <td className={styles.num}>{amount}</td>
      <td className={styles.nowrap}>
        {formatDateTime(task.queued_at)}
        {task.queued_by && <span className={styles.muted}>{` · ${task.queued_by}`}</span>}
      </td>
      <td className={styles.rowActions}>
        {(task.status === "failed" || task.status === "cancelled") && (
          <Button size="xs" disabled={busy} onClick={onRetry}>
            Erneut
          </Button>
        )}
        {task.status === "waiting" && (
          <Button size="xs" variant="link" disabled={busy} onClick={onCancel}>
            Abbrechen
          </Button>
        )}
      </td>
    </tr>
  );
}

// Results ---------------------------------------------------------------------------------------

const RESULT_FILTERS: readonly AiResultState[] = ["valid", "replaced", "discarded"];

type DiscardTarget = { result: AiResultItem } | { job: number };

/** The results (D185): what each read, discard one or every valid one of a run. */
export function ResultsCard({ alive }: { alive: boolean }) {
  const [state, setState] = useState<AiResultState[]>([]);
  const [target, setTarget] = useState<DiscardTarget | null>(null);
  const results = useAiResults({ state }, alive);
  const items = results.data?.pages.flatMap((page) => page.items) ?? [];
  const toggle = (value: AiResultState) =>
    setState(state.includes(value) ? state.filter((s) => s !== value) : [...state, value]);

  return (
    <Card aria-labelledby="ai-results-title">
      <CardTitle id="ai-results-title">Ergebnisse</CardTitle>
      <p className={styles.muted}>
        Jeder erkannte Text und jedes Transkript bleibt hier verzeichnet. Verworfen geht es aus der
        Suche, das Dokument bekommt einen früheren Text zurück oder steht wieder ohne Text da.
      </p>
      <div className={styles.chips} role="group" aria-label="Nach Zustand filtern">
        {RESULT_FILTERS.map((value) => (
          <Toggle key={value} active={state.includes(value)} onClick={() => toggle(value)}>
            {RESULT_STATE_LABELS[value]}
          </Toggle>
        ))}
      </div>
      {results.isPending ? (
        <div className={styles.listLoading}>
          <Spinner label="Ergebnisse werden geladen" />
        </div>
      ) : results.isError ? (
        <p className={styles.warning}>Die Ergebnisse konnten nicht geladen werden.</p>
      ) : items.length === 0 ? (
        <EmptyState title="Noch keine Ergebnisse.">
          Sobald ein KI-Lauf ein Dokument gelesen hat, steht es hier.
        </EmptyState>
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Dokument</th>
                <th>Verfahren</th>
                <th className={styles.num}>Umfang</th>
                <th className={styles.num}>Zeichen</th>
                <th>Erstellt</th>
                <th>Zustand</th>
                <th>
                  <span className="sr-only">Aktionen</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((result) => (
                <ResultRow key={result.id} result={result} onDiscard={setTarget} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <LoadMore
        hasNext={Boolean(results.hasNextPage)}
        fetching={results.isFetchingNextPage}
        onMore={() => void results.fetchNextPage()}
      />
      {target && <DiscardDialog target={target} onClose={() => setTarget(null)} />}
    </Card>
  );
}

function ResultRow({
  result,
  onDiscard,
}: {
  result: AiResultItem;
  onDiscard: (target: DiscardTarget) => void;
}) {
  const total = result.pages_total ?? result.pages_read;
  const transcript = result.kind === "transcribe";
  const lines = result.segments ?? 0;
  const uncertain = result.uncertain_segments ?? 0;
  return (
    <tr>
      <td>
        <DocumentCell document={result.document} />
        {transcript && lines > 0 && (
          <span className={styles.sub}>
            {`${formatNumber(lines)} ${lines === 1 ? "Zeile" : "Zeilen"}${uncertain > 0 ? `, davon ${formatNumber(uncertain)} unsicher` : ""}`}
          </span>
        )}
        {result.uncertain.length > 0 && (
          <span className={styles.sub}>{`Unsicher: ${pageNumbers(result.uncertain)}`}</span>
        )}
        {result.failed.length > 0 && (
          <span
            className={styles.warningText}
          >{`Nicht gelesen: ${pageNumbers(result.failed)}`}</span>
        )}
      </td>
      <td>
        {transcript ? transcriberName(result.model) : engineName(result.engine, result.model)}
        {result.remote && <span className={cx(styles.place, styles.remote)}>Internet</span>}
        <span className={styles.sub}>{TASK_KIND_LABELS[result.kind]}</span>
      </td>
      <td className={styles.num}>
        {transcript
          ? secondsAmount(result.transcribed, result.duration)
          : pagesAmount(result.pages_text, total)}
      </td>
      <td className={styles.num}>
        {result.characters > 0
          ? formatNumber(result.characters)
          : transcript
            ? "keine Sprache"
            : "keine Schrift"}
      </td>
      <td className={styles.nowrap}>
        {formatDateTime(result.created_at)}
        <span className={styles.muted}>{` · ${formatElapsed(result.seconds)}`}</span>
        {result.job_id !== null && (
          <span className={styles.muted}>{` · Lauf ${formatNumber(result.job_id)}`}</span>
        )}
      </td>
      <td>
        <span className={cx(styles.state, styles[`result_${result.state}`])}>
          {RESULT_STATE_LABELS[result.state]}
        </span>
        {result.discarded_by && <span className={styles.muted}>{` · ${result.discarded_by}`}</span>}
      </td>
      <td className={styles.rowActions}>
        {result.state === "valid" && (
          <>
            <Button size="xs" variant="link" onClick={() => onDiscard({ result })}>
              Verwerfen
            </Button>
            {result.job_id !== null && (
              <Button size="xs" variant="link" onClick={() => onDiscard({ job: result.job_id! })}>
                ganzen Lauf
              </Button>
            )}
          </>
        )}
      </td>
    </tr>
  );
}

function DiscardDialog({ target, onClose }: { target: DiscardTarget; onClose: () => void }) {
  const discard = useDiscardAi();
  const [done, setDone] = useState<number | null>(null);
  const one = "result" in target;
  return (
    <Dialog
      title={
        !one
          ? "Alle Texte dieses Laufs verwerfen?"
          : target.result.kind === "transcribe"
            ? "Transkript verwerfen?"
            : "Erkannten Text verwerfen?"
      }
      onClose={onClose}
    >
      {done !== null ? (
        <p className={styles.dialogText} role="status">
          {`${formatNumber(done)} ${done === 1 ? "Text" : "Texte"} verworfen.`}
        </p>
      ) : (
        <p className={styles.dialogText}>
          {one
            ? `Der Text von „${target.result.document?.name ?? "ohne Namen"}“ wird aus der Suche genommen; das Dokument bekommt einen früheren Text zurück oder steht wieder ohne Text da.`
            : `Jeder noch gültige Text, den Lauf ${formatNumber(target.job)} erkannt oder transkribiert hat, wird aus der Suche genommen. Das lässt sich nur durch neues Erkennen oder Transkribieren rückgängig machen.`}
        </p>
      )}
      {discard.error && (
        <p className={styles.warning} role="alert">
          {aiErrorText(discard.error)}
        </p>
      )}
      <div className={styles.dialogFoot}>
        {done !== null ? (
          <Button variant="primary" onClick={onClose}>
            Schließen
          </Button>
        ) : (
          <>
            <Button onClick={onClose}>Abbrechen</Button>
            <Button
              variant="primary"
              disabled={discard.isPending}
              onClick={() =>
                discard.mutate(one ? { result: target.result.id } : { job: target.job }, {
                  onSuccess: (changed) => setDone(changed.changed),
                })
              }
            >
              Verwerfen
            </Button>
          </>
        )}
      </div>
    </Dialog>
  );
}

// Sent ------------------------------------------------------------------------------------------

/** What went to a service outside this machine (D181): only shown once something did. */
export function SentCard() {
  const log = useAiSendLog(true);
  const items = log.data?.pages.flatMap((page) => page.items) ?? [];
  const total = log.data?.pages[0]?.total ?? 0;
  return (
    <Card aria-labelledby="ai-sent-title">
      <CardTitle id="ai-sent-title">Gesendet</CardTitle>
      <p className={styles.muted}>
        {`Seitenbilder, die an einen Dienst im Internet gingen: ${formatNumber(total)} ${total === 1 ? "Sendung" : "Sendungen"}. Jede ist hier verzeichnet.`}
      </p>
      {log.isPending ? (
        <div className={styles.listLoading}>
          <Spinner label="Wird geladen" />
        </div>
      ) : log.isError ? (
        <p className={styles.warning}>Die Liste konnte nicht geladen werden.</p>
      ) : items.length === 0 ? (
        <EmptyState title="Nichts gesendet." />
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Gesendet</th>
                <th>Dienst</th>
                <th>Dokument</th>
                <th className={styles.num}>Größe</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td className={styles.nowrap}>{formatDateTime(item.sent_at)}</td>
                  <td className={styles.mono}>{item.service_url}</td>
                  <td>
                    <DocumentCell document={item.document} />
                  </td>
                  <td className={styles.num}>{formatBytes(item.bytes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <LoadMore
        hasNext={Boolean(log.hasNextPage)}
        fetching={log.isFetchingNextPage}
        onMore={() => void log.fetchNextPage()}
      />
    </Card>
  );
}
