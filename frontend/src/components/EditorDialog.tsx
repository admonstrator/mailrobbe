import { useState, type FormEvent } from "react";

import { Dialog } from "../features/persons/Dialog";
import { EDITOR_LIMIT, getEditor, setEditor } from "../lib/editor";
import { Button } from "./Button";
import styles from "./EditorDialog.module.css";

/** Asks for the editor's name (D54); an empty name forgets it. */
export function EditorDialog({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState(getEditor);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setEditor(name);
    onClose();
  }

  return (
    <Dialog title="Name für Notizen und Änderungen" onClose={onClose}>
      <form className={styles.form} onSubmit={onSubmit}>
        <label htmlFor="editor-name" className={styles.label}>
          Name
        </label>
        <input
          id="editor-name"
          className={styles.input}
          value={name}
          maxLength={EDITOR_LIMIT}
          autoComplete="name"
          onChange={(event) => setName(event.target.value)}
        />
        <p className={styles.hint}>
          Der Name steht an Notizen und Änderungen, wird nur in diesem Browser gespeichert und ist
          keine Anmeldung.
        </p>
        <div className={styles.foot}>
          <Button onClick={onClose}>Abbrechen</Button>
          <Button type="submit" variant="primary">
            Speichern
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
