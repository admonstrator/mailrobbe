import { useState, type FormEvent } from "react";

import { useArchivePreview, useStartKeysRun } from "../../api/queries";
import type { KeyArchivePreview } from "../../api/types";
import { Button } from "../../components/Button";
import { Spinner } from "../../components/Spinner";
import { formatDateTime, formatNumber } from "../../lib/format";
import { Dialog } from "../persons/Dialog";
import styles from "./ArchivePreviewDialog.module.css";
import { keysErrorText, RUN_LIST_LIMIT } from "./labels";

/** "Schlüsselarchiv abfragen" (D102): which domains a fetch would send to which archive and
 *  when each was last asked, before anything is sent; the fetch asks only the checked ones. */
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
            Das Schlüsselarchiv ist abgeschaltet (MAILROBBE_DKIM_KEY_ARCHIVE_URL=off). Mailrobbe
            fragt kein Archiv; die Rekonstruktion und die Suche im eigenen Archiv gehen weiter.
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
  // Every domain starts checked; the set holds those unchecked.
  const [left, setLeft] = useState<ReadonlySet<string>>(new Set());
  const chosen = preview.domains.map(({ domain }) => domain).filter((domain) => !left.has(domain));
  const tooMany = chosen.length > RUN_LIST_LIMIT;

  function toggle(domain: string, checked: boolean) {
    const next = new Set(left);
    if (checked) next.delete(domain);
    else next.add(domain);
    setLeft(next);
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (chosen.length === 0 || tooMany) return;
    start.mutate({ task: "fetch", domains: chosen }, { onSuccess: onClose });
  }

  return (
    <form className={styles.form} onSubmit={onSubmit}>
      <p className={styles.text}>
        Archiv: <code className={styles.url}>{url}</code>
      </p>
      <p className={styles.privacy}>
        Mailrobbe schickt dem Archiv nur die Namen der angehakten Domains, eine Anfrage je Domain.
        Selektoren, Mails, Adressen und alles andere bleiben hier; hochgeladen wird nichts.
      </p>
      {preview.domains.length === 0 ? (
        <p className={styles.text}>Keine Domain zu fragen: Kein Selektor ist ohne Schlüssel.</p>
      ) : (
        <>
          <div className={styles.listHead}>
            <span>{`${formatNumber(chosen.length)} von ${formatNumber(preview.domains.length)} Domains gewählt`}</span>
            <Button variant="link" size="xs" onClick={() => setLeft(new Set())}>
              Alle
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
                {preview.domains.map(({ domain, names, mails, last_asked_at }) => (
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
          {`Eine Abfrage nimmt höchstens ${formatNumber(RUN_LIST_LIMIT)} Domains; bitte weniger wählen.`}
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
