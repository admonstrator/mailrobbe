import { useMemo, useRef, useState } from "react";
import { Link } from "react-router";

import { useDeleteSearch, useMailSummary, useUpdateSearch } from "../../api/queries";
import { NAME_LIMIT, type CollectionInfo, type SavedSearch } from "../../api/types";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { Spinner } from "../../components/Spinner";
import { parseListState, toFilters } from "../mails/listState";
import { formatTotal } from "../mails/SummaryTiles";
import styles from "./AktenScreen.module.css";
import { ConfirmDialog } from "./ConfirmDialog";
import forms from "./forms.module.css";
import { InlineEdit } from "./InlineEdit";
import { researchErrorText, searchHref } from "./labels";
import { useInView } from "./useInView";

/** The Gespeicherte Suchen tab (D59): each search opens the mail list anew; its number of
 *  matches is counted only once its row is on screen, since a broad count takes a while. */
export function SearchList({
  searches,
  collections,
}: {
  searches: SavedSearch[];
  collections: CollectionInfo[];
}) {
  const [deleting, setDeleting] = useState<SavedSearch | null>(null);
  const remove = useDeleteSearch();

  return (
    <>
      <div className={styles.toolbar}>
        <p className={styles.intro}>
          Eine gespeicherte Suche merkt sich Suchtext, Filter und Sortierung der Mailliste. Sie
          läuft bei jedem Öffnen neu, ihre Treffer folgen also dem Archiv.
        </p>
      </div>
      <Card className={styles.listCard}>
        {searches.length === 0 ? (
          <EmptyState title="Noch keine gespeicherte Suche">
            Eine Suche wird in der Mailliste gespeichert; das Themen-Startset legt die Suchen der
            Themen an.
          </EmptyState>
        ) : (
          <ul className={styles.list}>
            {searches.map((search) => (
              <SearchRow
                key={search.id}
                search={search}
                collections={collections}
                onDelete={() => {
                  remove.reset();
                  setDeleting(search);
                }}
              />
            ))}
          </ul>
        )}
      </Card>
      {deleting && (
        <ConfirmDialog
          title="Suche löschen"
          confirmLabel="Löschen"
          pending={remove.isPending}
          error={remove.error}
          onClose={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting.id, { onSuccess: () => setDeleting(null) })}
        >
          Die gespeicherte Suche „{deleting.name}“ wird gelöscht. Die Mails und alles, was zu ihnen
          notiert ist, bleiben.
        </ConfirmDialog>
      )}
    </>
  );
}

function SearchRow({
  search,
  collections,
  onDelete,
}: {
  search: SavedSearch;
  collections: CollectionInfo[];
  onDelete: () => void;
}) {
  const update = useUpdateSearch();
  const row = useRef<HTMLLIElement>(null);
  const shown = useInView(row);
  const assign = `search-collection-${search.id}`;

  return (
    <li ref={row} className={styles.item}>
      <div className={styles.itemMain}>
        <InlineEdit
          value={search.name}
          label={`Name von „${search.name}“`}
          maxLength={NAME_LIMIT}
          required
          onSave={(name) => update.mutateAsync({ id: search.id, name })}
        >
          <Link to={searchHref(search.query)} className={styles.itemTitle}>
            {search.name}
          </Link>
        </InlineEdit>
        <span className={styles.itemSub}>
          {search.created_by ? `gespeichert von ${search.created_by}` : "gespeichert"}
          {" · "}
          {shown ? <SearchCount query={search.query} /> : "…"}
        </span>
      </div>
      <div className={styles.itemActions}>
        <label htmlFor={assign} className="sr-only">
          Akte von „{search.name}“
        </label>
        <select
          id={assign}
          className={styles.select}
          value={search.collection_id ?? ""}
          disabled={update.isPending}
          onChange={(event) =>
            update.mutate({
              id: search.id,
              collection_id: event.target.value ? Number(event.target.value) : null,
            })
          }
        >
          <option value="">Keine Akte</option>
          {collections.map((collection) => (
            <option key={collection.id} value={collection.id}>
              {collection.name}
            </option>
          ))}
        </select>
        <Button size="sm" onClick={onDelete} aria-label={`„${search.name}“ löschen`}>
          Löschen
        </Button>
      </div>
      {update.isError && (
        <p className={forms.error} role="alert">
          {researchErrorText(update.error)}
        </p>
      )}
    </li>
  );
}

/** "1.204 Treffer", counted as the mail list counts. */
function SearchCount({ query }: { query: string }) {
  const filters = useMemo(() => toFilters(parseListState(new URLSearchParams(query))), [query]);
  const summary = useMailSummary(filters);
  if (summary.isPending) return <Spinner label="Treffer werden gezählt" />;
  if (summary.isError) return <>Treffer nicht zählbar</>;
  return <>{formatTotal(summary.data)} Treffer</>;
}
