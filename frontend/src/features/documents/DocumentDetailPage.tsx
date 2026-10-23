import { useEffect, useMemo, useRef, useState, type Ref } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { ApiError, attachmentContentUrl, attachmentDecryptedUrl } from "../../api/client";
import { useDocument } from "../../api/queries";
import type { DocumentDetail, PreviewKind } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { CompactBar, useScrolledPast } from "../../components/CompactBar";
import { ErrorState } from "../../components/ErrorState";
import { Figures, type Figure } from "../../components/PageHead";
import { PersonLink } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import {
  formatBytes,
  formatClock,
  formatDate,
  formatDateTime,
  formatNumber,
} from "../../lib/format";
import { useRecordVisit } from "../../lib/history";
import { SummarizeButton, SummaryCard } from "../ai/SummaryCard";
import { AttachmentPreview } from "../preview/AttachmentPreview";
import { ContentsCard } from "./ContentsCard";
import styles from "./DocumentDetailPage.module.css";
import { DocumentMails } from "./DocumentMails";
import { RecognizeButton } from "./DocumentOcr";
import {
  DocumentContainers,
  DocumentNames,
  DocumentPersons,
  DocumentPreview,
} from "./DocumentSide";
import { StatusLabel } from "./DocumentRows";
import { DocumentTextCard } from "./DocumentTextCard";
import { KindIcon } from "./KindIcon";
import { MachineMark } from "./MachineMark";
import { MetadataCard } from "./MetadataCard";
import { ProtectionCard } from "./ProtectionCard";
import { TranscriptCard } from "./TranscriptCard";
import {
  documentName,
  hasStoredText,
  KIND_LABELS,
  pagesText,
  TEXT_STATUS_LABELS,
  TEXT_STATUS_TEXTS,
} from "./labels";
import {
  documentMailSearch,
  documentPath,
  parseDocumentMailState,
  type DocumentMailState,
} from "./urlState";

/** The document page (D75): what the document is, who sent it when to whom, its text. */
export function DocumentDetailPage() {
  const { id } = useParams();
  if (!id || !/^\d+$/.test(id)) {
    return (
      <div className={styles.page}>
        <DocumentNotFound />
      </div>
    );
  }
  return <DocumentView key={id} id={Number(id)} />;
}

/** The document's entry in "Zuletzt angesehen" (D333): its name, and the mail it came with
 *  first, else its kind. */
function documentVisit(document: DocumentDetail) {
  const first = document.first_mail;
  return {
    kind: "document" as const,
    id: document.id,
    title: documentName(document.name),
    subtitle: first
      ? `aus „${first.subject || "(ohne Betreff)"}“`
      : document.kind
        ? KIND_LABELS[document.kind]
        : undefined,
    path: documentPath(document.id),
  };
}

function DocumentView({ id }: { id: number }) {
  const detail = useDocument(id);
  const name = detail.data ? documentName(detail.data.name) : null;
  useRecordVisit(detail.data ? documentVisit(detail.data) : null);
  return (
    <div className={styles.page}>
      <title>{`${name ?? "Dokument"} · Mailrobbe`}</title>
      <nav aria-label="Pfad" className={styles.breadcrumb}>
        <Link to="/anhaenge">Anhänge</Link>
        {name && (
          <>
            <span aria-hidden="true">›</span>
            <span className={styles.crumb}>{name}</span>
          </>
        )}
      </nav>
      {detail.isPending ? (
        <div className={styles.loading}>
          <Spinner label="Dokument wird geladen" />
        </div>
      ) : detail.isError ? (
        detail.error instanceof ApiError && detail.error.code === "not_found" ? (
          <DocumentNotFound id={id} />
        ) : (
          <Card className={styles.message}>
            <ErrorState
              title="Das Dokument konnte nicht geladen werden."
              actions={<Button onClick={() => void detail.refetch()}>Erneut versuchen</Button>}
            >
              Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
            </ErrorState>
          </Card>
        )
      ) : (
        <DocumentContent document={detail.data} />
      )}
    </div>
  );
}

function DocumentContent({ document }: { document: DocumentDetail }) {
  const [searchParams] = useSearchParams();
  const state = useMemo(() => parseDocumentMailState(searchParams), [searchParams]);
  const href = (next: DocumentMailState) => {
    const search = documentMailSearch(next).toString();
    return `${documentPath(document.id)}${search ? `?${search}` : ""}`;
  };
  // Scrolled past the header, a compact bar keeps name and download in view (D166).
  const [header, compact] = useScrolledPast<HTMLElement>();
  // The player of a recording, which the transcript's times play from (D296).
  const [player, setPlayer] = useState<HTMLMediaElement | null>(null);
  const transcript = Boolean(document.transcribable || document.transcript);

  return (
    <div className={styles.columns}>
      {compact && (
        <CompactBar label="Kopfzeile des Dokuments">
          <CompactDocument document={document} />
        </CompactBar>
      )}
      <main className={styles.main}>
        <DocumentHeader ref={header} document={document} />
        {document.protection && <ProtectionCard document={document} />}
        <DocumentFigures document={document} />
        <SummaryCard target="document" id={document.id} />
        {document.preview && document.preview !== "image" && document.protection !== "locked" && (
          <PreviewCard document={document} kind={document.preview} onMedia={setPlayer} />
        )}
        {/* A recording's transcript in place of the text card, below its player (D296). */}
        {transcript && <TranscriptCard document={document} player={player} />}
        {document.members && <ContentsCard document={document} members={document.members} />}
        <DocumentMails document={document} state={state} href={href} />
        {!transcript &&
          (hasStoredText(document.text_status) || document.ocr_readable || document.ai) && (
            <DocumentTextCard document={document} />
          )}
      </main>
      <aside className={styles.side} aria-label="Zum Dokument">
        {document.preview === "image" && <DocumentPreview key={document.id} document={document} />}
        {document.containers && document.containers.length > 0 && (
          <DocumentContainers containers={document.containers} />
        )}
        <DocumentNames document={document} />
        <MetadataCard document={document} />
        <DocumentPersons
          id="document-senders-title"
          title="Absender"
          persons={document.senders}
          total={document.sender_count}
          empty="Kein Absender bekannt."
        />
        <DocumentPersons
          id="document-recipients-title"
          title="Empfänger"
          persons={document.recipients}
          total={document.recipient_count}
          empty="Kein Empfänger bekannt."
        />
      </aside>
    </div>
  );
}

/** "PDF · 14 Seiten · 168 KB", "Audio/Video · 3:12 · 96 KB" */
function documentMeta(document: DocumentDetail): string[] {
  return [
    document.kind ? KIND_LABELS[document.kind] : "Art unbekannt",
    document.pages !== null && pagesText(document.pages),
    typeof document.duration === "number" && formatClock(document.duration),
    formatBytes(document.size),
  ].filter((part) => part !== false);
}

/** The download, or why there is none: the MBOX file is gone or changed. */
function Download({ document, size }: { document: DocumentDetail; size?: "sm" }) {
  if (document.text_status === "unreadable") {
    return (
      <span
        className={buttonClass("primary", size)}
        aria-disabled="true"
        title="Die MBOX-Datei dieses Anhangs fehlt oder hat sich geändert."
      >
        Herunterladen
      </span>
    );
  }
  return (
    <a
      href={attachmentContentUrl(document.attachment_id)}
      className={buttonClass("primary", size)}
      title={document.protection ? "Die Datei, wie sie verschickt wurde: verschlüsselt" : undefined}
      download
    >
      Herunterladen
    </a>
  );
}

/** An opened file decrypted with the password found (D209), beside the original; a container's
 *  contents are its members instead. */
function DecryptedDownload({ document }: { document: DocumentDetail }) {
  if (document.protection !== "open" || document.members || document.text_status === "unreadable")
    return null;
  return (
    <a href={attachmentDecryptedUrl(document.attachment_id)} className={buttonClass()} download>
      Entschlüsselt herunterladen
    </a>
  );
}

/** Name, kind, size, hash, first mail, the text status in plain German, the download. */
function DocumentHeader({ document, ref }: { document: DocumentDetail; ref?: Ref<HTMLElement> }) {
  const meta = [...documentMeta(document), document.mime_type];
  const first = document.first_mail;
  const machine =
    (document.text_origin === "ocr" || document.text_origin === "transcript") &&
    document.text_status === "text";
  const heard = machine && document.text_origin === "transcript";

  return (
    <header ref={ref} className={styles.header}>
      <div className={styles.identity}>
        <KindIcon kind={document.kind} size={36} />
        <div className={styles.titles}>
          <h1 className={styles.name}>{documentName(document.name)}</h1>
          <p className={styles.meta}>{meta.join(" · ")}</p>
        </div>
        <div className={styles.downloads}>
          <Download document={document} />
          <RecognizeButton document={document} />
          <SummarizeButton documentId={document.id} />
          <DecryptedDownload document={document} />
        </div>
      </div>
      <dl className={styles.facts}>
        <div className={styles.fact}>
          <dt>SHA-256</dt>
          <dd>
            {document.sha256 ? (
              <HashValue hash={document.sha256} />
            ) : (
              <span className={styles.muted}>nicht gehasht (über dem Hash-Limit)</span>
            )}
          </dd>
        </div>
        <div className={styles.fact}>
          <dt>Erste Mail</dt>
          <dd>
            {first ? (
              <>
                <Link
                  to={`/mails/${first.id}`}
                  className={!first.subject ? styles.muted : undefined}
                >
                  {first.subject || "(kein Betreff)"}
                </Link>
                {first.sender && (
                  <>
                    {" · von "}
                    <PersonLink person={first.sender} className={styles.person} />
                  </>
                )}
                {first.date && (
                  <span className={styles.muted}>{` · ${formatDateTime(first.date)}`}</span>
                )}
              </>
            ) : (
              <span className={styles.muted}>unbekannt</span>
            )}
          </dd>
        </div>
        {(document.preview === null || document.protection === "locked") && (
          <div className={styles.fact}>
            <dt>Vorschau</dt>
            <dd className={styles.muted}>
              {document.protection === "locked"
                ? "Keine Vorschau, solange das Kennwort fehlt."
                : "Keine Vorschau im Browser, nur Download."}
              {hasStoredText(document.text_status) && " Text siehe unten."}
            </dd>
          </div>
        )}
        <div className={styles.fact}>
          <dt>Text</dt>
          <dd className={styles.status}>
            <span className={styles.statusHead}>
              {document.text_status === "text" ? (
                <span className={styles.ok}>{TEXT_STATUS_LABELS.text}</span>
              ) : (
                <StatusLabel status={document.text_status} />
              )}
              {machine && <MachineMark transcript={heard} />}
              {document.extracted_at && (
                <span
                  className={styles.muted}
                >{`${heard ? "transkribiert" : machine ? "erkannt" : "ausgelesen"} ${formatDateTime(
                  document.extracted_at,
                )}`}</span>
              )}
            </span>
            <span>
              {heard
                ? "Der Text wurde maschinell aus dem Ton der Aufnahme transkribiert (siehe „Transkript“); die Volltextsuche findet das Dokument über seine Wörter."
                : machine
                  ? "Der Text wurde aus den Seitenbildern erkannt (siehe „Erkannter Text“); die Volltextsuche findet das Dokument über seine Wörter."
                  : TEXT_STATUS_TEXTS[document.text_status]}
              {document.text_status === "text" &&
                document.text_truncated &&
                " Gespeichert sind die ersten 400.000 Zeichen."}
            </span>
            {document.text_error && <code className={styles.error}>{document.text_error}</code>}
          </dd>
        </div>
      </dl>
    </header>
  );
}

/** The header in the compact bar (D166): icon, name on one line, kind and size, the download. */
function CompactDocument({ document }: { document: DocumentDetail }) {
  const name = documentName(document.name);
  return (
    <>
      <KindIcon kind={document.kind} size={20} />
      <span className={styles.compactName} title={name}>
        {name}
      </span>
      <span className={styles.compactMeta}>{documentMeta(document).join(" · ")}</span>
      <Download document={document} size="sm" />
      <RecognizeButton document={document} size="sm" />
      <SummarizeButton documentId={document.id} size="sm" />
    </>
  );
}

/** The document as the browser shows it (D120): PDF, Word, audio and video; an image keeps its
 *  card beside. onMedia gets the player of a recording. */
function PreviewCard({
  document,
  kind,
  onMedia,
}: {
  document: DocumentDetail;
  kind: PreviewKind;
  onMedia: (player: HTMLMediaElement | null) => void;
}) {
  return (
    <Card aria-labelledby="document-view-title">
      <CardTitle id="document-view-title">Vorschau</CardTitle>
      <AttachmentPreview
        attachmentId={document.attachment_id}
        kind={kind}
        name={documentName(document.name)}
        decrypted={document.protection === "open"}
        onMedia={onMedia}
      />
    </Card>
  );
}

/** The hash in full, selectable at once, with a button that copies it. */
function HashValue({ hash }: { hash: string }) {
  const value = useRef<HTMLElement>(null);
  const [copied, setCopied] = useState<"copied" | "selected" | null>(null);
  useEffect(() => {
    if (copied === null) return;
    const timer = setTimeout(() => setCopied(null), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  function select() {
    if (value.current) window.getSelection()?.selectAllChildren(value.current);
    setCopied("selected");
  }

  return (
    <span className={styles.hash}>
      <code ref={value} className={styles.hashValue}>
        {hash}
      </code>
      <Button
        variant="link"
        size="xs"
        onClick={() => {
          // Without a secure context (plain HTTP on another host) there is no clipboard API.
          if (!navigator.clipboard) return select();
          navigator.clipboard.writeText(hash).then(() => setCopied("copied"), select);
        }}
      >
        Kopieren
      </Button>
      <span className={styles.copied} role="status">
        {copied === "copied"
          ? "Kopiert"
          : copied === "selected"
            ? "Markiert, mit Strg+C kopieren"
            : ""}
      </span>
    </span>
  );
}

/** The figures of D70 as a row (D334): mails without duplicates, every occurrence, first and
 *  last date. */
function DocumentFigures({ document }: { document: DocumentDetail }) {
  const items: Figure[] = [
    { value: formatNumber(document.mails), label: "Mails", title: "ohne Duplikate" },
    {
      value: formatNumber(document.attachments),
      label: "Anhänge",
      title: "Vorkommen, mit Duplikaten",
    },
  ];
  for (const [label, iso] of [
    ["erster Versand", document.first_date],
    ["letzter Versand", document.last_date],
  ] as const) {
    if (iso) items.push({ value: formatDate(iso), label, title: `${formatDateTime(iso)} Uhr` });
  }
  return <Figures items={items} label="Kennzahlen" />;
}

function DocumentNotFound({ id }: { id?: number }) {
  return (
    <Card className={styles.message}>
      <ErrorState
        title="Dieses Dokument gibt es nicht."
        actions={
          <Link to="/anhaenge" className={buttonClass()}>
            Zu den Anhängen
          </Link>
        }
      >
        {id === undefined
          ? "Die Adresse nennt keine gültige Dokument-Nummer."
          : `Im Archiv gibt es kein Dokument mit der Nummer #${id}.`}
      </ErrorState>
    </Card>
  );
}
