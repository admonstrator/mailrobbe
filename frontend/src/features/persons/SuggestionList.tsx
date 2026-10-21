import type { InfiniteData, UseInfiniteQueryResult } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";

import { useDismissSuggestion, useMergePersons } from "../../api/queries";
import type { AliasSuggestion, SuggestionPage } from "../../api/types";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { personPath } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { personErrorText, personLabel, suggestionReasons } from "./labels";
import { PersonBadge } from "./PersonBadge";
import styles from "./SuggestionList.module.css";

/** The open alias suggestions (D30): merge (keeping the first, or the second with
 *  "andersherum") or dismiss each; the row goes and a confirmation stays above the list. */
export function SuggestionList({
  suggestions,
}: {
  suggestions: UseInfiniteQueryResult<InfiniteData<SuggestionPage>>;
}) {
  const [notice, setNotice] = useState<ReactNode>(null);

  if (suggestions.isPending) {
    return (
      <Card className={styles.loading}>
        <Spinner label="Vorschläge werden geladen" />
      </Card>
    );
  }
  if (suggestions.isError) {
    return (
      <Card>
        <ErrorState
          title="Die Vorschläge konnten nicht geladen werden."
          actions={<Button onClick={() => void suggestions.refetch()}>Erneut versuchen</Button>}
        >
          Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
        </ErrorState>
      </Card>
    );
  }

  const items = suggestions.data.pages.flatMap((page) => page.items);
  return (
    <>
      <p className={styles.intro}>
        Adressen mit gleichem Namen oder gleichem Adressteil gehören vielleicht derselben Person.
        Zusammengeführt wird nur per Klick; im Profil lässt sich ein Alias wieder lösen.
      </p>
      <p role="status" className={cx(styles.notice, !notice && "sr-only")}>
        {notice}
      </p>
      <Card className={styles.card}>
        {items.length === 0 ? (
          <EmptyState title="Keine offenen Vorschläge">
            Neue Vorschläge entstehen beim nächsten Import.
          </EmptyState>
        ) : (
          <ul className={styles.list} aria-label="Alias-Vorschläge">
            {items.map((suggestion) => (
              <SuggestionRow
                key={`${suggestion.first.id}-${suggestion.second.id}`}
                suggestion={suggestion}
                onDone={setNotice}
              />
            ))}
          </ul>
        )}
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
      <ul className={styles.reasons}>
        {suggestionReasons(suggestion).map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
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
