import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";

import {
  useAiSummary,
  useChangeMailCollections,
  useCreateCollection,
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
import { documentName } from "../documents/labels";
import { AttachmentDialog } from "../mail/AttachmentDialog";
import { TextView } from "../mail/BodyCard";
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
  const summary = ai.data?.result?.summary;

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

      {summary && (
        <p className={styles.summary}>
          <span className={styles.summaryLabel} title="Von einem Sprachmodell; kann irren">
            KI-Kurzfassung
          </span>{" "}
          {summary}
        </p>
      )}

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

/** "an Anna Keller, Jonas Brandt und 4 weitere", a line per role. */
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
