import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";

import { ApiError } from "../../api/client";
import { useMailDetail, useMailHits, useMailNeighbors, useMailSummary } from "../../api/queries";
import { buttonClass } from "../../components/Button";
import { Card } from "../../components/Card";
import { CompactBar, useScrolledPast } from "../../components/CompactBar";
import { ErrorState } from "../../components/ErrorState";
import { Spinner } from "../../components/Spinner";
import { formatNumber } from "../../lib/format";
import { isPlainKey } from "../../lib/keys";
import {
  listSearch,
  parseListState,
  toFilters,
  toHitsParams,
  toOrderParams,
} from "../mails/listState";
import { formatTotal } from "../mails/SummaryTiles";
import { ActionsCard } from "./ActionsCard";
import { AttachmentsCard } from "./AttachmentsCard";
import { BodyCard, type BodyTab } from "./BodyCard";
import { DkimCard } from "./DkimCard";
import { EntitiesCard } from "./EntitiesCard";
import { EventCard } from "./EventCard";
import { CompactHeader, HeaderCard } from "./HeaderCard";
import styles from "./MailDetailPage.module.css";
import { NearCard } from "./NearCard";
import { ParticipantsCard } from "./ParticipantsCard";
import { ResearchCard } from "./ResearchCard";
import { SearchHitsCard } from "./SearchHitsCard";
import { SignalsCard } from "./SignalsCard";
import { ThreadCard } from "./ThreadCard";

/** The mail detail (SPEC 5.2). The list's parameters travel in the query string, so Vorherige,
 *  Nächste and the way back follow the list the mail was opened from. */
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

function MailDetailView({ id, listQuery }: { id: number; listQuery: string }) {
  const navigate = useNavigate();
  const list = useMemo(() => parseListState(new URLSearchParams(listQuery)), [listQuery]);
  const detail = useMailDetail(id);
  const neighbors = useMailNeighbors(id, toOrderParams(list));
  const summary = useMailSummary(toFilters(list));
  const hits = useMailHits(id, toHitsParams(list));
  // the search words of the list's query (D79); none without full text words
  const marks =
    hits.data && hits.data.words.length + hits.data.stems.length > 0 ? hits.data : undefined;
  const [tab, setTab] = useState<BodyTab>("text");
  const body = useRef<HTMLElement>(null);
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
            <HeaderCard ref={header} mail={detail.data} mailHref={mailHref} marks={marks} />
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
            <DkimCard mail={detail.data} />
            <EventCard events={detail.data.events} mailId={id} mailHref={mailHref} />
            <BodyCard ref={body} mailId={id} tab={tab} onTab={setTab} marks={marks} />
          </main>
          <aside className={styles.side} aria-label="Zur Mail">
            <ResearchCard mail={detail.data} />
            {detail.data.attachments.length > 0 && (
              <AttachmentsCard
                attachments={detail.data.attachments}
                hits={marks?.attachments}
                marks={marks}
              />
            )}
            <SignalsCard mailId={id} />
            <ParticipantsCard participants={detail.data.participants} />
            {detail.data.thread_size > 0 && <ThreadCard mail={detail.data} mailHref={mailHref} />}
            {detail.data.near_group !== null && <NearCard mail={detail.data} mailHref={mailHref} />}
            <EntitiesCard mailId={id} />
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
