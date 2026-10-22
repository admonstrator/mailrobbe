import { useState } from "react";
import { Link } from "react-router";

import { useMailBody, useRecheckDkim } from "../../api/queries";
import type { DkimKeyInfo, DkimSignature, MailDetail, MailDkim } from "../../api/types";
import { Button } from "../../components/Button";
import { FoldCard } from "../../components/FoldCard";
import { KeyOriginBadge } from "../../components/KeyOriginBadge";
import { ShortHash } from "../../components/ShortHash";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import {
  CONSISTENT_TEXT,
  DKIM_REASON_TEXTS,
  DKIM_STATUS_LABELS,
  evidenceLine,
  keyName,
  selectorPath,
} from "../../lib/dkim";
import { setFoldOpen } from "../../lib/folds";
import { formatDateTime, formatDuration, formatNumber } from "../../lib/format";
import styles from "./DkimCard.module.css";
import { sourceErrorText } from "./errors";

const yesNo = (value: boolean | null, yes: string, no: string) =>
  value === null ? "unbekannt" : value ? yes : no;

/** "geprüft am 20.10.2026 03:14 · DNS-Antwort aus Cache (TTL 12 h)" */
function checkedLine(signature: DkimSignature): string {
  const dns = signature.dns_cached ? "DNS-Antwort aus Cache" : "DNS-Antwort frisch abgefragt";
  const ttl = signature.dns_ttl === null ? "" : ` (TTL ${formatDuration(signature.dns_ttl)})`;
  return `geprüft am ${formatDateTime(signature.checked_at)} · ${dns}${ttl}`;
}

/** The id of the DKIM box, which the header's badge scrolls to. */
export const DKIM_CARD_ID = "mail-dkim";
/** Its fold (lib/folds): folded unless opened once, the badge in the header opens it. */
export const DKIM_FOLD = "mail.dkim";

/** Folded: "2 Signaturen · Schlüssel nicht im DNS (Selector gelöscht) · geprüft am …". */
function foldedSummary({ status, signatures }: MailDkim): string {
  if (status === null) return "Noch nicht geprüft";
  if (status === "unsigned" || signatures.length === 0) return "Keine DKIM-Signatur";
  const count =
    signatures.length === 1 ? "1 Signatur" : `${formatNumber(signatures.length)} Signaturen`;
  const findings = signatures.map((signature) =>
    signature.reason ? DKIM_REASON_TEXTS[signature.reason] : DKIM_STATUS_LABELS[signature.status],
  );
  return [
    count,
    ...new Set(findings),
    `geprüft am ${formatDateTime(signatures[0].checked_at)}`,
  ].join(" · ");
}

/** The DKIM box (SPEC 3.4, 5.2): one block per signature, "Neu prüfen" checks again and
 *  opens it. It folds to one line, and is folded until opened once. */
export function DkimCard({ mail }: { mail: MailDetail }) {
  const recheck = useRecheckDkim(mail.id);
  const { status, signatures } = mail.dkim;

  return (
    <FoldCard
      id={DKIM_FOLD}
      elementId={DKIM_CARD_ID}
      variant="main"
      defaultOpen={false}
      className={styles.card}
      title="DKIM-Prüfung"
      summary={foldedSummary(mail.dkim)}
      actions={
        <Button
          size="xs"
          disabled={recheck.isPending}
          onClick={() => {
            setFoldOpen(DKIM_FOLD, true);
            recheck.mutate();
          }}
        >
          {recheck.isPending ? (
            <>
              <Spinner label="Prüfung läuft" /> Prüfe …
            </>
          ) : (
            "Neu prüfen"
          )}
        </Button>
      }
    >
      {signatures.length > 0 && <p className={styles.sub}>{checkedLine(signatures[0])}</p>}
      {recheck.isError && (
        <p className={styles.error} role="alert">
          Neu prüfen fehlgeschlagen: {sourceErrorText(recheck.error)}
        </p>
      )}
      {status === null ? (
        <p className={styles.note}>Noch nicht geprüft.</p>
      ) : status === "unsigned" || signatures.length === 0 ? (
        <p className={styles.note}>Diese Mail trägt keine DKIM-Signatur.</p>
      ) : (
        signatures.map((signature, position) => (
          <SignatureBlock
            key={signature.index}
            mailId={mail.id}
            signature={signature}
            number={signatures.length > 1 ? position + 1 : null}
          />
        ))
      )}
    </FoldCard>
  );
}

function SignatureBlock({
  mailId,
  signature,
  number,
}: {
  mailId: number;
  signature: DkimSignature;
  number: number | null;
}) {
  const algorithm = [signature.algorithm, signature.key_bits && `${signature.key_bits} Bit`]
    .filter(Boolean)
    .join(" · ");
  const name = keyName(signature.selector, signature.domain);
  // The selector page lists the names whose signatures lack a key, or no longer fit the key
  // published today; a key from another source links to it in its own block.
  const selectorLink =
    name !== null &&
    signature.key === null &&
    (signature.status === "no_key" ||
      (signature.reason === "signature_mismatch" && signature.body_hash_ok === true));
  return (
    <div className={styles.signature}>
      {number !== null && <h3 className={styles.number}>Signatur {number}</h3>}
      <div className={styles.tiles}>
        <div className={styles.tile}>
          <span className={styles.tileLabel}>Ergebnis</span>
          <span className={styles.resultLine}>
            <span className={cx(styles.result, styles[signature.status])}>{signature.status}</span>
            {signature.key_origin && <KeyOriginBadge origin={signature.key_origin} />}
          </span>
        </div>
        <div className={styles.tile}>
          <span className={styles.tileLabel}>Domain (d=)</span>
          <span className={styles.tileValue}>{signature.domain ?? "–"}</span>
        </div>
        <div className={styles.tile}>
          <span className={styles.tileLabel}>Selector (s=)</span>
          <span className={styles.tileValue}>{signature.selector ?? "–"}</span>
        </div>
        <div className={styles.tile}>
          <span className={styles.tileLabel}>Algorithmus</span>
          <span className={styles.tileValue}>{algorithm || "–"}</span>
        </div>
      </div>
      <div className={styles.facts}>
        <div>
          <span className={styles.muted}>Signierte Header:</span>{" "}
          <span className={styles.mono}>{signature.signed_headers?.join(":") ?? "–"}</span>
        </div>
        <div>
          <span className={styles.muted}>Body-Hash:</span>{" "}
          <span className={styles.mono}>
            {yesNo(signature.body_hash_ok, "übereinstimmend", "abweichend")}
          </span>
        </div>
        <div>
          <span className={styles.muted}>Signiert am:</span>{" "}
          {signature.signed_at ? `${formatDateTime(signature.signed_at, true)} (t=)` : "–"}
        </div>
        <div>
          <span className={styles.muted}>Absender-Domain = d=:</span>{" "}
          {yesNo(signature.aligned, "ja (aligned)", "nein")}
        </div>
      </div>
      {signature.reason && (
        <p className={cx(styles.reason, styles[`reason_${signature.status}`])}>
          {DKIM_REASON_TEXTS[signature.reason]}
          {selectorLink && (
            <>
              {" · "}
              <Link to={selectorPath(name)} className={styles.reasonLink}>
                Selektor ansehen
              </Link>
            </>
          )}
        </p>
      )}
      {signature.status === "consistent" && (
        <p className={cx(styles.reason, styles.reason_consistent)}>{CONSISTENT_TEXT}</p>
      )}
      {signature.key && <KeyBlock dkimKey={signature.key} />}
      <SignatureSource mailId={mailId} signature={signature} />
    </div>
  );
}

/** The stored key that verified the signature, kept from DNS (D106) or from another source
 *  (D100): its SHA-256, size, evidence in one line each and the way to everything about its
 *  name. */
function KeyBlock({ dkimKey: key }: { dkimKey: DkimKeyInfo }) {
  return (
    <div className={styles.key}>
      <div className={styles.keyHead}>
        <span className={styles.muted}>Schlüssel</span>
        <ShortHash hash={key.key_sha256} copy />
        <span>{`${key.key_type.toUpperCase()} · ${formatNumber(key.bits)} Bit`}</span>
        <Link to={selectorPath(key.name)} className={styles.keyLink}>
          Selektor ansehen
        </Link>
      </div>
      <ul className={styles.evidence} aria-label="Belege">
        {key.evidence.map((evidence) => (
          <li key={evidence.id}>{evidenceLine(evidence)}</li>
        ))}
      </ul>
    </div>
  );
}

/** The disclosure with the signature's header field and the key's DNS record; the headers are
 *  read from the MBOX file only when it is opened. */
function SignatureSource({ mailId, signature }: { mailId: number; signature: DkimSignature }) {
  const [open, setOpen] = useState(false);
  const headers = useMailBody(mailId, "headers", open);
  const field = headers.data?.headers.filter(
    (header) => header.name.toLowerCase() === "dkim-signature",
  )[signature.index];
  const recordName = keyName(signature.selector, signature.domain);

  return (
    <details className={styles.details} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className={styles.summary}>DKIM-Signature-Header und DNS-Record anzeigen</summary>
      {headers.isPending && open ? (
        <Spinner />
      ) : headers.isError ? (
        <p className={styles.error}>{sourceErrorText(headers.error)}</p>
      ) : (
        <pre className={styles.source}>
          {field ? `${field.name}: ${field.value}` : "DKIM-Signature-Header nicht gefunden."}
          {"\n\n"}
          {recordName && `${recordName}  TXT  `}
          {signature.dns_record ?? "kein DNS-Record im Cache"}
        </pre>
      )}
    </details>
  );
}
