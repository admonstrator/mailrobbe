import { useState, type FormEvent } from "react";

import { useMergePersons, usePersonPage } from "../../api/queries";
import type { AliasCandidate, PersonProfile, PersonSummary } from "../../api/types";
import { Button } from "../../components/Button";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { useDebounced } from "../../lib/useDebounced";
import { Dialog } from "./Dialog";
import { formatNumber } from "../../lib/format";
import { personErrorText, personLabel, suggestionReasons } from "./labels";
import styles from "./MergeDialog.module.css";
import { PersonBadge } from "./PersonBadge";

/** Persons the search lists at most. */
const SEARCH_LIMIT = 20;

/** "+ Adresse zusammenführen": choose a suggested or searched person and merge it, with its
 *  aliases, into this one (D28). The certain suggestions come first, the uncertain ones folded
 *  behind their count (D160). The profile then shows the answer, the merged profile. */
export function MergeDialog({ profile, onClose }: { profile: PersonProfile; onClose: () => void }) {
  const merge = useMergePersons();
  const [search, setSearch] = useState("");
  const q = useDebounced(search.trim(), 300);
  const results = usePersonPage({ q, limit: SEARCH_LIMIT }, q !== "");
  const [chosen, setChosen] = useState<PersonSummary | null>(null);
  const name = personLabel(profile);
  const suggested = new Set(profile.suggestions.map((candidate) => candidate.person.id));
  const found = (q === "" ? [] : (results.data?.items ?? [])).filter(
    (person) => person.id !== profile.id && !suggested.has(person.id),
  );

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!chosen) return;
    try {
      await merge.mutateAsync({ target: profile.id, sources: [chosen.id] });
      onClose();
    } catch {
      // shown below the list
    }
  }

  const option = (person: PersonSummary, reasons: string[] = []) => (
    <label key={person.id} className={cx(styles.option, chosen?.id === person.id && styles.chosen)}>
      <input
        type="radio"
        name="merge-source"
        value={person.id}
        checked={chosen?.id === person.id}
        onChange={() => setChosen(person)}
      />
      <PersonBadge person={person} link={false}>
        {reasons.map((reason) => ` · ${reason}`).join("")}
      </PersonBadge>
    </label>
  );

  const certain = profile.suggestions.filter((candidate) => candidate.tier === "certain");
  const uncertain = profile.suggestions.filter((candidate) => candidate.tier === "uncertain");
  const uncertainTotal = Math.max(uncertain.length, profile.suggestion_counts.uncertain);
  const suggestion = (candidate: AliasCandidate) =>
    option(candidate.person, suggestionReasons(candidate));

  return (
    <Dialog title="Adresse zusammenführen" onClose={onClose}>
      <form className={styles.form} onSubmit={(event) => void onSubmit(event)}>
        <p className={styles.intro}>
          Die gewählte Person wird mit {name} zusammengeführt. Ihre Adressen werden zu Aliasen von{" "}
          {name}, ihre Mails zählen dann zu {name}. Im Profil lässt sich ein Alias wieder lösen.
        </p>
        <div className={styles.scroll}>
          {profile.suggestions.length > 0 && (
            <fieldset className={styles.group}>
              <legend className={styles.legend}>Vorschläge</legend>
              {certain.map(suggestion)}
              {uncertain.length > 0 && (
                <details className={styles.uncertain}>
                  <summary>
                    {uncertainTotal === 1
                      ? "1 unsicherer Vorschlag"
                      : `${formatNumber(uncertainTotal)} unsichere Vorschläge`}
                    {uncertainTotal > uncertain.length &&
                      `, hier die ${formatNumber(uncertain.length)} mit den meisten Mails`}
                  </summary>
                  <div className={styles.group}>{uncertain.map(suggestion)}</div>
                </details>
              )}
            </fieldset>
          )}
          <fieldset className={styles.group}>
            <legend className={styles.legend}>Andere Person suchen</legend>
            <label htmlFor="merge-search" className="sr-only">
              Person oder Adresse suchen
            </label>
            <input
              id="merge-search"
              type="search"
              className={styles.search}
              placeholder="Name oder Adresse …"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              autoComplete="off"
              spellCheck={false}
            />
            {q !== "" && results.isPending && <Spinner label="Personen werden gesucht" />}
            {q !== "" && results.isError && (
              <p className={styles.note}>Die Suche ist fehlgeschlagen.</p>
            )}
            {q !== "" && results.data && found.length === 0 && (
              <p className={styles.note}>Keine andere Person gefunden.</p>
            )}
            {found.map((person) => option(person))}
          </fieldset>
        </div>
        {merge.isError && (
          <p className={styles.error} role="alert">
            {personErrorText(merge.error)}
          </p>
        )}
        <div className={styles.foot}>
          <span className={styles.choice}>
            {chosen ? `${chosen.email} wird Alias von ${name}.` : "Noch keine Person gewählt."}
          </span>
          <Button onClick={onClose}>Abbrechen</Button>
          <Button type="submit" variant="primary" disabled={!chosen || merge.isPending}>
            Zusammenführen
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
