import { Fragment, useId, useState, type FormEvent } from "react";
import { Link } from "react-router";

import { ApiError } from "../../api/client";
import { useDocument, useTryPassword } from "../../api/queries";
import {
  PASSWORD_LENGTH,
  type DocumentDetail,
  type DocumentPassword,
  type PasswordFinding,
  type PasswordTryResult,
} from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { EditorDialog } from "../../components/EditorDialog";
import { PersonLink } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { useEditor } from "../../lib/editor";
import { formatDateTime, formatNumber } from "../../lib/format";
import { documentName, passwordOrigin } from "./labels";
import styles from "./ProtectionCard.module.css";
import { ProtectionMark } from "./ProtectionMark";
import { DEFAULT_DOCUMENT_LIST_STATE, documentListHref, documentPath } from "./urlState";

/** The documents a try on every locked one opened, listed by name; the rest are counted. */
export const OPENED_SHOWN = 20;

type Attempt = ReturnType<typeof useTryPassword>;

/** A protected document (D233 to D237). Locked: what the imports tried, and a field for a
 *  password known some other way, told by phone say, which Mailrobbe knows only once it is typed
 *  in. Open: the password in plain text with where it was found, as evidence (D208). The answer
 *  of a try stays below while the page loads the document's new state. */
export function ProtectionCard({ document }: { document: DocumentDetail }) {
  const attempt = useTryPassword();
  const protection = document.protection;
  if (!protection) return null;
  return (
    <Card aria-labelledby="document-protection-title">
      <div className={styles.head}>
        <ProtectionMark protection={protection} size={18} />
        <CardTitle id="document-protection-title">
          {protection === "locked" ? "Verschlüsselt" : "Verschlüsselt und geöffnet"}
        </CardTitle>
      </div>
      {protection === "locked" ? (
        <Locked document={document} attempt={attempt} />
      ) : document.password ? (
        <Opened password={document.password} />
      ) : (
        <p className={styles.lead}>Mit einem gefundenen Kennwort geöffnet.</p>
      )}
      <TryAnswer attempt={attempt} documentId={document.id} />
    </Card>
  );
}

function Locked({ document, attempt }: { document: DocumentDetail; attempt: Attempt }) {
  return (
    <>
      <p className={styles.lead}>Die Datei ist verschlüsselt, das Kennwort ist nicht bekannt.</p>
      {document.password_trial ? (
        <>
          <p className={styles.text}>
            {triesText(document.password_tries ?? 0, document.password_tried_at ?? null)}
          </p>
          <PasswordForm documentId={document.id} attempt={attempt} />
        </>
      ) : (
        <p className={styles.text}>
          Dateien dieses Formats kann Mailrobbe noch nicht öffnen (etwa verschlüsselte
          OpenDocument-Dateien); erkannt wird nur, dass sie verschlüsselt sind. Wer das Kennwort
          kennt, lädt die Datei herunter und öffnet sie damit in einem anderen Programm.
        </p>
      )}
    </>
  );
}

/** How many passwords the imports tried on it, and when last (D235). */
function triesText(tries: number, at: string | null): string {
  if (tries === 0) {
    return "Bisher wurde kein Kennwort an ihr probiert. Jeder Import sucht Kennwörter in den Mails und Anhängen und probiert die naheliegenden zuerst.";
  }
  const count = `${formatNumber(tries)} ${tries === 1 ? "Kennwort" : "Kennwörter"}`;
  return `Die Importe haben ${count} aus dem Archiv an ihr probiert${at ? `, zuletzt am ${formatDateTime(at)}` : ""}.`;
}

/** The password typed in, in plain text (found passwords are evidence, D208), tried on this
 *  document or on every locked one (D237). */
function PasswordForm({ documentId, attempt }: { documentId: number; attempt: Attempt }) {
  const id = useId();
  const editor = useEditor();
  const [password, setPassword] = useState("");
  const [everywhere, setEverywhere] = useState(false);
  const [editorDialog, setEditorDialog] = useState(false);
  const value = password.trim();

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!value || attempt.isPending) return;
    attempt.mutate({ document: everywhere ? null : documentId, password: value });
  }

  return (
    <>
      <form className={styles.form} onSubmit={onSubmit}>
        <label htmlFor={`${id}-password`} className={styles.label}>
          Kennwort ausprobieren
        </label>
        <div className={styles.field}>
          <input
            id={`${id}-password`}
            className={styles.input}
            type="text"
            value={password}
            maxLength={PASSWORD_LENGTH}
            autoComplete="off"
            autoCapitalize="off"
            spellCheck={false}
            aria-describedby={`${id}-hint`}
            onChange={(event) => setPassword(event.target.value)}
          />
          <Button type="submit" variant="primary" disabled={!value || attempt.isPending}>
            Probieren
          </Button>
        </div>
        <label className={styles.check}>
          <input
            type="checkbox"
            checked={everywhere}
            onChange={(event) => setEverywhere(event.target.checked)}
          />
          an allen verschlüsselten Dateien probieren
        </label>
        <p id={`${id}-hint`} className={styles.text}>
          Ein Kennwort, das nicht im Archiv steht, etwa am Telefon genannt, kennt Mailrobbe erst,
          wenn es hier eingegeben ist. Es wird im Klartext gespeichert und als Beleg gezeigt; öffnet
          es nichts, probieren es spätere Importe an neu gefundenen Dateien.
        </p>
        <p className={styles.text}>
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
      </form>
      {editorDialog && <EditorDialog onClose={() => setEditorDialog(false)} />}
    </>
  );
}

/** What the try did: opened, kept for later imports (D237), or on every locked document how
 *  many it was tried on and which it opened. */
function TryAnswer({ attempt, documentId }: { attempt: Attempt; documentId: number }) {
  if (attempt.isPending) {
    return (
      <p className={styles.busy}>
        <Spinner label="Kennwort wird probiert" />
        {attempt.variables.document === null
          ? "Wird an allen verschlüsselten Dateien probiert. Bei einem großen Archiv kann das eine Minute dauern."
          : "Wird probiert …"}
      </p>
    );
  }
  if (attempt.isError) {
    return (
      <p className={styles.error} role="alert">
        {tryErrorText(attempt.error)}
      </p>
    );
  }
  if (!attempt.isSuccess) return null;
  if (attempt.variables.document === null) return <EverywhereAnswer result={attempt.data} />;
  return (
    <p className={styles.answer} role="status">
      {oneText(attempt.data, documentId)}
    </p>
  );
}

const KEPT =
  "Das Kennwort bleibt gespeichert; spätere Importe probieren es an neu gefundenen verschlüsselten Dateien.";

function oneText(result: PasswordTryResult, documentId: number): string {
  if (result.opened.includes(documentId)) return "Das Kennwort hat die Datei geöffnet.";
  if (result.errors > 0) {
    return `Die Datei ließ sich nicht lesen: Die MBOX-Datei fehlt oder hat sich geändert, oder die Datei ist beschädigt. ${KEPT}`;
  }
  return `Das Kennwort öffnet diese Datei nicht. ${KEPT}`;
}

function EverywhereAnswer({ result }: { result: PasswordTryResult }) {
  const { tried, opened, errors } = result;
  if (tried === 0) {
    return (
      <p className={styles.answer} role="status">
        {`Es gibt keine verschlüsselte Datei, an der es sich probieren ließe. ${KEPT}`}
      </p>
    );
  }
  const figures = [
    `An ${formatNumber(tried)} ${tried === 1 ? "Datei" : "Dateien"} probiert`,
    `${formatNumber(opened.length)} geöffnet`,
    errors > 0 && `${formatNumber(errors)} nicht lesbar`,
  ].filter(Boolean);
  const rest = opened.length - OPENED_SHOWN;
  return (
    <div className={styles.answer} role="status">
      <p>{`${figures.join(", ")}${opened.length > 0 ? ":" : "."}`}</p>
      {opened.length > 0 ? (
        <ul className={styles.opened}>
          {opened.slice(0, OPENED_SHOWN).map((id) => (
            <li key={id}>
              <OpenedLink id={id} />
            </li>
          ))}
          {rest > 0 && (
            <li>
              <Link to={documentListHref({ ...DEFAULT_DOCUMENT_LIST_STATE, protection: ["open"] })}>
                {`und ${formatNumber(rest)} weitere`}
              </Link>
            </li>
          )}
        </ul>
      ) : (
        <p>{KEPT}</p>
      )}
    </div>
  );
}

/** An opened document by its name, once its page is loaded. */
function OpenedLink({ id }: { id: number }) {
  const detail = useDocument(id);
  return (
    <Link to={documentPath(id)}>
      {detail.data ? documentName(detail.data.name) : `Dokument #${id}`}
    </Link>
  );
}

function tryErrorText(error: Error): string {
  if (error instanceof ApiError && error.code === "not_locked") {
    return "Die Datei braucht kein Kennwort mehr: Inzwischen wurde sie geöffnet. Die Seite zeigt den neuen Stand.";
  }
  return "Das Kennwort konnte nicht probiert werden: Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.";
}

/** The password that opened it, where it came from, the evidence and when it opened it. */
function Opened({ password }: { password: DocumentPassword }) {
  const { finding } = password;
  // Typed in by hand: on this page found_by names who did it, for every locked document the
  // finding does.
  const editor = password.found_by ?? finding?.editor ?? null;
  return (
    <>
      <p className={styles.lead}>
        Geöffnet mit dem Kennwort{" "}
        <span className={styles.password}>
          »<code className={styles.value}>{password.value}</code>«
        </span>
      </p>
      <dl className={styles.facts}>
        <div className={styles.fact}>
          <dt>Herkunft</dt>
          <dd>{passwordOrigin(password.tier, editor)}</dd>
        </div>
        <div className={styles.fact}>
          <dt>Beleg</dt>
          <dd>
            <Evidence finding={finding} value={password.value} />
          </dd>
        </div>
        <div className={styles.fact}>
          <dt>Geöffnet</dt>
          <dd>{formatDateTime(password.found_at)}</dd>
        </div>
      </dl>
    </>
  );
}

/** Where the password stands (D208): the mail, the document whose text holds it, or when it was
 *  typed in; and the line(s) around it with the password marked. */
function Evidence({ finding, value }: { finding: PasswordFinding | null; value: string }) {
  if (!finding)
    return <span className={styles.muted}>Wo es gefunden wurde, ist nicht bekannt.</span>;
  const { mail, recipients, document } = finding;
  return (
    <div className={styles.evidence}>
      {mail && (
        <span>
          <Link to={`/mails/${mail.id}`} title={mail.subject || "(kein Betreff)"}>
            {mail.date ? `Mail vom ${formatDateTime(mail.date)}` : "Mail ohne Datum"}
          </Link>
          {mail.sender && (
            <>
              {" von "}
              <PersonLink person={mail.sender} />
            </>
          )}
          {recipients.length > 0 && " an "}
          {recipients.map((person, index) => (
            <Fragment key={`${person.person_id}-${person.email}`}>
              {index > 0 && ", "}
              <PersonLink person={person} />
            </Fragment>
          ))}
        </span>
      )}
      {document && (
        <span>
          {"Im Text von "}
          <Link to={documentPath(document.id)}>{documentName(document.name)}</Link>
        </span>
      )}
      {!mail && !document && <span>{`Eingegeben am ${formatDateTime(finding.created_at)}`}</span>}
      {finding.context && (
        <blockquote className={styles.context}>
          {finding.context.split(value).map((part, index) => (
            <Fragment key={index}>
              {index > 0 && <mark>{value}</mark>}
              {part}
            </Fragment>
          ))}
        </blockquote>
      )}
    </div>
  );
}
