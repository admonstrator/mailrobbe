import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { ApiError } from "../../api/client";
import {
  useAiSummary,
  useMailDetail,
  useMailHits,
  useMailNeighbors,
  useMailSummary,
} from "../../api/queries";
import type { AiSummaryResult, AttachmentInfo, MailDetail } from "../../api/types";
import { buttonClass } from "../../components/Button";
import { Card } from "../../components/Card";
import { CompactBar, useScrolledPast } from "../../components/CompactBar";
import { ErrorState } from "../../components/ErrorState";
import { Spinner } from "../../components/Spinner";
import { formatDate, formatNumber } from "../../lib/format";
import { useRecordVisit } from "../../lib/history";
import { isPlainKey } from "../../lib/keys";
import { personName } from "../../lib/person";
import { SummaryCard } from "../ai/SummaryCard";
import { HiddenNote, HideCard } from "../hiding/MailHiding";
import {
  listSearch,
  parseListState,
  toFilters,
  toHitsParams,
  toOrderParams,
} from "../mails/listState";
import { formatTotal } from "../mails/SummaryTiles";
import { ActionsCard } from "./ActionsCard";
import { AttachmentDialog } from "./AttachmentDialog";
import { AttachmentsCard } from "./AttachmentsCard";
import { BodyCard, type BodyTab } from "./BodyCard";
import { DkimCard } from "./DkimCard";
import { EntitiesCard } from "./EntitiesCard";
import { EventCard } from "./EventCard";
import { CompactHeader, HeaderCard, TechCard } from "./HeaderCard";
import styles from "./MailDetailPage.module.css";
import { NearCard } from "./NearCard";
import { ParticipantsCard } from "./ParticipantsCard";
import { ResearchCard } from "./ResearchCard";
import { SearchHitsCard } from "./SearchHitsCard";
import { SignalsCard } from "./SignalsCard";
import { ThreadCard } from "./ThreadCard";

/** The mail detail (SPEC 5.2), laid out as a mail program shows a mail: header, text and
 *  attachments first, the DKIM check and the technical fields folded below them; every block
 *  folds, as the browser remembers. The list's parameters travel in the query string, so
 *  Vorherige, Nächste and the way back follow the list the mail was opened from. */
export function MailDetailPage() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const listQuery = useMemo(
    () => listSearch(parseListState(searchParams)).toString(),
    [searchParams],
  );
  if (!id || !/^\d+$/.test(id)) {
    return (
      <div className={styles.page}>
        <MailNotFound listQuery={listQuery} />
      </div>
    );
  }
  return <MailDetailView key={id} id={Number(id)} listQuery={listQuery} />;
}

function withList(path: string, listQuery: string): string {
  return listQuery ? `${path}?${listQuery}` : path;
}

/** The mail's entry in "Zuletzt angesehen" (D333): subject, sender and day. */
function mailVisit(mail: MailDetail) {
  const sender = mail.participants.find((person) => person.role === "from");
  const subtitle = [sender && personName(sender), mail.date && formatDate(mail.date)]
    .filter(Boolean)
    .join(" · ");
  return {
    kind: "mail" as const,
    id: mail.id,
    title: mail.subject || "(ohne Betreff)",
    subtitle: subtitle || undefined,
    path: `/mails/${mail.id}`,
  };
}

function MailDetailView({ id, listQuery }: { id: number; listQuery: string }) {
  const navigate = useNavigate();
  const list = useMemo(() => parseListState(new URLSearchParams(listQuery)), [listQuery]);
  const detail = useMailDetail(id);
  useRecordVisit(detail.data ? mailVisit(detail.data) : null);
  const neighbors = useMailNeighbors(id, toOrderParams(list));
  const summary = useMailSummary(toFilters(list));
  const hits = useMailHits(id, toHitsParams(list));
  // the search words of the list's query (D79); none without full text words
  const marks =
    hits.data && hits.data.words.length + hits.data.stems.length > 0 ? hits.data : undefined;
  const [tab, setTab] = useState<BodyTab>("text");
  const body = useRef<HTMLElement>(null);
  // The attachment open over the page, with the summaries of the attachments' documents beside
  // it and in the list (D331).
  const [opened, setOpened] = useState<AttachmentInfo | null>(null);
  const ai = useAiSummary({ mail: id });
  const summaries = useMemo(
    () =>
      new Map<number, AiSummaryResult>(
        (ai.data?.attachments ?? []).map(({ document_id, result }) => [document_id, result]),
      ),
    [ai.data],
  );
  // Scrolled past the header, a compact bar keeps subject, status and the steps in view (D166).
  const [header, compact] = useScrolledPast<HTMLElement>();
  const prevId = neighbors.data?.prev_id ?? null;
  const nextId = neighbors.data?.next_id ?? null;
  const mailHref = (other: number) => withList(`/mails/${other}`, listQuery);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (!isPlainKey(event) || event.shiftKey) return;
      // Keys in an open dialog, such as a preview over the page, belong to it.
      if (event.target instanceof Element && event.target.closest("dialog")) return;
      const target = { ArrowLeft: prevId, ArrowRight: nextId }[event.key];
      if (target === undefined || target === null) return;
      event.preventDefault();
      void navigate(withList(`/mails/${target}`, listQuery));
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [prevId, nextId, listQuery, navigate]);

  const position = neighbors.data?.position;
  const step = (target: number | null, label: string, keyHint: string) =>
    target === null ? (
      <span className={buttonClass("default", "sm")} aria-disabled="true">
        {label}
      </span>
    ) : (
      <Link to={mailHref(target)} className={buttonClass("default", "sm")} title={keyHint}>
        {label}
      </Link>
    );

  const steps = (
    <div className={styles.steps}>
      {step(prevId, "‹ Vorherige", "Taste ←")}
      {step(nextId, "Nächste ›", "Taste →")}
    </div>
  );

  return (
    <div className={styles.page}>
      <title>{`${detail.data?.subject || "Mail"} · Mailrobbe`}</title>
      {compact && detail.data && (
        <CompactBar label="Kopfzeile der Mail">
          <CompactHeader mail={detail.data} steps={steps} />
        </CompactBar>
      )}
      <div className={styles.topBar}>
        <nav aria-label="Pfad" className={styles.breadcrumb}>
          <Link to={withList("/mails", listQuery)}>Mails</Link>
          <span aria-hidden="true">›</span>
          {position != null && (
            <span>
              Treffer {formatNumber(position)}
              {summary.data && summary.data.total !== null && ` von ${formatTotal(summary.data)}`}
            </span>
          )}
        </nav>
        {steps}
      </div>

      {detail.isPending ? (
        <div className={styles.loading}>
          <Spinner label="Mail wird geladen" />
        </div>
      ) : detail.isError ? (
        detail.error instanceof ApiError && detail.error.code === "not_found" ? (
          <MailNotFound listQuery={listQuery} id={id} />
        ) : (
          <Card className={styles.message}>
            <ErrorState
              title="Die Mail konnte nicht geladen werden."
              actions={
                <button
                  type="button"
                  className={buttonClass()}
                  onClick={() => void detail.refetch()}
                >
                  Erneut versuchen
                </button>
              }
            >
              Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
            </ErrorState>
          </Card>
        )
      ) : (
        <div className={styles.columns}>
          <main className={styles.main}>
            <HeaderCard ref={header} mail={detail.data} mailHref={mailHref} marks={marks}>
              {detail.data.thread_id !== null && detail.data.thread_size > 1 && (
                <SummaryCard
                  target="thread"
                  id={detail.data.thread_id}
                  threadSize={detail.data.thread_size}
                />
              )}
            </HeaderCard>
            <HiddenNote mail={detail.data} />
            {marks && (
              <SearchHitsCard
                hits={marks}
                attachments={detail.data.attachments}
                onShowText={() => {
                  setTab("text");
                  body.current?.scrollIntoView({ block: "start", behavior: "smooth" });
                }}
              />
            )}
            <EventCard events={detail.data.events} mailId={id} mailHref={mailHref} />
            <SummaryCard
              target="mail"
              id={id}
              onQuote={() => {
                setTab("text");
                body.current?.scrollIntoView({ block: "start", behavior: "smooth" });
              }}
              onAttachment={(documentId) =>
                setOpened(attachmentOfDocument(detail.data.attachments, documentId))
              }
            />
            <BodyCard ref={body} mailId={id} tab={tab} onTab={setTab} marks={marks} />
            {detail.data.attachments.length > 0 && (
              <AttachmentsCard
                attachments={detail.data.attachments}
                hits={marks?.attachments}
                marks={marks}
                summaries={summaries}
                mailId={id}
                onOpen={setOpened}
              />
            )}
            {opened && (
              <AttachmentDialog
                mail={detail.data}
                attachment={opened}
                summaries={summaries}
                marks={marks}
                onOpen={setOpened}
              />
            )}
            <DkimCard mail={detail.data} />
            <TechCard mail={detail.data} mailHref={mailHref} />
          </main>
          <aside className={styles.side} aria-label="Zur Mail">
            <ResearchCard mail={detail.data} />
            <SignalsCard mailId={id} />
            <ParticipantsCard participants={detail.data.participants} />
            {detail.data.thread_size > 0 && <ThreadCard mail={detail.data} mailHref={mailHref} />}
            {detail.data.near_group !== null && <NearCard mail={detail.data} mailHref={mailHref} />}
            <EntitiesCard mailId={id} />
            <HideCard mail={detail.data} />
            <ActionsCard
              mail={detail.data}
              onShowRaw={() => {
                setTab("raw");
                body.current?.scrollIntoView({ block: "start" });
              }}
            />
          </aside>
        </div>
      )}
    </div>
  );
}

/** The attachment, or a container's member, that is this document; null when none is. */
function attachmentOfDocument(
  attachments: AttachmentInfo[],
  documentId: number,
): AttachmentInfo | null {
  for (const attachment of attachments) {
    if (attachment.document_id === documentId) return attachment;
    const member = attachment.members?.find((entry) => entry.document_id === documentId);
    if (member) return member;
  }
  return null;
}

function MailNotFound({ listQuery, id }: { listQuery: string; id?: number }) {
  return (
    <Card className={styles.message}>
      <ErrorState
        title="Diese Mail gibt es nicht."
        actions={
          <Link to={withList("/mails", listQuery)} className={buttonClass()}>
            Zur Mailliste
          </Link>
        }
      >
        {id === undefined
          ? "Die Adresse nennt keine gültige Mail-Nummer."
          : `Im Archiv gibt es keine Mail mit der Nummer #${id}.`}
      </ErrorState>
    </Card>
  );
}
