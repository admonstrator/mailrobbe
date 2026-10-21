import { Link } from "react-router";

import { lookupRawUrl } from "../../api/client";
import { SELECTOR_MAILS_LIMIT, type KeyLookupInfo, type SelectorMail } from "../../api/types";
import { DkimDot } from "../../components/DkimDot";
import { KeyOriginBadge } from "../../components/KeyOriginBadge";
import { PersonLink } from "../../components/PersonLink";
import { cx } from "../../lib/cx";
import { DKIM_REASON_TEXTS, DKIM_STATUS_LABELS, KEY_SOURCE_LABELS } from "../../lib/dkim";
import { formatBytes, formatDateTime, formatNumber } from "../../lib/format";
import { OUTCOME_LABELS } from "./labels";
import styles from "./SelectorTables.module.css";

/** Every question to a source about the name or its domain, newest first (D101), with the
 *  answer as it came. */
export function LookupTable({ lookups }: { lookups: KeyLookupInfo[] }) {
  if (lookups.length === 0) {
    return (
      <p className={styles.empty}>Noch keine Abfrage zu diesem Selektor oder seiner Domain.</p>
    );
  }
  return (
    <div className={styles.scroll}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Zeitpunkt</th>
            <th>Quelle</th>
            <th>Abfrage</th>
            <th>Ergebnis</th>
            <th className={styles.num}>Schlüssel</th>
            <th>Antwort</th>
          </tr>
        </thead>
        <tbody>
          {lookups.map((lookup) => (
            <tr key={lookup.id}>
              <td className={styles.nowrap} title={`Mailrobbe ${lookup.tool_version}`}>
                {formatDateTime(lookup.asked_at)}
                {lookup.editor && <span className={styles.sub}>{lookup.editor}</span>}
              </td>
              <td>{KEY_SOURCE_LABELS[lookup.source]}</td>
              <td className={styles.query}>{lookup.query}</td>
              <td>
                <span className={cx(styles.outcome, styles[lookup.outcome])}>
                  {OUTCOME_LABELS[lookup.outcome]}
                </span>
                {lookup.http_status !== null && (
                  <span className={styles.muted}>{` HTTP ${lookup.http_status}`}</span>
                )}
                {lookup.message && <span className={styles.message}>{lookup.message}</span>}
              </td>
              <td className={styles.num}>{formatNumber(lookup.keys)}</td>
              <td className={styles.nowrap}>
                {lookup.raw_sha256 ? (
                  <a href={lookupRawUrl(lookup.id)} download title={`SHA-256 ${lookup.raw_sha256}`}>
                    {`Herunterladen${lookup.raw_size === null ? "" : ` (${formatBytes(lookup.raw_size)})`}`}
                  </a>
                ) : (
                  <span className={styles.muted}>–</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The name's latest signed mails, newest first, with the signature's status and the origin of
 *  the key it rests on. */
export function SelectorMails({ mails, total }: { mails: SelectorMail[]; total: number }) {
  if (mails.length === 0) {
    return <p className={styles.empty}>Keine Mail trägt eine Signatur dieses Selektors.</p>;
  }
  return (
    <>
      <div className={styles.scroll}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Datum</th>
              <th>Betreff</th>
              <th>Absender</th>
              <th>Signatur</th>
              <th>Schlüssel</th>
            </tr>
          </thead>
          <tbody>
            {mails.map((mail) => (
              <tr key={`${mail.id}-${mail.signature_index}`}>
                <td className={styles.nowrap}>{mail.date ? formatDateTime(mail.date) : "–"}</td>
                <td>
                  <Link
                    to={`/mails/${mail.id}`}
                    className={!mail.subject ? styles.muted : undefined}
                  >
                    {mail.subject || "(kein Betreff)"}
                  </Link>
                </td>
                <td>{mail.sender ? <PersonLink person={mail.sender} /> : "–"}</td>
                <td>
                  <span className={styles.status}>
                    <DkimDot status={mail.status} decorative />
                    {DKIM_STATUS_LABELS[mail.status]}
                    {mail.signature_index > 0 && (
                      <span
                        className={styles.muted}
                      >{`(Signatur ${mail.signature_index + 1})`}</span>
                    )}
                  </span>
                  {mail.reason && (
                    <span className={styles.sub}>{DKIM_REASON_TEXTS[mail.reason]}</span>
                  )}
                </td>
                <td>
                  {mail.key_origin ? (
                    <KeyOriginBadge origin={mail.key_origin} />
                  ) : (
                    <span className={styles.muted}>–</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {mails.length >= SELECTOR_MAILS_LIMIT && total > mails.length && (
        <p className={styles.more}>
          {`Die neuesten ${formatNumber(mails.length)} von ${formatNumber(total)} Mails.`}
        </p>
      )}
    </>
  );
}
