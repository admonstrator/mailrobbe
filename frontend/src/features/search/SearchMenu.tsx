import { useRef } from "react";
import { Link } from "react-router";

import { useResearch } from "../../api/queries";
import { Button } from "../../components/Button";
import { Checkbox } from "../../components/Checkbox";
import type { SearchOptions as Options } from "../mails/listState";
import {
  changedOptions,
  DEFAULT_SEARCH_OPTIONS,
  SearchOptions,
  SearchSyntax,
} from "../mails/SearchOptions";
import { searchHref } from "../research/labels";
import styles from "./SearchMenu.module.css";

/** The content of the search menu: the options of the search words (D171 to D174), words to
 *  exclude, the syntax, and the saved searches (D59). */
export function SearchMenu({
  options,
  onList,
  change,
  exclude,
  save,
  onLeave,
}: {
  options: Options;
  /** The options act on the list shown; otherwise they wait for the next search. */
  onList: boolean;
  change: (patch: Partial<Options>) => void;
  exclude: (text: string) => void;
  /** Saves the list's search; null where there is no list with a search or filter. */
  save: (() => void) | null;
  /** A saved search was opened. */
  onLeave: () => void;
}) {
  return (
    <div className={styles.menu}>
      <div className={styles.head}>
        <h2 className={styles.title}>Suchoptionen</h2>
        <span className={styles.note}>
          {onList ? "Wirkt sofort auf die Liste" : "Gilt für die nächste Suche"}
        </span>
        <Button
          variant="link"
          size="sm"
          className={styles.reset}
          disabled={changedOptions(options) === 0}
          onClick={() => change(DEFAULT_SEARCH_OPTIONS)}
        >
          Zurücksetzen
        </Button>
      </div>
      <div className={styles.columns}>
        <div className={styles.column}>
          <p className={styles.text}>Wirkt auf die Wörter der Suche, nicht auf from:, has: usw.</p>
          <SearchOptions options={options} change={change} />
          <ExcludeField exclude={exclude} />
          <HiddenMails options={options} change={change} onLeave={onLeave} />
        </div>
        <div className={styles.column}>
          <section aria-labelledby="search-menu-saved">
            <h3 id="search-menu-saved" className={styles.heading}>
              Gespeicherte Suchen
            </h3>
            <SavedSearches onLeave={onLeave} />
            <Button
              variant="outline"
              size="sm"
              className={styles.save}
              disabled={!save}
              title={save ? undefined : "In der Mailliste mit einer Suche oder einem Filter"}
              onClick={() => save?.()}
            >
              Aktuelle Suche speichern
            </Button>
          </section>
          <section aria-labelledby="search-menu-syntax">
            <h3 id="search-menu-syntax" className={styles.heading}>
              Suchsyntax
            </h3>
            <SearchSyntax />
          </section>
        </div>
      </div>
    </div>
  );
}

/** "Wörter ausschließen": the words become "-Wort" terms of the search. */
function ExcludeField({ exclude }: { exclude: (text: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  function apply() {
    const text = input.current?.value.trim() ?? "";
    if (!text || !input.current) return;
    exclude(text);
    input.current.value = "";
  }
  return (
    <section aria-labelledby="search-menu-exclude" className={styles.exclude}>
      <h3 id="search-menu-exclude" className={styles.heading}>
        Ausschließen
      </h3>
      <p className={styles.text}>
        Ein Minus vor einem Wort schließt Mails mit diesem Wort aus, etwa <code>-Entwurf</code> oder{" "}
        <code>-from:@beispiel.de</code>.
      </p>
      <div className={styles.excludeRow}>
        <label htmlFor="search-exclude" className="sr-only">
          Wörter ausschließen
        </label>
        <input
          ref={input}
          id="search-exclude"
          type="text"
          autoComplete="off"
          spellCheck={false}
          placeholder="Wörter ausschließen"
          className={styles.input}
          onKeyDown={(event) => {
            if (event.key !== "Enter") return;
            event.preventDefault();
            apply();
          }}
        />
        <Button size="sm" onClick={apply}>
          Ausschließen
        </Button>
      </div>
    </section>
  );
}

/** "Ausgeblendete Mails" (D222, D223): the switch that includes the mails a hide rule hides,
 *  and the way to the rules. */
function HiddenMails({
  options,
  change,
  onLeave,
}: {
  options: Options;
  change: (patch: Partial<Options>) => void;
  onLeave: () => void;
}) {
  return (
    <section aria-labelledby="search-menu-hidden" className={styles.exclude}>
      <h3 id="search-menu-hidden" className={styles.heading}>
        Ausgeblendete Mails
      </h3>
      <Checkbox
        checked={options.include_hidden}
        onChange={(include_hidden) => change({ include_hidden })}
      >
        Ausgeblendete einbeziehen
      </Checkbox>
      <p className={styles.text}>
        Ausblendregeln nehmen Newsletter, Rundmails und Systemmails aus Liste und Suche.{" "}
        <Link to="/ausgeblendet" onClick={onLeave}>
          Regeln verwalten
        </Link>
      </p>
    </section>
  );
}

function SavedSearches({ onLeave }: { onLeave: () => void }) {
  const research = useResearch();
  if (!research.data) {
    return (
      <p className={styles.text}>
        {research.isError ? "Die gespeicherten Suchen sind nicht verfügbar." : "Lädt …"}
      </p>
    );
  }
  const searches = research.data.searches;
  if (searches.length === 0) {
    return <p className={styles.text}>Noch keine gespeicherte Suche.</p>;
  }
  return (
    <ul className={styles.saved}>
      {searches.map((search) => (
        <li key={search.id}>
          <Link to={searchHref(search.query)} className={styles.savedLink} onClick={onLeave}>
            {search.name}
          </Link>
        </li>
      ))}
    </ul>
  );
}
