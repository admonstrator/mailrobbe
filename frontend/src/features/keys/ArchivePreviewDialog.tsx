import { useState, type FormEvent } from "react";

import { useArchivePreview, useStartKeysRun } from "../../api/queries";
import {
  RUN_LIST_LIMIT,
  type ArchiveDomain,
  type DkimKeysRunRequest,
  type KeyArchivePreview,
} from "../../api/types";
import { Button } from "../../components/Button";
import { Spinner } from "../../components/Spinner";
import { formatDateTime, formatNumber } from "../../lib/format";
import { Dialog } from "../persons/Dialog";
import styles from "./ArchivePreviewDialog.module.css";
import { keysErrorText } from "./labels";

/** The run for the checked domains (D107): every domain less the unchecked ones, as long as no
 *  domain the interrupted fetch answered is checked again, which the run leaves out by itself;
 *  otherwise exactly the checked ones. null when that list would be too long for one request. */
export function fetchRequest(
  domains: readonly ArchiveDomain[],
  left: ReadonlySet<string>,
): DkimKeysRunRequest | null {
  const chosen = domains.filter(({ domain }) => !left.has(domain));
  if (chosen.every(({ done }) => !done)) {
    const skip = domains.filter(({ domain, done }) => !done && left.has(domain));
    if (skip.length > RUN_LIST_LIMIT) return null;
    if (skip.length === 0) return { task: "fetch" };
    return { task: "fetch", skip_domains: skip.map(({ domain }) => domain) };
  }
  if (chosen.length > RUN_LIST_LIMIT) return null;
  return { task: "fetch", domains: chosen.map(({ domain }) => domain) };
}

/** "Schlüsselarchiv abfragen" (D102): which domains a fetch would send to which archive and
 *  when each was last asked, before anything is sent; the fetch asks only the checked ones,
 *  one after the other, and after an interrupted fetch only those it did not get to (D107). */
export function ArchivePreviewDialog({
  busy,
  onClose,
}: {
  /** Why no run can start now, or null. */
  busy: string | null;
  onClose: () => void;
}) {
  const preview = useArchivePreview();
  return (
    <Dialog title="Schlüsselarchiv abfragen" onClose={onClose}>
      {preview.isPending ? (
        <div className={styles.loading}>
          <Spinner label="Vorschau wird geladen" />
        </div>
      ) : preview.isError ? (
        <>
          <p className={styles.error} role="alert">
            {keysErrorText(preview.error)}
          </p>
          <div className={styles.foot}>
            <Button onClick={onClose}>Schließen</Button>
          </div>
        </>
      ) : preview.data.url === null ? (
        <>
          <p className={styles.text}>
            Das Schlüsselarchiv ist in den Einstellungen abgeschaltet („off“). Mailrobbe fragt kein
            Archiv; die Rekonstruktion und die Suche im eigenen Archiv gehen weiter.
          </p>
          <div className={styles.foot}>
            <Button onClick={onClose}>Schließen</Button>
          </div>
        </>
      ) : (
        <DomainForm preview={preview.data} url={preview.data.url} busy={busy} onClose={onClose} />
      )}
    </Dialog>
  );
}

function DomainForm({
  preview,
  url,
  busy,
  onClose,
}: {
  preview: KeyArchivePreview;
  url: string;
  busy: string | null;
  onClose: () => void;
}) {
  const start = useStartKeysRun();
  // Every domain starts checked but those an interrupted fetch answered already; the set holds
  // those unchecked.
  const answered = preview.domains.filter(({ done }) => done).map(({ domain }) => domain);
  const [left, setLeft] = useState<ReadonlySet<string>>(() => new Set(answered));
  const chosen = preview.domains.map(({ domain }) => domain).filter((domain) => !left.has(domain));
  const request = fetchRequest(preview.domains, left);
  const tooMany = request === null;

  function toggle(domain: string, checked: boolean) {
    const next = new Set(left);
    if (checked) next.delete(domain);
    else next.add(domain);
    setLeft(next);
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (chosen.length === 0 || request === null) return;
    start.mutate(request, { onSuccess: onClose });
  }

  return (
    <form className={styles.form} onSubmit={onSubmit}>
      <p className={styles.text}>
        Archiv: <code className={styles.url}>{url}</code>
      </p>
      <p className={styles.privacy}>
        Mailrobbe schickt dem Archiv nur die Namen der angehakten Domains, eine Anfrage je Domain.
        Selektoren, Mails, Adressen und alles andere bleiben hier; hochgeladen wird nichts. Die
        Anfragen gehen nacheinander hinaus; ein angehaltener Lauf macht beim nächsten Start weiter.
      </p>
      {preview.continues && (
        <p className={styles.text}>
          {`Die Abfrage vom ${formatDateTime(preview.continues)} ist nicht zu Ende gelaufen. ${formatNumber(answered.length)} ${answered.length === 1 ? "Domain hat" : "Domains haben"} seither geantwortet und ${answered.length === 1 ? "bleibt" : "bleiben"} diesmal aus.`}
        </p>
      )}
      {preview.domains.length === 0 ? (
        <p className={styles.text}>Keine Domain zu fragen: Kein Selektor ist ohne Schlüssel.</p>
      ) : (
        <>
          <div className={styles.listHead}>
            <span>{`${formatNumber(chosen.length)} von ${formatNumber(preview.domains.length)} Domains gewählt`}</span>
            <Button variant="link" size="xs" onClick={() => setLeft(new Set(answered))}>
              {answered.length > 0 ? "Alle übrigen" : "Alle"}
            </Button>
            <Button
              variant="link"
              size="xs"
              onClick={() => setLeft(new Set(preview.domains.map(({ domain }) => domain)))}
            >
              Keine
            </Button>
          </div>
          <div className={styles.scroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Domain</th>
                  <th className={styles.num}>Selektoren</th>
                  <th className={styles.num}>Mails</th>
                  <th>Zuletzt gefragt</th>
                </tr>
              </thead>
              <tbody>
                {preview.domains.map(({ domain, names, mails, last_asked_at, done }) => (
                  <tr key={domain}>
                    <td>
                      <label className={styles.domain}>
                        <input
                          type="checkbox"
                          checked={!left.has(domain)}
                          onChange={(event) => toggle(domain, event.target.checked)}
                        />
                        {domain}
                      </label>
                    </td>
                    <td className={styles.num}>{formatNumber(names)}</td>
                    <td className={styles.num}>{formatNumber(mails)}</td>
                    <td className={styles.muted}>
                      {last_asked_at ? formatDateTime(last_asked_at) : "noch nie"}
                      {done && " · beantwortet"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      {preview.skipped.length > 0 && (
        <p className={styles.text}>
          {`Nicht gefragt, weil ihre Endung reserviert ist (.example, .test, …); solche Domains gehen nur an ein Archiv auf diesem Rechner: ${preview.skipped.join(", ")}.`}
        </p>
      )}
      {tooMany && (
        <p className={styles.error} role="alert">
          {`Eine Abfrage nimmt höchstens ${formatNumber(RUN_LIST_LIMIT)} einzeln gewählte oder abgewählte Domains; „Alle“ fragt jede Domain ohne Grenze.`}
        </p>
      )}
      {start.isError && (
        <p className={styles.error} role="alert">
          {keysErrorText(start.error)}
        </p>
      )}
      <div className={styles.foot}>
        <Button onClick={onClose}>Abbrechen</Button>
        <Button
          type="submit"
          variant="primary"
          disabled={chosen.length === 0 || tooMany || busy !== null || start.isPending}
          title={busy ?? undefined}
        >
          Abfragen
        </Button>
      </div>
    </form>
  );
}
