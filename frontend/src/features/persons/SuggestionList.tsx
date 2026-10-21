import { useState, type ReactNode } from "react";
import { Link } from "react-router";

import {
  useDismissSuggestion,
  useMergeCertain,
  useMergePersons,
  useSuggestions,
  useUndoMergeBatch,
} from "../../api/queries";
import type { AliasSuggestion, CertainMergeResult } from "../../api/types";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { personPath } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { BulkMergeDialog } from "./BulkMergeDialog";
import {
  mergeCount,
  personCount,
  personErrorText,
  personLabel,
  REASON_TEXTS,
  suggestionReasons,
} from "./labels";
import { PersonBadge } from "./PersonBadge";
import styles from "./SuggestionList.module.css";

/** The open alias suggestions (D30, D160): the certain ones, or the uncertain ones behind the
 *  switch. Each can be merged (keeping the first, or the second with "andersherum") or
 *  dismissed; "Alle sicheren zusammenführen" merges every certain one as one run (D162). The
 *  row goes and a confirmation stays above the list, for a run with its "Rückgängig". */
export function SuggestionList({
  uncertain,
  onUncertain,
  hasPersons,
}: {
  uncertain: boolean;
  onUncertain: (uncertain: boolean) => void;
  hasPersons: boolean;
}) {
  const certain = useSuggestions("certain");
  const suggestions = useSuggestions(uncertain ? "uncertain" : "certain");
  const mergeCertain = useMergeCertain();
  const [notice, setNotice] = useState<ReactNode>(null);
  const [confirming, setConfirming] = useState(false);
  const counts = (certain.data ?? suggestions.data)?.pages[0]?.counts;

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
      <p className={styles.intro}>
        {uncertain
          ? "Unsichere Vorschläge: Nur ein Teil spricht dafür, etwa der gleiche Name ohne gemeinsame Kontakte. Gleichnamige sind häufig, bitte einzeln prüfen."
          : "Sichere Vorschläge: Name und Adressen passen zusammen, und beide schreiben mit denselben Leuten. Zusammengeführt wird nur per Klick, und jede Zusammenführung lässt sich rückgängig machen."}
      </p>
      <div className={styles.toolbar}>
        <label className={styles.switch}>
          <input
            type="checkbox"
            role="switch"
            checked={uncertain}
            onChange={(event) => {
              setNotice(null);
              onUncertain(event.target.checked);
            }}
          />
          {counts
            ? `Unsichere Vorschläge zeigen (${formatNumber(counts.uncertain)})`
            : "Unsichere Vorschläge zeigen"}
        </label>
        {!uncertain && counts !== undefined && counts.certain > 0 && (
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
      <p role="status" className={cx(styles.notice, !notice && "sr-only")}>
        {notice}
      </p>
      {suggestions.isPending ? (
        <Card className={styles.loading}>
          <Spinner label="Vorschläge werden geladen" />
        </Card>
      ) : suggestions.isError ? (
        <Card>
          <ErrorState
            title="Die Vorschläge konnten nicht geladen werden."
            actions={<Button onClick={() => void suggestions.refetch()}>Erneut versuchen</Button>}
          >
            Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
          </ErrorState>
        </Card>
      ) : (
        <>
          <Card className={styles.card}>
            <Rows
              items={suggestions.data.pages.flatMap((page) => page.items)}
              computed={suggestions.data.pages[0].computed}
              uncertainLeft={!uncertain && (counts?.uncertain ?? 0) > 0}
              hasPersons={hasPersons}
              onDone={setNotice}
            />
          </Card>
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
  uncertainLeft,
  hasPersons,
  onDone,
}: {
  items: AliasSuggestion[];
  computed: boolean;
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
        Die unsicheren lassen sich mit dem Schalter oben zeigen.
      </EmptyState>
    );
  }
  return (
    <EmptyState title="Keine offenen Vorschläge">
      Neue Vorschläge entstehen beim nächsten Import.
    </EmptyState>
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
        <Button variant="primary" size="sm" disabled={busy} onClick={() => void onMerge()}>
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
