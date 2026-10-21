// The card "Auffällige Begriffe" of the person profile (D144, D148): the terms of the person's
// sent mails against the rest of the archive. The profile is in the main chunk, so the card uses
// the small modules of the topics (labels, urlState, TermChip), never the topics screen.

import { Link } from "react-router";

import { useThemes, useTopicTerms } from "../../api/queries";
import type { ThemeInfo, TopicTerms } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { Spinner } from "../../components/Spinner";
import { formatNumber } from "../../lib/format";
import { DEFAULT_LIST_STATE, toFilters, withFilters, type ListState } from "../mails/listState";
import { termFigures, themesOf } from "./labels";
import styles from "./PersonTermsCard.module.css";
import { TermChip, TermList } from "./TermChip";
import { selectionHref, termMailsHref } from "./urlState";

/** Terms the card shows at most. */
export const PROFILE_TERMS = 12;

export function PersonTermsCard({ personId }: { personId: number }) {
  const list = withFilters(DEFAULT_LIST_STATE, { person: [personId], person_role: "sent" });
  const terms = useTopicTerms({ ...toFilters(list), limit: PROFILE_TERMS });
  const themes = useThemes();

  return (
    <Card className={styles.card}>
      <div className={styles.head}>
        <CardTitle>Auffällige Begriffe</CardTitle>
        <span className={styles.hint}>
          in den gesendeten Mails, verglichen mit dem übrigen Archiv
        </span>
        <Link to={selectionHref(list)} className={styles.all}>
          Alle Begriffe
        </Link>
      </div>
      {terms.isPending ? (
        <p className={styles.line}>
          <Spinner label="Begriffe werden gezählt" /> Begriffe werden gezählt …
        </p>
      ) : terms.isError ? (
        <p className={styles.line} role="alert">
          Die Begriffe konnten nicht geladen werden.{" "}
          <Button variant="link" size="sm" onClick={() => void terms.refetch()}>
            Erneut versuchen
          </Button>
        </p>
      ) : (
        <Found data={terms.data} list={list} themes={themes.data} />
      )}
    </Card>
  );
}

/** The terms, or a quiet line why there are none. */
function Found({
  data,
  list,
  themes,
}: {
  data: TopicTerms;
  list: ListState;
  themes: ThemeInfo[] | undefined;
}) {
  if (data.state.computed_at === null) {
    return (
      <p className={styles.line}>
        Die Begriffe werden beim nächsten Import berechnet. <Link to="/import">Zum Import</Link>
      </p>
    );
  }
  if (data.timed_out) return <p className={styles.line}>Die Zählung hat zu lange gedauert.</p>;
  if (data.terms.length === 0) {
    return (
      <p className={styles.line}>
        Kein Wort ist in den gesendeten Mails mindestens doppelt so häufig wie im übrigen Archiv.
      </p>
    );
  }
  return (
    <>
      <TermList label="Auffällige Begriffe der gesendeten Mails">
        {data.terms.map((term) => (
          <TermChip
            key={term.term}
            label={term.label}
            mails={term.mails}
            href={termMailsHref(list, term.label)}
            figures={termFigures(term, data.mails, data.sampled)}
            themes={themesOf(term.themes, themes)}
          />
        ))}
      </TermList>
      {data.sampled && data.mails !== null && (
        <p className={styles.line}>
          Gezählt über {formatNumber(data.counted)} von {formatNumber(data.mails)} Mails, Zahlen
          geschätzt
        </p>
      )}
    </>
  );
}
