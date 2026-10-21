import { useState } from "react";
import { Link } from "react-router";

import { useSelectorSummary, useStartKeysRun } from "../../api/queries";
import type { DkimKeysRunRequest, SelectorSummary } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { DkimDot } from "../../components/DkimDot";
import { Spinner } from "../../components/Spinner";
import { KEY_ORIGIN_LABELS, KEY_ORIGINS } from "../../lib/dkim";
import { formatDateTime, formatNumber } from "../../lib/format";
import { ArchivePreviewDialog } from "./ArchivePreviewDialog";
import styles from "./KeyRecoveryCard.module.css";
import { KeysRun, useKeysRun } from "./KeysRun";
import { keysErrorText } from "./labels";

const HINTS = {
  reconstruct:
    "Berechnet Schlüssel aus je zwei RSA-Signaturen eines Selektors; ein 2048-Bit-Schlüssel braucht etwa eine Minute.",
  search:
    "Sucht in Mails und Anhängen nach Schlüsseleinträgen (v=DKIM1; p=…) und prüft jeden Fund an den Signaturen.",
  fetch: "Zeigt vorher, welche Domains an das Schlüsselarchiv gingen; gefragt wird erst danach.",
};

const selectors = (count: number) =>
  `${formatNumber(count)} ${count === 1 ? "Selektor" : "Selektoren"}`;
const mails = (count: number) => `${formatNumber(count)} ${count === 1 ? "Mail" : "Mails"}`;

/** The dashboard card "Gelöschte Selektoren" (D100 to D102): signatures whose key is no longer
 *  in the DNS, what reconstruction, the archive's own texts and the key archive found, and the
 *  runs that look for keys. It reads its figures and the latest run itself. */
export function KeyRecoveryCard() {
  const summary = useSelectorSummary();
  const { job, busy } = useKeysRun();
  const start = useStartKeysRun();
  const [notice, setNotice] = useState<string | null>(null);
  const [preview, setPreview] = useState(false);

  function run(request: DkimKeysRunRequest) {
    setNotice(null);
    start.mutate(request, { onError: (error) => setNotice(keysErrorText(error)) });
  }

  const blocked = busy !== null || start.isPending;
  return (
    <Card variant="side" className={styles.card} aria-labelledby="keys-card-title">
      <CardTitle id="keys-card-title">Gelöschte Selektoren</CardTitle>
      <p className={styles.lead}>
        Signaturen, deren Schlüssel nicht mehr im DNS steht, und was Mailrobbe dazu gefunden hat.
      </p>
      {summary.data ? (
        <Figures summary={summary.data} />
      ) : summary.isError ? (
        <p className={styles.error}>Die Zahlen konnten nicht geladen werden.</p>
      ) : (
        <div className={styles.loading}>
          <Spinner label="Zahlen werden geladen" />
        </div>
      )}
      <KeysRun job={job} onError={setNotice} />
      {notice && (
        <p className={styles.error} role="alert">
          {notice}
        </p>
      )}
      <div className={styles.actions}>
        <Button
          disabled={blocked}
          title={busy ?? HINTS.reconstruct}
          onClick={() => run({ task: "reconstruct" })}
        >
          Schlüssel rekonstruieren
        </Button>
        <Button
          disabled={blocked}
          title={busy ?? HINTS.search}
          onClick={() => run({ task: "search" })}
        >
          Im Archiv suchen
        </Button>
        <Button
          disabled={blocked}
          title={busy ?? HINTS.fetch}
          onClick={() => {
            setNotice(null);
            setPreview(true);
          }}
        >
          Schlüsselarchiv abfragen …
        </Button>
      </div>
      <Link to="/import/selektoren" className={styles.more}>
        Alle Selektoren ansehen
      </Link>
      {preview && <ArchivePreviewDialog busy={busy} onClose={() => setPreview(false)} />}
    </Card>
  );
}

function Figures({ summary }: { summary: SelectorSummary }) {
  const keys = KEY_ORIGINS.filter((origin) => summary.keys[origin] > 0);
  return (
    <>
      <dl className={styles.figures}>
        <div>
          <dt>Ohne Schlüssel</dt>
          <dd>{`${selectors(summary.names_missing)} · ${mails(summary.mails_missing)}`}</dd>
        </div>
        <div
          className={styles.sub}
          title="Selektoren mit mindestens zwei verschiedenen RSA-Signaturen"
        >
          <dt>davon rekonstruierbar</dt>
          <dd>{selectors(summary.reconstructable)}</dd>
        </div>
        <div title="Selektoren, deren Signaturen ein Schlüssel aus einer anderen Quelle als dem heutigen DNS bestätigt">
          <dt>Geklärt</dt>
          <dd>{selectors(summary.names_resolved)}</dd>
        </div>
        <div>
          <dt className={styles.status}>
            <DkimDot status="consistent" decorative />
            Signatur stimmig
          </dt>
          <dd>{mails(summary.mails_consistent)}</dd>
        </div>
        <div>
          <dt>Gefundene Schlüssel</dt>
          <dd>
            {keys.length === 0
              ? "noch keine"
              : keys
                  .map(
                    (origin) =>
                      `${formatNumber(summary.keys[origin])} ${KEY_ORIGIN_LABELS[origin]}`,
                  )
                  .join(" · ")}
          </dd>
        </div>
      </dl>
      {summary.factorable > 0 && (
        <p className={styles.warning}>
          {`${formatNumber(summary.factorable)} ${summary.factorable === 1 ? "Schlüssel teilt" : "Schlüssel teilen"} einen Primfaktor mit einem anderen: Jeder hätte damit signieren können, Mailrobbe prüft mit ${summary.factorable === 1 ? "ihm" : "ihnen"} nichts.`}
        </p>
      )}
      {summary.last_lookup_at && (
        <p
          className={styles.stand}
        >{`Zuletzt gesucht ${formatDateTime(summary.last_lookup_at)}`}</p>
      )}
    </>
  );
}
