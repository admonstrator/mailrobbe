import { useId, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { useCreateHideRule, useHideRulePreview, useUpdateHideRule } from "../../api/queries";
import {
  HIDE_EXAMPLES,
  type HideRuleFields,
  type HideRuleInfo,
  type HideRulePreview,
  type SubjectMatch,
} from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { EditorDialog } from "../../components/EditorDialog";
import { cx } from "../../lib/cx";
import { useEditor } from "../../lib/editor";
import { formatDate, formatNumber } from "../../lib/format";
import { personName } from "../../lib/person";
import { Dialog } from "../persons/Dialog";
import forms from "../research/forms.module.css";
import { mailCount } from "../research/labels";
import { describeRule, hasCriterion, hidingErrorText, type RuleCriteria } from "./labels";
import styles from "./RuleDialog.module.css";

/** What the dialog starts from: criteria for a new rule, or a rule to change (with its id). The
 *  person is the one person_id names, or a mail's sender, offered beside its address. */
export interface RuleDraft extends RuleCriteria {
  id?: number;
  enabled?: boolean;
}

type SenderMode = "address" | "person";

/** "Ausblendregel anlegen" or "bearbeiten" (D221, D223): the criteria, every filled one must
 *  hold, and a preview of the mails they match while they are typed. A new rule ends on what it
 *  hides, with the way to the rules, unless the dialog was opened on the rules' page. */
export function RuleDialog({
  draft,
  onClose,
  onRulesPage = false,
}: {
  draft: RuleDraft;
  onClose: () => void;
  onRulesPage?: boolean;
}) {
  const id = useId();
  const editor = useEditor();
  const create = useCreateHideRule();
  const update = useUpdateHideRule();
  const creating = draft.id === undefined;
  const write = creating ? create : update;
  const person = draft.person ?? null;
  const personId = draft.person_id ?? person?.person_id ?? null;
  const [name, setName] = useState(draft.name ?? "");
  const [mode, setMode] = useState<SenderMode>(draft.person_id != null ? "person" : "address");
  const [sender, setSender] = useState(draft.sender ?? "");
  const [domain, setDomain] = useState(draft.domain ?? "");
  const [listId, setListId] = useState(draft.list_id ?? "");
  const [automated, setAutomated] = useState(draft.automated ?? false);
  const [subject, setSubject] = useState(draft.subject ?? "");
  const [subjectMatch, setSubjectMatch] = useState<SubjectMatch>(draft.subject_match ?? "contains");
  const [editorDialog, setEditorDialog] = useState(false);

  const criteria = useMemo<HideRuleFields>(
    () => ({
      sender: mode === "address" ? sender.trim() || null : null,
      person_id: mode === "person" ? personId : null,
      domain: domain.trim() || null,
      list_id: listId.trim() || null,
      automated,
      subject: subject.trim() || null,
      subject_match: subjectMatch,
    }),
    [mode, sender, personId, domain, listId, automated, subject, subjectMatch],
  );
  const ready = hasCriterion(criteria);
  const { preview, stale } = useHideRulePreview(ready ? criteria : null);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!ready || write.isPending) return;
    const fields = { ...criteria, name: name.trim() || null };
    if (draft.id === undefined) {
      create.mutate(fields, {
        onSuccess: () => {
          if (onRulesPage) onClose();
        },
      });
    } else {
      update.mutate(
        { id: draft.id, ...fields, enabled: draft.enabled ?? true },
        { onSuccess: onClose },
      );
    }
  }

  if (create.data && !onRulesPage) return <Saved rule={create.data} onClose={onClose} />;

  return (
    <>
      <Dialog
        title={creating ? "Ausblendregel anlegen" : "Ausblendregel bearbeiten"}
        onClose={onClose}
      >
        <form className={cx(forms.form, styles.form)} onSubmit={onSubmit}>
          <p className={forms.text}>
            Alle ausgefüllten Angaben müssen zutreffen, leere zählen nicht. Mails in einer Akte, mit
            Notiz, Lesezeichen oder „relevant“ bleiben immer sichtbar.
          </p>
          <div className={styles.grid}>
            <div className={cx(forms.field, styles.wide)}>
              <label htmlFor={`${id}-name`} className={forms.label}>
                Name (optional)
              </label>
              <input
                id={`${id}-name`}
                className={forms.input}
                value={name}
                autoComplete="off"
                placeholder="etwa Wochenrückblick des Vereins"
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <fieldset className={cx(forms.field, styles.wide)}>
              <legend className={forms.label}>Absender</legend>
              {personId !== null && (
                <div className={styles.choices}>
                  <label className={styles.choice}>
                    <input
                      type="radio"
                      name={`${id}-sender`}
                      checked={mode === "address"}
                      onChange={() => setMode("address")}
                    />
                    Adresse
                  </label>
                  <label className={styles.choice}>
                    <input
                      type="radio"
                      name={`${id}-sender`}
                      checked={mode === "person"}
                      onChange={() => setMode("person")}
                    />
                    {person
                      ? `${personName(person)} mit allen Adressen`
                      : `Person #${personId} (nicht mehr im Archiv)`}
                  </label>
                </div>
              )}
              {mode === "address" && (
                <input
                  className={forms.input}
                  aria-label="Absenderadresse"
                  value={sender}
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="name@beispiel.example"
                  onChange={(event) => setSender(event.target.value)}
                />
              )}
            </fieldset>
            <div className={forms.field}>
              <label htmlFor={`${id}-domain`} className={forms.label}>
                Domain
              </label>
              <input
                id={`${id}-domain`}
                className={forms.input}
                value={domain}
                autoComplete="off"
                spellCheck={false}
                placeholder="newsletter.example, mit Subdomains"
                onChange={(event) => setDomain(event.target.value)}
              />
            </div>
            <div className={forms.field}>
              <label htmlFor={`${id}-list`} className={forms.label}>
                Verteiler (List-Id)
              </label>
              <input
                id={`${id}-list`}
                className={forms.input}
                value={listId}
                autoComplete="off"
                spellCheck={false}
                placeholder="news.newsletter.example"
                onChange={(event) => setListId(event.target.value)}
              />
            </div>
            <div className={cx(forms.field, styles.wide)}>
              <span className={forms.label} id={`${id}-subject-label`}>
                Betreff
              </span>
              <div className={styles.subject}>
                <select
                  className={cx(forms.input, styles.match)}
                  aria-label="Vergleich des Betreffs"
                  value={subjectMatch}
                  onChange={(event) => setSubjectMatch(event.target.value as SubjectMatch)}
                >
                  <option value="contains">enthält</option>
                  <option value="starts">beginnt mit</option>
                </select>
                <input
                  className={forms.input}
                  aria-labelledby={`${id}-subject-label`}
                  value={subject}
                  autoComplete="off"
                  placeholder="Wochenrückblick"
                  onChange={(event) => setSubject(event.target.value)}
                />
              </div>
            </div>
            <label className={cx(styles.check, styles.wide)}>
              <input
                type="checkbox"
                checked={automated}
                onChange={(event) => setAutomated(event.target.checked)}
              />
              automatisch versendet
              <span className={styles.hint}>
                Newsletter, Benachrichtigungen, noreply-Absender: wie der Import sie erkennt
              </span>
            </label>
          </div>
          <Preview ready={ready} preview={preview} stale={stale} />
          <p className={forms.text}>
            {editor ? (
              <>
                Wird gespeichert als <strong>{editor}</strong>.
              </>
            ) : (
              "Wird ohne Namen gespeichert."
            )}{" "}
            Die Regel gilt für das ganze Team.{" "}
            <Button variant="link" size="xs" onClick={() => setEditorDialog(true)}>
              {editor ? "Namen ändern" : "Namen eintragen"}
            </Button>
          </p>
          {write.isError && (
            <p className={forms.error} role="alert">
              {hidingErrorText(write.error)}
            </p>
          )}
          <div className={forms.foot}>
            <Button onClick={onClose}>Abbrechen</Button>
            <Button
              type="submit"
              variant="primary"
              disabled={!ready || write.isPending}
              title={ready ? undefined : "Mindestens eine Angabe ausfüllen"}
            >
              Speichern
            </Button>
          </div>
        </form>
      </Dialog>
      {editorDialog && <EditorDialog onClose={() => setEditorDialog(false)} />}
    </>
  );
}

/** The figures and the newest mails of the criteria; the examples open in a new tab, so the
 *  rule in the making stays. */
function Preview({
  ready,
  preview,
  stale,
}: {
  ready: boolean;
  preview: ReturnType<typeof useHideRulePreview>["preview"];
  stale: boolean;
}) {
  if (!ready) {
    return (
      <p className={styles.note}>
        Sobald eine Angabe ausgefüllt ist, zeigt die Vorschau, welche Mails die Regel ausblendet.
      </p>
    );
  }
  if (preview.isError) {
    return (
      <p className={forms.error} role="alert">
        {hidingErrorText(preview.error)}
      </p>
    );
  }
  if (!preview.data) return <p className={styles.note}>Vorschau lädt …</p>;
  return <Figures preview={preview.data} stale={stale} />;
}

function Figures({ preview, stale }: { preview: HideRulePreview; stale: boolean }) {
  const { mails, kept, with_terms: withTerms, examples } = preview;
  return (
    <section
      aria-label="Vorschau"
      aria-busy={stale}
      className={cx(styles.preview, stale && styles.stale)}
    >
      <p className={styles.figures}>
        <strong>{mailCount(mails)}</strong> {mails === 1 ? "passt" : "passen"}
        {kept > 0 && (
          <>
            , {formatNumber(kept)} davon {kept === 1 ? "bleibt" : "bleiben"} sichtbar (Akte, Notiz,
            Lesezeichen oder „relevant“)
          </>
        )}
        .
      </p>
      {withTerms > 0 && (
        <p className={styles.warning}>
          {formatNumber(withTerms)} {withTerms === 1 ? "enthält" : "enthalten"} Begriffe aus den
          Themenfeldern; vor dem Speichern lohnt ein Blick hinein.
        </p>
      )}
      {examples.length > 0 && (
        <>
          <h3 className={styles.examplesTitle}>
            {mails > HIDE_EXAMPLES ? `Die neuesten ${examples.length}` : "Die Mails"}
          </h3>
          <ol className={styles.examples}>
            {examples.map((mail) => (
              <li key={mail.id}>
                <Link
                  to={`/mails/${mail.id}`}
                  target="_blank"
                  rel="noopener"
                  className={styles.example}
                  title="Öffnet die Mail in einem neuen Tab"
                >
                  <span className={styles.date}>
                    {mail.date ? formatDate(mail.date) : "ohne Datum"}
                  </span>
                  <span className={styles.sender}>
                    {mail.sender ? personName(mail.sender) : "unbekannt"}
                  </span>
                  <span className={styles.exampleSubject}>{mail.subject || "(ohne Betreff)"}</span>
                </Link>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

/** After a new rule is saved away from the rules' page: what it hides, and the way there. */
function Saved({ rule, onClose }: { rule: HideRuleInfo; onClose: () => void }) {
  return (
    <Dialog title="Ausblendregel gespeichert" onClose={onClose}>
      <p className={forms.text}>
        „{rule.name || describeRule(rule)}“ passt auf {mailCount(rule.mails)}. Sie fehlen ab jetzt
        in Liste, Suche und Zahlen; über das Suchmenü lassen sie sich jederzeit einbeziehen.
      </p>
      <div className={forms.foot}>
        <Button onClick={onClose}>Schließen</Button>
        <Link to="/ausgeblendet" className={buttonClass("primary")} onClick={onClose}>
          Zu den Ausblendregeln
        </Link>
      </div>
    </Dialog>
  );
}
