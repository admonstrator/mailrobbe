import { useState } from "react";
import { Link, useParams } from "react-router";

import { ApiError } from "../../api/client";
import { useSelector, useStartKeysRun } from "../../api/queries";
import type { DkimKeysJob, SelectorDetail } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { ErrorState } from "../../components/ErrorState";
import { CrossIcon } from "../../components/icons";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatDateTime, formatNumber } from "../../lib/format";
import { KeyList } from "./KeyList";
import { KeysRun, useKeysRun } from "./KeysRun";
import { dnsStatusLabel, keysErrorText, periodText } from "./labels";
import { ManualKeyDialog } from "./ManualKeyDialog";
import styles from "./SelectorDetailPage.module.css";
import { LookupTable, SelectorMails } from "./SelectorTables";
import { StatusMix } from "./StatusMix";
import { SELECTOR_LIST_PATH } from "./urlState";

interface Notice {
  tone: "info" | "error";
  text: string;
}

/** The page of one key name (D100 to D104): today's DNS answer, its figures, the keys from
 *  other sources with all their evidence, every lookup and its latest mails. */
export function SelectorDetailPage() {
  const { name = "" } = useParams();
  return <SelectorView key={name} name={name} />;
}

function SelectorView({ name }: { name: string }) {
  const detail = useSelector(name);
  return (
    <div className={styles.page}>
      <title>{`${name} · Mailrobbe`}</title>
      <nav aria-label="Pfad" className={styles.breadcrumb}>
        <Link to="/import">Import</Link>
        <span aria-hidden="true">›</span>
        <Link to={SELECTOR_LIST_PATH}>Gelöschte Selektoren</Link>
        <span aria-hidden="true">›</span>
        <span className={styles.crumb}>{name}</span>
      </nav>
      {detail.isPending ? (
        <div className={styles.loading}>
          <Spinner label="Selektor wird geladen" />
        </div>
      ) : detail.isError ? (
        <Card className={styles.message}>
          {detail.error instanceof ApiError && detail.error.code === "not_found" ? (
            <ErrorState
              title="Diesen Selektor gibt es nicht."
              actions={
                <Link to={SELECTOR_LIST_PATH} className={buttonClass()}>
                  Zu den Selektoren
                </Link>
              }
            >
              {`Keine Signatur im Archiv nennt den Schlüsselnamen „${name}“.`}
            </ErrorState>
          ) : (
            <ErrorState
              title="Der Selektor konnte nicht geladen werden."
              actions={<Button onClick={() => void detail.refetch()}>Erneut versuchen</Button>}
            >
              Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
            </ErrorState>
          )}
        </Card>
      ) : (
        <SelectorContent detail={detail.data} />
      )}
    </div>
  );
}

/** The run belongs on this page while it is alive, and after it when it worked on this name. */
function concerns(job: DkimKeysJob | null, name: string): boolean {
  return job !== null && (job.alive || job.options.names.includes(name));
}

function SelectorContent({ detail }: { detail: SelectorDetail }) {
  const { job, busy } = useKeysRun();
  const start = useStartKeysRun();
  const [notice, setNotice] = useState<Notice | null>(null);
  const [manual, setManual] = useState(false);
  const showError = (text: string) => setNotice({ tone: "error", text });

  function run(task: "reconstruct" | "check") {
    setNotice(null);
    start.mutate(
      { task, names: [detail.name] },
      { onError: (error) => showError(keysErrorText(error)) },
    );
  }

  const blocked = busy ?? (start.isPending ? "Der Lauf wird gestartet." : null);
  const reconstructBlocked =
    blocked ??
    (detail.rsa_signatures < 2
      ? "Dafür braucht es mindestens zwei verschiedene RSA-Signaturen dieses Selektors."
      : null);

  return (
    <div className={styles.content}>
      <Card className={styles.header}>
        <div className={styles.identity}>
          <div className={styles.titles}>
            <h1 className={styles.name}>{detail.name}</h1>
            <p className={styles.meta}>
              Selektor <strong>{detail.selector}</strong> · Domain <strong>{detail.domain}</strong>
            </p>
          </div>
          <div className={styles.actions}>
            <Button
              disabled={reconstructBlocked !== null}
              title={
                reconstructBlocked ??
                "Berechnet den Schlüssel aus zwei RSA-Signaturen; ein 2048-Bit-Schlüssel braucht etwa eine Minute."
              }
              onClick={() => run("reconstruct")}
            >
              Schlüssel rekonstruieren
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                setNotice(null);
                setManual(true);
              }}
            >
              Schlüssel von Hand hinzufügen
            </Button>
          </div>
        </div>
        <dl className={styles.facts}>
          <div className={styles.fact}>
            <dt>DNS heute</dt>
            <dd>
              {dnsStatusLabel(detail.dns_status)}
              {detail.dns_fetched_at && (
                <span
                  className={styles.muted}
                >{` · abgefragt ${formatDateTime(detail.dns_fetched_at)}`}</span>
              )}
              {detail.dns_record && <pre className={styles.record}>{detail.dns_record}</pre>}
            </dd>
          </div>
          <div className={styles.fact}>
            <dt>Signaturen</dt>
            <dd>
              <StatusMix statuses={detail.statuses} labels />
            </dd>
          </div>
        </dl>
      </Card>

      {concerns(job, detail.name) && <KeysRun job={job} onError={showError} />}
      {notice && (
        <div
          role={notice.tone === "error" ? "alert" : "status"}
          className={cx(styles.notice, styles[notice.tone])}
        >
          <span>{notice.text}</span>
          <Button
            variant="link"
            size="xs"
            className={styles.noticeClose}
            aria-label="Hinweis schließen"
            onClick={() => setNotice(null)}
          >
            <CrossIcon />
          </Button>
        </div>
      )}

      <ul className={styles.tiles} aria-label="Kennzahlen">
        <Tile label="Signaturen" value={formatNumber(detail.signatures)} sub="ohne Duplikate" />
        <Tile label="Mails" value={formatNumber(detail.mails)} sub="mit dieser Signatur" />
        <Tile
          label="RSA-Signaturen"
          value={formatNumber(detail.rsa_signatures)}
          sub={detail.rsa_signatures >= 2 ? "rekonstruierbar" : "zu wenige zum Rekonstruieren"}
        />
        <Tile
          label="Zeitraum"
          value={periodText(detail.first_signed, detail.last_signed)}
          sub="erste bis letzte Signatur (t=)"
          small
        />
      </ul>

      <Card aria-labelledby="selector-keys-title">
        <CardTitle id="selector-keys-title">
          {`Schlüssel aus anderen Quellen (${formatNumber(detail.keys.length)})`}
        </CardTitle>
        <KeyList keys={detail.keys} checkBlocked={blocked} onCheck={() => run("check")} />
      </Card>

      <Card aria-labelledby="selector-lookups-title">
        <CardTitle id="selector-lookups-title">
          {`Abfragen (${formatNumber(detail.lookups.length)})`}
        </CardTitle>
        <LookupTable lookups={detail.lookups} />
      </Card>

      <Card aria-labelledby="selector-mails-title">
        <CardTitle id="selector-mails-title">Mails, neueste zuerst</CardTitle>
        <SelectorMails mails={detail.recent_mails} total={detail.mails} />
      </Card>

      {manual && (
        <ManualKeyDialog
          name={detail.name}
          onClose={() => setManual(false)}
          onAdded={() => {
            setManual(false);
            setNotice({
              tone: "info",
              text: "Schlüssel hinzugefügt. Mailrobbe prüft die Mails dieses Selektors jetzt mit ihm; die Zahlen folgen, sobald die Prüfung fertig ist.",
            });
          }}
        />
      )}
    </div>
  );
}

function Tile({
  label,
  value,
  sub,
  small = false,
}: {
  label: string;
  value: string;
  sub: string;
  small?: boolean;
}) {
  return (
    <li className={styles.tile}>
      <span className={styles.tileLabel}>{label}</span>
      <span className={cx(styles.tileValue, small && styles.small)}>{value}</span>
      <span className={styles.tileSub}>{sub}</span>
    </li>
  );
}
