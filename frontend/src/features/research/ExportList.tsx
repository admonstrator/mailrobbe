import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { queryKeys, useExports } from "../../api/queries";
import type { ExportInfo } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { HelpTip } from "../../components/PageHead";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { Spinner } from "../../components/Spinner";
import { formatDateTime } from "../../lib/format";
import styles from "./AktenScreen.module.css";
import { mailCount } from "./labels";

const DIGITS = 12; // of the SHA-256 shown

/** The Exporte tab (D62): every export with who made it and the SHA-256 of its SHA256SUMS,
 *  recorded at the first complete download, which vouches for every file of the ZIP. */
export function ExportList() {
  const exports = useExports();
  const queryClient = useQueryClient();
  // A download finishes after the list was loaded; show what has been recorded since.
  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.exports });
  }, [queryClient]);

  return (
    <>
      <div className={styles.toolbar}>
        <p className={styles.intro}>
          Exporte entstehen in der Mailliste und auf der Seite einer Akte.
          <HelpTip text="Ein Export ist ein ZIP mit den Originalmails, PDF-Lesefassungen, Manifest und Prüfsummen." />
        </p>
      </div>
      <div className={styles.listCard}>
        {exports.isPending ? (
          <div className={styles.loading}>
            <Spinner label="Exporte werden geladen" />
          </div>
        ) : exports.isError ? (
          <ErrorState
            title="Die Exporte konnten nicht geladen werden."
            actions={<Button onClick={() => void exports.refetch()}>Erneut versuchen</Button>}
          >
            Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
          </ErrorState>
        ) : exports.data.length === 0 ? (
          <EmptyState title="Noch kein Export" />
        ) : (
          <ul className={styles.list}>
            {exports.data.map((item) => (
              <ExportRow key={item.id} item={item} />
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function ExportRow({ item }: { item: ExportInfo }) {
  return (
    <li className={styles.item}>
      <div className={styles.itemMain}>
        <span className={styles.itemTitle}>
          {item.label || `Export ${item.id}`}
          <span className={styles.badge}>
            {item.include_research ? "mit Rechercheangaben" : "ohne Rechercheangaben"}
          </span>
          {item.include_passwords && <span className={styles.badge}>mit Kennwörtern</span>}
        </span>
        <span className={styles.itemSub}>
          Export {item.id} · {mailCount(item.mails)} · {formatDateTime(item.created_at)}
          {item.created_by && ` · ${item.created_by}`}
        </span>
        <span className={styles.itemSub}>
          {item.manifest_sha256 ? (
            <ExportHash hash={item.manifest_sha256} />
          ) : (
            "noch nicht heruntergeladen"
          )}
        </span>
      </div>
      <div className={styles.itemActions}>
        <a href={item.download_url} className={buttonClass("default", "sm")} download>
          ZIP herunterladen
        </a>
      </div>
    </li>
  );
}

/** The recorded SHA-256 of SHA256SUMS: shortened, whole on hover, and copyable. */
function ExportHash({ hash }: { hash: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(hash);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }
  return (
    <span className={styles.hash}>
      SHA256SUMS:{" "}
      <code className="mono" title={hash}>
        {hash.slice(0, DIGITS)}…
      </code>
      <Button variant="link" size="xs" onClick={() => void copy()}>
        {copied ? "Kopiert" : "Kopieren"}
      </Button>
    </span>
  );
}
