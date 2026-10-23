import { useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { ApiError } from "../../api/client";
import {
  useAiStatus,
  useCollection,
  useDeleteCollection,
  useMailDetail,
  useMailPage,
  useResearch,
  useUpdateCollection,
} from "../../api/queries";
import {
  DESCRIPTION_LIMIT,
  NAME_LIMIT,
  type CollectionDetail,
  type MailListItem,
  type TagInfo,
} from "../../api/types";
import { Avatar } from "../../components/Avatar";
import { Button, buttonClass } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { HelpMark } from "../../components/HelpMark";
import { OverflowMenu } from "../../components/OverflowMenu";
import { PersonLink, personPath } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps, type TabItem } from "../../components/Tabs";
import { cx } from "../../lib/cx";
import { formatDate, formatDateTime, formatIsoDay, formatNumber } from "../../lib/format";
import { useRecordVisit } from "../../lib/history";
import { personName } from "../../lib/person";
import { TAG_COLORS, TAG_PALETTE } from "../../lib/research";
import { SummarizeManyDialog } from "../ai/SummarizeManyDialog";
import { ColorChip } from "./ColorChip";
import styles from "./CollectionScreen.module.css";
import { ConfirmDialog } from "./ConfirmDialog";
import { ExportDialog } from "./ExportDialog";
import { InlineEdit } from "./InlineEdit";
import { useInView } from "./useInView";
import { collectionMailsHref, mailCount, searchHref } from "./labels";

type AkteTab = "mails" | "notizen" | "personen";
const AKTE_TABS: readonly AkteTab[] = ["mails", "notizen", "personen"];
const TABS_ID = "akte";

const MONTHS = [
  "Januar",
  "Februar",
  "März",
  "April",
  "Mai",
  "Juni",
  "Juli",
  "August",
  "September",
  "Oktober",
  "November",
  "Dezember",
];

/** /akten/:id: one Akte (D58) with its mails by month, their notes, its persons and figures. */
export function CollectionScreen() {
  const { id } = useParams();
  if (!id || !/^\d+$/.test(id)) {
    return (
      <div className={styles.page}>
        <CollectionNotFound />
      </div>
    );
  }
  return <CollectionView key={id} id={Number(id)} />;
}

function CollectionView({ id }: { id: number }) {
  const collection = useCollection(id);
  return (
    <div className={styles.page}>
      <title>{`${collection.data?.name ?? "Akte"} · Mailrobbe`}</title>
      <nav aria-label="Pfad" className={styles.breadcrumb}>
        <Link to="/akten">Akten</Link>
        {collection.data && (
          <>
            <span aria-hidden="true">/</span>
            <span className={styles.crumb}>{collection.data.name}</span>
          </>
        )}
      </nav>
      {collection.isPending ? (
        <div className={styles.loading}>
          <Spinner label="Akte wird geladen" />
        </div>
      ) : collection.isError ? (
        collection.error instanceof ApiError && collection.error.code === "not_found" ? (
          <CollectionNotFound id={id} />
        ) : (
          <ErrorState
            title="Die Akte konnte nicht geladen werden."
            actions={<Button onClick={() => void collection.refetch()}>Erneut versuchen</Button>}
          >
            Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
          </ErrorState>
        )
      ) : (
        <Collection collection={collection.data} />
      )}
    </div>
  );
}

/** The Akte's colour mark: the API keeps no colour for an Akte, so it follows the id. */
function markColor(id: number): string {
  return TAG_PALETTE[TAG_COLORS[id % TAG_COLORS.length]].text;
}

function parseTab(value: string | null): AkteTab {
  return AKTE_TABS.includes(value as AkteTab) ? (value as AkteTab) : "mails";
}

function Collection({ collection }: { collection: CollectionDetail }) {
  const update = useUpdateCollection();
  const remove = useDeleteCollection();
  const ai = useAiStatus();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [exporting, setExporting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [describe, setDescribe] = useState(0);
  const { id } = collection;
  const tab = parseTab(searchParams.get("tab"));
  // The newest mails, shared by the Mails tab and the tags of the facts column.
  const mails = useMailPage({ collection: [id] });

  useRecordVisit({
    kind: "akte",
    id,
    title: collection.name,
    subtitle: `Akte · ${mailCount(collection.mails)}`,
    path: `/akten/${id}`,
  });

  const setTab = (next: AkteTab) =>
    setSearchParams(next === "mails" ? {} : { tab: next }, { preventScrollReset: true });
  const tabs: TabItem<AkteTab>[] = [
    { id: "mails", label: `Mails ${formatNumber(collection.mails)}` },
    { id: "notizen", label: "Notizen" },
    { id: "personen", label: `Personen ${formatNumber(collection.persons.length)}` },
  ];
  const textUsable = ai.data?.text === true;

  return (
    <>
      <div className={styles.head}>
        <div className={styles.heading}>
          <div className={styles.titleLine}>
            <span className={styles.mark} style={{ background: markColor(id) }} />
            <InlineEdit
              value={collection.name}
              label="Name"
              maxLength={NAME_LIMIT}
              required
              quiet
              onSave={(name) => update.mutateAsync({ id, name })}
            >
              <h1 className={styles.title}>{collection.name}</h1>
            </InlineEdit>
          </div>
          <InlineEdit
            value={collection.description}
            label="Beschreibung"
            multiline
            maxLength={DESCRIPTION_LIMIT}
            quiet
            editRequest={describe}
            onSave={(description) => update.mutateAsync({ id, description })}
          >
            <p className={cx(styles.description, !collection.description && styles.muted)}>
              {collection.description || "Noch keine Beschreibung."}
            </p>
          </InlineEdit>
          <p className={styles.meta}>
            Geändert {formatDateTime(collection.updated_at)}
            {collection.created_by && ` · angelegt von ${collection.created_by}`}
          </p>
        </div>
        <div className={styles.actions}>
          <Link to={collectionMailsHref(id)} className={buttonClass()}>
            In Mailliste öffnen
          </Link>
          <Button variant="primary" onClick={() => setExporting(true)}>
            Exportieren
          </Button>
          <OverflowMenu
            items={[
              {
                label: textUsable ? "Zusammenfassen" : "Zusammenfassen (kein Textmodell)",
                onSelect: () => setSummarizing(true),
                disabled: !textUsable,
              },
              { label: "Beschreibung bearbeiten", onSelect: () => setDescribe((n) => n + 1) },
              {
                label: "Akte löschen …",
                danger: true,
                separated: true,
                onSelect: () => {
                  remove.reset();
                  setDeleting(true);
                },
              },
            ]}
          />
        </div>
      </div>

      <div className={styles.tabs}>
        <Tabs<AkteTab>
          items={tabs}
          active={tab}
          onSelect={setTab}
          idPrefix={TABS_ID}
          label="Bereiche der Akte"
        />
      </div>

      <div className={styles.columns}>
        <div {...tabPanelProps(TABS_ID, tab)} className={styles.main}>
          {tab === "mails" && <MailsTab id={id} page={mails} />}
          {tab === "notizen" && <NotesTab id={id} />}
          {tab === "personen" && <PersonsTab collection={collection} />}
        </div>
        <Facts
          collection={collection}
          items={mails.data?.items}
          onPersons={() => setTab("personen")}
        />
      </div>

      {exporting && (
        <ExportDialog
          selection={{ filters: { collection: [id] } }}
          count={collection.mails}
          label={collection.name}
          onClose={() => setExporting(false)}
        />
      )}
      {summarizing && (
        <SummarizeManyDialog
          selection={{ mail_filters: { collection: [id] } }}
          onClose={() => setSummarizing(false)}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title="Akte löschen"
          confirmLabel="Akte löschen"
          pending={remove.isPending}
          error={remove.error}
          onClose={() => setDeleting(false)}
          onConfirm={() => remove.mutate(id, { onSuccess: () => void navigate("/akten") })}
        >
          Die Akte „{collection.name}“ wird gelöscht. Ihre Mails, Notizen und Schlagworte bleiben;
          nur die Zuordnung zur Akte geht verloren, ihre gespeicherten Suchen gehören danach zu
          keiner Akte.
        </ConfirmDialog>
      )}
    </>
  );
}

type MailPageQuery = ReturnType<typeof useMailPage>;

function monthOf(mail: MailListItem): string {
  if (!mail.date) return "Ohne Datum";
  const [year, month] = formatIsoDay(mail.date).split("-");
  return `${MONTHS[Number(month) - 1]} ${year}`;
}

/** The mails in runs of one month, in the order the API gives them (newest first). */
function byMonth(items: MailListItem[]): { month: string; mails: MailListItem[] }[] {
  const groups: { month: string; mails: MailListItem[] }[] = [];
  for (const mail of items) {
    const month = monthOf(mail);
    const last = groups[groups.length - 1];
    if (last?.month === month) last.mails.push(mail);
    else groups.push({ month, mails: [mail] });
  }
  return groups;
}

function useTagsById(): Map<number, TagInfo> {
  const research = useResearch();
  return new Map((research.data?.tags ?? []).map((tag) => [tag.id, tag]));
}

/** The newest mails of the Akte by month, with their tags and notes; each opens with the Akte
 *  as the list, so Vorherige and Nächste stay inside it. */
function MailsTab({ id, page }: { id: number; page: MailPageQuery }) {
  const tags = useTagsById();
  if (page.isPending) {
    return (
      <div className={styles.loading}>
        <Spinner label="Mails werden geladen" />
      </div>
    );
  }
  if (page.isError) {
    return (
      <ErrorState
        title="Die Mails konnten nicht geladen werden."
        actions={<Button onClick={() => void page.refetch()}>Erneut versuchen</Button>}
      />
    );
  }
  if (page.data.items.length === 0) {
    return (
      <EmptyState title="Noch keine Mail in dieser Akte">
        Mails kommen in der Mailliste oder in der Detailansicht einer Mail in die Akte.
      </EmptyState>
    );
  }
  return (
    <div className={styles.timeline}>
      {byMonth(page.data.items).map(({ month, mails }) => (
        <section key={month} className={styles.month} aria-label={month}>
          <h2 className={styles.monthTitle}>{month}</h2>
          <ul className={styles.monthMails}>
            {mails.map((mail) => (
              <MailRow key={mail.id} mail={mail} listQuery={`collection=${id}`} tags={tags} />
            ))}
          </ul>
        </section>
      ))}
      {page.data.next_cursor && (
        <Link to={collectionMailsHref(id)} className={styles.moreLink}>
          Weitere in der Mailliste ›
        </Link>
      )}
    </div>
  );
}

function MailRow({
  mail,
  listQuery,
  tags,
}: {
  mail: MailListItem;
  listQuery: string;
  tags: Map<number, TagInfo>;
}) {
  const marked = mail.notes > 0 || mail.review === "relevant" || mail.flagged;
  return (
    <li className={styles.mailRow}>
      <span className={cx(styles.dot, marked && styles.dotMarked)} aria-hidden="true" />
      {mail.sender ? (
        <Avatar
          personId={mail.sender.person_id}
          name={mail.sender.name}
          email={mail.sender.email}
          size="sm"
        />
      ) : (
        <span className={styles.noAvatar} aria-hidden="true" />
      )}
      <div className={styles.mailBody}>
        <div className={styles.mailLine}>
          <span className={styles.mailSender}>
            {mail.sender ? <PersonLink person={mail.sender} /> : "(unbekannt)"}
          </span>
          <span className={styles.mailDate}>{mail.date ? formatDate(mail.date) : "–"}</span>
        </div>
        <Link
          to={`/mails/${mail.id}?${listQuery}`}
          className={cx(styles.mailSubject, !mail.subject && styles.muted)}
        >
          {mail.subject || "(ohne Betreff)"}
        </Link>
        {mail.notes > 0 && <MailNotes mailId={mail.id} count={mail.notes} first />}
      </div>
      {mail.tags.length > 0 && (
        <span className={styles.mailTags}>
          {mail.tags.map((tagId) => {
            const tag = tags.get(tagId);
            return tag ? (
              <ColorChip key={tagId} color={tag.color}>
                {tag.name}
              </ColorChip>
            ) : null;
          })}
        </span>
      )}
    </li>
  );
}

/** The notes of one mail, loaded once the row is on screen: the first one in a row of the
 *  timeline, all of them in the Notizen tab. */
function MailNotes({
  mailId,
  count,
  first = false,
}: {
  mailId: number;
  count: number;
  first?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const seen = useInView(ref);
  const detail = useMailDetail(mailId, seen);
  const notes = detail.data?.research.notes ?? [];
  const shown = first ? notes.slice(0, 1) : notes;
  return (
    <div ref={ref} className={styles.notes}>
      {notes.length === 0 ? (
        <p className={styles.note}>{count === 1 ? "1 Notiz" : `${formatNumber(count)} Notizen`}</p>
      ) : (
        shown.map((note) =>
          first ? (
            <p key={note.id} className={styles.note}>
              <span className={styles.noteBy}>
                {note.author ? `Notiz ${note.author}: ` : "Notiz: "}
              </span>
              {note.body}
            </p>
          ) : (
            <div key={note.id} className={styles.noteFull}>
              <span className={styles.noteBy}>
                {note.author ?? "Ohne Namen"} · {formatDate(note.updated_at)}
              </span>
              <p className={styles.noteBody}>{note.body}</p>
            </div>
          ),
        )
      )}
      {first && notes.length > 1 && (
        <span className={styles.noteMore}>
          und {notes.length - 1 === 1 ? "1 weitere" : `${formatNumber(notes.length - 1)} weitere`}
        </span>
      )}
    </div>
  );
}

/** The mails of the Akte that carry notes, each with its notes. */
function NotesTab({ id }: { id: number }) {
  const page = useMailPage({ collection: [id], has_note: true });
  if (page.isPending) {
    return (
      <div className={styles.loading}>
        <Spinner label="Notizen werden geladen" />
      </div>
    );
  }
  if (page.isError) {
    return (
      <ErrorState
        title="Die Notizen konnten nicht geladen werden."
        actions={<Button onClick={() => void page.refetch()}>Erneut versuchen</Button>}
      />
    );
  }
  if (page.data.items.length === 0) {
    return (
      <EmptyState title="Noch keine Notiz in dieser Akte">
        Notizen entstehen in der Detailansicht einer Mail und gelten für die Mail, nicht für die
        Akte.
      </EmptyState>
    );
  }
  return (
    <div className={styles.noteList}>
      <ul className={styles.notedMails}>
        {page.data.items.map((mail) => (
          <li key={mail.id} className={styles.notedMail}>
            <div className={styles.mailLine}>
              <Link
                to={`/mails/${mail.id}?collection=${id}&has_note=true`}
                className={cx(styles.mailSubject, !mail.subject && styles.muted)}
              >
                {mail.subject || "(ohne Betreff)"}
              </Link>
              <span className={styles.mailDate}>
                {mail.sender ? personName(mail.sender) : "(unbekannt)"}
                {mail.date && ` · ${formatDate(mail.date)}`}
              </span>
            </div>
            <MailNotes mailId={mail.id} count={mail.notes} />
          </li>
        ))}
      </ul>
      {page.data.next_cursor && (
        <Link to={`/mails?collection=${id}&has_note=true`} className={styles.moreLink}>
          Weitere in der Mailliste ›
        </Link>
      )}
    </div>
  );
}

function PersonsTab({ collection }: { collection: CollectionDetail }) {
  if (collection.persons.length === 0) {
    return <p className={styles.muted}>Noch keine Personen, die Akte hat keine Mail.</p>;
  }
  return (
    <ul className={styles.personGrid} aria-label="Beteiligte Personen">
      {collection.persons.map(({ person, mails }) => (
        <li key={person.person_id} className={styles.personCard}>
          <Avatar personId={person.person_id} name={person.name} email={person.email} />
          <span className={styles.personText}>
            <PersonLink person={person} className={styles.personName} />
            <span className={styles.personCount}>
              {formatNumber(mails)} {mails === 1 ? "Mail" : "Mails"} in dieser Akte
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

const SHOWN_AVATARS = 8;

/** The quiet column of facts: period, mails, persons, tags of the newest mails, searches. */
function Facts({
  collection,
  items,
  onPersons,
}: {
  collection: CollectionDetail;
  items: MailListItem[] | undefined;
  onPersons: () => void;
}) {
  const tags = useTagsById();
  const counts = new Map<number, number>();
  for (const mail of items ?? []) {
    for (const tagId of mail.tags) counts.set(tagId, (counts.get(tagId) ?? 0) + 1);
  }
  const tagged = [...counts]
    .map(([tagId, n]) => ({ tag: tags.get(tagId), n }))
    .filter((entry): entry is { tag: TagInfo; n: number } => entry.tag !== undefined)
    .sort((a, b) => b.n - a.n || a.tag.name.localeCompare(b.tag.name, "de"));
  const { id, persons } = collection;

  return (
    <aside className={styles.facts} aria-label="Über diese Akte">
      <section className={styles.factSection}>
        <h2 className={styles.factTitle}>Über diese Akte</h2>
        <dl className={styles.factList}>
          <div>
            <dt>Zeitraum</dt>
            <dd>
              {collection.date_min && collection.date_max
                ? `${formatDate(collection.date_min)} bis ${formatDate(collection.date_max)}`
                : "–"}
            </dd>
          </div>
          <div>
            <dt>Mails</dt>
            <dd>{formatNumber(collection.mails)}</dd>
          </div>
          {collection.missing > 0 && (
            <div>
              <dt>
                Nicht im Archiv
                <HelpMark text="Mails der Akte, deren Inhalt keine Mail des Archivs (mehr) hat, etwa nach einem neuen Import" />
              </dt>
              <dd>{formatNumber(collection.missing)}</dd>
            </div>
          )}
          <div>
            <dt>Angelegt</dt>
            <dd>{formatDate(collection.created_at)}</dd>
          </div>
        </dl>
      </section>

      <section className={styles.factSection}>
        <div className={styles.factHead}>
          <h2 className={styles.factTitle}>Beteiligte</h2>
          {persons.length > 0 && (
            <Button variant="link" size="xs" onClick={onPersons}>
              Alle {formatNumber(persons.length)}
            </Button>
          )}
        </div>
        {persons.length === 0 ? (
          <p className={styles.muted}>Noch keine.</p>
        ) : (
          <ul className={styles.avatars}>
            {persons.slice(0, SHOWN_AVATARS).map(({ person, mails }) => (
              <li key={person.person_id}>
                <Link
                  to={personPath(person.person_id)}
                  className={styles.avatarLink}
                  aria-label={`${personName(person)}, ${mailCount(mails)}`}
                  title={`${personName(person)}, ${mailCount(mails)}`}
                >
                  <Avatar
                    personId={person.person_id}
                    name={person.name}
                    email={person.email}
                    size="sm"
                  />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {tagged.length > 0 && (
        <section className={styles.factSection}>
          <div className={styles.factHead}>
            <h2 className={styles.factTitle}>Schlagworte</h2>
            <HelpMark
              text={`Gezählt in den ${formatNumber(items?.length ?? 0)} neuesten Mails der Akte`}
            />
          </div>
          <ul className={styles.tagList}>
            {tagged.map(({ tag, n }) => (
              <li key={tag.id}>
                <Link to={`/mails?collection=${id}&tag=${tag.id}`} className={styles.tagLink}>
                  <ColorChip color={tag.color}>
                    {tag.name} {formatNumber(n)}
                  </ColorChip>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className={styles.factSection}>
        <h2 className={styles.factTitle}>Gespeicherte Suchen</h2>
        {collection.searches.length === 0 ? (
          <p className={styles.muted}>
            Noch keine. <Link to={collectionMailsHref(id)}>Aus der Mailliste zuordnen</Link>
          </p>
        ) : (
          <ul className={styles.searches}>
            {collection.searches.map((search) => (
              <li key={search.id}>
                <Link to={searchHref(search.query)}>{search.name}</Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </aside>
  );
}

function CollectionNotFound({ id }: { id?: number }) {
  return (
    <ErrorState
      title="Diese Akte gibt es nicht."
      actions={
        <Link to="/akten" className={buttonClass()}>
          Zu den Akten
        </Link>
      }
    >
      {id === undefined
        ? "Die Adresse nennt keine gültige Akten-Nummer."
        : `Es gibt keine Akte mit der Nummer ${id}; vielleicht wurde sie gelöscht.`}
    </ErrorState>
  );
}
