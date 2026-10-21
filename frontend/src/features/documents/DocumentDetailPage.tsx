import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";

import { ApiError, attachmentContentUrl } from "../../api/client";
import { useDocument } from "../../api/queries";
import type { DocumentDetail } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Card } from "../../components/Card";
import { ErrorState } from "../../components/ErrorState";
import { PersonLink } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { formatBytes, formatDate, formatDateTime, formatNumber } from "../../lib/format";
import styles from "./DocumentDetailPage.module.css";
import { DocumentMails } from "./DocumentMails";
import { DocumentNames, DocumentPersons, DocumentPreview } from "./DocumentSide";
import { StatusLabel } from "./DocumentTable";
import { DocumentTextCard } from "./DocumentTextCard";
import { KindIcon } from "./KindIcon";
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

function DocumentView({ id }: { id: number }) {
  const detail = useDocument(id);
  const name = detail.data ? documentName(detail.data.name) : null;
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

  return (
    <div className={styles.columns}>
      <main className={styles.main}>
        <DocumentHeader document={document} />
        <DocumentTiles document={document} />
        <DocumentMails document={document} state={state} href={href} />
        {hasStoredText(document.text_status) && <DocumentTextCard document={document} />}
      </main>
      <aside className={styles.side} aria-label="Zum Dokument">
        {document.preview === "image" && <DocumentPreview key={document.id} document={document} />}
        <DocumentNames document={document} />
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

/** Name, kind, size, hash, first mail, the text status in plain German, the download. */
function DocumentHeader({ document }: { document: DocumentDetail }) {
  const meta = [
    document.kind ? KIND_LABELS[document.kind] : "Art unbekannt",
    document.pages !== null && pagesText(document.pages),
    formatBytes(document.size),
    document.mime_type,
  ].filter(Boolean);
  const first = document.first_mail;
  const unreadable = document.text_status === "unreadable";

  return (
    <Card className={styles.header}>
      <div className={styles.identity}>
        <KindIcon kind={document.kind} size={36} />
        <div className={styles.titles}>
          <h1 className={styles.name}>{documentName(document.name)}</h1>
          <p className={styles.meta}>{meta.join(" · ")}</p>
        </div>
        {unreadable ? (
          <span
            className={buttonClass("primary")}
            aria-disabled="true"
            title="Die MBOX-Datei dieses Anhangs fehlt oder hat sich geändert."
          >
            Herunterladen
          </span>
        ) : (
          <a
            href={attachmentContentUrl(document.attachment_id)}
            className={buttonClass("primary")}
            download
          >
            Herunterladen
          </a>
        )}
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
        <div className={styles.fact}>
          <dt>Text</dt>
          <dd className={styles.status}>
            <span className={styles.statusHead}>
              {document.text_status === "text" ? (
                <span className={styles.ok}>{TEXT_STATUS_LABELS.text}</span>
              ) : (
                <StatusLabel status={document.text_status} />
              )}
              {document.extracted_at && (
                <span
                  className={styles.muted}
                >{`ausgelesen ${formatDateTime(document.extracted_at)}`}</span>
              )}
            </span>
            <span>
              {TEXT_STATUS_TEXTS[document.text_status]}
              {document.text_status === "text" &&
                document.text_truncated &&
                " Gespeichert sind die ersten 400.000 Zeichen."}
            </span>
            {document.text_error && <code className={styles.error}>{document.text_error}</code>}
          </dd>
        </div>
      </dl>
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

interface Tile {
  label: string;
  value: string;
  sub: string;
}

function dateTile(label: string, iso: string | null): Tile {
  if (!iso) return { label, value: "–", sub: "unbekannt" };
  return { label, value: formatDate(iso), sub: formatDateTime(iso).slice(-5) + " Uhr" };
}

/** The figures of D70: mails without duplicates, every occurrence, first and last date. */
function DocumentTiles({ document }: { document: DocumentDetail }) {
  const tiles: Tile[] = [
    { label: "Mails", value: formatNumber(document.mails), sub: "ohne Duplikate" },
    {
      label: "Anhänge",
      value: formatNumber(document.attachments),
      sub: "Vorkommen, mit Duplikaten",
    },
    dateTile("Erstmals", document.first_date),
    dateTile("Zuletzt", document.last_date),
  ];
  return (
    <ul className={styles.tiles} aria-label="Kennzahlen">
      {tiles.map((tile) => (
        <li key={tile.label} className={styles.tile}>
          <span className={styles.tileLabel}>{tile.label}</span>
          <span className={styles.tileValue}>{tile.value}</span>
          <span className={styles.tileSub}>{tile.sub}</span>
        </li>
      ))}
    </ul>
  );
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
