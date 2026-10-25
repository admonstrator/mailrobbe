import { useId, useState, type ReactNode } from "react";
import { Link } from "react-router";

import { useAdoptAiTag, useAiSummary, useDiscardAi, useEnqueueAi } from "../../api/queries";
import type {
  AiAttachmentSummary,
  AiJob,
  AiQueued,
  AiQueueRequest,
  AiSummaryParams,
  AiSummaryResult,
  AiSummaryTheme,
  AiSummaryView,
  AiTagAdopted,
  AiTagCount,
  AiTarget,
} from "../../api/types";
import { Button } from "../../components/Button";
import { FoldCard } from "../../components/FoldCard";
import { formatNumber } from "../../lib/format";
import { setFoldOpen, useFold } from "../../lib/folds";
import { documentName } from "../documents/labels";
import { documentPath } from "../documents/urlState";
import { StepList } from "../import/StepList";
import { DEFAULT_LIST_STATE, listSearch } from "../mails/listState";
import { Dialog } from "../persons/Dialog";
import { SummarizeBox } from "./AiBox";
import { AiBusy } from "./AiBusy";
import {
  aiErrorText,
  mailCount,
  partsText,
  preworkText,
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
 *  or an element that can be summarised now. */
function shown(view: AiSummaryView): boolean {
  if (view.result || view.task || view.failed || view.attachments.length > 0) return true;
  return view.available && view.summarizable;
}

/** A theme hint with the attachment whose summary found it; null: the element's own. */
export interface SourcedHint {
  hint: AiSummaryTheme;
  source: AiAttachmentSummary | null;
}

/** Tags shown before "+n weitere". */
export const TAGS_SHOWN = 6;

/** The tags of a mail's summary and of its attachments' summaries, each once, the mail's first
 *  (D331). */
export function mergedTags(view: AiSummaryView): AiTagCount[] {
  const tags = new Map<number, AiTagCount>();
  for (const tag of [
    view.result?.tags ?? [],
    ...view.attachments.map((a) => a.result.tags),
  ].flat()) {
    if (!tags.has(tag.id)) tags.set(tag.id, tag);
  }
  return [...tags.values()];
}

const ownHints = (result: AiSummaryResult): SourcedHint[] =>
  result.themes.map((hint) => ({ hint, source: null }));

/** The theme hints of a mail's attachments, each with its attachment (D331). */
export function attachmentHints(view: AiSummaryView): SourcedHint[] {
  return view.attachments.flatMap((source) =>
    source.result.themes.map((hint) => ({ hint, source })),
  );
}

/** The card "KI-Zusammenfassung" of a mail (above its text) or a document (above its text card),
 *  D307: the summary with model and date, as machine made (D311), its tags with the mails each
 *  describes, its theme hints with their quotes; "Neu zusammenfassen" and "Verwerfen"; an open
 *  task's progress, asked again every 3 s. Without a summary the light blue block "KI-Zusammenfassung
 *  erstellen" (D352) stands in the card, or alone in its place when there is nothing else to show. A mail's card gathers the tags and
 *  hints of its attachments' summaries too, a hint naming its attachment, which onAttachment opens;
 *  the summaries themselves stand in the attachment list (D331). A thread's summary is a line in
 *  the mail's head that opens to the whole (D331). Nothing while loading or failing to load, and
 *  nothing with neither a summary nor a text service. */
export function SummaryCard({
  target,
  id,
  threadSize,
  onQuote,
  onAttachment,
}: {
  target: AiTarget;
  id: number;
  /** The mails of the thread, for its line. */
  threadSize?: number;
  /** A quote's link was followed: the page shows the text it marks. */
  onQuote?: () => void;
  /** The attachment of a hint was chosen, by its document. */
  onAttachment?: (documentId: number) => void;
}) {
  const summary = useAiSummary(summaryParams(target, id));
  const enqueue = useEnqueueAi();
  const [dialog, setDialog] = useState<"again" | "discard" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const view = summary.data;
  if (!view || !shown(view)) return null;

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
        setNotice(startedNotice(queued, target));
        setFoldOpen(foldId, true);
      },
      onError: (error) => {
        setDialog(null);
        setNotice(aiErrorText(error));
        setFoldOpen(foldId, true);
      },
    });

  const alone =
    target !== "thread" && !result && !view.failed && !view.attachments.length && !preparing;
  if (offered && alone) {
    return (
      <>
        <SummarizeBox disabled={enqueue.isPending} onClick={queue} />
        {notice && (
          <p className={styles.note} role="status">
            {notice}
          </p>
        )}
      </>
    );
  }

  const tags = target === "mail" ? mergedTags(view) : (result?.tags ?? []);
  const hints = [
    ...(result ? ownHints(result) : []),
    ...(target === "mail" ? attachmentHints(view) : []),
  ];
  const gathered = target === "mail" ? view.attachments.length : 0;
  const content = (
    <>
      <div className={styles.card}>
        {result ? (
          <SummaryBlock
            result={result}
            tags={tags}
            hints={hints}
            mailId={mailId}
            quoteTo={quoteTo}
            onQuote={onQuote}
            onSource={onAttachment}
          />
        ) : (
          !task &&
          (offered && target !== "thread" ? (
            <SummarizeBox
              failed={Boolean(view.failed)}
              disabled={enqueue.isPending}
              onClick={queue}
            />
          ) : (
            <p className={styles.note}>{NONE_YET[target]}</p>
          ))
        )}
        {!result && (tags.length > 0 || hints.length > 0) && (
          <div className={styles.summary}>
            {tags.length > 0 && <TagList tags={tags} mailId={mailId} />}
            {hints.length > 0 && (
              <HintList
                hints={hints}
                mailId={mailId}
                quoteTo={quoteTo}
                onQuote={onQuote}
                onSource={onAttachment}
              />
            )}
          </div>
        )}
        {gathered > 0 && <p className={styles.note}>{gatheredText(gathered)}</p>}
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
    </>
  );
  if (target === "thread") {
    const start =
      !result && offered ? (
        <Button size="sm" disabled={enqueue.isPending} onClick={queue}>
          Zusammenfassen
        </Button>
      ) : null;
    return (
      <ThreadLine
        foldId={foldId}
        size={threadSize}
        teaser={view.task || result ? foldedText(view) : NONE_YET.thread}
        action={start}
      >
        {content}
      </ThreadLine>
    );
  }
  return (
    <FoldCard id={foldId} variant="main" title="KI-Zusammenfassung" summary={foldedText(view)}>
      {content}
    </FoldCard>
  );
}

/** "Schlagwörter und Hinweise auch aus 3 Anhängen; ihre Zusammenfassungen stehen in der Liste der
 *  Anhänge." */
function gatheredText(count: number): string {
  const from = count === 1 ? "einem Anhang" : `${formatNumber(count)} Anhängen`;
  const theirs = count === 1 ? "seine Zusammenfassung steht" : "ihre Zusammenfassungen stehen";
  return `Schlagwörter und Hinweise auch aus ${from}; ${theirs} in der Liste der Anhänge.`;
}

/** A thread's summary as a line in the mail's head (D331): its size, the beginning of the summary
 *  or what is under way, and "Mehr" for the whole card's content, remembered like a block. */
function ThreadLine({
  foldId,
  size,
  teaser,
  action,
  children,
}: {
  foldId: string;
  size?: number;
  teaser: string;
  action: ReactNode;
  children: ReactNode;
}) {
  const [open, setOpen] = useFold(foldId, false);
  const bodyId = useId();
  return (
    <section className={styles.thread} aria-label="KI-Zusammenfassung des Threads">
      <div className={styles.threadHead}>
        <span className={styles.threadTitle}>
          {size ? `Thread · ${formatNumber(size)} Mails` : "Thread"}
        </span>
        <span className={styles.ki} title="Maschinell erzeugte Zusammenfassung">
          KI
        </span>
        {!open && <span className={styles.teaser}>{teaser}</span>}
        <span className={styles.threadTools}>
          {action}
          <Button
            size="xs"
            variant="link"
            aria-expanded={open}
            aria-controls={open ? bodyId : undefined}
            onClick={() => setOpen(!open)}
          >
            {open ? "Weniger" : "Mehr"}
          </Button>
        </span>
      </div>
      {open && <div id={bodyId}>{children}</div>}
    </section>
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

/** One summary: the machine line, the text, how much of it was read, tags and theme hints; a
 *  mail's card passes the tags and hints it gathered from the attachments too. */
export function SummaryBlock({
  result,
  tags = result.tags,
  hints = ownHints(result),
  mailId,
  quoteTo,
  onQuote,
  onSource,
}: {
  result: AiSummaryResult;
  tags?: AiTagCount[];
  hints?: SourcedHint[];
  /** The mail its tags can be adopted for (D310); none on a document's or thread's card. */
  mailId?: number;
  /** Where a quote is shown with its words marked: the mail's text, the thread's mails. */
  quoteTo?: (quote: string) => string;
  onQuote?: () => void;
  onSource?: (documentId: number) => void;
}) {
  const parts = partsText(result);
  return (
    <div className={styles.summary}>
      <p className={styles.line}>{summaryLine(result)}</p>
      {result.summary && <p className={styles.text}>{result.summary}</p>}
      {result.short && <p className={styles.note}>{SHORT_SUMMARY_TEXT}</p>}
      {parts && <p className={styles.note}>{parts}</p>}
      {tags.length > 0 && <TagList tags={tags} mailId={mailId} />}
      {hints.length > 0 && (
        <HintList
          hints={hints}
          mailId={mailId}
          quoteTo={quoteTo}
          onQuote={onQuote}
          onSource={onSource}
        />
      )}
    </div>
  );
}

/** Theme hints with their quotes; one found in an attachment names it, a button when the page
 *  can open it, else a link to its document. */
function HintList({
  hints,
  mailId,
  quoteTo,
  onQuote,
  onSource,
}: {
  hints: SourcedHint[];
  mailId?: number;
  quoteTo?: (quote: string) => string;
  onQuote?: () => void;
  onSource?: (documentId: number) => void;
}) {
  return (
    <ul className={styles.hints}>
      {hints.map(({ hint, source }, index) => (
        <li key={`${source?.document_id ?? "own"}-${hint.theme}-${index}`}>
          <span className={styles.theme}>{`Hinweis: ${hint.label}`}</span>{" "}
          {hint.quote &&
            (quoteTo ? (
              <Link
                to={quoteTo(hint.quote)}
                title={
                  mailId === undefined ? "Die Mails mit diesem Zitat" : "Im Text der Mail zeigen"
                }
                onClick={mailId === undefined ? undefined : onQuote}
              >
                {`„${hint.quote}“`}
              </Link>
            ) : (
              <span>{`„${hint.quote}“`}</span>
            ))}
          {source && (
            <>
              {" · "}
              {onSource ? (
                <button
                  type="button"
                  className={styles.source}
                  title="Den Anhang mit Vorschau und Angaben öffnen"
                  onClick={() => onSource(source.document_id)}
                >
                  {documentName(source.name)}
                </button>
              ) : (
                <Link to={documentPath(source.document_id)}>{documentName(source.name)}</Link>
              )}
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

/** The tags of a summary, each a link to the mails it describes, the first TAGS_SHOWN and the
 *  rest on request; on a mail each can become a team tag of this mail (D310), its "+" showing on
 *  hover and focus (D331). */
function TagList({ tags, mailId }: { tags: AiTagCount[]; mailId?: number }) {
  const adopt = useAdoptAiTag();
  const [notice, setNotice] = useState<string | null>(null);
  const [all, setAll] = useState(false);
  const hidden = all ? 0 : Math.max(0, tags.length - TAGS_SHOWN);
  return (
    <div className={styles.tagField}>
      <ul className={styles.tags} aria-label="Schlagwörter">
        {tags.slice(0, tags.length - hidden).map((tag) => (
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
        {(hidden > 0 || all) && tags.length > TAGS_SHOWN && (
          <li>
            <Button variant="link" size="xs" onClick={() => setAll(!all)}>
              {all ? "weniger" : `+${formatNumber(hidden)} weitere`}
            </Button>
          </li>
        )}
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

/** "Die Zusammenfassung läuft … Erst ist Vorarbeit nötig: …" after a button started it (D348). */
export function startedNotice(queued: AiQueued, target: AiTarget): string {
  const started = summaryStartedText(queued, target);
  const before = queued.prework && preworkText(queued.prework, 1);
  return before ? `${before} ${started}` : started;
}

/** The summary of an attachment's document in the attachment's dialog, where the mail's view had
 *  none (D348): the summary once there, the running task with its time, or the light blue block
 *  "KI-Zusammenfassung erstellen" (D352) for
 *  a document with a text or one OCR or the transcriber reads first, which the notice says with
 *  how long it takes. Asked again every 3 s while its task is open, so it shows without a
 *  reload. */
export function DocumentSummary({
  documentId,
  mailId,
  recognizable,
}: {
  documentId: number;
  mailId: number;
  recognizable: boolean;
}) {
  const summary = useAiSummary(summaryParams("document", documentId));
  const enqueue = useEnqueueAi();
  const [notice, setNotice] = useState<string | null>(null);
  const view = summary.data;
  if (!view) return <p className={styles.note}>Noch keine Zusammenfassung.</p>;
  if (view.result && !view.task) return <SummaryBlock result={view.result} mailId={mailId} />;
  const offered = view.available && (view.summarizable || recognizable);
  const queue = () =>
    enqueue.mutate(summaryRequest("document", documentId), {
      onSuccess: (queued) => setNotice(startedNotice(queued, "document")),
      onError: (error) => setNotice(aiErrorText(error)),
    });
  return (
    <div className={styles.card}>
      {view.task ? (
        <AiBusy
          what={summaryTaskText(view.task)}
          from={view.task.started_at ?? view.task.queued_at}
        />
      ) : offered ? (
        <SummarizeBox
          failed={Boolean(view.failed)}
          hint={
            view.summarizable
              ? undefined
              : "Die Datei wird zuerst gelesen, dann zusammengefasst; kann irren"
          }
          disabled={enqueue.isPending}
          onClick={queue}
        />
      ) : (
        <p className={styles.note}>
          {view.failed ? "Der letzte Versuch ist fehlgeschlagen." : "Noch keine Zusammenfassung."}
        </p>
      )}
      {notice && (
        <p className={styles.note} role="status">
          {notice}
        </p>
      )}
    </div>
  );
}
