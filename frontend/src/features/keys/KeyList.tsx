import { Link } from "react-router";

import { lookupRawUrl } from "../../api/client";
import type { DkimKeyInfo, KeyEvidenceInfo, UsedSignature } from "../../api/types";
import { Button } from "../../components/Button";
import { KeyOriginBadge } from "../../components/KeyOriginBadge";
import { ShortHash } from "../../components/ShortHash";
import { evidenceTimes, KEY_SOURCE_LABELS, KEY_SOURCE_VERBS } from "../../lib/dkim";
import { formatBytes, formatDateTime, formatNumber } from "../../lib/format";
import styles from "./KeyList.module.css";
import { Reference } from "./Reference";

/** The keys of a name from sources other than today's DNS, strongest first (D100), each with
 *  all its evidence. */
export function KeyList({
  keys,
  checkBlocked,
  onCheck,
}: {
  keys: DkimKeyInfo[];
  /** Why no check can start now, or null. */
  checkBlocked: string | null;
  onCheck: () => void;
}) {
  if (keys.length === 0) {
    return (
      <p className={styles.empty}>
        Noch kein Schlüssel aus einer anderen Quelle als dem heutigen DNS. „Schlüssel
        rekonstruieren“ berechnet einen aus zwei RSA-Signaturen; einen anderswo gefundenen trägt
        „Schlüssel von Hand hinzufügen“ ein.
      </p>
    );
  }
  return (
    <ol className={styles.keys}>
      {keys.map((key) => (
        <KeyBlock key={key.id} dkimKey={key} checkBlocked={checkBlocked} onCheck={onCheck} />
      ))}
    </ol>
  );
}

function KeyBlock({
  dkimKey: key,
  checkBlocked,
  onCheck,
}: {
  dkimKey: DkimKeyInfo;
  checkBlocked: string | null;
  onCheck: () => void;
}) {
  return (
    <li className={styles.key} aria-label={`Schlüssel ${key.key_sha256}`}>
      <div className={styles.head}>
        <KeyOriginBadge origin={key.origin} />
        <span
          className={styles.type}
        >{`${key.key_type.toUpperCase()} · ${formatNumber(key.bits)} Bit`}</span>
        <span className={styles.hash}>
          <span className={styles.muted}>SHA-256</span>
          <ShortHash hash={key.key_sha256} copy />
        </span>
        <span className={styles.count}>
          {`${formatNumber(key.signatures)} ${key.signatures === 1 ? "Signatur" : "Signaturen"} bestätigt`}
        </span>
      </div>
      {key.factorable ? (
        <p className={styles.warning}>
          Dieser Schlüssel teilt einen Primfaktor mit einem anderen: Wer beide kennt, kann den
          privaten Schlüssel berechnen und damit signieren. Mailrobbe prüft mit ihm nichts.
        </p>
      ) : (
        key.signatures === 0 && (
          <p className={styles.note}>
            Er hat bisher keine Signatur bestätigt: Entweder passt er zu keiner, oder die Prüfung
            steht noch aus, weil beim Eintragen ein anderer Lauf lief.{" "}
            <Button
              variant="link"
              size="xs"
              disabled={checkBlocked !== null}
              title={checkBlocked ?? undefined}
              onClick={onCheck}
            >
              Signaturen prüfen
            </Button>
          </p>
        )
      )}
      <details className={styles.details}>
        <summary className={styles.summary}>Schlüsseleintrag anzeigen</summary>
        <pre className={styles.record}>{key.record}</pre>
      </details>
      <h3 className={styles.evidenceTitle}>
        {key.evidence.length === 1 ? "Beleg" : `Belege (${formatNumber(key.evidence.length)})`}
      </h3>
      <ol className={styles.evidence}>
        {key.evidence.map((evidence) => (
          <Evidence key={evidence.id} evidence={evidence} />
        ))}
      </ol>
    </li>
  );
}

function Evidence({ evidence }: { evidence: KeyEvidenceInfo }) {
  const times = evidenceTimes(evidence.observed_from, evidence.observed_to);
  return (
    <li className={styles.item}>
      <div className={styles.line}>
        <strong>{KEY_SOURCE_LABELS[evidence.source]}</strong>
        <KeyOriginBadge origin={evidence.origin} />
        <span className={styles.muted}>
          {`${KEY_SOURCE_VERBS[evidence.source]} ${formatDateTime(evidence.asked_at)}`}
          {evidence.editor && ` von ${evidence.editor}`}
        </span>
      </div>
      {times && <div>{times}</div>}
      {evidence.reference && (
        <div className={styles.reference}>
          <span className={styles.muted}>Beleg: </span>
          <Reference value={evidence.reference} />
        </div>
      )}
      {evidence.note && <p className={styles.evidenceNote}>{evidence.note}</p>}
      {evidence.raw_sha256 && (
        <div className={styles.line}>
          <a href={lookupRawUrl(evidence.lookup_id)} download>
            Antwort der Quelle herunterladen
          </a>
          {evidence.raw_size !== null && (
            <span className={styles.muted}>{formatBytes(evidence.raw_size)}</span>
          )}
          <span className={styles.muted}>SHA-256</span>
          <ShortHash hash={evidence.raw_sha256} />
        </div>
      )}
      {evidence.signatures.length > 0 && <UsedSignatures signatures={evidence.signatures} />}
    </li>
  );
}

/** The signatures a reconstruction computed the key from (D104), each leading to its mail. */
function UsedSignatures({ signatures }: { signatures: UsedSignature[] }) {
  return (
    <div className={styles.used}>
      <span className={styles.muted}>
        {`Berechnet aus ${formatNumber(signatures.length)} ${signatures.length === 1 ? "Signatur" : "Signaturen"}:`}
      </span>
      <ul className={styles.usedList}>
        {signatures.map((signature) => (
          <li key={`${signature.mail_sha256}-${signature.signature_index}`}>
            {signature.mail_id === null ? (
              <span className={styles.muted}>
                {`Mail nicht mehr im Archiv (SHA-256 ${signature.mail_sha256.slice(0, 16)}…)`}
              </span>
            ) : (
              <Link to={`/mails/${signature.mail_id}`}>{`Mail #${signature.mail_id}`}</Link>
            )}
            <span className={styles.muted}>{` · Signatur ${signature.signature_index + 1}`}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
