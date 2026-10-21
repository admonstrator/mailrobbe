import { useId, useState, type FormEvent } from "react";

import { ApiError } from "../../api/client";
import { useAddManualKey } from "../../api/queries";
import { EVIDENCE_FILE_LIMIT, NOTE_LIMIT, type ManualKeyRequest } from "../../api/types";
import { Button } from "../../components/Button";
import { EditorDialog } from "../../components/EditorDialog";
import { useEditor } from "../../lib/editor";
import { formatNumber } from "../../lib/format";
import { Dialog } from "../persons/Dialog";
import forms from "../research/forms.module.css";
import { keysErrorText } from "./labels";
import styles from "./ManualKeyDialog.module.css";

const RECORD_LIMIT = 8192; // ManualKeyRequest.record
const REFERENCE_LIMIT = 2000;

const FILE_LIMIT_TEXT = `${formatNumber(EVIDENCE_FILE_LIMIT / 1024 ** 2)} MB`;
const TOO_LARGE = `Die Datei ist größer als ${FILE_LIMIT_TEXT}; so große Belege nimmt Mailrobbe nicht an.`;

/** The file's bytes as base64, read in the browser. */
function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] ?? "");
    reader.onerror = () => reject(reader.error ?? new Error("unreadable"));
    reader.readAsDataURL(file);
  });
}

/** A day of a date field as the start of that UTC day; null when empty. */
const dayTime = (day: string) => (day ? `${day}T00:00:00Z` : null);

function addErrorText(error: Error): string {
  if (error instanceof ApiError && error.code === "invalid_key") {
    return "Kein gültiger Schlüssel. Erwartet wird ein DKIM-Eintrag wie „v=DKIM1; k=rsa; p=MIIB…“ oder nur der Wert nach p=.";
  }
  return keysErrorText(error);
}

/** "Schlüssel von Hand hinzufügen" (D103): a key found elsewhere, with where it comes from, an
 *  optional note, the times the source names and an optional evidence file, stored unchanged
 *  with its SHA-256. The editor's name (D54) goes with it. */
export function ManualKeyDialog({
  name,
  onClose,
  onAdded,
}: {
  name: string;
  onClose: () => void;
  onAdded: () => void;
}) {
  const add = useAddManualKey(name);
  const editor = useEditor();
  const id = useId();
  const [record, setRecord] = useState("");
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [reading, setReading] = useState(false);
  const [editorDialog, setEditorDialog] = useState(false);

  function check(): string | null {
    if (!record.trim()) return "Bitte den Schlüssel eintragen.";
    if (!reference.trim()) return "Bitte angeben, woher der Schlüssel stammt.";
    if (from && to && to < from) return "„Bis“ liegt vor „Von“.";
    if (file && file.size > EVIDENCE_FILE_LIMIT) return TOO_LARGE;
    return null;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    add.reset();
    const found = check();
    setProblem(found);
    if (found) return;
    const request: ManualKeyRequest = {
      record: record.trim(),
      reference: reference.trim(),
      note: note.trim(),
      observed_from: dayTime(from),
      observed_to: dayTime(to),
      file_name: file?.name ?? null,
      file_base64: null,
    };
    if (file) {
      setReading(true);
      try {
        request.file_base64 = await readBase64(file);
      } catch {
        setProblem("Die Datei ließ sich nicht lesen.");
        return;
      } finally {
        setReading(false);
      }
    }
    add.mutate(request, { onSuccess: onAdded });
  }

  return (
    <>
      <Dialog title="Schlüssel von Hand hinzufügen" onClose={onClose}>
        <form className={forms.form} onSubmit={(event) => void onSubmit(event)} noValidate>
          <p className={forms.text}>
            Für <code className={styles.name}>{name}</code>: ein Schlüssel aus einer Zonendatei,
            einer Mail des Providers oder einer anderen Quelle. Er gilt als dokumentiert und zählt
            nur für Signaturen, die er tatsächlich bestätigt.
          </p>
          <div className={forms.field}>
            <label htmlFor={`${id}-record`} className={forms.label}>
              Schlüssel (TXT-Eintrag oder nur der Wert nach p=)
            </label>
            <textarea
              id={`${id}-record`}
              className={`${forms.textarea} ${styles.mono}`}
              value={record}
              maxLength={RECORD_LIMIT}
              spellCheck={false}
              placeholder="v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA…"
              onChange={(event) => setRecord(event.target.value)}
            />
          </div>
          <div className={forms.field}>
            <label htmlFor={`${id}-reference`} className={forms.label}>
              Herkunft
            </label>
            <input
              id={`${id}-reference`}
              className={forms.input}
              value={reference}
              maxLength={REFERENCE_LIMIT}
              autoComplete="off"
              aria-describedby={`${id}-reference-hint`}
              onChange={(event) => setReference(event.target.value)}
            />
            <span id={`${id}-reference-hint`} className={forms.text}>
              Pflicht: eine Web-Adresse, der Permalink einer Mail (/m/…), ein Dateiname oder eine
              kurze Beschreibung der Quelle.
            </span>
          </div>
          <div className={forms.field}>
            <label htmlFor={`${id}-note`} className={forms.label}>
              Notiz (optional)
            </label>
            <textarea
              id={`${id}-note`}
              className={forms.textarea}
              value={note}
              maxLength={NOTE_LIMIT}
              onChange={(event) => setNote(event.target.value)}
            />
          </div>
          <fieldset className={forms.field}>
            <legend className={forms.label}>Laut Quelle veröffentlicht (optional)</legend>
            <div className={styles.dates}>
              <label className={styles.date}>
                von
                <input
                  type="date"
                  className={forms.input}
                  value={from}
                  onChange={(event) => setFrom(event.target.value)}
                />
              </label>
              <label className={styles.date}>
                bis
                <input
                  type="date"
                  className={forms.input}
                  value={to}
                  onChange={(event) => setTo(event.target.value)}
                />
              </label>
            </div>
          </fieldset>
          <div className={forms.field}>
            <label htmlFor={`${id}-file`} className={forms.label}>
              {`Belegdatei (optional, höchstens ${FILE_LIMIT_TEXT})`}
            </label>
            <input
              id={`${id}-file`}
              type="file"
              className={styles.file}
              onChange={(event) => {
                const chosen = event.target.files?.[0] ?? null;
                setFile(chosen);
                setProblem(chosen && chosen.size > EVIDENCE_FILE_LIMIT ? TOO_LARGE : null);
              }}
            />
            <span className={forms.text}>
              Wird unverändert mit seiner SHA-256 gespeichert und kommt mit in den Export.
            </span>
          </div>
          <p className={forms.text}>
            {editor ? (
              <>
                Wird gespeichert als <strong>{editor}</strong>.
              </>
            ) : (
              "Ohne Namen gespeichert, nennt der Beleg niemanden."
            )}{" "}
            <Button variant="link" size="xs" onClick={() => setEditorDialog(true)}>
              {editor ? "Namen ändern" : "Namen eintragen"}
            </Button>
          </p>
          {(problem ?? add.error) && (
            <p className={forms.error} role="alert">
              {problem ?? (add.error && addErrorText(add.error))}
            </p>
          )}
          <div className={forms.foot}>
            <Button onClick={onClose}>Abbrechen</Button>
            <Button type="submit" variant="primary" disabled={add.isPending || reading}>
              Schlüssel hinzufügen
            </Button>
          </div>
        </form>
      </Dialog>
      {editorDialog && <EditorDialog onClose={() => setEditorDialog(false)} />}
    </>
  );
}
