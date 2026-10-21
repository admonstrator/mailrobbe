import { useEffect, useId, useRef, useState, type ReactNode, type RefObject } from "react";

import { ApiError, buildQuery } from "../../api/client";
import { useGraphSize, useSenderDomains } from "../../api/queries";
import { MAX_GRAPH_NODES, type Graph, type GraphMode, type GraphParams } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Checkbox } from "../../components/Checkbox";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatDateTime, formatNumber } from "../../lib/format";
import { useDebounced } from "../../lib/useDebounced";
import { CenterField } from "./CenterField";
import type { GraphCanvasHandle } from "./GraphCanvas";
import styles from "./GraphSidebar.module.css";
import {
  draftProblem,
  excerptKey,
  MAX_DEPTH,
  toGraphParams,
  type GraphLayout,
  type GraphState,
} from "./graphState";

/** The positions of the threshold slider: fine steps where most excerpts are decided. */
export const THRESHOLD_STOPS = [
  1, 2, 3, 4, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 60, 75, 100, 125, 150, 200, 250, 300, 400,
  500,
];

const LAYOUT_LABELS: Record<GraphLayout, string> = {
  force: "Kräftebasiert (Force)",
  domains: "Domain-Cluster",
  circle: "Kreis",
  tree: "Hierarchisch vom Zentrum",
};

function nearestStop(value: number): number {
  let best = 0;
  THRESHOLD_STOPS.forEach((stop, index) => {
    if (Math.abs(stop - value) < Math.abs(THRESHOLD_STOPS[best] - value)) best = index;
  });
  return best;
}

/** The left column (SPEC 5.4): the excerpt as a draft, drawn with "Karte zeichnen"; layout,
 *  colours and arrows apply at once. */
export function GraphSidebar({
  draft,
  onDraft,
  state,
  onView,
  onDraw,
  onReset,
  years,
  graph,
  suggestedDomains,
  playing,
  onPlay,
  onStop,
  exportParams,
  canvas,
}: {
  draft: GraphState;
  onDraft: (patch: Partial<GraphState>) => void;
  state: GraphState;
  onView: (patch: Partial<GraphState>) => void;
  onDraw: () => void;
  onReset: (patch: Partial<GraphState>) => void;
  years: number[];
  graph: Graph | undefined;
  suggestedDomains: string[];
  playing: number | null;
  onPlay: () => void;
  onStop: () => void;
  exportParams: GraphParams;
  canvas: RefObject<GraphCanvasHandle | null>;
}) {
  const problem = draftProblem(draft);
  const dirty = excerptKey(draft) !== excerptKey(state);

  function setMode(mode: GraphMode) {
    if (mode === "domains" && draft.domain.length === 0) {
      onDraft({ mode, domain: suggestedDomains.slice(0, 2) });
    } else onDraft({ mode });
  }

  function setYear(key: "from" | "to", value: string) {
    const year = value ? Number(value) : null;
    const patch: Partial<GraphState> = { [key]: year };
    if (year !== null && key === "from" && draft.to !== null && year > draft.to) patch.to = year;
    if (year !== null && key === "to" && draft.from !== null && year < draft.from)
      patch.from = year;
    onDraft(patch);
  }

  const example =
    suggestedDomains.length >= 2 ? `${suggestedDomains[0]} ↔ ${suggestedDomains[1]}` : "";

  return (
    <aside className={styles.column} aria-label="Ausschnitt">
      <h2 className={styles.title}>Beziehungskarte</h2>

      <fieldset className={styles.group}>
        <legend className={styles.legend}>Ausschnitt</legend>
        <ModeOption
          mode="ego"
          current={draft.mode}
          onChange={setMode}
          hint="um Personen, Tiefe 1–3"
        >
          Ego-Netzwerk
        </ModeOption>
        <ModeOption
          mode="top"
          current={draft.mode}
          onChange={setMode}
          hint="die N aktivsten Personen"
        >
          Top-N nach Mailvolumen
        </ModeOption>
        <ModeOption
          mode="domains"
          current={draft.mode}
          onChange={setMode}
          hint={example ? `z. B. ${example}` : "Personen zweier Domains"}
        >
          Zwei Domains gegenüber
        </ModeOption>
      </fieldset>

      {draft.mode === "ego" && (
        <div className={styles.group}>
          <CenterField
            ids={draft.center}
            graph={graph}
            onChange={(center) => onDraft(center.length ? { center } : { center, mode: "top" })}
          />
          <div className={styles.inline}>
            <label htmlFor="graph-depth" className={styles.small}>
              Tiefe
            </label>
            <select
              id="graph-depth"
              className={styles.select}
              value={draft.depth}
              onChange={(event) => onDraft({ depth: Number(event.target.value) })}
            >
              {Array.from({ length: MAX_DEPTH }, (_, index) => index + 1).map((depth) => (
                <option key={depth} value={depth}>
                  {depth}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}
      {draft.mode === "top" && (
        <div className={styles.inline}>
          <label htmlFor="graph-limit" className={styles.label}>
            Anzahl Personen
          </label>
          <NumberField
            id="graph-limit"
            value={draft.limit}
            max={MAX_GRAPH_NODES}
            onChange={(limit) => onDraft({ limit })}
          />
        </div>
      )}
      {draft.mode === "domains" && (
        <div className={styles.group}>
          <span className={styles.label}>Domains</span>
          {[0, 1].map((index) => (
            <DomainField
              key={index}
              label={index === 0 ? "Erste Domain" : "Zweite Domain"}
              value={draft.domain[index] ?? ""}
              onChange={(value) => {
                const domain = [draft.domain[0] ?? "", draft.domain[1] ?? ""];
                domain[index] = value;
                onDraft({ domain });
              }}
            />
          ))}
        </div>
      )}

      <div className={styles.group}>
        <div className={styles.thresholdHead}>
          <label htmlFor="graph-min" className={styles.label}>
            Mindestens Mails pro Kante
          </label>
          <span className={styles.value}>≥ {formatNumber(draft.min)}</span>
        </div>
        <div className={styles.inline}>
          <input
            id="graph-min"
            type="range"
            className={styles.range}
            min={0}
            max={THRESHOLD_STOPS.length - 1}
            value={nearestStop(draft.min)}
            aria-valuetext={`mindestens ${formatNumber(draft.min)} Mails`}
            onChange={(event) => onDraft({ min: THRESHOLD_STOPS[Number(event.target.value)] })}
          />
          <NumberField
            id="graph-min-exact"
            label="Mindestanzahl genau"
            value={draft.min}
            max={1_000_000}
            onChange={(min) => onDraft({ min })}
          />
        </div>
        <SizePreview draft={draft} problem={problem} />
      </div>

      <fieldset className={styles.group}>
        <legend className={styles.legend}>Zeitraum</legend>
        <div className={styles.years}>
          <YearSelect
            id="graph-from"
            label="Von"
            empty="Anfang"
            value={draft.from}
            years={years}
            onChange={(value) => setYear("from", value)}
          />
          <YearSelect
            id="graph-to"
            label="Bis"
            empty="Ende"
            value={draft.to}
            years={years}
            onChange={(value) => setYear("to", value)}
          />
        </div>
        {playing === null ? (
          <Button
            className={styles.play}
            onClick={onPlay}
            disabled={years.length === 0 || problem !== null}
          >
            ▶ Zeitverlauf abspielen (Jahr für Jahr)
          </Button>
        ) : (
          <Button className={styles.play} onClick={onStop}>
            ■ Anhalten bei {playing}
          </Button>
        )}
      </fieldset>

      <fieldset className={styles.group}>
        <legend className={styles.legend}>Optionen</legend>
        <Checkbox checked={state.color} onChange={(color) => onView({ color })}>
          Nach Domain einfärben
        </Checkbox>
        <Checkbox checked={draft.dkimOnly} onChange={(dkimOnly) => onDraft({ dkimOnly })}>
          Nur DKIM-gültige Mails zählen
        </Checkbox>
        <Checkbox checked={draft.hideLists} onChange={(hideLists) => onDraft({ hideLists })}>
          Verteiler und Automaten ausblenden
        </Checkbox>
        <Checkbox checked={state.arrows} onChange={(arrows) => onView({ arrows })}>
          Richtung als Pfeile zeigen
        </Checkbox>
        <Checkbox checked={draft.cc} onChange={(cc) => onDraft({ cc })}>
          Cc-Beteiligung mitzählen
        </Checkbox>
      </fieldset>

      <div className={styles.group}>
        <label htmlFor="graph-layout" className={styles.label}>
          Layout
        </label>
        <select
          id="graph-layout"
          className={styles.select}
          value={state.layout}
          onChange={(event) => onView({ layout: event.target.value as GraphLayout })}
        >
          {(Object.keys(LAYOUT_LABELS) as GraphLayout[]).map((layout) => (
            <option key={layout} value={layout}>
              {LAYOUT_LABELS[layout]}
            </option>
          ))}
        </select>
      </div>

      <div className={styles.foot}>
        {(state.hide.length > 0 || state.expand.length > 0) && (
          <div className={styles.adjusted}>
            {state.expand.length > 0 && (
              <span>
                {formatNumber(state.expand.length)} aufgeklappt ·{" "}
                <button
                  type="button"
                  className={styles.linkButton}
                  onClick={() => onReset({ expand: [] })}
                >
                  Zurücksetzen
                </button>
              </span>
            )}
            {state.hide.length > 0 && (
              <span>
                {formatNumber(state.hide.length)} ausgeblendet ·{" "}
                <button
                  type="button"
                  className={styles.linkButton}
                  onClick={() => onReset({ hide: [] })}
                >
                  Alle einblenden
                </button>
              </span>
            )}
          </div>
        )}
        <Button
          variant="primary"
          className={styles.draw}
          onClick={onDraw}
          disabled={problem !== null}
        >
          Karte zeichnen
        </Button>
        {dirty && problem === null && (
          <span className={styles.pending}>Geänderte Einstellungen, noch nicht gezeichnet.</span>
        )}
        <div className={styles.exports}>
          <ImageExport canvas={canvas} disabled={!graph} />
          <a
            className={cx(buttonClass("default", "sm"), styles.export)}
            href={`/api/graph/export.graphml?${buildQuery(exportParams)}`}
            download="mailrobbe-karte.graphml"
          >
            GraphML / Gephi
          </a>
        </div>
        {graph && (
          <p className={styles.edgeTable}>
            Kantentabelle: {formatNumber(graph.edge_table.pairs)} Paare ·{" "}
            {graph.edge_table.refreshed_at
              ? `letzte Aggregation ${formatDateTime(graph.edge_table.refreshed_at)}`
              : "noch nicht aggregiert"}
          </p>
        )}
      </div>
    </aside>
  );
}

function ModeOption({
  mode,
  current,
  onChange,
  hint,
  children,
}: {
  mode: GraphMode;
  current: GraphMode;
  onChange: (mode: GraphMode) => void;
  hint: string;
  children: ReactNode;
}) {
  return (
    <label className={styles.mode}>
      <input
        type="radio"
        name="graph-mode"
        className={styles.radio}
        checked={current === mode}
        onChange={() => onChange(mode)}
      />
      <span>
        {children}
        <span className={styles.hint}>{hint}</span>
      </span>
    </label>
  );
}

/** The live size of the draft from /api/graph/size, asked once the draft rests for 300 ms. */
function SizePreview({ draft, problem }: { draft: GraphState; problem: string | null }) {
  const settled = useDebounced(draft, 300);
  const size = useGraphSize(problem === null ? toGraphParams(settled) : null);
  if (problem) return <p className={styles.preview}>{problem}</p>;
  if (size.isError) {
    const notFound = size.error instanceof ApiError && size.error.code === "not_found";
    return (
      <p className={styles.preview}>
        {notFound
          ? "Eine Person im Zentrum gibt es nicht."
          : "Die Größe ließ sich nicht ermitteln."}
      </p>
    );
  }
  if (!size.data) {
    return (
      <p className={styles.preview}>
        <Spinner label="Größe wird berechnet" /> Größe wird berechnet …
      </p>
    );
  }
  const { nodes, edges, too_large } = size.data;
  const stale = size.isPlaceholderData || settled !== draft;
  return (
    <p
      className={cx(styles.preview, too_large && styles.tooLarge, stale && styles.stale)}
      aria-live="polite"
    >
      {too_large
        ? `Ergibt ${formatNumber(nodes)} Knoten, höchstens ${formatNumber(MAX_GRAPH_NODES)} sind möglich.`
        : `Ergibt ${formatNumber(nodes)} Knoten, ${formatNumber(edges)} ${edges === 1 ? "Kante" : "Kanten"}.`}
    </p>
  );
}

/** A whole number from 1 to max; other input waits and is undone when the field loses focus. */
function NumberField({
  id,
  label,
  value,
  max,
  onChange,
}: {
  id: string;
  label?: string;
  value: number;
  max: number;
  onChange: (value: number) => void;
}) {
  const [text, setText] = useState(String(value));
  const [shown, setShown] = useState(value);
  if (shown !== value) {
    setShown(value);
    setText(String(value));
  }
  const parse = (raw: string) => {
    const n = /^\d+$/.test(raw.trim()) ? Number(raw) : NaN;
    return n >= 1 && n <= max ? n : null;
  };
  return (
    <input
      id={id}
      type="number"
      inputMode="numeric"
      className={styles.number}
      min={1}
      max={max}
      value={text}
      aria-label={label}
      onChange={(event) => {
        setText(event.target.value);
        const n = parse(event.target.value);
        if (n !== null && n !== value) onChange(n);
      }}
      onBlur={() => setText(String(value))}
    />
  );
}

function YearSelect({
  id,
  label,
  empty,
  value,
  years,
  onChange,
}: {
  id: string;
  label: string;
  empty: string;
  value: number | null;
  years: number[];
  onChange: (value: string) => void;
}) {
  const options = value !== null && !years.includes(value) ? [...years, value].sort() : years;
  return (
    <div className={styles.yearField}>
      <label htmlFor={id} className={styles.small}>
        {label}
      </label>
      <select
        id={id}
        className={styles.select}
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{empty}</option>
        {options.map((year) => (
          <option key={year} value={year}>
            {year}
          </option>
        ))}
      </select>
    </div>
  );
}

/** A domain with suggestions from the sender domains. */
function DomainField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  const q = useDebounced(value, 250);
  const suggestions = useSenderDomains(q, value !== "");
  return (
    <>
      <input
        type="text"
        className={styles.text}
        aria-label={label}
        placeholder={label}
        value={value}
        list={`${id}-domains`}
        autoComplete="off"
        spellCheck={false}
        onChange={(event) => onChange(event.target.value.trim().toLowerCase())}
      />
      <datalist id={`${id}-domains`}>
        {suggestions.data?.slice(0, 12).map(({ domain }) => (
          <option key={domain} value={domain} />
        ))}
      </datalist>
    </>
  );
}

function saveFile(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** "PNG / SVG" with its small menu. */
function ImageExport({
  canvas,
  disabled,
}: {
  canvas: RefObject<GraphCanvasHandle | null>;
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  function save(format: "png" | "svg") {
    setOpen(false);
    if (format === "png") {
      const png = canvas.current?.png();
      if (png) saveFile(png, "mailrobbe-karte.png");
    } else {
      const svg = canvas.current?.svg();
      if (svg) saveFile(new Blob([svg], { type: "image/svg+xml" }), "mailrobbe-karte.svg");
    }
  }

  return (
    <div ref={root} className={styles.menuRoot}>
      <Button
        size="sm"
        className={styles.export}
        aria-expanded={open}
        aria-controls={menuId}
        disabled={disabled}
        onClick={() => setOpen(!open)}
      >
        PNG / SVG
      </Button>
      {open && (
        <div id={menuId} role="menu" className={styles.menu}>
          <button
            type="button"
            role="menuitem"
            className={styles.menuItem}
            onClick={() => save("png")}
          >
            Als PNG speichern (Bild)
          </button>
          <button
            type="button"
            role="menuitem"
            className={styles.menuItem}
            onClick={() => save("svg")}
          >
            Als SVG speichern (Vektor)
          </button>
        </div>
      )}
    </div>
  );
}
