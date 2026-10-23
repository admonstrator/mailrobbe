import { useMemo, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router";

import { ApiError } from "../../api/client";
import {
  useDocument,
  useFirstMentions,
  useMailDetail,
  useMboxFiles,
  useResearch,
  useTimeline,
} from "../../api/queries";
import {
  FIRST_MENTIONS,
  MAX_FIRST_MENTIONS,
  type FirstMentions,
  type Timeline,
  type TimelineSeries,
} from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Chip } from "../../components/Chip";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { SearchIcon } from "../../components/icons";
import { Spinner } from "../../components/Spinner";
import { PageHead } from "../../components/PageHead";
import { formatNumber } from "../../lib/format";
import { personName } from "../../lib/person";
import { TAG_PALETTE } from "../../lib/research";
import { filterChips } from "../mails/chips";
import { DEFAULT_LIST_STATE, hasFilters, withFilters } from "../mails/listState";
import { invalidTerm } from "../mails/queryText";
import { useSignalChipNames } from "../mails/SignalFacets";
import { selectionHref } from "../topics/urlState";
import { formatBucket } from "./buckets";
import { FirstMentionList } from "./FirstMentionList";
import { markRules, mailsText, NO_SUBJECT } from "./labels";
import { TimelineChart } from "./TimelineChart";
import { TimelineControls } from "./TimelineControls";
import styles from "./TimelinePage.module.css";
import {
  bucketList,
  mailListHref,
  parseTimelineState,
  timelineHref,
  timelineSearch,
  toFirstMentionParams,
  toTimelineParams,
  type TimelineState,
} from "./urlState";

/** Names of the persons the screen has loaded: the split's series, the first mentions and the
 *  persons picked in the split's field. */
function knownPersons(
  timeline: Timeline | undefined,
  mentions: FirstMentions | undefined,
  picked: Map<number, string>,
): Map<number, string> {
  const names = new Map(picked);
  for (const one of timeline?.series ?? []) {
    if (one.person) names.set(one.person.person_id, personName(one.person));
  }
  for (const mention of mentions?.items ?? []) {
    names.set(mention.person.person_id, personName(mention.person));
  }
  return names;
}

/** "214 Treffer ohne Datum sind nicht auf der Achse." */
function undatedText(undated: number): string {
  return undated === 1
    ? "1 Treffer ohne Datum ist nicht auf der Achse."
    : `${formatNumber(undated)} Treffer ohne Datum sind nicht auf der Achse.`;
}

/** The timeline "Zeitachse" (D90 to D94): the mails of the mail list's filters over time, split
 *  by person, thread or search string, with marks, and who appears first. */
export function TimelinePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => parseTimelineState(searchParams), [searchParams]);
  const setState = (next: TimelineState) =>
    setSearchParams(timelineSearch(next), { preventScrollReset: true });
  const timeline = useTimeline(toTimelineParams(state));
  const [limit, setLimit] = useState(FIRST_MENTIONS);
  const mentions = useFirstMentions(toFirstMentionParams(state, limit));
  const research = useResearch();
  const mboxFiles = useMboxFiles();
  const filtered = useDocument(state.list.document ?? 0, state.list.document !== null);
  const threadMail = useMailDetail(state.list.thread ?? 0, state.list.thread !== null);
  const signalNames = useSignalChipNames();
  const [picked, setPicked] = useState<Map<number, string>>(new Map());

  const persons = knownPersons(timeline.data, mentions.data, picked);
  const chips = filterChips(state.list, [], {
    person: (id) => persons.get(id) ?? `#${id}`,
    mboxFile: (id) => mboxFiles.data?.find((file) => file.id === id)?.path ?? `Datei #${id}`,
    tag: (id) => research.data?.tags.find((tag) => tag.id === id),
    collection: (id) => research.data?.collections.find((other) => other.id === id)?.name,
    document: (id) =>
      filtered.data?.id === id ? (filtered.data.name ?? "(ohne Dateinamen)") : `#${id}`,
    thread: (id) =>
      threadMail.data?.id === id ? threadMail.data.subject || NO_SUBJECT : undefined,
    signal: signalNames,
  });

  /** The name of a chosen person or thread, from the series shown or the person picked. */
  function seriesName(id: number): string {
    const series = timeline.data?.series.find(
      (one) => one.person?.person_id === id || one.thread_id === id,
    );
    if (state.split === "thread") return series ? series.label || NO_SUBJECT : `Thread #${id}`;
    return persons.get(id) ?? `#${id}`;
  }

  function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const q = String(new FormData(event.currentTarget).get("q") ?? "").trim();
    setState({ ...state, list: withFilters(state.list, { q }) });
  }

  const data = timeline.data;
  const hrefFor = (series: TimelineSeries | null, index: number) =>
    data ? mailListHref(bucketList(state, data.starts[index], data.bucket, series)) : "/mails";

  return (
    <main className={styles.page}>
      <title>Zeitachse · Mailrobbe</title>
      <PageHead
        title="Zeitachse"
        sub="Mailaufkommen für die aktuelle Suche und Filter"
        actions={
          <>
            <Link
              to={selectionHref(state.list)}
              className={buttonClass()}
              title="Wörter, die in diesen Mails häufiger sind als im übrigen Archiv"
            >
              Begriffe
            </Link>
            <Link to={mailListHref(state.list)} className={buttonClass()}>
              In der Mailliste öffnen
            </Link>
          </>
        }
      />

      {/* The controls stick below the header while the chart is in view; the first mentions'
          table header takes their place further down. */}
      <section className={styles.chartArea} aria-label="Zeitachse">
        <div className={styles.bar}>
          <TimelineControls
            state={state}
            onChange={setState}
            timeline={data}
            seriesName={seriesName}
            onPickPerson={(person) => setPicked(new Map(picked).set(person.id, personName(person)))}
          >
            <form role="search" className={styles.search} onSubmit={onSearch}>
              <SearchIcon className={styles.searchIcon} />
              <label htmlFor="timeline-search" className="sr-only">
                Mails durchsuchen
              </label>
              <input
                key={state.list.q}
                id="timeline-search"
                name="q"
                type="search"
                defaultValue={state.list.q}
                placeholder="Suche wie in der Mailliste, z. B. Spende oder from:kasse@ …"
                autoComplete="off"
                spellCheck={false}
                className={styles.searchInput}
              />
            </form>
            {chips.map((chip) => (
              <Chip
                key={chip.id}
                label={chip.label}
                color={chip.color && TAG_PALETTE[chip.color].text}
                onRemove={() => setState({ ...state, list: chip.next })}
              />
            ))}
          </TimelineControls>
        </div>

        <div className={styles.chartCard}>
          {timeline.isPending ? (
            <div className={styles.loading}>
              <Spinner label="Zeitachse wird gezählt" />
            </div>
          ) : timeline.isError ? (
            <TimelineError
              error={timeline.error}
              state={state}
              onChange={setState}
              onRetry={() => void timeline.refetch()}
            />
          ) : timeline.data.total === null ? (
            <EmptyState title="Die Zählung hat zu lange gedauert.">
              Grenzen Sie die Suche ein, etwa mit einem Zeitraum.
            </EmptyState>
          ) : timeline.data.total.total === 0 ? (
            <NoMatches timeline={timeline.data} state={state} />
          ) : (
            <>
              <p className={styles.summary}>
                {mailsText(timeline.data.total.total)} von{" "}
                {formatBucket(timeline.data.starts[0], timeline.data.bucket)} bis{" "}
                {formatBucket(
                  timeline.data.starts[timeline.data.starts.length - 1],
                  timeline.data.bucket,
                )}
                {timeline.data.undated ? ` · ${undatedText(timeline.data.undated)}` : ""}
              </p>
              {timeline.data.timed_out && (
                <p className={styles.notice} role="status">
                  {state.split !== "none" && timeline.data.series.length === 0
                    ? "Die Aufschlüsselung hat zu lange gedauert."
                    : "Die Zählung hat zu lange gedauert."}{" "}
                  Grenzen Sie die Suche ein, etwa mit einem Zeitraum.
                </p>
              )}
              {state.split === "term" && state.term.length === 0 && (
                <p className={styles.notice}>
                  Fügen Sie oben Suchbegriffe hinzu, um sie einzeln über die Zeit zu vergleichen.
                </p>
              )}
              <TimelineChart
                bucket={timeline.data.bucket}
                starts={timeline.data.starts}
                total={timeline.data.total}
                series={timeline.data.series}
                mentions={mentions.data?.timed_out === false ? mentions.data.items : []}
                mentionPersons={mentions.data?.persons ?? null}
                hrefFor={hrefFor}
                stale={timeline.isPlaceholderData}
              />
              <Explanation timeline={timeline.data} total={timeline.data.total} />
            </>
          )}
        </div>
      </section>

      <FirstMentionList
        state={state}
        onChange={setState}
        query={mentions}
        limit={limit}
        onMore={() => setLimit(Math.min(limit + FIRST_MENTIONS, MAX_FIRST_MENTIONS))}
      />
    </main>
  );
}

/** Below the chart: a legend of the marks that occur, worded as the compact histogram above the
 *  mail list words them, and the rules of all marks in plain words with the numbers of D93. */
function Explanation({ timeline, total }: { timeline: Timeline; total: TimelineSeries }) {
  const all = [total, ...timeline.series];
  const kinds = new Set(all.flatMap((one) => one.outliers.map((outlier) => outlier.kind)));
  const silent = [...new Set(all.flatMap((one) => one.silent_from ?? []))];
  const rules = markRules(timeline.bucket);
  return (
    <div className={styles.explanation}>
      {(kinds.size > 0 || silent.length > 0) && (
        <ul className={styles.legend} aria-label="Zeichen in der Zeitachse">
          {kinds.has("high") && (
            <li>
              <span className={styles.high}>▲</span> viel mehr als üblich
            </li>
          )}
          {kinds.has("low") && (
            <li>
              <span className={styles.low}>▽</span> viel weniger als üblich
            </li>
          )}
          {silent.length > 0 && (
            <li>
              <span className={styles.hatch} aria-hidden="true" />
              {silent.length === 1
                ? `verstummt seit ${formatBucket(silent[0], timeline.bucket)}`
                : "verstummt"}
            </li>
          )}
        </ul>
      )}
      <details className={styles.help}>
        <summary>Wie lese ich das?</summary>
        <p className={styles.rules}>
          {rules.compare} Jede Zeile hat ihren eigenen Maßstab: Ihr höchster Balken ist ihre Spitze.
          Die Punkte bei „Erste Erwähnungen“ zeigen, wann Personen zum ersten Mal unter den Treffern
          auftauchen (Liste unten). Ein Klick auf einen Balken öffnet diese Mails in der Mailliste.
          Die Zeichen bewerten nichts, sie zeigen Stellen zum Nachlesen.
        </p>
        <ul className={styles.rules}>
          <li>▲ viel mehr als üblich: {rules.high}</li>
          <li>▽ viel weniger als üblich: {rules.low}</li>
          <li>verstummt: {rules.silent}</li>
        </ul>
      </details>
    </div>
  );
}

function NoMatches({ timeline, state }: { timeline: Timeline; state: TimelineState }) {
  const filtered = hasFilters(state.list);
  if (timeline.undated) {
    return <EmptyState title="Keine datierten Treffer">{undatedText(timeline.undated)}</EmptyState>;
  }
  return (
    <EmptyState
      title="Keine Mails gefunden"
      actions={
        filtered && (
          <Link to={timelineHref({ ...state, list: DEFAULT_LIST_STATE })} className={buttonClass()}>
            Alle Filter zurücksetzen
          </Link>
        )
      }
    >
      {filtered ? "Kein Treffer für diese Suche und Filter." : "Das Archiv ist leer."}
    </EmptyState>
  );
}

/** The part of the search an invalid_query names: q, or one of the split's search strings. */
function invalidPart(message: string, state: TimelineState): { term: string; index: number } {
  for (const [index, text] of [state.list.q, ...state.term].entries()) {
    if (!text) continue;
    const term = invalidTerm(message, text);
    if (text.includes(term)) return { term, index: index - 1 };
  }
  return { term: invalidTerm(message, state.list.q), index: -1 };
}

function TimelineError({
  error,
  state,
  onChange,
  onRetry,
}: {
  error: Error;
  state: TimelineState;
  onChange: (next: TimelineState) => void;
  onRetry: () => void;
}) {
  const code = error instanceof ApiError ? error.code : null;
  if (code === "invalid_query") {
    const { term, index } = invalidPart(error.message, state);
    const inTerm = index >= 0;
    return (
      <ErrorState
        title={inTerm ? `Suchbegriff nicht verstanden: ${term}` : `Suche nicht verstanden: ${term}`}
        actions={
          <Button
            onClick={() =>
              onChange(
                inTerm
                  ? { ...state, term: state.term.filter((_, at) => at !== index) }
                  : { ...state, list: withFilters(state.list, { q: "" }) },
              )
            }
          >
            {inTerm ? "Suchbegriff entfernen" : "Suche leeren"}
          </Button>
        }
      >
        Suchoperatoren brauchen einen gültigen Wert, zum Beispiel after:2024-01-31, dkim:fail oder
        has:attachment.
      </ErrorState>
    );
  }
  if (code === "invalid_filter") {
    return (
      <ErrorState
        title="Diese Filter lassen sich nicht anwenden."
        actions={
          <Link to="/zeitachse" className={buttonClass()}>
            Filter zurücksetzen
          </Link>
        }
      >
        Die Adresse enthält eine Filterkombination, die Mailrobbe nicht auswerten kann.
      </ErrorState>
    );
  }
  return (
    <ErrorState
      title="Die Zeitachse konnte nicht geladen werden."
      actions={<Button onClick={onRetry}>Erneut versuchen</Button>}
    >
      Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
    </ErrorState>
  );
}
