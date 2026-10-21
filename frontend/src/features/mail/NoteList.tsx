import { useId, useState, type KeyboardEvent } from "react";

import { useAddNote, useDeleteNote, useEditNote } from "../../api/queries";
import { NOTE_LIMIT, type NoteInfo } from "../../api/types";
import { Button } from "../../components/Button";
import { formatDateTime, formatNumber } from "../../lib/format";
import styles from "./NoteList.module.css";

/** Ctrl+Enter (Cmd+Enter on a Mac) saves a note's text. */
function isSaveKey(event: KeyboardEvent): boolean {
  return event.key === "Enter" && (event.ctrlKey || event.metaKey);
}

/** "9.120 / 10.000 Zeichen" once a text gets close to the limit, else "". */
function lengthHint(text: string): string {
  return text.length > NOTE_LIMIT * 0.9
    ? `${formatNumber(text.length)} / ${formatNumber(NOTE_LIMIT)} Zeichen`
    : "";
}

/** The notes of a mail (D56), oldest first: anyone may add, edit or delete one. */
export function NoteList({
  mailId,
  notes,
  onWritten,
}: {
  mailId: number;
  notes: NoteInfo[];
  onWritten: () => void;
}) {
  const add = useAddNote(mailId);
  const [draft, setDraft] = useState("");
  const fieldId = useId();
  const body = draft.trim();

  function submit() {
    if (!body || add.isPending) return;
    add.mutate(body, {
      onSuccess: () => {
        setDraft("");
        onWritten();
      },
    });
  }

  return (
    <div className={styles.notes}>
      <span className={styles.label}>
        Notizen{notes.length > 0 && ` (${formatNumber(notes.length)})`}
      </span>
      {notes.length > 0 && (
        <ul className={styles.list} aria-label="Notizen">
          {notes.map((note) => (
            <NoteItem key={note.id} mailId={mailId} note={note} onWritten={onWritten} />
          ))}
        </ul>
      )}
      <form
        className={styles.form}
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label htmlFor={fieldId} className="sr-only">
          Neue Notiz
        </label>
        <textarea
          id={fieldId}
          className={styles.textarea}
          rows={2}
          maxLength={NOTE_LIMIT}
          placeholder="Notiz hinzufügen …"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (!isSaveKey(event)) return;
            event.preventDefault();
            submit();
          }}
        />
        <div className={styles.foot}>
          <span className={styles.hint}>
            {["Strg+Enter speichert", lengthHint(draft)].filter(Boolean).join(" · ")}
          </span>
          <Button type="submit" variant="primary" size="xs" disabled={!body || add.isPending}>
            Notiz speichern
          </Button>
        </div>
        {add.isError && (
          <p className={styles.error} role="alert">
            Die Notiz wurde nicht gespeichert. Bitte noch einmal versuchen.
          </p>
        )}
      </form>
    </div>
  );
}

function NoteItem({
  mailId,
  note,
  onWritten,
}: {
  mailId: number;
  note: NoteInfo;
  onWritten: () => void;
}) {
  const edit = useEditNote(mailId);
  const remove = useDeleteNote(mailId);
  const [draft, setDraft] = useState<string | null>(null); // null: not being edited
  const [confirming, setConfirming] = useState(false);
  const fieldId = useId();

  if (draft !== null) {
    const body = draft.trim();
    const save = () => {
      if (!body || edit.isPending) return;
      if (body === note.body) {
        setDraft(null);
        return;
      }
      edit.mutate(
        { id: note.id, body },
        {
          onSuccess: () => {
            setDraft(null);
            onWritten();
          },
        },
      );
    };
    return (
      <li className={styles.note}>
        <form
          className={styles.form}
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          <label htmlFor={fieldId} className="sr-only">
            Notiz bearbeiten
          </label>
          <textarea
            id={fieldId}
            className={styles.textarea}
            rows={4}
            maxLength={NOTE_LIMIT}
            value={draft}
            autoFocus
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (isSaveKey(event)) {
                event.preventDefault();
                save();
              } else if (event.key === "Escape") {
                event.preventDefault();
                setDraft(null);
              }
            }}
          />
          <div className={styles.foot}>
            <span className={styles.hint}>{lengthHint(draft)}</span>
            <Button size="xs" onClick={() => setDraft(null)}>
              Abbrechen
            </Button>
            <Button type="submit" variant="primary" size="xs" disabled={!body || edit.isPending}>
              Speichern
            </Button>
          </div>
          {edit.isError && (
            <p className={styles.error} role="alert">
              Die Änderung wurde nicht gespeichert.
            </p>
          )}
        </form>
      </li>
    );
  }

  const edited = note.updated_at !== note.created_at;
  return (
    <li className={styles.note}>
      <p className={styles.body}>{note.body}</p>
      <div className={styles.meta}>
        <span className={styles.byline}>
          {note.author ?? "ohne Namen"} · {formatDateTime(note.created_at)}
          {edited && ` · bearbeitet ${formatDateTime(note.updated_at)}`}
        </span>
        {confirming ? (
          <span className={styles.confirm}>
            Notiz löschen?
            <Button
              variant="link"
              size="xs"
              className={styles.danger}
              disabled={remove.isPending}
              onClick={() =>
                remove.mutate(note.id, {
                  onSuccess: onWritten,
                  onError: () => setConfirming(false),
                })
              }
            >
              Endgültig löschen
            </Button>
            <Button variant="link" size="xs" onClick={() => setConfirming(false)}>
              Abbrechen
            </Button>
          </span>
        ) : (
          <span className={styles.actions}>
            <Button variant="link" size="xs" onClick={() => setDraft(note.body)}>
              Bearbeiten
            </Button>
            <Button variant="link" size="xs" onClick={() => setConfirming(true)}>
              Löschen
            </Button>
          </span>
        )}
      </div>
      {remove.isError && (
        <p className={styles.error} role="alert">
          Die Notiz wurde nicht gelöscht.
        </p>
      )}
    </li>
  );
}
