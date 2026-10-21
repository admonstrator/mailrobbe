import { useId, useState, type FormEvent, type ReactNode } from "react";

import { useSaveLabel } from "../../api/queries";
import {
  LABEL_NAME_LIMIT,
  LABEL_NOTE_LIMIT,
  type PersonLabelUpdate,
  type PersonProfile,
} from "../../api/types";
import { Button } from "../../components/Button";
import { EditorDialog } from "../../components/EditorDialog";
import { useEditor } from "../../lib/editor";
import { formatNumber } from "../../lib/format";
import forms from "../research/forms.module.css";
import { Dialog } from "./Dialog";
import styles from "./LabelDialog.module.css";
import { personErrorText } from "./labels";

const REMOVED: PersonLabelUpdate = { name: "", role: "", note: "" };

/** "Benennen" (D156): Klarname, Rolle and Notiz of the person's own address, which then show
 *  wherever the person appears. Blank fields are removed; the editor's name (D54) goes with it. */
export function LabelDialog({ profile, onClose }: { profile: PersonProfile; onClose: () => void }) {
  const save = useSaveLabel(profile.id);
  const editor = useEditor();
  const id = useId();
  const shown = profile.label;
  const [name, setName] = useState(shown?.name ?? "");
  const [role, setRole] = useState(shown?.role ?? "");
  const [note, setNote] = useState(shown?.note ?? "");
  const [editorDialog, setEditorDialog] = useState(false);
  // Removing deletes the label of this address; one of an alias stays and then shows.
  const own = shown !== null && shown.email === profile.email;

  function store(update: PersonLabelUpdate) {
    save.mutate(update, { onSuccess: onClose });
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    store({ name, role, note });
  }

  return (
    <>
      <Dialog title={own ? "Benennung bearbeiten" : "Benennen"} onClose={onClose}>
        <form className={forms.form} onSubmit={onSubmit}>
          <p className={forms.text}>
            Die Benennung gilt für die Adresse{" "}
            <span className={styles.address}>{profile.email}</span> und erscheint überall, wo die
            Person auftaucht: in Mails, Listen, Karte und Zeitachse, im Export nur mit den
            Rechercheangaben. Sie stammt vom Team, nicht aus den Mails.
          </p>
          {shown && !own && (
            <p className={forms.text}>
              Bisher zeigt die Person die Benennung ihrer Adresse{" "}
              <span className={styles.address}>{shown.email}</span>.
            </p>
          )}
          <Field id={`${id}-name`} label="Klarname" value={name} limit={LABEL_NAME_LIMIT}>
            <input
              id={`${id}-name`}
              className={forms.input}
              value={name}
              maxLength={LABEL_NAME_LIMIT}
              autoComplete="off"
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
          <Field id={`${id}-role`} label="Rolle" value={role} limit={LABEL_NAME_LIMIT}>
            <input
              id={`${id}-role`}
              className={forms.input}
              value={role}
              maxLength={LABEL_NAME_LIMIT}
              autoComplete="off"
              placeholder="etwa Kassenwart, Vorstand, Sachbearbeiterin"
              onChange={(event) => setRole(event.target.value)}
            />
          </Field>
          <Field id={`${id}-note`} label="Notiz" value={note} limit={LABEL_NOTE_LIMIT}>
            <textarea
              id={`${id}-note`}
              className={forms.textarea}
              value={note}
              maxLength={LABEL_NOTE_LIMIT}
              onChange={(event) => setNote(event.target.value)}
            />
          </Field>
          <p className={forms.text}>
            {editor ? (
              <>
                Wird gespeichert als <strong>{editor}</strong>.
              </>
            ) : (
              "Wird ohne Namen gespeichert."
            )}{" "}
            <Button variant="link" size="xs" onClick={() => setEditorDialog(true)}>
              {editor ? "Namen ändern" : "Namen eintragen"}
            </Button>
          </p>
          {save.isError && (
            <p className={forms.error} role="alert">
              {personErrorText(save.error)}
            </p>
          )}
          <div className={forms.foot}>
            {own && (
              <Button
                className={styles.remove}
                disabled={save.isPending}
                onClick={() => store(REMOVED)}
              >
                Benennung entfernen
              </Button>
            )}
            <Button onClick={onClose}>Abbrechen</Button>
            <Button type="submit" variant="primary" disabled={save.isPending}>
              Speichern
            </Button>
          </div>
        </form>
      </Dialog>
      {editorDialog && <EditorDialog onClose={() => setEditorDialog(false)} />}
    </>
  );
}

/** A labelled field with how many characters it takes. */
function Field({
  id,
  label,
  value,
  limit,
  children,
}: {
  id: string;
  label: string;
  value: string;
  limit: number;
  children: ReactNode;
}) {
  return (
    <div className={forms.field}>
      <div className={styles.head}>
        <label htmlFor={id} className={forms.label}>
          {label}
        </label>
        <span className={styles.count}>
          {formatNumber(value.length)} / {formatNumber(limit)}
        </span>
      </div>
      {children}
    </div>
  );
}
