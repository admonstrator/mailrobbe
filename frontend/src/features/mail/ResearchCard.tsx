import { useEffect, useEffectEvent, useId, useState } from "react";
import { Link } from "react-router";

import { ApiError } from "../../api/client";
import {
  useChangeMailCollections,
  useChangeMailTags,
  useCreateCollection,
  useCreateTag,
  useResearch,
  useSaveMark,
} from "../../api/queries";
import {
  NAME_LIMIT,
  TAG_NAME_LIMIT,
  type LinkChange,
  type MailDetail,
  type MarkUpdate,
  type ReviewKey,
} from "../../api/types";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { EditorDialog } from "../../components/EditorDialog";
import { FoldHeading } from "../../components/FoldCard";
import { FlagIcon } from "../../components/icons";
import { cx } from "../../lib/cx";
import { getEditor, useEditor } from "../../lib/editor";
import { useFold } from "../../lib/folds";
import { formatDateTime, formatNumber } from "../../lib/format";
import { isPlainKey } from "../../lib/keys";
import { permalinkPath, REVIEW_KEYS, REVIEW_LABELS, TAG_COLORS } from "../../lib/research";
import { LinkField } from "./LinkField";
import { NoteList } from "./NoteList";
import styles from "./ResearchCard.module.css";

/** The key that sets each status while the detail is open; FLAG_KEY toggles the bookmark. */
const REVIEW_SHORTCUTS: Record<ReviewKey, string> = {
  unreviewed: "u",
  seen: "g",
  relevant: "r",
  irrelevant: "n",
};
const FLAG_KEY = "m";

const counted = (n: number, one: string, many: string) =>
  `${formatNumber(n)} ${n === 1 ? one : many}`;

/** "Lena Vogt · 20.10.2026 16:02", or "ohne Namen · …" for a change without editor name. */
function attribution(by: string | null, at: string | null): string | null {
  return at && `${by ?? "ohne Namen"} · ${formatDateTime(at)}`;
}

function linkErrorText(error: Error | null): string | null {
  if (!error) return null;
  if (error instanceof ApiError && error.code === "duplicate_name") {
    return "Diesen Namen gibt es schon, auch in anderer Schreibweise.";
  }
  return "Die Änderung wurde nicht gespeichert. Bitte noch einmal versuchen.";
}

/** What the research file records about this mail (D55 to D61): review status and bookmark,
 *  also by key, tags, Akten, notes and the permalink. Opening a mail sets nothing. It folds to
 *  one line (D166) like every block of the page, which the browser remembers (lib/folds); the
 *  keys work folded too. */
export function ResearchCard({ mail }: { mail: MailDetail }) {
  const { mark, tags, collections, notes } = mail.research;
  const research = useResearch();
  const save = useSaveMark(mail.id);
  const changeTags = useChangeMailTags(mail.id);
  const changeCollections = useChangeMailCollections(mail.id);
  const createTag = useCreateTag();
  const createCollection = useCreateCollection();
  const editor = useEditor();
  const [unnamed, setUnnamed] = useState(false);
  const [editorDialog, setEditorDialog] = useState(false);
  const [open, setOpen] = useFold("mail.research", true);
  const folded = !open;
  const titleId = useId();
  const statusId = useId();
  const bodyId = useId();

  /** After a write: saved without author when no name is set, which a quiet hint then says. */
  const written = () => setUnnamed(!getEditor());

  // A status or bookmark being saved shows at once.
  const pending: MarkUpdate | undefined = save.isPending ? save.variables : undefined;
  const review = pending && "review" in pending ? (pending.review ?? null) : mark.review;
  const flagged = pending?.flagged ?? mark.flagged;

  function setReview(key: ReviewKey) {
    const status = key === "unreviewed" ? null : key;
    if (status !== review) save.mutate({ review: status }, { onSuccess: written });
  }

  function toggleFlag() {
    save.mutate({ flagged: !flagged }, { onSuccess: written });
  }

  const onShortcut = useEffectEvent((event: KeyboardEvent) => {
    if (!isPlainKey(event) || event.shiftKey || event.repeat) return;
    // Keys in an open dialog, such as the one for the editor's name, belong to it.
    if (event.target instanceof Element && event.target.closest("dialog")) return;
    const key = event.key.toLowerCase();
    const status = REVIEW_KEYS.find((other) => REVIEW_SHORTCUTS[other] === key);
    if (status) setReview(status);
    else if (key === FLAG_KEY) toggleFlag();
    else return;
    event.preventDefault();
  });

  useEffect(() => {
    const listener = (event: KeyboardEvent) => onShortcut(event);
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);

  // Each field shows the error of its latest change, whether a link or a creation.
  function linkTags(change: LinkChange) {
    createTag.reset();
    changeTags.mutate(change, { onSuccess: written });
  }

  function linkCollections(change: LinkChange) {
    createCollection.reset();
    changeCollections.mutate(change, { onSuccess: written });
  }

  const knownTags = research.data?.tags ?? [];
  async function addNewTag(name: string) {
    changeTags.reset();
    try {
      // New tags take the palette's colours in turn, so neighbours differ.
      const color = TAG_COLORS[knownTags.length % TAG_COLORS.length];
      const tag = await createTag.mutateAsync({ name, color });
      linkTags({ add: [tag.id] });
    } catch {
      // shown below the field
    }
  }

  async function addNewCollection(name: string) {
    changeCollections.reset();
    try {
      const collection = await createCollection.mutateAsync({ name });
      linkCollections({ add: [collection.id] });
    } catch {
      // shown below the field
    }
  }

  const tagError = linkErrorText(changeTags.error ?? createTag.error);
  const collectionError = linkErrorText(changeCollections.error ?? createCollection.error);
  const reviewBy = review === mark.review ? attribution(mark.review_by, mark.review_at) : null;
  const flaggedBy = flagged && mark.flagged ? attribution(mark.flagged_by, mark.flagged_at) : null;

  const saveError = save.isError && (
    <p className={styles.error} role="alert">
      Nicht gespeichert. Bitte noch einmal versuchen.
    </p>
  );

  return (
    <Card variant="side" aria-labelledby={titleId}>
      <div className={styles.head}>
        <FoldHeading id={titleId} open={open} controls={bodyId} onToggle={() => setOpen(!open)}>
          Recherche
        </FoldHeading>
      </div>
      {unnamed && !editor && (
        <p className={styles.unnamed}>
          Ohne Namen gespeichert.{" "}
          <Button variant="link" size="xs" onClick={() => setEditorDialog(true)}>
            Namen eintragen
          </Button>
        </p>
      )}

      {folded ? (
        <div id={bodyId} className={styles.folded}>
          <p className={styles.summary}>
            <span
              className={cx(styles.summaryStatus, review && styles.active)}
              title={reviewBy ?? undefined}
            >
              {REVIEW_LABELS[review ?? "unreviewed"]}
            </span>
            {flagged && (
              <span className={styles.summaryFlag} title={flaggedBy ?? undefined}>
                <FlagIcon size={12} />
                Markiert
              </span>
            )}
            <span>{counted(notes.length, "Notiz", "Notizen")}</span>
            <span>{counted(tags.length, "Schlagwort", "Schlagwörter")}</span>
            <span>{counted(collections.length, "Akte", "Akten")}</span>
          </p>
          {saveError}
        </div>
      ) : (
        <div id={bodyId} className={styles.body}>
          <div className={styles.section}>
            <span id={statusId} className={styles.label}>
              Status
            </span>
            <div role="group" aria-labelledby={statusId} className={styles.segments}>
              {REVIEW_KEYS.map((key) => {
                const active = (review ?? "unreviewed") === key;
                return (
                  <button
                    key={key}
                    type="button"
                    aria-pressed={active}
                    title={`Taste ${REVIEW_SHORTCUTS[key]}`}
                    className={cx(styles.segment, active && styles.active)}
                    onClick={() => setReview(key)}
                  >
                    {REVIEW_LABELS[key]}
                    <kbd aria-hidden="true">{REVIEW_SHORTCUTS[key]}</kbd>
                  </button>
                );
              })}
            </div>
            {reviewBy && review && <span className={styles.by}>{reviewBy}</span>}
            <div className={styles.flagRow}>
              <button
                type="button"
                aria-pressed={flagged}
                title={`Taste ${FLAG_KEY}`}
                className={cx(styles.flag, flagged && styles.flagged)}
                onClick={toggleFlag}
              >
                <FlagIcon size={14} />
                Markiert
                <kbd aria-hidden="true">{FLAG_KEY}</kbd>
              </button>
              {flaggedBy && <span className={styles.by}>{flaggedBy}</span>}
            </div>
            {saveError}
          </div>

          <div className={styles.section}>
            <LinkField
              label="Schlagwörter"
              addLabel="Schlagwort hinzufügen"
              removeLabel="Schlagwort entfernen"
              createLabel={(name) => `„${name}“ als neues Schlagwort anlegen`}
              items={tags}
              known={knownTags}
              maxLength={TAG_NAME_LIMIT}
              onAdd={(id) => linkTags({ add: [id] })}
              onRemove={(id) => linkTags({ remove: [id] })}
              onCreate={(name) => void addNewTag(name)}
            />
            {tagError && (
              <p className={styles.error} role="alert">
                {tagError}
              </p>
            )}
          </div>

          <div className={styles.section}>
            <LinkField
              label="Akten"
              addLabel="Zu Akte hinzufügen"
              removeLabel="Aus Akte entfernen"
              createLabel={(name) => `Neue Akte „${name}“ anlegen`}
              items={collections}
              known={research.data?.collections ?? []}
              maxLength={NAME_LIMIT}
              href={(id) => `/akten/${id}`}
              onAdd={(id) => linkCollections({ add: [id] })}
              onRemove={(id) => linkCollections({ remove: [id] })}
              onCreate={(name) => void addNewCollection(name)}
            />
            {collectionError && (
              <p className={styles.error} role="alert">
                {collectionError}
              </p>
            )}
          </div>

          <NoteList mailId={mail.id} notes={notes} onWritten={written} />

          <Permalink sha256={mail.raw_sha256} />

          {(mail.duplicate_of !== null || mail.duplicates.length > 0) && (
            <p className={styles.shared}>
              {mail.duplicate_of !== null ? (
                <>
                  Byte-identisch mit{" "}
                  <Link to={`/mails/${mail.duplicate_of}`}>#{mail.duplicate_of}</Link>: Status,
                  Schlagwörter, Akten und Notizen gelten für alle Kopien.
                </>
              ) : (
                `Status, Schlagwörter, Akten und Notizen gelten auch für ${
                  mail.duplicates.length === 1
                    ? "die byte-identische Kopie"
                    : `die ${formatNumber(mail.duplicates.length)} byte-identischen Kopien`
                } dieser Mail.`
              )}
            </p>
          )}
        </div>
      )}
      {editorDialog && <EditorDialog onClose={() => setEditorDialog(false)} />}
    </Card>
  );
}

/** The mail's permalink (D61): copied as a whole URL, shown as its path to be read out. */
function Permalink({ sha256 }: { sha256: string }) {
  const path = permalinkPath(sha256);
  const url = window.location.origin + path;
  const [copied, setCopied] = useState<boolean | null>(null);

  useEffect(() => {
    if (copied === null) return;
    const timer = setTimeout(() => setCopied(null), copied ? 2_000 : 8_000);
    return () => clearTimeout(timer);
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
    } catch {
      setCopied(false); // no clipboard, e.g. on plain HTTP from another machine
    }
  }

  return (
    <div className={styles.section}>
      <span className={styles.label}>Permalink</span>
      <div className={styles.permalink}>
        <code className={styles.path} title={url}>
          {path}
        </code>
        <Button size="xs" onClick={() => void copy()}>
          Link kopieren
        </Button>
      </div>
      <span role="status" className={cx(styles.by, copied === null && "sr-only")}>
        {copied === true && "Link kopiert."}
        {copied === false && `Kopieren nicht möglich; der Link lautet ${url}`}
      </span>
    </div>
  );
}
