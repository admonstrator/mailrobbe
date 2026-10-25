import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";

import {
  useAiSummary,
  useChangeMailCollections,
  useCreateCollection,
  useEnqueueAi,
  useMailBody,
  useMailDetail,
  useMailNeighbors,
  useMailSignals,
  useResearch,
  useSaveMark,
  useThemes,
} from "../../api/queries";
import {
  NAME_LIMIT,
  type AiSummaryResult,
  type AiSummaryView,
  type AttachmentInfo,
  type MailDetail,
  type MailOrderParams,
} from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { buttonClass } from "../../components/Button";
import { DkimBadge } from "../../components/DkimBadge";
import type { SearchMarks } from "../../components/Highlighted";
import {
  ChevronDownIcon,
  ChevronUpIcon,
  NewWindowIcon,
  PaperclipIcon,
} from "../../components/icons";
import { PersonLink } from "../../components/PersonLink";
import { SidePanel } from "../../components/SidePanel";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { dkimKey } from "../../lib/dkim";
import { formatBytes, formatDateTime } from "../../lib/format";
import { personName } from "../../lib/person";
import { AiBar, AiBox, SummarizeBox } from "../ai/AiBox";
import { aiErrorText, summaryTaskText } from "../ai/labels";
import { startedNotice, summaryRequest } from "../ai/SummaryCard";
import { documentName } from "../documents/labels";
import { AttachmentDialog } from "../mail/AttachmentDialog";
import { ShowStandardOption, TextView } from "../mail/BodyCard";
import { LinkField } from "../mail/LinkField";
import { NoteList } from "../mail/NoteList";
import { signalName, signalThemeInfo } from "../signals/labels";
import styles from "./MailPreview.module.css";

const ROLE_WORDS = { to: "an", cc: "Cc", bcc: "Bcc" } as const;
/** Recipients named per role before "und n weitere". */
const NAMES_SHOWN = 3;

/** The mail of a row in the panel beside the list (D335): "Ganz öffnen" leads to the detail
 *  with the list's state, "In neuem Fenster" opens it in a new tab, the arrows step through the
 *  list's order. Below: subject, DKIM and signals, sender and recipients, date, the AI summary's
 *  line, the text with its quotes folded, the attachments, and the marks of the research file. */
export function MailPreview({
  id,
  detailHref,
  order,
  marks,
  onStep,
  onClose,
}: {
  id: number;
  detailHref: (id: number) => string;
  order: MailOrderParams;
  marks: SearchMarks | undefined;
  onStep: (id: number) => void;
  onClose: () => void;
}) {
  const detail = useMailDetail(id);
  const neighbors = useMailNeighbors(id, order);
  const prevId = neighbors.data?.prev_id ?? null;
  const nextId = neighbors.data?.next_id ?? null;
  const body = useRef<HTMLDivElement>(null);

  // A new mail starts at its top.
  useEffect(() => {
    body.current?.closest("[data-panel-body]")?.scrollTo?.({ top: 0 });
  }, [id]);

  const actions = (
    <>
      <Link to={detailHref(id)} className={buttonClass("primary", "sm")}>
        Ganz öffnen
      </Link>
      <a
        href={detailHref(id)}
        target="_blank"
        rel="noopener"
        className={styles.icon}
        aria-label="In neuem Fenster öffnen"
        title="In neuem Fenster öffnen"
      >
        <NewWindowIcon size={17} />
      </a>
      <button
        type="button"
        className={styles.icon}
        aria-label="Vorige Mail"
        title="Vorige Mail (k)"
        disabled={prevId === null}
        onClick={() => prevId !== null && onStep(prevId)}
      >
        <ChevronUpIcon size={18} />
      </button>
      <button
        type="button"
        className={styles.icon}
        aria-label="Nächste Mail"
        title="Nächste Mail (j)"
        disabled={nextId === null}
        onClick={() => nextId !== null && onStep(nextId)}
      >
        <ChevronDownIcon size={18} />
      </button>
    </>
  );

  return (
    <SidePanel
      label="Vorschau"
      actions={actions}
      onClose={onClose}
      movable
      className={styles.panel}
    >
      <div ref={body}>
        {detail.isPending ? (
          <div className={styles.loading}>
            <Spinner label="Mail wird geladen" />
          </div>
        ) : detail.isError ? (
          <p className={styles.error} role="alert">
            Die Mail konnte nicht geladen werden.
          </p>
        ) : (
          <PreviewBody key={id} mail={detail.data} marks={marks} />
        )}
      </div>
    </SidePanel>
  );
}

function PreviewBody({ mail, marks }: { mail: MailDetail; marks: SearchMarks | undefined }) {
  const sender = mail.participants.find((person) => person.role === "from");
  const text = useMailBody(mail.id, "text", true);
  const ai = useAiSummary({ mail: mail.id });
  const [opened, setOpened] = useState<AttachmentInfo | null>(null);
  const summaries = useMemo(
    () =>
      new Map<number, AiSummaryResult>(
        (ai.data?.attachments ?? []).map(({ document_id, result }) => [document_id, result]),
      ),
    [ai.data],
  );

  return (
    <div className={styles.body}>
      <h2 className={cx(styles.subject, !mail.subject && styles.muted)}>
        {mail.subject || "(kein Betreff)"}
      </h2>
      <div className={styles.badges}>
        <DkimBadge status={dkimKey(mail.dkim.status)} />
        <SignalBadges mailId={mail.id} />
      </div>

      <div className={styles.people}>
        {sender && <Avatar personId={sender.person_id} name={sender.name} email={sender.email} />}
        <div className={styles.names}>
          {sender ? (
            <div className={styles.from}>
              <PersonLink person={sender} className={styles.sender} />{" "}
              {sender.name && <span className={styles.address}>{sender.email}</span>}
            </div>
          ) : (
            <div className={styles.muted}>Absender unbekannt</div>
          )}
          <Recipients mail={mail} />
        </div>
        {mail.date && <span className={styles.date}>{formatDateTime(mail.date)}</span>}
      </div>

      {ai.data && <PreviewSummary mailId={mail.id} view={ai.data} />}

      <ShowStandardOption />
      <div className={styles.text}>
        {text.data ? (
          <TextView data={text.data} marks={marks} />
        ) : text.isError ? (
          <p className={styles.error} role="alert">
            Der Text konnte nicht gelesen werden.
          </p>
        ) : (
          <Spinner label="Wird aus der MBOX-Datei gelesen" />
        )}
      </div>

      {mail.attachments.length > 0 && (
        <ul className={styles.attachments} aria-label="Anhänge">
          {mail.attachments.map((attachment) => (
            <li key={attachment.id}>
              <button
                type="button"
                className={styles.attachment}
                title="Ansehen"
                onClick={() => setOpened(attachment)}
              >
                <PaperclipIcon size={15} />
                <span className={styles.fileName}>{documentName(attachment.filename)}</span>
                <span className={styles.fileSize}>{formatBytes(attachment.size)}</span>
              </button>
              <AttachmentSummaryLine
                attachment={attachment}
                summary={
                  attachment.document_id === null
                    ? undefined
                    : summaries.get(attachment.document_id)
                }
                available={ai.data?.available ?? false}
              />
            </li>
          ))}
        </ul>
      )}
      {opened && (
        <AttachmentDialog
          mail={mail}
          attachment={opened}
          summaries={summaries}
          marks={marks}
          onOpen={setOpened}
        />
      )}

      <PreviewActions mail={mail} />
    </div>
  );
}

/** "1:05": minutes and seconds since an ISO time. */
function since(iso: string, now: number): string {
  const seconds = Math.max(0, Math.floor((now - Date.parse(iso)) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** The AI summary right below the participants (D345) in the light blue block (D352): the
 *  summary, the running task with the time it has taken, ticking every second, or "KI-Zusammenfassung
 *  erstellen". useAiSummary asks again every 3 s while a task is open, so the text shows when it is
 *  there, without a reload. */
function PreviewSummary({ mailId, view }: { mailId: number; view: AiSummaryView }) {
  const enqueue = useEnqueueAi();
  const [now, setNow] = useState(Date.now);
  const task = view.task;
  const preparing = view.preparing ?? 0;
  const busy = task !== null || preparing > 0;
  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  if (view.result && !task) {
    return (
      <AiBox heading="KI-Zusammenfassung" note="vom Sprachmodell, kann irren">
        <p className={styles.summaryText}>{view.result.summary}</p>
      </AiBox>
    );
  }
  if (busy) {
    const from = task?.started_at ?? task?.queued_at;
    const what = task ? summaryTaskText(task) : "Anhänge werden erst erkannt oder zusammengefasst";
    return (
      <AiBox heading="KI-Zusammenfassung wird erstellt" busy>
        <AiBar />
        <span className={styles.summaryNote}>
          {from ? `${what} · KI rechnet seit ${since(from, now)} Min.` : what}
        </span>
      </AiBox>
    );
  }
  if (!view.available || !view.summarizable) return null;
  return (
    <div>
      <SummarizeBox
        failed={Boolean(view.failed)}
        disabled={enqueue.isPending}
        onClick={() =>
          enqueue.mutate({ kind: "summarize", mail_ids: [mailId], single: true, start: true })
        }
      />
      {enqueue.isError && (
        <p className={styles.error} role="alert">
          {aiErrorText(enqueue.error)}
        </p>
      )}
    </div>
  );
}

function Recipients({ mail }: { mail: MailDetail }) {
  return (["to", "cc", "bcc"] as const).map((role) => {
    const people = mail.participants.filter((person) => person.role === role);
    if (people.length === 0) return null;
    const shown = people.slice(0, NAMES_SHOWN).map((person) => personName(person));
    const rest = people.length - shown.length;
    return (
      <div key={role} className={styles.recipients} title={people.map((p) => p.email).join(", ")}>
        {ROLE_WORDS[role]} {shown.join(", ")}
        {rest > 0 && ` und ${rest} weitere`}
      </div>
    );
  });
}

function SignalBadges({ mailId }: { mailId: number }) {
  const signals = useMailSignals(mailId);
  const themes = useThemes();
  return signals.data?.signals.map((reason) => (
    <span key={reason.key} className={styles.signal}>
      {signalName(reason.key, signalThemeInfo(reason.key, themes.data)?.name)}
    </span>
  ));
}

/** Gesichtet, Merken, Zur Akte and Notiz: the research file's marks of the mail. */
function PreviewActions({ mail }: { mail: MailDetail }) {
  const save = useSaveMark(mail.id);
  const changeCollections = useChangeMailCollections(mail.id);
  const createCollection = useCreateCollection();
  const research = useResearch();
  const [open, setOpen] = useState<"akte" | "note" | null>(null);
  const pending = save.isPending ? save.variables : undefined;
  const { mark, collections, notes } = mail.research;
  const review = pending && "review" in pending ? (pending.review ?? null) : mark.review;
  const flagged = pending?.flagged ?? mark.flagged;
  const toggle = (which: "akte" | "note") => setOpen(open === which ? null : which);

  async function addNewCollection(name: string) {
    try {
      const collection = await createCollection.mutateAsync({ name });
      changeCollections.mutate({ add: [collection.id] });
    } catch {
      // the field keeps the name; the error stands below
    }
  }

  return (
    <div className={styles.actions}>
      <div className={styles.buttons}>
        <button
          type="button"
          className={buttonClass(review === "seen" ? "outline" : "default", "sm")}
          aria-pressed={review === "seen"}
          onClick={() => save.mutate({ review: review === "seen" ? null : "seen" })}
        >
          Gesichtet
        </button>
        <button
          type="button"
          className={buttonClass(flagged ? "outline" : "default", "sm")}
          aria-pressed={flagged}
          onClick={() => save.mutate({ flagged: !flagged })}
        >
          {flagged ? "Gemerkt" : "Merken"}
        </button>
        <button
          type="button"
          className={buttonClass("default", "sm")}
          aria-expanded={open === "akte"}
          onClick={() => toggle("akte")}
        >
          Zur Akte …
        </button>
        <button
          type="button"
          className={buttonClass("default", "sm")}
          aria-expanded={open === "note"}
          onClick={() => toggle("note")}
        >
          Notiz{notes.length > 0 ? ` (${notes.length})` : ""}
        </button>
      </div>
      {(save.isError || changeCollections.isError || createCollection.isError) && (
        <p className={styles.error} role="alert">
          Nicht gespeichert. Bitte noch einmal versuchen.
        </p>
      )}
      {open === "akte" && (
        <LinkField
          label="Akten"
          addLabel="Zu Akte hinzufügen"
          removeLabel="Aus Akte entfernen"
          createLabel={(name) => `Neue Akte „${name}“ anlegen`}
          items={collections}
          known={research.data?.collections ?? []}
          maxLength={NAME_LIMIT}
          href={(collection) => `/akten/${collection}`}
          onAdd={(collection) => changeCollections.mutate({ add: [collection] })}
          onRemove={(collection) => changeCollections.mutate({ remove: [collection] })}
          onCreate={(name) => void addNewCollection(name)}
        />
      )}
      {open === "note" && <NoteList mailId={mail.id} notes={notes} onWritten={() => {}} />}
    </div>
  );
}

/** Below an attachment of the preview (D348): the beginning of its summary, or "Zusammenfassen",
 *  which starts it first in the queue, a scan or a recording read first; the mail's summary
 *  view then asks again while it is under way and shows the summary here once there. */
function AttachmentSummaryLine({
  attachment,
  summary,
  available,
}: {
  attachment: AttachmentInfo;
  summary: AiSummaryResult | undefined;
  available: boolean;
}) {
  const enqueue = useEnqueueAi();
  const [notice, setNotice] = useState<string | null>(null);
  const documentId = attachment.document_id;
  if (summary) {
    return (
      <p className={styles.attachmentSummary} title={summary.summary}>
        <span className={styles.summaryLabel}>KI</span> {summary.summary}
      </p>
    );
  }
  if (documentId === null || !attachment.sha256 || !available) return null;
  return (
    <p className={styles.attachmentSummary}>
      {notice ?? (
        <button
          type="button"
          className={buttonClass("link", "xs")}
          disabled={enqueue.isPending}
          onClick={() =>
            enqueue.mutate(summaryRequest("document", documentId), {
              onSuccess: (queued) => setNotice(startedNotice(queued, "document")),
              onError: (error) => setNotice(aiErrorText(error)),
            })
          }
        >
          KI-Zusammenfassung holen
        </button>
      )}
    </p>
  );
}
