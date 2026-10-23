import { useState } from "react";
import { Link } from "react-router";

import { useAdoptAiTag, useAiSummary, useDiscardAi, useEnqueueAi } from "../../api/queries";
import type {
  AiJob,
  AiQueueRequest,
  AiSummaryParams,
  AiSummaryResult,
  AiSummaryView,
  AiTagAdopted,
  AiTagCount,
  AiTarget,
} from "../../api/types";
import { Button } from "../../components/Button";
import { FoldCard } from "../../components/FoldCard";
import { formatNumber } from "../../lib/format";
import { setFoldOpen } from "../../lib/folds";
import { documentName } from "../documents/labels";
import { documentPath } from "../documents/urlState";
import { StepList } from "../import/StepList";
import { DEFAULT_LIST_STATE, listSearch } from "../mails/listState";
import { Dialog } from "../persons/Dialog";
import {
  aiErrorText,
  mailCount,
  partsText,
  SHORT_SUMMARY_TEXT,
  summaryLine,
  summaryStartedText,
  summaryTaskText,
} from "./labels";
import styles from "./SummaryCard.module.css";

/** The summary of one mail, document or thread (by its thread_id) as GET /api/ai/summary names
 *  it; the card and the button beside the download share it. */
export function summaryParams(target: AiTarget, id: number): AiSummaryParams {
  return { [target]: id };
}

/** Summarise one element now: first in the queue, a run of its own (D307); a mail takes its
 *  attachments along, their text recognised first where none is (D317). */
export function summaryRequest(target: AiTarget, id: number): AiQueueRequest {
  const ids = {
    mail: { mail_ids: [id] },
    document: { document_ids: [id] },
    thread: { thread_ids: [id] },
  };
  return { kind: "summarize", ...ids[target], single: true, start: true };
}

/** The mail list of the mails an AI tag describes (D309). */
export function aiTagHref(tag: AiTagCount): string {
  return `/mails?ai_tag=${tag.id}`;
}

function phrase(quote: string): string {
  return `"${quote.replaceAll('"', " ").trim()}"`;
}

/** The mail with the words of a quote marked in its text: the quote as a phrase search. */
export function quoteHref(mailId: number, quote: string): string {
  return `/mails/${mailId}?${listSearch({ ...DEFAULT_LIST_STATE, q: phrase(quote) })}`;
}

/** The mails of a thread holding a quote of its summary (D316). */
export function threadQuoteHref(threadId: number, quote: string): string {
  return `/mails?${listSearch({ ...DEFAULT_LIST_STATE, thread: threadId, q: phrase(quote) })}`;
}

const NONE_YET: Record<AiTarget, string> = {
  mail: "Noch keine Zusammenfassung dieser Mail.",
  document: "Noch keine Zusammenfassung dieses Dokuments.",
  thread: "Noch keine Zusammenfassung dieses Threads.",
};

/** Whether the card shows: a summary, an open or failed task, a mail's attachments' summaries,
 *  or a mail that can be summarised now. A document offers it beside its download instead. */
function shown(view: AiSummaryView, target: AiTarget): boolean {
  if (view.result || view.task || view.failed || view.attachments.length > 0) return true;
  return target !== "document" && view.available && view.summarizable;
}

/** The card "KI-Zusammenfassung" of a mail (above its text) or a document (above its text card),
 *  D307: the summary with model and date, as machine made (D311), its tags with the mails each
 *  describes, its theme hints with their quotes, a mail's attachments' summaries; "Zusammenfassen",
 *  "Neu zusammenfassen" and "Verwerfen"; an open task's progress, asked again every 3 s. Nothing
 *  while loading or failing to load, and nothing with neither a summary nor a text service. */
export function SummaryCard({
  target,
  id,
  onQuote,
}: {
  target: AiTarget;
  id: number;
  /** A quote's link was followed: the page shows the text it marks. */
  onQuote?: () => void;
}) {
  const summary = useAiSummary(summaryParams(target, id));
  const enqueue = useEnqueueAi();
  const [dialog, setDialog] = useState<"again" | "discard" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const view = summary.data;
  if (!view || !shown(view, target)) return null;

  const foldId = `${target}.summary`;
  const { result, task } = view;
  const offered = view.available && view.summarizable && !task;
  const mailId = target === "mail" ? id : undefined;
  const quoteTo =
    target === "mail"
      ? (quote: string) => quoteHref(id, quote)
      : target === "thread"
        ? (quote: string) => threadQuoteHref(id, quote)
        : undefined;
  const preparing = view.preparing ?? 0;
  const queue = () =>
    enqueue.mutate(summaryRequest(target, id), {
      onSuccess: (queued) => {
        setDialog(null);
        setNotice(summaryStartedText(queued, target));
        setFoldOpen(foldId, true);
      },
      onError: (error) => {
        setDialog(null);
        setNotice(aiErrorText(error));
        setFoldOpen(foldId, true);
      },
    });

  return (
    <FoldCard
      id={foldId}
      variant="main"
      title={target === "thread" ? "KI-Zusammenfassung des Threads" : "KI-Zusammenfassung"}
      summary={foldedText(view)}
      actions={
        !result &&
        offered && (
          <Button size="sm" disabled={enqueue.isPending} onClick={queue}>
            Zusammenfassen
          </Button>
        )
      }
    >
      <div className={styles.card}>
        {result ? (
          <SummaryBlock result={result} mailId={mailId} quoteTo={quoteTo} onQuote={onQuote} />
        ) : (
          !task && <p className={styles.note}>{NONE_YET[target]}</p>
        )}
        {result && view.stale && !task && (
          <p className={styles.note}>
            Seit dieser Zusammenfassung hat sich der Thread geändert: Mails kamen hinzu oder fielen
            weg.
          </p>
        )}
        {(task || preparing > 0) && (
          <div className={styles.task}>
            <p>
              {preparingText(task ? summaryTaskText(task) : null, preparing)}
              {" · "}
              <Link to="/ki">zur Seite „KI“</Link>
            </p>
            {view.run && <RunProgress run={view.run} />}
          </div>
        )}
        {view.failed && (
          <p
            className={styles.warning}
          >{`Die Zusammenfassung ist fehlgeschlagen: ${view.failed}`}</p>
        )}
        {!view.available && (
          <p className={styles.note}>
            Kein Textmodell eingerichtet, siehe <Link to="/einstellungen">Einstellungen</Link>.
          </p>
        )}
        {result && !task && (
          <div className={styles.actions}>
            {offered && (
              <Button size="sm" onClick={() => setDialog("again")}>
                Neu zusammenfassen
              </Button>
            )}
            <Button size="sm" variant="link" onClick={() => setDialog("discard")}>
              Verwerfen
            </Button>
          </div>
        )}
        {notice && (
          <p className={styles.note} role="status">
            {notice}
          </p>
        )}
        {view.attachments.length > 0 && (
          <section className={styles.attachments} aria-label="Zusammenfassungen der Anhänge">
            <h3 className={styles.heading}>Anhänge</h3>
            {view.attachments.map((attachment) => (
              <div key={attachment.document_id} className={styles.attachment}>
                <Link to={documentPath(attachment.document_id)} className={styles.name}>
                  {documentName(attachment.name)}
                </Link>
                <SummaryBlock result={attachment.result} mailId={mailId} />
              </div>
            ))}
          </section>
        )}
      </div>
      {dialog === "again" && (
        <AgainDialog
          target={target}
          pending={enqueue.isPending}
          onQueue={queue}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog === "discard" && result && (
        <DiscardDialog
          target={target}
          resultId={result.id}
          onClose={() => setDialog(null)}
          onDone={setNotice}
        />
      )}
    </FoldCard>
  );
}

/** Folded: the summary's beginning, its tags, or what is under way. */
function foldedText(view: AiSummaryView): string {
  if (view.task) return summaryTaskText(view.task);
  if (view.result) {
    return view.result.summary || view.result.tags.map((tag) => tag.label).join(", ");
  }
  const count = view.attachments.length;
  if (count > 0) return `${formatNumber(count)} ${count === 1 ? "Anhang" : "Anhänge"}`;
  return "noch keine";
}

/** What is under way: the element's own task and its attachments' (D317). */
function preparingText(task: string | null, preparing: number): string {
  if (preparing === 0) return task ?? "";
  const attachments = `${formatNumber(preparing)} ${preparing === 1 ? "Anhang wird" : "Anhänge werden"} erkannt oder zusammengefasst`;
  return task ? `${task} · ${attachments}` : attachments;
}

/** The live AI run's steps with their bars (D318): what this card waits for, done or to come;
 *  the steps it skips are left out. */
function RunProgress({ run }: { run: AiJob }) {
  const steps = run.progress.steps.filter(
    (step) => step.status !== "skipped" && step.key !== "check",
  );
  return (
    <div className={styles.progress}>
      {run.progress.current && (
        <p className={styles.current}>{`In Arbeit: ${run.progress.current}`}</p>
      )}
      {steps.length > 0 && (
        <StepList
          steps={steps}
          alive={run.alive}
          age={run.report_age_seconds}
          database={run.progress.database}
          kind="ai"
        />
      )}
    </div>
  );
}

/** One summary: the machine line, the text, how much of it was read, tags and theme hints. */
function SummaryBlock({
  result,
  mailId,
  quoteTo,
  onQuote,
}: {
  result: AiSummaryResult;
  /** The mail its tags can be adopted for (D310); none on a document's or thread's card. */
  mailId?: number;
  /** Where a quote is shown with its words marked: the mail's text, the thread's mails. */
  quoteTo?: (quote: string) => string;
  onQuote?: () => void;
}) {
  const parts = partsText(result);
  return (
    <div className={styles.summary}>
      <p className={styles.line}>{summaryLine(result)}</p>
      {result.summary && <p className={styles.text}>{result.summary}</p>}
      {result.short && <p className={styles.note}>{SHORT_SUMMARY_TEXT}</p>}
      {parts && <p className={styles.note}>{parts}</p>}
      {result.tags.length > 0 && <TagList tags={result.tags} mailId={mailId} />}
      {result.themes.length > 0 && (
        <ul className={styles.hints}>
          {result.themes.map((hint, index) => (
            <li key={`${hint.theme}-${index}`}>
              <span className={styles.theme}>{`Hinweis: ${hint.label}`}</span>{" "}
              {hint.quote &&
                (quoteTo ? (
                  <Link
                    to={quoteTo(hint.quote)}
                    title={
                      mailId === undefined
                        ? "Die Mails mit diesem Zitat"
                        : "Im Text der Mail zeigen"
                    }
                    onClick={mailId === undefined ? undefined : onQuote}
                  >
                    {`„${hint.quote}“`}
                  </Link>
                ) : (
                  <span>{`„${hint.quote}“`}</span>
                ))}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The tags of a summary, each a link to the mails it describes; on a mail each can become a
 *  team tag of this mail (D310). */
function TagList({ tags, mailId }: { tags: AiTagCount[]; mailId?: number }) {
  const adopt = useAdoptAiTag();
  const [notice, setNotice] = useState<string | null>(null);
  return (
    <div className={styles.tagField}>
      <ul className={styles.tags} aria-label="Schlagwörter">
        {tags.map((tag) => (
          <li key={tag.id} className={styles.tag}>
            <Link to={aiTagHref(tag)} title={`${mailCount(tag.mails)} mit diesem Schlagwort`}>
              {tag.label}
            </Link>
            <span className={styles.count}>{formatNumber(tag.mails)}</span>
            {mailId !== undefined && (
              <button
                type="button"
                className={styles.adopt}
                title="Als Team-Tag übernehmen"
                aria-label={`„${tag.label}“ als Team-Tag übernehmen`}
                disabled={adopt.isPending}
                onClick={() =>
                  adopt.mutate(
                    { tagId: tag.id, mail_id: mailId },
                    {
                      onSuccess: (adopted) => setNotice(adoptedText(tag.label, adopted)),
                      onError: (error) => setNotice(aiErrorText(error)),
                    },
                  )
                }
              >
                +
              </button>
            )}
          </li>
        ))}
      </ul>
      {notice && (
        <p className={styles.note} role="status">
          {notice}
        </p>
      )}
    </div>
  );
}

function adoptedText(label: string, adopted: AiTagAdopted): string {
  if (adopted.created) return `Team-Tag „${label}“ angelegt und dieser Mail gegeben.`;
  if (adopted.mails > 0) return `Diese Mail hat jetzt den Team-Tag „${label}“.`;
  return `Diese Mail hat den Team-Tag „${label}“ schon.`;
}

function AgainDialog({
  target,
  pending,
  onQueue,
  onClose,
}: {
  target: AiTarget;
  pending: boolean;
  onQueue: () => void;
  onClose: () => void;
}) {
  return (
    <Dialog title="Neu zusammenfassen?" onClose={onClose}>
      <p className={styles.dialogText}>
        {`Ein KI-Lauf fasst ${target === "mail" ? "die Mail" : "das Dokument"} gleich noch einmal zusammen. Die neue Zusammenfassung ersetzt die bisherige erst, wenn sie da ist; bis dahin bleibt die bisherige stehen.`}
      </p>
      <div className={styles.foot}>
        <Button onClick={onClose}>Abbrechen</Button>
        <Button variant="primary" disabled={pending} onClick={onQueue}>
          Jetzt zusammenfassen
        </Button>
      </div>
    </Dialog>
  );
}

function DiscardDialog({
  target,
  resultId,
  onClose,
  onDone,
}: {
  target: AiTarget;
  resultId: number;
  onClose: () => void;
  onDone: (notice: string) => void;
}) {
  const discard = useDiscardAi();
  return (
    <Dialog title="Zusammenfassung verwerfen?" onClose={onClose}>
      <p className={styles.dialogText}>
        {`Die Zusammenfassung ${target === "mail" ? "der Mail" : "des Dokuments"} verschwindet mit ihren Schlagwörtern und Hinweisen, auch aus den Filtern der Mailliste. Sie bleibt als verworfen auf der Seite „KI“ verzeichnet.`}
      </p>
      {discard.error && (
        <p className={styles.warning} role="alert">
          {aiErrorText(discard.error)}
        </p>
      )}
      <div className={styles.foot}>
        <Button onClick={onClose}>Abbrechen</Button>
        <Button
          variant="primary"
          disabled={discard.isPending}
          onClick={() =>
            discard.mutate(
              { result: resultId },
              {
                onSuccess: () => {
                  onDone("Die Zusammenfassung ist verworfen.");
                  onClose();
                },
              },
            )
          }
        >
          Verwerfen
        </Button>
      </div>
    </Dialog>
  );
}

/** "Zusammenfassen" beside a document's download and in its narrow bar (D307): for a document
 *  with a text and no summary yet while a text service is usable; starts a run for just this
 *  document, whose card then follows it. */
export function SummarizeButton({ documentId, size }: { documentId: number; size?: "sm" }) {
  const summary = useAiSummary(summaryParams("document", documentId));
  const enqueue = useEnqueueAi();
  const [notice, setNotice] = useState<string | null>(null);
  const view = summary.data;
  if (!view || !view.available || !view.summarizable || view.result || view.task) return null;
  return (
    <>
      <Button
        size={size}
        disabled={enqueue.isPending}
        title={notice ?? "Fasst den Text des Dokuments jetzt mit dem Textmodell zusammen"}
        onClick={() =>
          enqueue.mutate(summaryRequest("document", documentId), {
            onSuccess: (queued) => setNotice(summaryStartedText(queued, "document")),
            onError: (error) => setNotice(aiErrorText(error)),
          })
        }
      >
        Zusammenfassen
      </Button>
      {notice && size === undefined && (
        <span className={styles.note} role="status">
          {notice}
        </span>
      )}
    </>
  );
}
