import { useState } from "react";
import { Link } from "react-router";

import { useNotes } from "../../api/queries";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { SearchIcon } from "../../components/icons";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatDateTime, formatNumber } from "../../lib/format";
import { useDebounced } from "../../lib/useDebounced";
import styles from "./AktenScreen.module.css";

const SEARCH_DELAY = 300;

/** The Notizen tab (D56): every note, newest first, with its mail; searchable by its text. */
export function NoteList() {
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), SEARCH_DELAY);
  const notes = useNotes(q);
  const items = notes.data?.pages.flatMap((page) => page.items) ?? [];
  const total = notes.data?.pages[0]?.total;

  return (
    <>
      <div className={styles.toolbar}>
        <div className={styles.search}>
          <SearchIcon className={styles.searchIcon} />
          <label htmlFor="note-search" className="sr-only">
            Notizen durchsuchen
          </label>
          <input
            id="note-search"
            type="search"
            value={search}
            placeholder="In Notizen suchen …"
            autoComplete="off"
            className={styles.searchInput}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        {total !== undefined && (
          <span className={styles.total} aria-live="polite">
            {q
              ? `${formatNumber(total)} ${total === 1 ? "Notiz" : "Notizen"} gefunden`
              : `${formatNumber(total)} ${total === 1 ? "Notiz" : "Notizen"}`}
          </span>
        )}
      </div>
      <div className={styles.listCard}>
        {notes.isPending ? (
          <div className={styles.loading}>
            <Spinner label="Notizen werden geladen" />
          </div>
        ) : notes.isError ? (
          <ErrorState
            title="Die Notizen konnten nicht geladen werden."
            actions={<Button onClick={() => void notes.refetch()}>Erneut versuchen</Button>}
          >
            Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
          </ErrorState>
        ) : items.length === 0 ? (
          <EmptyState title={q ? "Keine Notiz gefunden" : "Noch keine Notiz"}>
            {q
              ? `Keine Notiz enthält „${q}“.`
              : "Notizen entstehen in der Detailansicht einer Mail."}
          </EmptyState>
        ) : (
          <ul className={cx(styles.list, notes.isPlaceholderData && styles.stale)}>
            {items.map((note) => (
              <li key={note.id} className={styles.note}>
                <p className={styles.noteBody}>{note.body}</p>
                <div className={styles.noteMeta}>
                  <span>
                    {note.author ?? "ohne Namen"} · {formatDateTime(note.created_at)}
                    {note.updated_at !== note.created_at && " (bearbeitet)"}
                  </span>
                  {note.mail.id === null ? (
                    <span>Mail nicht mehr im Archiv</span>
                  ) : (
                    <Link to={`/mails/${note.mail.id}`} className={styles.noteMail}>
                      {note.mail.subject || "(ohne Betreff)"}
                    </Link>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
      {notes.hasNextPage && (
        <div className={styles.more}>
          <Button onClick={() => void notes.fetchNextPage()} disabled={notes.isFetchingNextPage}>
            Mehr laden
          </Button>
        </div>
      )}
    </>
  );
}
