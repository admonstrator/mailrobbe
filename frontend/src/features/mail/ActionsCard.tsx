import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { useSaveNote } from "../../api/queries";
import { NOTE_LIMIT, type MailDetail } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { Checkbox } from "../../components/Checkbox";
import { FlagIcon } from "../../components/icons";
import { formatDateTime, formatNumber } from "../../lib/format";
import styles from "./ActionsCard.module.css";

export function ActionsCard({ mail, onShowRaw }: { mail: MailDetail; onShowRaw: () => void }) {
  const sender = mail.participants.find((person) => person.role === "from");
  const recipient = mail.participants.find(
    (person) => person.role !== "from" && person.person_id !== sender?.person_id,
  );

  return (
    <Card variant="side">
      <CardTitle variant="caps">Aktionen</CardTitle>
      <a href={`/api/mails/${mail.id}/eml`} className={styles.action} download>
        Als EML herunterladen
      </a>
      <button type="button" className={styles.action} onClick={onShowRaw}>
        Rohmail aus MBOX anzeigen
      </button>
      {sender && recipient && (
        <Link
          to={`/mails?between=${sender.person_id}&between=${recipient.person_id}`}
          className={styles.action}
        >
          Alle Mails zwischen {sender.name || sender.email} und {recipient.name || recipient.email}
        </Link>
      )}
      <NoteForm mail={mail} />
    </Card>
  );
}

/** Flag and note of the mail (D23), saved explicitly. */
function NoteForm({ mail }: { mail: MailDetail }) {
  const save = useSaveNote(mail.id);
  const saved = mail.note;
  const [open, setOpen] = useState(saved.flagged || saved.note !== "");
  const [flagged, setFlagged] = useState(saved.flagged);
  const [note, setNote] = useState(saved.note);
  const dirty = flagged !== saved.flagged || note !== saved.note;

  if (!open) {
    return (
      <button type="button" className={styles.action} onClick={() => setOpen(true)}>
        Markieren / Notiz hinzufügen
      </button>
    );
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    save.mutate({ flagged, note });
  }

  const status = save.isPending
    ? "Wird gespeichert …"
    : dirty
      ? "Nicht gespeichert"
      : saved.updated_at
        ? `Gespeichert ${formatDateTime(saved.updated_at)}`
        : "";

  return (
    <form className={styles.note} onSubmit={onSubmit} aria-label="Markierung und Notiz">
      <Checkbox checked={flagged} onChange={setFlagged}>
        <FlagIcon size={14} className={styles.flag} />
        Markiert
      </Checkbox>
      <label htmlFor="mail-note" className={styles.noteLabel}>
        Notiz
      </label>
      <textarea
        id="mail-note"
        className={styles.textarea}
        rows={4}
        maxLength={NOTE_LIMIT}
        value={note}
        onChange={(event) => setNote(event.target.value)}
      />
      <div className={styles.noteFoot}>
        <span className={styles.status} aria-live="polite">
          {status}
          {note.length > NOTE_LIMIT * 0.9 &&
            ` · ${formatNumber(note.length)} / ${formatNumber(NOTE_LIMIT)} Zeichen`}
        </span>
        <Button type="submit" variant="primary" size="sm" disabled={!dirty || save.isPending}>
          Speichern
        </Button>
      </div>
      {save.isError && (
        <p className={styles.error} role="alert">
          Speichern fehlgeschlagen. Bitte noch einmal versuchen.
        </p>
      )}
    </form>
  );
}
