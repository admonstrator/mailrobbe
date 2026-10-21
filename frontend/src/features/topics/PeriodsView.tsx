import { useId, useState } from "react";
import { Link } from "react-router";

import { useTopicPeriods } from "../../api/queries";
import {
  TOPIC_PERIOD_TERMS,
  TOPIC_TERMS,
  type ThemeInfo,
  type TopicPeriod,
  type TopicUnit,
} from "../../api/types";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { mailsText, periodName, termFigures, themesOf, UNIT_LABELS, UNIT_PLURALS } from "./labels";
import styles from "./PeriodsView.module.css";
import { Segments } from "./Segments";
import { TermChip, TermList } from "./TermChip";
import {
  periodList,
  periodMailsHref,
  periodTimelineHref,
  termMailsHref,
  topicsHref,
  TOPIC_UNITS,
  type TopicsState,
} from "./urlState";

/** Periods shown at first and added per click: two years of months. */
const PERIODS_SHOWN = 24;

/** Zeiträume (D143): every month, quarter or year with mails, newest first, with the terms that
 *  stand out most in it against the whole archive. */
export function PeriodsView({
  state,
  onChange,
  themes,
}: {
  state: TopicsState;
  onChange: (next: TopicsState) => void;
  themes: ThemeInfo[] | undefined;
}) {
  const periods = useTopicPeriods(state.unit === "month" ? {} : { unit: state.unit });
  const data = periods.data;
  const [shown, setShown] = useState(PERIODS_SHOWN);

  return (
    <div className={styles.view}>
      <div className={styles.controls}>
        <Segments<TopicUnit>
          label="Zeiteinheit"
          options={TOPIC_UNITS.map((unit) => [unit, UNIT_LABELS[unit]])}
          value={state.unit}
          onChange={(unit) => {
            setShown(PERIODS_SHOWN);
            onChange({ ...state, unit });
          }}
        />
        {data && data.periods.length > 0 && (
          <span className={styles.summary}>
            {formatNumber(data.periods.length)}{" "}
            {data.periods.length === 1 ? UNIT_LABELS[data.unit] : UNIT_PLURALS[data.unit]} mit
            Mails, neueste zuerst
          </span>
        )}
      </div>
      <Card className={styles.card}>
        {periods.isPending ? (
          <div className={styles.loading}>
            <Spinner label="Zeiträume werden geladen" />
          </div>
        ) : periods.isError ? (
          <ErrorState
            title="Die Zeiträume konnten nicht geladen werden."
            actions={<Button onClick={() => void periods.refetch()}>Erneut versuchen</Button>}
          >
            Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
          </ErrorState>
        ) : periods.data.periods.length === 0 ? (
          <EmptyState title="Keine Zeiträume">
            Keine Mail des Archivs hat ein Datum, nach dem sie sich einem Zeitraum zuordnen ließe.
          </EmptyState>
        ) : (
          <>
            <ol
              className={cx(styles.periods, periods.isPlaceholderData && styles.stale)}
              aria-label={UNIT_PLURALS[periods.data.unit]}
            >
              {periods.data.periods.slice(0, shown).map((period) => (
                <Period
                  key={period.start}
                  period={period}
                  unit={periods.data.unit}
                  themes={themes}
                />
              ))}
            </ol>
            {periods.data.periods.length > shown && (
              <div className={styles.older}>
                <Button onClick={() => setShown(shown + PERIODS_SHOWN)}>
                  Ältere Zeiträume zeigen (noch {formatNumber(periods.data.periods.length - shown)})
                </Button>
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}

/** One period: its name, its mails and links, and its terms; "mehr" asks for the rest of the
 *  terms the phase kept for it. */
function Period({
  period,
  unit,
  themes,
}: {
  period: TopicPeriod;
  unit: TopicUnit;
  themes: ThemeInfo[] | undefined;
}) {
  const titleId = useId();
  const [expanded, setExpanded] = useState(false);
  const { start, end } = period;
  const more = useTopicPeriods(
    { unit, date_from: start, date_to: end, limit: TOPIC_PERIOD_TERMS },
    expanded,
  );
  const all = expanded ? more.data?.periods.find((other) => other.start === start) : undefined;
  const terms = all?.terms ?? period.terms;
  const name = periodName(start, unit);
  const list = periodList(start, end);

  return (
    <li className={styles.period} aria-labelledby={titleId}>
      <div className={styles.head}>
        <h3 id={titleId} className={styles.name}>
          {name}
        </h3>
        <span className={styles.mails}>{mailsText(period.mails)}</span>
        <span className={styles.links}>
          <Link to={periodMailsHref(start, end)} aria-label={`Mails von ${name}`}>
            Mails
          </Link>
          <Link to={periodTimelineHref(start, end)} aria-label={`Zeitachse von ${name}`}>
            Zeitachse
          </Link>
          <Link
            to={topicsHref({ view: "selection", unit, list })}
            aria-label={`Als Auswahl: ${name}`}
            title="Die Begriffe dieses Zeitraums neu zählen, auch für eine Person oder eine Suche"
          >
            Als Auswahl
          </Link>
        </span>
      </div>
      {terms.length === 0 ? (
        <p className={styles.none}>Kein Wort hebt sich in diesem Zeitraum ab.</p>
      ) : (
        <div className={styles.terms}>
          <TermList label={`Begriffe ${name}`}>
            {terms.map((term) => (
              <TermChip
                key={term.term}
                label={term.label}
                mails={term.mails}
                href={termMailsHref(list, term.label)}
                figures={termFigures(term, period.mails)}
                themes={themesOf(term.themes, themes)}
              />
            ))}
          </TermList>
          {(period.terms.length >= TOPIC_TERMS || expanded) && (
            <button
              type="button"
              className={styles.more}
              aria-expanded={expanded}
              onClick={() => setExpanded(!expanded)}
            >
              {!expanded ? "mehr" : more.isFetching && !all ? "lädt …" : "weniger"}
            </button>
          )}
        </div>
      )}
    </li>
  );
}
