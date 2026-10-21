import { useState } from "react";

import { useMailBody, useRecheckDkim } from "../../api/queries";
import type { DkimSignature, MailDetail } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { DKIM_REASON_TEXTS } from "../../lib/dkim";
import { formatDateTime, formatDuration } from "../../lib/format";
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

/** The DKIM box (SPEC 3.4, 5.2): one block per signature, "Neu prüfen" checks again. */
export function DkimCard({ mail }: { mail: MailDetail }) {
  const recheck = useRecheckDkim(mail.id);
  const { status, signatures } = mail.dkim;

  return (
    <Card>
      <div className={styles.head}>
        <CardTitle>DKIM-Prüfung</CardTitle>
        {signatures.length > 0 && <span className={styles.sub}>{checkedLine(signatures[0])}</span>}
        <Button
          size="xs"
          className={styles.recheck}
          disabled={recheck.isPending}
          onClick={() => recheck.mutate()}
        >
          {recheck.isPending ? (
            <>
              <Spinner label="Prüfung läuft" /> Prüfe …
            </>
          ) : (
            "Neu prüfen"
          )}
        </Button>
      </div>
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
    </Card>
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
  return (
    <div className={styles.signature}>
      {number !== null && <h3 className={styles.number}>Signatur {number}</h3>}
      <div className={styles.tiles}>
        <div className={styles.tile}>
          <span className={styles.tileLabel}>Ergebnis</span>
          <span className={cx(styles.result, styles[signature.status])}>{signature.status}</span>
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
        </p>
      )}
      <SignatureSource mailId={mailId} signature={signature} />
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
  const recordName =
    signature.selector && signature.domain
      ? `${signature.selector}._domainkey.${signature.domain}`.toLowerCase()
      : null;

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
