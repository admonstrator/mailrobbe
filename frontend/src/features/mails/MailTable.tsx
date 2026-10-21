import type { MouseEvent } from "react";
import { Link, useNavigate } from "react-router";

import { useResearch } from "../../api/queries";
import type { MailHitCounts, MailListItem, PersonRef, TagRef } from "../../api/types";
import { DkimDot } from "../../components/DkimDot";
import { CalendarIcon, CopyIcon, FlagIcon, NoteIcon, PaperclipIcon } from "../../components/icons";
import { PersonLink } from "../../components/PersonLink";
import { cx } from "../../lib/cx";
import { dkimKey } from "../../lib/dkim";
import { formatBytes, formatDateTime, formatNumber } from "../../lib/format";
import { personName } from "../../lib/person";
import { TAG_PALETTE } from "../../lib/research";
import { EVENT_LABELS } from "./chips";
import type { ColumnChoice } from "./columns";
import styles from "./MailTable.module.css";
import { ReviewMark } from "./ReviewMark";

const personLabel = (person: PersonRef) => personName(person);
const notesLabel = (count: number) => (count === 1 ? "1 Notiz" : `${formatNumber(count)} Notizen`);
const nearLabel = (count: number) =>
  count === 1
    ? "1 weitere nahezu gleiche Mail"
    : `${formatNumber(count)} weitere nahezu gleiche Mails`;

/** Tag dots shown per row; the rest is "+n", all names are in the tooltip. */
const TAG_DOTS = 3;

/** "Jonas Brandt +2": all names for up to two recipients, else the first one and the rest. */
function Recipients({ mail }: { mail: MailListItem }) {
  const { recipients, recipient_count: count } = mail;
  if (count === 0) return <span className={styles.muted}>–</span>;
  const shown = count <= 2 ? recipients : recipients.slice(0, 1);
  const rest = count - shown.length;
  return (
    <span title={recipients.map(personLabel).join(", ") + (count > recipients.length ? " …" : "")}>
      {shown.map(personLabel).join(", ")}
      {rest > 0 && <span className={styles.muted}> +{rest}</span>}
    </span>
  );
}

/** A mail's tags as coloured dots, by the colours and names of the research overview. */
function TagDots({ ids, tags }: { ids: number[]; tags: Map<number, TagRef> }) {
  const names = ids.map((id) => tags.get(id)?.name ?? `Schlagwort #${id}`).join(", ");
  return (
    <span className={styles.tags} role="img" aria-label={`Schlagwörter: ${names}`} title={names}>
      {ids.slice(0, TAG_DOTS).map((id) => {
        const tag = tags.get(id);
        return (
          <span
            key={id}
            className={styles.tagDot}
            style={{ background: TAG_PALETTE[tag?.color ?? "gray"].text }}
          />
        );
      })}
      {ids.length > TAG_DOTS && <span className={styles.more}>+{ids.length - TAG_DOTS}</span>}
    </span>
  );
}

/** The places of MailHitCounts as a row names them, and in its title. */
const HIT_PLACES: readonly [keyof MailHitCounts, string, string][] = [
  ["subject", "Betreff", "im Betreff"],
  ["body", "Text", "im Mailtext"],
  ["attachment", "Anhang", "im Text von Anhängen"],
  ["filename", "Dateiname", "in Dateinamen"],
];

/** Why a mail matched (D176): how often the search words occur where, places without any left
 *  out, so a mail found only through a file name says so. Nothing when none is counted. */
function HitPlaces({ hits }: { hits: MailHitCounts }) {
  const places = HIT_PLACES.filter(([key]) => hits[key] > 0);
  if (places.length === 0) return null;
  const title = places.map(([key, , long]) => `${formatNumber(hits[key])} ${long}`).join(", ");
  return (
    <span className={styles.hitPlaces} title={`Suchwörter: ${title}`}>
      {places.map(([key, label]) => `${label} ${formatNumber(hits[key])}`).join(" · ")}
    </span>
  );
}

/** The title of the mark of D73, or null for none: the search words occur in an attachment.
 *  With the counts of D176 it names where, text or file name, and shows only where they count. */
function attachmentMatch(mail: MailListItem): string | null {
  if (!mail.hits) return mail.attachment_match ? "Suchbegriff steht im Text eines Anhangs" : null;
  const places = [
    ...(mail.hits.attachment > 0 ? ["im Text"] : []),
    ...(mail.hits.filename > 0 ? ["im Dateinamen"] : []),
  ];
  return places.length ? `Suchbegriff steht ${places.join(" und ")} eines Anhangs` : null;
}

/** The checkboxes of the rows: which are selected and how a click changes that. */
export interface TableSelection {
  ids: ReadonlySet<number>;
  onToggle: (id: number, selected: boolean) => void;
  onTogglePage: (selected: boolean) => void;
}

/** One page of the mail list. Each row opens the mail; the subject is the real link, so
 *  middle-click and "open in new tab" work. With a selection, each row has a checkbox, which
 *  selects and never opens. */
export function MailTable({
  items,
  columns,
  detailSearch,
  mboxPath,
  stale,
  selection,
}: {
  items: MailListItem[];
  columns: ColumnChoice;
  /** Query string the detail links carry, so the detail knows the list around it. */
  detailSearch: string;
  mboxPath: (id: number) => string;
  stale: boolean;
  selection?: TableSelection;
}) {
  const navigate = useNavigate();
  const research = useResearch();
  const tags = new Map(research.data?.tags.map((tag) => [tag.id, tag]));
  const href = (id: number) => `/mails/${id}${detailSearch ? `?${detailSearch}` : ""}`;
  const selectedOnPage = selection ? items.filter((mail) => selection.ids.has(mail.id)).length : 0;

  function openRow(event: MouseEvent<HTMLTableRowElement>, id: number) {
    const target = event.target as HTMLElement;
    if (target.closest("a, button, input, label") || window.getSelection()?.toString()) return;
    void navigate(href(id));
  }

  return (
    <div className={styles.frame}>
      <div className={styles.scroll}>
        <table className={cx(styles.table, stale && styles.stale)}>
          <thead>
            <tr>
              {selection && (
                <th className={styles.selectCol}>
                  <label className={styles.selectLabel}>
                    <input
                      type="checkbox"
                      aria-label="Alle Mails dieser Seite auswählen"
                      checked={selectedOnPage > 0 && selectedOnPage === items.length}
                      ref={(box) => {
                        if (box)
                          box.indeterminate = selectedOnPage > 0 && selectedOnPage < items.length;
                      }}
                      onChange={(event) => selection.onTogglePage(event.target.checked)}
                    />
                  </label>
                </th>
              )}
              <th className={styles.dkimCol}>DKIM</th>
              <th className={styles.fromCol}>Von</th>
              {columns.to && <th className={styles.toCol}>An</th>}
              <th>Betreff</th>
              {columns.attachment && (
                <th className={styles.iconCol}>
                  <span className="sr-only">Anhang</span>
                </th>
              )}
              {columns.size && <th className={styles.sizeCol}>Größe</th>}
              {columns.mbox && <th>MBOX-Datei</th>}
              <th className={styles.dateCol}>Datum</th>
            </tr>
          </thead>
          <tbody>
            {items.map((mail) => {
              const selected = selection?.ids.has(mail.id) ?? false;
              const inAttachment = attachmentMatch(mail);
              return (
                <tr
                  key={mail.id}
                  className={cx(selected && styles.selected)}
                  onClick={(event) => openRow(event, mail.id)}
                >
                  {selection && (
                    <td className={styles.select}>
                      <label className={styles.selectLabel}>
                        <input
                          type="checkbox"
                          aria-label={`Auswählen: ${mail.subject || "(kein Betreff)"}`}
                          checked={selected}
                          onChange={(event) => selection.onToggle(mail.id, event.target.checked)}
                        />
                      </label>
                    </td>
                  )}
                  <td>
                    <DkimDot status={dkimKey(mail.dkim_status)} />
                  </td>
                  <td className={styles.from}>
                    {mail.sender ? (
                      <>
                        <PersonLink person={mail.sender} className={styles.name} />
                        {mail.sender.name && (
                          <span className={styles.address} title={mail.sender.email}>
                            {mail.sender.email}
                          </span>
                        )}
                      </>
                    ) : (
                      <span className={styles.muted}>(unbekannt)</span>
                    )}
                  </td>
                  {columns.to && (
                    <td className={styles.to}>
                      <Recipients mail={mail} />
                    </td>
                  )}
                  <td className={styles.subject}>
                    <ReviewMark status={mail.review ?? "unreviewed"} />
                    <Link
                      to={href(mail.id)}
                      className={cx(styles.subjectLink, !mail.subject && styles.muted)}
                    >
                      {mail.subject || "(kein Betreff)"}
                    </Link>
                    {mail.flagged && (
                      <FlagIcon size={13} label="Markiert" className={styles.flag} />
                    )}
                    {mail.is_duplicate && (
                      <CopyIcon size={13} label="Duplikat" className={styles.duplicate} />
                    )}
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
                    {mail.event && (
                      <CalendarIcon
                        size={13}
                        label={`Termin: ${EVENT_LABELS[mail.event]}`}
                        className={cx(styles.event, mail.event === "cancel" && styles.eventCancel)}
                      />
                    )}
                    {(mail.tags.length > 0 || mail.notes > 0) && (
                      <span className={styles.research}>
                        {mail.tags.length > 0 && <TagDots ids={mail.tags} tags={tags} />}
                        {mail.notes > 0 && (
                          <span
                            className={styles.notes}
                            role="img"
                            aria-label={notesLabel(mail.notes)}
                            title={notesLabel(mail.notes)}
                          >
                            <NoteIcon size={13} />
                            {formatNumber(mail.notes)}
                          </span>
                        )}
                      </span>
                    )}
                    {mail.hits && <HitPlaces hits={mail.hits} />}
                  </td>
                  {columns.attachment && (
                    <td className={styles.icon}>
                      {mail.has_attachments && <PaperclipIcon size={14} label="Anhang" />}
                      {inAttachment && (
                        <span className={styles.inAttachment} title={inAttachment}>
                          im Anhang
                        </span>
                      )}
                    </td>
                  )}
                  {columns.size && <td className={styles.size}>{formatBytes(mail.size)}</td>}
                  {columns.mbox && <td className={styles.mbox}>{mboxPath(mail.mbox_file_id)}</td>}
                  <td className={styles.date}>{mail.date ? formatDateTime(mail.date) : "–"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
