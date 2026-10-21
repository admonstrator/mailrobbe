import { useId, useState, type FormEvent } from "react";

import { ApiError } from "../../api/client";
import { useCreateExport } from "../../api/queries";
import { EXPORT_LIMIT, LABEL_LIMIT, type MailSelection } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { formatNumber } from "../../lib/format";
import { Dialog } from "../persons/Dialog";
import styles from "./ExportDialog.module.css";
import forms from "./forms.module.css";
import { mailCount } from "./labels";

export interface ExportDialogProps {
  /** The mails to export: the list's filters, selected ids, or an Akte as filter. */
  selection: MailSelection;
  /** How many mails the selection has, when the caller knows it; null: unknown. */
  count: number | null;
  /** Suggested label for the export log, e.g. the Akte's name. */
  label: string;
  onClose: () => void;
}

/** Export of mails as ZIP with EML, PDF and manifest (D62): label and options, then the link to
 *  the ZIP. Research data stays out unless asked for (source protection). */
export function ExportDialog({ selection, count, label, onClose }: ExportDialogProps) {
  const create = useCreateExport();
  const id = useId();
  const [name, setName] = useState(label.slice(0, LABEL_LIMIT));
  const [research, setResearch] = useState(false);
  const tooMany = count !== null && count > EXPORT_LIMIT;
  const result = create.data;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (tooMany) return;
    create.mutate({ ...selection, label: name.trim(), include_research: research });
  }

  if (result) {
    return (
      <Dialog title="Export angelegt" onClose={onClose}>
        <div className={forms.form}>
          <p className={styles.summary}>
            Export {result.id}
            {result.label && ` „${result.label}“`}: {mailCount(result.mails)},{" "}
            {result.include_research ? "mit Rechercheangaben" : "ohne Rechercheangaben"}.
          </p>
          <p className={forms.text}>
            Das ZIP enthält je Mail die Originaldatei (mail.eml) und eine PDF-Lesefassung, dazu
            manifest.json, manifest.csv, LIESMICH.txt und SHA256SUMS. Ob alle Dateien unverändert
            sind, prüft „sha256sum -c SHA256SUMS“ im entpackten Ordner; LIESMICH.txt erklärt es auch
            für macOS und Windows.
          </p>
          <div className={forms.foot}>
            <Button onClick={onClose}>Schließen</Button>
            <a href={result.download_url} className={buttonClass("primary")} download>
              ZIP herunterladen
            </a>
          </div>
        </div>
      </Dialog>
    );
  }

  return (
    <Dialog title="Mails exportieren" onClose={onClose}>
      <form className={forms.form} onSubmit={onSubmit}>
        <p className={styles.summary}>
          {count === null
            ? "Anzahl der Mails: unbekannt"
            : `${mailCount(count)} ${count === 1 ? "wird" : "werden"} exportiert, die älteste zuerst.`}
        </p>
        {tooMany && (
          <p className={styles.limit} role="alert">
            Ein Export umfasst höchstens {formatNumber(EXPORT_LIMIT)} Mails. Bitte die Auswahl enger
            fassen, etwa mit einem Zeitraum.
          </p>
        )}
        <div className={forms.field}>
          <label htmlFor={`${id}-label`} className={forms.label}>
            Bezeichnung
          </label>
          <input
            id={`${id}-label`}
            className={forms.input}
            value={name}
            maxLength={LABEL_LIMIT}
            autoComplete="off"
            aria-describedby={`${id}-hint`}
            onChange={(event) => setName(event.target.value)}
          />
          <span id={`${id}-hint`} className={forms.text}>
            Steht in der Liste der Exporte und im Export selbst (LIESMICH.txt, Manifest).
          </span>
        </div>
        <label className={styles.option}>
          <input
            type="checkbox"
            checked={research}
            onChange={(event) => setResearch(event.target.checked)}
          />
          <span>
            <span className={styles.optionLabel}>Notizen, Schlagworte und Bewertung beilegen</span>
            <span className={forms.text}>
              Ohne Haken enthält der Export nur die Mails und ihre Prüfangaben; interne
              Einschätzungen bleiben im Haus und schützen Quellen.
            </span>
          </span>
        </label>
        {create.isError && (
          <p className={forms.error} role="alert">
            {exportErrorText(create.error)}
          </p>
        )}
        <div className={forms.foot}>
          <Button onClick={onClose}>Abbrechen</Button>
          <Button type="submit" variant="primary" disabled={tooMany || create.isPending}>
            Export anlegen
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function exportErrorText(error: Error): string {
  const code = error instanceof ApiError ? error.code : null;
  if (code === "too_many_mails") {
    return `Die Auswahl umfasst mehr als ${formatNumber(EXPORT_LIMIT)} Mails. Bitte enger fassen.`;
  }
  if (code === "empty_selection") return "Die Auswahl enthält keine Mail.";
  if (code === "not_found") return "Eine der gewählten Mails gibt es nicht mehr.";
  if (code === "invalid_query" || code === "invalid_filter") {
    return "Die Suche oder ein Filter der Auswahl ist ungültig.";
  }
  return "Der Export konnte nicht angelegt werden: Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.";
}
