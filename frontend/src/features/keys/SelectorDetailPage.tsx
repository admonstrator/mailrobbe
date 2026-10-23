import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { ApiError } from "../../api/client";
import { useSelector, useStartKeysRun } from "../../api/queries";
import type { DkimKeysJob, SelectorDetail } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { ErrorState } from "../../components/ErrorState";
import { CrossIcon } from "../../components/icons";
import { Spinner } from "../../components/Spinner";
import { tabPanelProps, Tabs } from "../../components/Tabs";
import { cx } from "../../lib/cx";
import { formatDateTime, formatNumber } from "../../lib/format";
import { Figures, PageHead } from "../import/PageHead";
import { KeyList } from "./KeyList";
import { KeysRun, useKeysRun } from "./KeysRun";
import { dnsStatusLabel, keysErrorText, periodText } from "./labels";
import { ManualKeyDialog } from "./ManualKeyDialog";
import styles from "./SelectorDetailPage.module.css";
import { LookupTable, SelectorMails } from "./SelectorTables";
import { StatusMix } from "./StatusMix";
import { SELECTOR_LIST_PATH } from "./urlState";

type SelectorTab = "schluessel" | "abfragen" | "mails";

const TABS: readonly SelectorTab[] = ["schluessel", "abfragen", "mails"];

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
        <div className={styles.message}>
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
        </div>
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
  const [params, setParams] = useSearchParams();
  const requested = params.get("tab") as SelectorTab | null;
  const tab: SelectorTab = requested && TABS.includes(requested) ? requested : "schluessel";
  const select = (next: SelectorTab) =>
    setParams(
      (before) => {
        const search = new URLSearchParams(before);
        if (next === "schluessel") search.delete("tab");
        else search.set("tab", next);
        return search;
      },
      { replace: true, preventScrollReset: true },
    );
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
      <PageHead
        title={<span className={styles.name}>{detail.name}</span>}
        sub={
          <span className={styles.meta}>
            Selektor <strong>{detail.selector}</strong> · Domain <strong>{detail.domain}</strong>
          </span>
        }
        actions={
          <>
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
          </>
        }
      />
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

      <Figures
        label="Kennzahlen"
        items={[
          { value: formatNumber(detail.signatures), label: "Signaturen", sub: "ohne Duplikate" },
          { value: formatNumber(detail.mails), label: "Mails", sub: "mit dieser Signatur" },
          {
            value: formatNumber(detail.rsa_signatures),
            label: "RSA-Signaturen",
            sub: detail.rsa_signatures >= 2 ? "rekonstruierbar" : "zu wenige zum Rekonstruieren",
          },
          {
            value: periodText(detail.first_signed, detail.last_signed),
            label: "Zeitraum",
            sub: "erste bis letzte Signatur (t=)",
          },
        ]}
      />

      <Tabs
        idPrefix="selector"
        label="Bereiche des Selektors"
        active={tab}
        onSelect={select}
        items={[
          { id: "schluessel", label: "Schlüssel", count: formatNumber(detail.keys.length) },
          { id: "abfragen", label: "Abfragen", count: formatNumber(detail.lookups.length) },
          { id: "mails", label: "Mails", count: formatNumber(detail.mails) },
        ]}
      />
      <div {...tabPanelProps("selector", tab)}>
        {tab === "schluessel" ? (
          <section className={styles.panel} aria-labelledby="selector-keys-title">
            <h2 id="selector-keys-title" className="sr-only">
              {`Schlüssel aus anderen Quellen (${formatNumber(detail.keys.length)})`}
            </h2>
            <KeyList keys={detail.keys} checkBlocked={blocked} onCheck={() => run("check")} />
          </section>
        ) : tab === "abfragen" ? (
          <section className={styles.panel} aria-labelledby="selector-lookups-title">
            <h2 id="selector-lookups-title" className="sr-only">
              {`Abfragen (${formatNumber(detail.lookups.length)})`}
            </h2>
            <LookupTable lookups={detail.lookups} />
          </section>
        ) : (
          <section className={styles.panel} aria-labelledby="selector-mails-title">
            <h2 id="selector-mails-title" className="sr-only">
              Mails, neueste zuerst
            </h2>
            <SelectorMails mails={detail.recent_mails} total={detail.mails} />
          </section>
        )}
      </div>

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
