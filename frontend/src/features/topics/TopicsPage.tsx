import { useMemo } from "react";
import { Link, useSearchParams } from "react-router";

import { useThemes, useTopicPeriods } from "../../api/queries";
import { buttonClass } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Tabs, tabPanelProps, type TabItem } from "../../components/Tabs";
import { formatNumber } from "../../lib/format";
import { ClustersView } from "./ClustersView";
import { stateText } from "./labels";
import { PeriodsView } from "./PeriodsView";
import { SelectionView } from "./SelectionView";
import styles from "./TopicsPage.module.css";
import { parseTopicsState, topicsSearch, type TopicsState, type TopicView } from "./urlState";

const TABS_ID = "topics";

const VIEW_LABELS: Record<TopicView, string> = {
  periods: "Zeiträume",
  selection: "Auswahl",
  clusters: "Themen",
};

// The smallest stored answer that carries the state of the last computation: the years with
// one term each.
const STATE_PARAMS = { unit: "year", limit: 1 } as const;

/** The topics screen "Themen" (D148): the words that stand out per period, in a selection of the
 *  mail list, and groups of words that stand together, each leading to the mails. */
export function TopicsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => parseTopicsState(searchParams), [searchParams]);
  const setState = (next: TopicsState) =>
    setSearchParams(topicsSearch(next), { preventScrollReset: true });
  const status = useTopicPeriods(STATE_PARAMS);
  const themes = useThemes();
  const computed = status.data?.state;
  const line = computed ? stateText(computed) : null;

  const tabs: TabItem<TopicView>[] = (Object.keys(VIEW_LABELS) as TopicView[]).map((view) => ({
    id: view,
    label:
      view === "clusters" && computed?.computed_at
        ? `${VIEW_LABELS[view]} ${formatNumber(computed.clusters)}`
        : VIEW_LABELS[view],
  }));

  return (
    <div className={styles.page}>
      <title>Themen · Mailrobbe</title>
      <div className={styles.head}>
        <h1 className={styles.title}>Themen</h1>
        <p className={styles.intro}>
          Wörter, die irgendwo häufiger vorkommen als im übrigen Archiv, und Wörter, die oft
          zusammen stehen.
        </p>
      </div>
      {line && <p className={styles.state}>{line}</p>}
      <Explanation />

      <div className={styles.layout}>
        <div className={styles.main}>
          {computed?.computed_at === null ? (
            <div>
              <EmptyState
                title="Die Begriffe sind noch nicht berechnet."
                actions={
                  <Link to="/import" className={buttonClass()}>
                    Zum Import
                  </Link>
                }
              >
                Der nächste Import berechnet sie, nach den Entitäten, aus den schon importierten
                Mails; nichts wird neu eingelesen.
              </EmptyState>
            </div>
          ) : (
            <>
              <Tabs<TopicView>
                items={tabs}
                active={state.view}
                onSelect={(view) => view !== state.view && setState({ ...state, view })}
                idPrefix={TABS_ID}
                label="Ansichten"
              />
              <div {...tabPanelProps(TABS_ID, state.view)} className={styles.panel}>
                {state.view === "periods" && (
                  <PeriodsView state={state} onChange={setState} themes={themes.data} />
                )}
                {state.view === "selection" && (
                  <SelectionView state={state} onChange={setState} themes={themes.data} />
                )}
                {state.view === "clusters" && <ClustersView themes={themes.data} />}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** How the terms are found and how to search with them (D142, D148), in plain words: folded
 *  below the head until asked for. */
function Explanation() {
  return (
    <details className={styles.explanation}>
      <summary className={styles.summary}>
        <h2 className={styles.summaryTitle}>So entstehen die Begriffe</h2>
      </summary>
      <div className={styles.rules}>
        <p>
          <strong>Ein Begriff</strong> ist ein Wort mit allen seinen Formen: Spende, Spenden und
          spenden zählen zusammen. Gezählt werden Mails ohne Duplikate, aus Betreff und Text, nicht
          aus Anhängen. Die Mailliste kann deshalb mehr Mails zeigen; die über einen Anhang
          gefundenen sind dort markiert.
        </p>
        <p>
          <strong>Gelistet</strong> wird ein Wort, das in mindestens 3 Mails steht und hier
          mindestens doppelt so häufig ist wie im übrigen Archiv. Sortiert wird nach einem
          statistischen Maß (Log-Likelihood), das beides zusammennimmt: wie viel häufiger und in wie
          vielen Mails. Die Zahlen am Wort zeigen seine Mails, den Anteil hier, den Anteil im
          übrigen Archiv und wie viel häufiger es hier ist.
        </p>
        <p>
          <strong>Weggelassen</strong> sind Namen der Personen des Archivs (sie haben eigene
          Profile), Grußformeln, Wochentage und Monate, dazu Zahlen, Adressen und Links. Die Liste
          der weggelassenen Wörter steht in themes.toml und lässt sich ergänzen.
        </p>
        <p>
          <strong>Ein Thema</strong> sind Wörter, die oft in denselben Mails zusammen stehen,
          gefunden im ganzen Archiv ohne Vorgabe.
        </p>
        <p>
          <strong>Ein farbiger Punkt</strong> markiert ein Wort aus dem Wortfeld eines
          Recherchethemas.
        </p>
        <p>
          <strong>So suchen Sie damit:</strong> Ein Klick auf ein Wort öffnet seine Mails. In der
          Suche verbindet „or“ mehrere Wörter, etwa{" "}
          <code className={styles.example}>Spende or Barzahlung</code>. Die Zeitachse vergleicht
          Wörter über die Zeit. Ein Wort zeigt eine Stelle zum Nachlesen; was dort steht, zeigen die
          Mails.
        </p>
      </div>
    </details>
  );
}
