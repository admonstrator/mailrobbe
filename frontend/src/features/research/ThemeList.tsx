import { Link } from "react-router";

import { useCreateStarter, useThemes } from "../../api/queries";
import { Button } from "../../components/Button";
import { HelpTip } from "../../components/PageHead";
import { Card } from "../../components/Card";
import { ErrorState } from "../../components/ErrorState";
import { Spinner } from "../../components/Spinner";
import { formatNumber } from "../../lib/format";
import { entityMailsHref } from "../entities/urlState";
import styles from "./AktenScreen.module.css";
import { ColorChip } from "./ColorChip";
import forms from "./forms.module.css";
import { researchErrorText, searchHref, termHref } from "./labels";

/** A term's mails: those its entity is found in, where the entities phase found it, since the
 *  full text search drops stop words such as "nicht" of a phrase (D138); else the search. */
function termLink(term: string, entityId: number | null): string {
  return entityId === null ? termHref(term) : entityMailsHref([entityId]);
}

/** The Themen tab (D64): each research theme with its word field and search templates, and the
 *  starter set that creates their tags and saved searches. */
export function ThemeList({ starterMissing }: { starterMissing: number }) {
  const themes = useThemes();
  const starter = useCreateStarter();

  return (
    <>
      <div className={styles.toolbar}>
        <p className={styles.intro}>
          Die Themen der Recherche mit ihrem Wortfeld.
          <HelpTip text="Jedes Wort und jede Suche öffnet die Mailliste. Was davon zählt, entscheiden die Lesenden." />
        </p>
      </div>
      {starterMissing > 0 && (
        <Card className={styles.starter}>
          <p className={styles.starterText}>
            Das Themen-Startset legt für jedes Thema ein Schlagwort und seine gespeicherten Suchen
            an ({formatNumber(starterMissing)} fehlen noch); es verschlagwortet selbst keine Mail.
          </p>
          <Button
            variant="primary"
            disabled={starter.isPending}
            onClick={() => starter.mutate(undefined)}
          >
            Themen-Startset anlegen
          </Button>
          {starter.isError && (
            <p className={forms.error} role="alert">
              {researchErrorText(starter.error)}
            </p>
          )}
        </Card>
      )}
      {themes.isPending ? (
        <Card className={styles.loading}>
          <Spinner label="Themen werden geladen" />
        </Card>
      ) : themes.isError ? (
        <Card>
          <ErrorState
            title="Die Themen konnten nicht geladen werden."
            actions={<Button onClick={() => void themes.refetch()}>Erneut versuchen</Button>}
          >
            Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
          </ErrorState>
        </Card>
      ) : (
        <div className={styles.themes}>
          {themes.data.map((theme) => (
            <Card key={theme.key} className={styles.theme} aria-labelledby={`theme-${theme.key}`}>
              <h2 id={`theme-${theme.key}`} className={styles.themeTitle}>
                <ColorChip color={theme.color}>{theme.name}</ColorChip>
              </h2>
              <p className={styles.themeText}>{theme.description}</p>
              {theme.searches.length > 0 && (
                <ul className={styles.links}>
                  {theme.searches.map((search) => (
                    <li key={search.name}>
                      <Link to={searchHref(search.query)}>{search.name}</Link>
                    </li>
                  ))}
                </ul>
              )}
              <ul className={styles.terms} aria-label={`Wortfeld ${theme.name}`}>
                {theme.terms.map((term, index) => (
                  <li key={term}>
                    <Link
                      to={termLink(term, theme.term_ids[index] ?? null)}
                      className={styles.term}
                    >
                      {term}
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
