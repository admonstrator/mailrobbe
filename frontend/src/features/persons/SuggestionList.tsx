import { useState, type ReactNode } from "react";
import { Link } from "react-router";

import {
  useDismissSuggestion,
  useMergeCertain,
  useMergePersons,
  useStartAliasCheck,
  useSuggestions,
  useUndoMergeBatch,
} from "../../api/queries";
import type {
  AliasCheckState,
  AliasSuggestion,
  CertainMergeResult,
  SuggestionCounts,
  SuggestionView,
} from "../../api/types";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { personPath } from "../../components/PersonLink";
import { HelpMark } from "../../components/HelpMark";
import { Segments } from "../../components/Segments";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatDateTime, formatNumber } from "../../lib/format";
import { BulkMergeDialog } from "./BulkMergeDialog";
import {
  mergeCount,
  personCount,
  personErrorText,
  personLabel,
  REASON_TEXTS,
  suggestionReasons,
  VERDICT_TEXTS,
} from "./labels";
import { PersonBadge } from "./PersonBadge";
import styles from "./SuggestionList.module.css";

const INTROS: Record<SuggestionView, string> = {
  certain:
    "Sichere Vorschläge: Name und Adressen passen zusammen, und beide schreiben mit denselben Leuten. Zusammengeführt wird nur per Klick, und jede Zusammenführung lässt sich rückgängig machen.",
  uncertain:
    "Unsichere Vorschläge: Nur ein Teil spricht dafür, etwa der gleiche Name ohne gemeinsame Kontakte. Gleichnamige sind häufig, bitte einzeln prüfen.",
  ai: "Diese Paare hält die KI für dieselbe Person. Sie hat Namen, Adressen, Kontakte, Betreffzeilen und Schlusszeilen verglichen und kann sich irren: bitte einzeln prüfen, zusammengeführt wird nur per Klick.",
};

/** The views of the suggestions: certain, uncertain (D160) and, once the text model judged pairs,
 *  those it holds for one person (D323). */
function views(
  counts: SuggestionCounts | undefined,
  check: AliasCheckState | undefined,
  view: SuggestionView,
) {
  const counted = (label: string, count: number | undefined) =>
    count === undefined ? label : `${label} (${formatNumber(count)})`;
  const options: [SuggestionView, string][] = [
    ["certain", counted("Sicher", counts?.certain)],
    ["uncertain", counted("Unsicher", counts?.uncertain)],
  ];
  if (view === "ai" || (check !== undefined && check.checked > 0)) {
    options.push(["ai", counted("KI: dieselbe Person", check?.same)]);
  }
  return options;
}

/** The open alias suggestions (D30, D160): the certain ones, the uncertain ones, or the pairs the
 *  text model judged one person (D323), each view one segment. Each can be merged (keeping the
 *  first, or the second with "andersherum") or dismissed; "Alle sicheren zusammenführen" merges
 *  every certain one as one run (D162). The row goes and a confirmation stays above the list,
 *  for a run with its "Rückgängig". "Mit KI prüfen" starts the alias check (D321). */
export function SuggestionList({
  view,
  onView,
  hasPersons,
}: {
  view: SuggestionView;
  onView: (view: SuggestionView) => void;
  hasPersons: boolean;
}) {
  const certain = useSuggestions("certain");
  const suggestions = useSuggestions(view);
  const mergeCertain = useMergeCertain();
  const [notice, setNotice] = useState<ReactNode>(null);
  const [confirming, setConfirming] = useState(false);
  const counts = (certain.data ?? suggestions.data)?.pages[0]?.counts;
  const check = (suggestions.data ?? certain.data)?.pages[0]?.check;

  async function onMergeAll() {
    try {
      const result = await mergeCertain.mutateAsync();
      setConfirming(false);
      setNotice(<RunNotice result={result} />);
    } catch {
      // shown in the dialog
    }
  }

  return (
    <>
      <div className={styles.toolbar}>
        <div className={styles.views}>
          <Segments<SuggestionView>
            label="Zeigen"
            options={views(counts, check, view)}
            value={view}
            onChange={(next) => {
              setNotice(null);
              onView(next);
            }}
          />
          <HelpMark text={INTROS[view]} />
        </div>
        {view === "certain" && counts !== undefined && counts.certain > 0 && (
          <Button
            variant="primary"
            disabled={mergeCertain.isPending}
            onClick={() => {
              mergeCertain.reset();
              setConfirming(true);
            }}
          >
            Alle sicheren zusammenführen
          </Button>
        )}
      </div>
      {check && <AliasCheck check={check} />}
      <p role="status" className={cx(styles.notice, !notice && "sr-only")}>
        {notice}
      </p>
      {suggestions.isPending ? (
        <div className={styles.loading}>
          <Spinner label="Vorschläge werden geladen" />
        </div>
      ) : suggestions.isError ? (
        <div>
          <ErrorState
            title="Die Vorschläge konnten nicht geladen werden."
            actions={<Button onClick={() => void suggestions.refetch()}>Erneut versuchen</Button>}
          >
            Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
          </ErrorState>
        </div>
      ) : (
        <>
          <div className={styles.card}>
            <Rows
              items={suggestions.data.pages.flatMap((page) => page.items)}
              computed={suggestions.data.pages[0].computed}
              view={view}
              uncertainLeft={view === "certain" && (counts?.uncertain ?? 0) > 0}
              hasPersons={hasPersons}
              onDone={setNotice}
            />
          </div>
          {suggestions.hasNextPage && (
            <div className={styles.more}>
              <Button
                onClick={() => void suggestions.fetchNextPage()}
                disabled={suggestions.isFetchingNextPage}
              >
                Weitere laden
              </Button>
            </div>
          )}
        </>
      )}
      {confirming && (
        <BulkMergeDialog
          running={mergeCertain.isPending}
          error={mergeCertain.error}
          onConfirm={() => void onMergeAll()}
          onClose={() => setConfirming(false)}
        />
      )}
    </>
  );
}

function Rows({
  items,
  computed,
  view,
  uncertainLeft,
  hasPersons,
  onDone,
}: {
  items: AliasSuggestion[];
  computed: boolean;
  view: SuggestionView;
  uncertainLeft: boolean;
  hasPersons: boolean;
  onDone: (notice: ReactNode) => void;
}) {
  if (items.length > 0) {
    return (
      <ul className={styles.list} aria-label="Alias-Vorschläge">
        {items.map((suggestion) => (
          <SuggestionRow
            key={`${suggestion.first.id}-${suggestion.second.id}`}
            suggestion={suggestion}
            onDone={onDone}
          />
        ))}
      </ul>
    );
  }
  if (view === "ai") {
    return (
      <EmptyState title="Keine Paare offen, die die KI für dieselbe Person hält">
        Mit „Mit KI prüfen“ prüft die KI die unsicheren Vorschläge und Personen mit ähnlichem Namen.
      </EmptyState>
    );
  }
  if (!computed && hasPersons) {
    return (
      <EmptyState title="Die Vorschläge sind noch nicht berechnet">
        Die Vorschläge werden beim nächsten Import-Lauf neu berechnet: unter{" "}
        <Link to="/import">Import</Link> auf „Import fortsetzen“ klicken.
      </EmptyState>
    );
  }
  if (uncertainLeft) {
    return (
      <EmptyState title="Keine sicheren Vorschläge offen">
        Die unsicheren lassen sich oben unter „Unsicher“ zeigen.
      </EmptyState>
    );
  }
  return (
    <EmptyState title="Keine offenen Vorschläge">
      Neue Vorschläge entstehen beim nächsten Import.
    </EmptyState>
  );
}

/** The alias check (D321 to D323): how far the text model got, and "Mit KI prüfen" while a text
 *  service on this machine is set; nothing while there is none and nothing was checked. */
function AliasCheck({ check }: { check: AliasCheckState }) {
  const start = useStartAliasCheck();
  if (!check.available && check.checked === 0) return null;
  const run = start.data?.run;
  const running = check.running || run === "started";
  return (
    <div className={styles.check}>
      <p className={styles.checkText}>
        {check.checked > 0
          ? `Die KI hat ${formatNumber(check.checked)} ${check.checked === 1 ? "Paar" : "Paare"} geprüft und hält ${formatNumber(check.same)} offene für dieselbe Person.`
          : "Die KI kann die unsicheren Vorschläge und Personen mit ähnlichem Namen prüfen. Sie vergleicht Namen, Adressen, Kontakte und Schlusszeilen eigener Mails, nur mit dem Textmodell auf diesem Rechner, und führt nie selbst zusammen."}
        {running && (
          <>
            {" Die Prüfung läuft, Paar für Paar. "}
            <Link to="/ki">Fortschritt unter KI</Link>
          </>
        )}
        {run === "running" &&
          " Gerade läuft ein anderer KI-Lauf. Die Prüfung lässt sich danach starten."}
        {run === "busy" &&
          " Gerade läuft ein Import oder ein anderer Lauf. Bitte später noch einmal."}
        {start.isError && " Das Starten hat nicht geklappt: Der Server hat einen Fehler gemeldet."}
      </p>
      {check.available && !running && (
        <Button size="sm" disabled={start.isPending} onClick={() => start.mutate()}>
          Mit KI prüfen
        </Button>
      )}
    </div>
  );
}

/** What a run of "Alle sicheren zusammenführen" did, with "Rückgängig" for the whole run. */
function RunNotice({ result }: { result: CertainMergeResult }) {
  const undo = useUndoMergeBatch();
  const batch = result.batch_id;
  if (batch === null) return <>Es gab nichts zusammenzuführen.</>;
  if (undo.isSuccess) {
    const { persons } = undo.data;
    return (
      <>
        Der Lauf ist rückgängig gemacht: {personCount(persons)} {persons === 1 ? "ist" : "sind"}{" "}
        wieder eigenständig.
      </>
    );
  }
  return (
    <>
      {personCount(result.persons)} in {mergeCount(result.merges)} zusammengeführt.{" "}
      <button
        type="button"
        className={styles.inline}
        disabled={undo.isPending}
        onClick={() => undo.mutate(batch)}
      >
        Rückgängig
      </button>
      {" · "}
      <Link to="/personen?tab=zusammengefuehrt">Zuletzt zusammengeführt</Link>
      {undo.isPending && " · Wird rückgängig gemacht …"}
      {undo.isError && <span className={styles.noticeError}> {personErrorText(undo.error)}</span>}
    </>
  );
}

function SuggestionRow({
  suggestion,
  onDone,
}: {
  suggestion: AliasSuggestion;
  onDone: (notice: ReactNode) => void;
}) {
  const merge = useMergePersons();
  const dismiss = useDismissSuggestion();
  const [reversed, setReversed] = useState(false);
  const { first, second } = suggestion;
  const [keep, other] = reversed ? [second, first] : [first, second];
  const busy = merge.isPending || dismiss.isPending;
  const error = merge.error ?? dismiss.error;

  // The row is gone once the mutation succeeds, so the confirmation goes to the list.
  async function onMerge() {
    try {
      const profile = await merge.mutateAsync({ target: keep.id, sources: [other.id] });
      onDone(
        <>
          {other.email} ist jetzt ein Alias von{" "}
          <Link to={personPath(profile.id)}>{personLabel(keep)}</Link>.
        </>,
      );
    } catch {
      // shown in the row
    }
  }

  async function onDismiss() {
    try {
      await dismiss.mutateAsync([first.id, second.id]);
      onDone(`Vorschlag verworfen: ${first.email} und ${second.email} bleiben getrennt.`);
    } catch {
      // shown in the row
    }
  }

  const tag = (stays: boolean) => (
    <span className={cx(styles.tag, stays && styles.stays)}>
      {stays ? " · bleibt" : " · wird Alias"}
    </span>
  );

  return (
    <li className={styles.row}>
      <PersonBadge person={first}>{tag(keep === first)}</PersonBadge>
      <PersonBadge person={second}>{tag(keep === second)}</PersonBadge>
      <div className={styles.why}>
        <p className={cx(styles.reason, suggestion.tier === "certain" && styles.certain)}>
          {REASON_TEXTS[suggestion.reason]}
        </p>
        <ul className={styles.reasons}>
          {suggestionReasons(suggestion).map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
        {suggestion.ai && (
          <p
            className={cx(styles.verdict, suggestion.ai.verdict === "same" && styles.same)}
            title={`${suggestion.ai.model}, ${formatDateTime(suggestion.ai.checked_at)}`}
          >
            <strong>{VERDICT_TEXTS[suggestion.ai.verdict]}.</strong> {suggestion.ai.reason}
          </p>
        )}
      </div>
      <div className={styles.actions}>
        <label className={styles.switch}>
          <input
            type="checkbox"
            role="switch"
            checked={reversed}
            disabled={busy}
            onChange={(event) => setReversed(event.target.checked)}
          />
          andersherum
        </label>
        <Button variant="outline" size="sm" disabled={busy} onClick={() => void onMerge()}>
          Zusammenführen
        </Button>
        <Button size="sm" disabled={busy} onClick={() => void onDismiss()}>
          Verwerfen
        </Button>
      </div>
      {error && (
        <p className={styles.error} role="alert">
          {personErrorText(error)}
        </p>
      )}
    </li>
  );
}
