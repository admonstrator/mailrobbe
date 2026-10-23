import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";

import { ApiError } from "../../api/client";
import { graphQuery, useGraph, useStats } from "../../api/queries";
import { MAX_GRAPH_NODES, type Graph } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { MinusIcon } from "../../components/icons";
import { Spinner } from "../../components/Spinner";
import { formatNumber } from "../../lib/format";
import { domainColors, OTHER_COLOR } from "./elements";
import { GraphCanvas, type GraphCanvasHandle } from "./GraphCanvas";
import styles from "./GraphScreen.module.css";
import { GraphSidebar } from "./GraphSidebar";
import {
  DEFAULT_GRAPH_STATE,
  excerptKey,
  graphHref,
  toGraphParams,
  withPerson,
  type GraphState,
} from "./graphState";
import { NodePanel } from "./NodePanel";
import { useGraphState } from "./useGraphState";

/** Seconds per year of the playback. */
const PLAY_STEP = 1500;

interface Playback {
  year: number;
  last: number;
  base: GraphState; // the draft when it started
}

/** The UTC years of the archive, oldest first; empty until the figures are loaded. */
function archiveYears(dateMin: string | null | undefined, dateMax: string | null | undefined) {
  if (!dateMin || !dateMax) return [];
  const first = new Date(dateMin).getUTCFullYear();
  const last = new Date(dateMax).getUTCFullYear();
  return Array.from({ length: last - first + 1 }, (_, index) => first + index);
}

/** The relationship map (SPEC 5.4, D37): excerpt in the left column, map, selected node. */
export function GraphScreen() {
  const [state, setState] = useGraphState();
  const stats = useStats();
  const years = archiveYears(stats.data?.date_min, stats.data?.date_max);
  const queryClient = useQueryClient();

  // The left column edits a draft; a new excerpt in the URL (drawing, back, the panel's
  // buttons) replaces it.
  const applied = excerptKey(state);
  const [draft, setDraft] = useState(state);
  const [draftOf, setDraftOf] = useState(applied);
  if (draftOf !== applied) {
    setDraftOf(applied);
    setDraft(state);
  }

  const [playback, setPlayback] = useState<Playback | null>(null);
  const shown: GraphState = playback
    ? { ...playback.base, from: playback.year, to: playback.year }
    : state;
  const params = toGraphParams(shown);
  const graph = useGraph(params);
  const data = graph.isError ? undefined : graph.data;

  const [selected, setSelected] = useState<number | null>(null);
  const selectedNode = data?.nodes.find((node) => node.id === selected) ?? null;
  const canvas = useRef<GraphCanvasHandle>(null);

  const view = (patch: Partial<GraphState>) => setState({ ...state, ...patch }, true);
  const draw = (next: GraphState) =>
    setState({ ...next, layout: state.layout, color: state.color, arrows: state.arrows });

  // Stopping leaves the URL at the year shown (with the view options of that moment).
  function stop(year: number, base: GraphState) {
    setPlayback(null);
    draw({ ...base, from: year, to: year });
  }
  const stopRef = useRef(stop);
  useEffect(() => {
    stopRef.current = stop;
  });

  // Playback: the next year once this one is drawn and has been shown for a moment; an error
  // (a year too large, say) stops it there.
  const loaded = playback !== null && graph.isSuccess && !graph.isPlaceholderData;
  const failed = playback !== null && graph.isError;
  useEffect(() => {
    if (!playback || !(loaded || failed)) return;
    const { year, last, base } = playback;
    if (loaded && year < last) {
      void queryClient.prefetchQuery(
        graphQuery(toGraphParams({ ...base, from: year + 1, to: year + 1 })),
      );
    }
    const timer = setTimeout(
      () => {
        if (loaded && year < last) setPlayback({ ...playback, year: year + 1 });
        else stopRef.current(year, base);
      },
      failed ? 0 : PLAY_STEP,
    );
    return () => clearTimeout(timer);
  }, [playback, loaded, failed, queryClient]);

  function play() {
    const first = draft.from ?? years[0];
    const last = draft.to ?? years[years.length - 1];
    if (first === undefined || last === undefined) return;
    setSelected(null);
    setPlayback({ year: first, last, base: draft });
  }

  const legend = useMemo(() => (data ? domainColors(data.nodes) : null), [data]);

  return (
    <div className={styles.page}>
      <title>Beziehungskarte · Mailrobbe</title>
      <GraphSidebar
        draft={draft}
        onDraft={(patch) => setDraft((current) => ({ ...current, ...patch }))}
        state={state}
        onView={view}
        onDraw={() => draw(draft)}
        onReset={(patch) => draw({ ...state, ...patch })}
        years={years}
        graph={data}
        suggestedDomains={stats.data?.sender_domains.slice(0, 2).map(({ domain }) => domain) ?? []}
        playing={playback?.year ?? null}
        onPlay={play}
        onStop={() => playback && stop(playback.year, playback.base)}
        exportParams={params}
        canvas={canvas}
      />
      <div className={styles.main}>
        <MapHeader
          graph={data}
          legend={state.color ? legend : null}
          onZoom={(factor) => canvas.current?.zoomBy(factor)}
          onFit={() => canvas.current?.fit()}
        />
        <div className={styles.body}>
          <div className={styles.map}>
            <GraphCanvas
              ref={canvas}
              graph={data}
              layout={state.layout}
              color={state.color}
              arrows={state.arrows}
              selected={selectedNode?.id ?? null}
              onSelect={setSelected}
              keepPositions={playback !== null}
            />
            {playback && (
              <div className={styles.year} aria-live="polite">
                {playback.year}
              </div>
            )}
            {graph.isPending && graph.fetchStatus !== "idle" && (
              <div className={styles.center}>
                <Spinner label="Karte wird geladen" />
              </div>
            )}
            {graph.isFetching && graph.isPlaceholderData && (
              <div className={styles.busy}>
                <Spinner label="Karte wird geladen" /> Wird geladen …
              </div>
            )}
            {graph.isError && (
              <div className={styles.center}>
                <div className={styles.stateCard}>
                  <MapError error={graph.error} onRetry={() => void graph.refetch()} />
                </div>
              </div>
            )}
            {data && data.edges.length === 0 && !graph.isFetching && (
              <div className={styles.notice}>
                <div className={styles.stateCard}>
                  <EmptyState title="Keine Verbindungen in diesem Ausschnitt">
                    Mindestanzahl Mails pro Kante senken oder den Zeitraum erweitern.
                  </EmptyState>
                </div>
              </div>
            )}
          </div>
          <NodePanel
            graph={data}
            node={selectedNode}
            ccCounted={shown.cc}
            expanded={selectedNode !== null && state.expand.includes(selectedNode.id)}
            onClose={() => setSelected(null)}
            onExpand={(id) => draw(withPerson(state, "expand", id))}
            onHide={(id) => {
              setSelected(null);
              draw(withPerson(state, "hide", id));
            }}
          />
        </div>
      </div>
    </div>
  );
}

function MapHeader({
  graph,
  legend,
  onZoom,
  onFit,
}: {
  graph: Graph | undefined;
  legend: ReturnType<typeof domainColors> | null;
  onZoom: (factor: number) => void;
  onFit: () => void;
}) {
  return (
    <div className={styles.header}>
      <span className={styles.counts}>
        {graph ? (
          <>
            <strong>{formatNumber(graph.nodes.length)}</strong> Knoten ·{" "}
            <strong>{formatNumber(graph.edges.length)}</strong>{" "}
            {graph.edges.length === 1 ? "Kante" : "Kanten"} ·{" "}
            <strong>{formatNumber(graph.mails)}</strong> Mails im Ausschnitt
          </>
        ) : (
          "Noch keine Karte"
        )}
      </span>
      {legend && (
        <ul className={styles.legend} aria-label="Domainfarben">
          {legend.legend.map(({ domain, color }) => (
            <li key={domain}>
              <span className={styles.swatch} style={{ background: color }} />
              {domain}
            </li>
          ))}
          {legend.others > 0 && (
            <li>
              <span className={styles.swatch} style={{ background: OTHER_COLOR }} />
              sonstige
            </li>
          )}
        </ul>
      )}
      <div className={styles.tools}>
        <span className={styles.explain}>
          Knotengröße = Mails gesamt · Kantenstärke = Mails zwischen beiden
        </span>
        <div className={styles.zoom}>
          <Button
            size="xs"
            aria-label="Vergrößern"
            className={styles.zoomButton}
            onClick={() => onZoom(1.25)}
          >
            +
          </Button>
          <Button
            size="xs"
            aria-label="Verkleinern"
            className={styles.zoomButton}
            onClick={() => onZoom(0.8)}
          >
            <MinusIcon size={14} />
          </Button>
          <Button size="xs" onClick={onFit}>
            Einpassen
          </Button>
        </div>
      </div>
    </div>
  );
}

function MapError({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const code = error instanceof ApiError ? error.code : null;
  if (code === "graph_too_large") {
    return (
      <ErrorState
        title={`Der Ausschnitt hätte mehr als ${formatNumber(MAX_GRAPH_NODES)} Personen.`}
      >
        Mindestanzahl Mails erhöhen, Tiefe verringern oder Zeitraum eingrenzen.
      </ErrorState>
    );
  }
  if (code === "not_found") {
    return (
      <ErrorState
        title="Person nicht gefunden"
        actions={
          <Link to={graphHref(DEFAULT_GRAPH_STATE)} className={buttonClass()}>
            Zur Übersicht
          </Link>
        }
      >
        Eine der Personen im Zentrum gibt es in diesem Archiv nicht (mehr).
      </ErrorState>
    );
  }
  if (code === "invalid_filter") {
    return (
      <ErrorState
        title="Dieser Ausschnitt lässt sich nicht zeichnen."
        actions={
          <Link to={graphHref(DEFAULT_GRAPH_STATE)} className={buttonClass()}>
            Zur Übersicht
          </Link>
        }
      >
        {error.message}
      </ErrorState>
    );
  }
  return (
    <ErrorState
      title="Die Karte konnte nicht geladen werden."
      actions={<Button onClick={onRetry}>Erneut versuchen</Button>}
    >
      Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
    </ErrorState>
  );
}
