import { Link } from "react-router";

import { attachmentContentUrl } from "../../api/client";
import { useDocument } from "../../api/queries";
import type { DocumentDetail } from "../../api/types";
import { buttonClass } from "../../components/Button";
import { NewWindowIcon } from "../../components/icons";
import { PersonLink } from "../../components/PersonLink";
import { SidePanel } from "../../components/SidePanel";
import { Spinner } from "../../components/Spinner";
import { formatBytes, formatClock, formatDate, formatDateTime } from "../../lib/format";
import { AttachmentPreview } from "../preview/AttachmentPreview";
import styles from "./DocumentPanel.module.css";
import { StatusLabel } from "./DocumentRows";
import { KindIcon } from "./KindIcon";
import { documentName, KIND_LABELS, mailsText, pagesText } from "./labels";
import { ProtectionMark } from "./ProtectionMark";
import { documentPath } from "./urlState";

/** A document of the list in the panel beside it (D335): "Ganz öffnen" leads to its page,
 *  "In neuem Fenster" opens that in a new tab. Below: name, kind and size, the mail it came
 *  with first, how often and when it was sent, the download and the browser's preview. */
export function DocumentPanel({ id, onClose }: { id: number; onClose: () => void }) {
  const detail = useDocument(id);
  const actions = (
    <>
      <Link to={documentPath(id)} className={buttonClass("primary", "sm")}>
        Ganz öffnen
      </Link>
      <a
        href={documentPath(id)}
        target="_blank"
        rel="noopener"
        className={styles.icon}
        aria-label="In neuem Fenster öffnen"
        title="In neuem Fenster öffnen"
      >
        <NewWindowIcon size={17} />
      </a>
    </>
  );
  return (
    <SidePanel label="Vorschau" actions={actions} onClose={onClose}>
      {detail.isPending ? (
        <div className={styles.loading}>
          <Spinner label="Dokument wird geladen" />
        </div>
      ) : detail.isError ? (
        <p className={styles.error} role="alert">
          Das Dokument konnte nicht geladen werden.
        </p>
      ) : (
        <PanelBody key={id} document={detail.data} />
      )}
    </SidePanel>
  );
}

function PanelBody({ document }: { document: DocumentDetail }) {
  const name = documentName(document.name);
  const first = document.first_mail;
  const meta = [
    document.kind ? KIND_LABELS[document.kind] : "Art unbekannt",
    document.pages !== null && pagesText(document.pages),
    typeof document.duration === "number" && formatClock(document.duration),
    formatBytes(document.size),
  ].filter(Boolean);
  const sent = [
    mailsText(document.mails),
    document.first_date && `erstmals ${formatDate(document.first_date)}`,
    document.last_date &&
      document.last_date !== document.first_date &&
      `zuletzt ${formatDate(document.last_date)}`,
  ].filter(Boolean);
  const shown = document.preview !== null && document.protection !== "locked";

  return (
    <div className={styles.body}>
      <div className={styles.identity}>
        <KindIcon kind={document.kind} size={28} />
        <div className={styles.titles}>
          <h2 className={styles.name}>{name}</h2>
          <p className={styles.muted}>{meta.join(" · ")}</p>
        </div>
      </div>
      <div className={styles.marks}>
        {document.protection && <ProtectionMark protection={document.protection} />}
        <StatusLabel status={document.text_status} />
      </div>
      {first && (
        <p className={styles.line}>
          {"aus „"}
          <Link to={`/mails/${first.id}`}>{first.subject || "(ohne Betreff)"}</Link>
          {"“"}
          {first.sender && (
            <>
              {" von "}
              <PersonLink person={first.sender} className={styles.person} />
            </>
          )}
          {first.date && <span className={styles.muted}>{` · ${formatDateTime(first.date)}`}</span>}
        </p>
      )}
      <p className={styles.muted}>{sent.join(" · ")}</p>
      {document.text_status !== "unreadable" && (
        <a
          href={attachmentContentUrl(document.attachment_id)}
          className={buttonClass("default", "sm")}
          download
        >
          Herunterladen
        </a>
      )}
      {shown ? (
        <AttachmentPreview
          attachmentId={document.attachment_id}
          kind={document.preview!}
          name={name}
          decrypted={document.protection === "open"}
        />
      ) : (
        <p className={styles.muted}>
          {document.protection === "locked"
            ? "Keine Vorschau, solange das Kennwort fehlt."
            : "Keine Vorschau im Browser, nur Download."}
        </p>
      )}
    </div>
  );
}
