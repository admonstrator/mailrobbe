import type { MouseEvent } from "react";
import { Link } from "react-router";

import { useResearch, useSaveMark } from "../../api/queries";
import type { MailListItem, PersonRef, TagRef } from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { DkimDot } from "../../components/DkimDot";
import { Highlighted, type SearchMarks } from "../../components/Highlighted";
import {
  CalendarIcon,
  CheckIcon,
  CopyIcon,
  NewWindowIcon,
  NoteIcon,
  PaperclipIcon,
  StarIcon,
} from "../../components/icons";
import { cx } from "../../lib/cx";
import { dkimKey } from "../../lib/dkim";
import { formatBytes, formatDateTime, formatNumber } from "../../lib/format";
import { formatListDate } from "../../lib/listDate";
import { personName } from "../../lib/person";
import { TAG_PALETTE } from "../../lib/research";
import { EVENT_LABELS } from "./chips";
import type { ColumnChoice } from "./columns";
import { hitPlaces } from "./hitPlaces";
import styles from "./MailRows.module.css";
import { ReviewMark } from "./ReviewMark";

export type Density = "comfortable" | "compact";

/** The checkboxes of the rows: which are selected and how a click changes that. */
export interface RowSelection {
  ids: ReadonlySet<number>;
  onToggle: (id: number, selected: boolean) => void;
}

const notesLabel = (count: number) => (count === 1 ? "1 Notiz" : `${formatNumber(count)} Notizen`);
const nearLabel = (count: number) =>
  count === 1
    ? "1 weitere nahezu gleiche Mail"
    : `${formatNumber(count)} weitere nahezu gleiche Mails`;

/** Tag dots shown per row; the rest is "+n", all names are in the tooltip. */
const TAG_DOTS = 3;

/** "an Jonas Brandt, Eva Roth", "an Jonas Brandt +2" for more than two recipients. */
function recipientsText(mail: MailListItem): string | null {
  const { recipients, recipient_count: count } = mail;
  if (count === 0) return null;
  const shown = count <= 2 ? recipients : recipients.slice(0, 1);
  const rest = count - shown.length;
  return `an ${shown.map((person: PersonRef) => personName(person)).join(", ")}${rest > 0 ? ` +${rest}` : ""}`;
}

/** The title of the mark of D73, or null for none: the search words occur in an attachment.
 *  With the counts of D176 it names where, text or file name, and shows only where they count. */
export function attachmentMatch(mail: MailListItem): string | null {
  if (!mail.hits) return mail.attachment_match ? "Suchbegriff steht im Text eines Anhangs" : null;
  const places = [
    ...(mail.hits.attachment > 0 ? ["im Text"] : []),
    ...(mail.hits.filename > 0 ? ["im Dateinamen"] : []),
  ];
  if (!places.length) return null;
  const machine = mail.attachment_transcript
    ? ", maschinell transkribiert (KI)"
    : mail.attachment_machine
      ? ", maschinell erkannt (KI)"
      : "";
  return `Suchbegriff steht ${places.join(" und ")} eines Anhangs${machine}`;
}

/** A mail's tags as coloured dots, by the colours and names of the research overview. */
function TagDots({ ids, tags }: { ids: number[]; tags: Map<number, TagRef> }) {
  const names = ids.map((id) => tags.get(id)?.name ?? `Schlagwort #${id}`).join(", ");
  return (
    <span className={styles.tags} role="img" aria-label={`Schlagwörter: ${names}`} title={names}>
      {ids.slice(0, TAG_DOTS).map((id) => (
        <span
          key={id}
          className={styles.tagDot}
          style={{ background: TAG_PALETTE[tags.get(id)?.color ?? "gray"].text }}
        />
      ))}
      {ids.length > TAG_DOTS && <span className={styles.more}>+{ids.length - TAG_DOTS}</span>}
    </span>
  );
}

/** One page of the mail list as rows of a mail program (D335): checkbox, review mark and star,
 *  avatar, sender, subject with the search words marked and the places of the hits or the
 *  recipients, the marks, the DKIM dot and a short date, which quick actions replace on hover.
 *  A click on a row opens the mail's preview (onOpen); the subject is the real link to the
 *  detail, so a middle click or Ctrl-click opens it in a new tab. */
export function MailRows({
  items,
  detailHref,
  marks,
  openId,
  onOpen,
  narrow,
  density,
  columns,
  mboxPath,
  stale,
  selection,
}: {
  items: MailListItem[];
  detailHref: (id: number) => string;
  /** The words of the list's search, marked in the subjects. */
  marks: SearchMarks | undefined;
  /** The mail shown in the preview. */
  openId: number | null;
  onOpen: (id: number) => void;
  /** A panel stands beside the list: the rows leave out the second text. */
  narrow: boolean;
  density: Density;
  columns: Pick<ColumnChoice, "size" | "mbox">;
  mboxPath: (id: number) => string;
  stale: boolean;
  selection: RowSelection;
}) {
  const research = useResearch();
  const tags = new Map(research.data?.tags.map((tag) => [tag.id, tag]));
  return (
    <ul
      className={cx(
        styles.rows,
        stale && styles.stale,
        narrow && styles.narrow,
        density === "compact" && styles.compact,
      )}
      aria-label="Mails"
    >
      {items.map((mail) => (
        <Row
          key={mail.id}
          mail={mail}
          href={detailHref(mail.id)}
          marks={marks}
          open={mail.id === openId}
          onOpen={onOpen}
          selected={selection.ids.has(mail.id)}
          onSelect={(on) => selection.onToggle(mail.id, on)}
          tags={tags}
          columns={columns}
          mboxPath={mboxPath}
        />
      ))}
    </ul>
  );
}

function Row({
  mail,
  href,
  marks,
  open,
  onOpen,
  selected,
  onSelect,
  tags,
  columns,
  mboxPath,
}: {
  mail: MailListItem;
  href: string;
  marks: SearchMarks | undefined;
  open: boolean;
  onOpen: (id: number) => void;
  selected: boolean;
  onSelect: (selected: boolean) => void;
  tags: Map<number, TagRef>;
  columns: Pick<ColumnChoice, "size" | "mbox">;
  mboxPath: (id: number) => string;
}) {
  const save = useSaveMark(mail.id);
  const pending = save.isPending ? save.variables : undefined;
  const flagged = pending?.flagged ?? mail.flagged;
  const review = (pending && "review" in pending ? pending.review : mail.review) ?? "unreviewed";
  const subject = mail.subject || "(kein Betreff)";
  const inAttachment = attachmentMatch(mail);
  const places = mail.hits && hitPlaces(mail.hits);
  const recipients = recipientsText(mail);
  const sender = mail.sender ? personName(mail.sender) : "(unbekannt)";

  function openRow(event: MouseEvent<HTMLLIElement>) {
    const target = event.target as HTMLElement;
    if (target.closest("a, button, input, label") || window.getSelection()?.toString()) return;
    onOpen(mail.id);
  }

  return (
    <li
      className={cx(
        styles.row,
        selected && styles.selected,
        open && styles.open,
        review === "unreviewed" && styles.unreviewed,
      )}
      data-mail-row
      aria-current={open ? "true" : undefined}
      onClick={openRow}
    >
      <label className={styles.check}>
        <input
          type="checkbox"
          aria-label={`Auswählen: ${subject}`}
          checked={selected}
          onChange={(event) => onSelect(event.target.checked)}
        />
      </label>
      <ReviewMark status={review} />
      <button
        type="button"
        className={cx(styles.star, flagged && styles.starred)}
        aria-label="Merken"
        aria-pressed={flagged}
        title={flagged ? "Gemerkt; Klick nimmt es zurück" : "Merken"}
        onClick={() => save.mutate({ flagged: !flagged })}
      >
        <StarIcon size={17} filled={flagged} strokeWidth={1.8} />
      </button>
      <span className={styles.avatar}>
        {mail.sender && (
          <Avatar
            personId={mail.sender.person_id}
            name={mail.sender.name}
            email={mail.sender.email}
          />
        )}
      </span>
      <span className={cx(styles.sender, !mail.sender && styles.muted)} title={mail.sender?.email}>
        {sender}
      </span>
      <span className={styles.text}>
        <Link
          to={href}
          data-subject
          className={cx(styles.subject, !mail.subject && styles.muted)}
          onClick={(event) => {
            // A plain click previews; Ctrl, Shift, Meta or the middle button open the detail.
            if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey) return;
            event.preventDefault();
            onOpen(mail.id);
          }}
        >
          {mail.subject ? <Highlighted text={mail.subject} marks={marks} /> : subject}
        </Link>
        {places ? (
          <span className={styles.second}>
            {" – Treffer: "}
            <span title={places.title}>{places.label}</span>
          </span>
        ) : (
          recipients && <span className={styles.second}>{` – ${recipients}`}</span>
        )}
      </span>
      <span className={styles.marks}>
        {mail.is_duplicate && <CopyIcon size={14} label="Duplikat" className={styles.quiet} />}
        {mail.near_count > 0 && (
          <span
            className={styles.near}
            role="img"
            aria-label={nearLabel(mail.near_count)}
            title={nearLabel(mail.near_count)}
          >
            +{formatNumber(mail.near_count)}
          </span>
        )}
        {mail.tags.length > 0 && <TagDots ids={mail.tags} tags={tags} />}
        {mail.notes > 0 && (
          <span
            className={styles.notes}
            role="img"
            aria-label={notesLabel(mail.notes)}
            title={notesLabel(mail.notes)}
          >
            <NoteIcon size={14} />
            {formatNumber(mail.notes)}
          </span>
        )}
        {inAttachment && (
          <span className={styles.inAttachment} title={inAttachment}>
            {mail.attachment_transcript
              ? "im Anhang · transkribiert"
              : mail.attachment_machine
                ? "im Anhang · maschinell erkannt"
                : "im Anhang"}
          </span>
        )}
        {mail.event && (
          <CalendarIcon
            size={15}
            label={`Termin: ${EVENT_LABELS[mail.event]}`}
            className={cx(styles.quiet, mail.event === "cancel" && styles.cancel)}
          />
        )}
        {mail.has_attachments && (
          <PaperclipIcon size={15} label="Anhang" className={styles.quiet} />
        )}
        {columns.size && <span className={styles.extra}>{formatBytes(mail.size)}</span>}
        {columns.mbox && (
          <span className={cx(styles.extra, styles.mbox)} title={mboxPath(mail.mbox_file_id)}>
            {mboxPath(mail.mbox_file_id)}
          </span>
        )}
        <DkimDot status={dkimKey(mail.dkim_status)} size={8} />
      </span>
      <span className={styles.end}>
        <span className={styles.date} title={mail.date ? formatDateTime(mail.date) : undefined}>
          {mail.date ? formatListDate(mail.date) : "–"}
        </span>
        <span className={styles.quick}>
          <button
            type="button"
            className={styles.action}
            aria-label={review === "seen" ? "Gesichtet zurücknehmen" : "Als gesichtet markieren"}
            title={review === "seen" ? "Gesichtet zurücknehmen" : "Gesichtet"}
            aria-pressed={review === "seen"}
            onClick={() => save.mutate({ review: review === "seen" ? null : "seen" })}
          >
            <CheckIcon size={16} />
          </button>
          <a
            href={href}
            target="_blank"
            rel="noopener"
            className={styles.action}
            aria-label="In neuem Fenster öffnen"
            title="In neuem Fenster öffnen"
          >
            <NewWindowIcon size={16} />
          </a>
        </span>
      </span>
    </li>
  );
}
