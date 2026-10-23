import { useSearchParams } from "react-router";

import { useResearch } from "../../api/queries";
import { Button } from "../../components/Button";
import { ErrorState } from "../../components/ErrorState";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps, type TabItem } from "../../components/Tabs";
import { formatNumber } from "../../lib/format";
import styles from "./AktenScreen.module.css";
import { CollectionList } from "./CollectionList";
import { ExportList } from "./ExportList";
import { NoteList } from "./NoteList";
import { SearchList } from "./SearchList";
import { TagList } from "./TagList";
import { ThemeList } from "./ThemeList";

type AktenTab = "akten" | "themen" | "suchen" | "schlagworte" | "notizen" | "exporte";

const TAB_LABELS: Record<AktenTab, string> = {
  akten: "Akten",
  themen: "Themen",
  suchen: "Gespeicherte Suchen",
  schlagworte: "Schlagworte",
  notizen: "Notizen",
  exporte: "Exporte",
};
const TABS = Object.keys(TAB_LABELS) as AktenTab[];
const TABS_ID = "akten";

/** The tab of a query string: ?tab=…, "akten" when missing or unknown. */
function parseAktenTab(search: URLSearchParams): AktenTab {
  return TABS.find((tab) => tab === search.get("tab")) ?? "akten";
}

/** /akten: the research file at a glance (D57 to D64). One tab per kind of entry, the tab in
 *  the URL, so each list stays short, a tab can be linked and Back returns to it. */
export function AktenScreen() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = parseAktenTab(searchParams);
  const research = useResearch();
  const data = research.data;

  const counts: Partial<Record<AktenTab, number>> = data
    ? {
        akten: data.collections.length,
        suchen: data.searches.length,
        schlagworte: data.tags.length,
        notizen: data.notes,
      }
    : {};
  const items: TabItem<AktenTab>[] = TABS.map((id) => {
    const count = counts[id];
    const label = TAB_LABELS[id];
    return { id, label: count === undefined ? label : `${label} ${formatNumber(count)}` };
  });

  return (
    <div className={styles.page}>
      <title>
        {tab === "akten" ? "Akten · Mailrobbe" : `${TAB_LABELS[tab]} · Akten · Mailrobbe`}
      </title>
      <div className={styles.head}>
        <h1 className={styles.title}>Akten</h1>
        {data && (
          <span className={styles.total}>
            {formatNumber(data.review.relevant)} relevant · {formatNumber(data.flagged)} markiert ·{" "}
            {formatNumber(data.review.seen + data.review.relevant + data.review.irrelevant)}{" "}
            gesichtet
          </span>
        )}
      </div>
      <div className={styles.tabs}>
        <Tabs<AktenTab>
          items={items}
          active={tab}
          onSelect={(next) =>
            setSearchParams(next === "akten" ? {} : { tab: next }, { preventScrollReset: true })
          }
          idPrefix={TABS_ID}
          label="Bereiche der Rechercheakte"
        />
      </div>

      <div {...tabPanelProps(TABS_ID, tab)} className={styles.panel}>
        {tab === "notizen" ? (
          <NoteList />
        ) : tab === "exporte" ? (
          <ExportList />
        ) : research.isPending ? (
          <div className={styles.loading}>
            <Spinner label="Rechercheakte wird geladen" />
          </div>
        ) : research.isError ? (
          <div>
            <ErrorState
              title="Die Rechercheakte konnte nicht geladen werden."
              actions={<Button onClick={() => void research.refetch()}>Erneut versuchen</Button>}
            >
              Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
            </ErrorState>
          </div>
        ) : tab === "themen" ? (
          <ThemeList starterMissing={research.data.starter_missing} />
        ) : tab === "suchen" ? (
          <SearchList searches={research.data.searches} collections={research.data.collections} />
        ) : tab === "schlagworte" ? (
          <TagList tags={research.data.tags} />
        ) : (
          <CollectionList collections={research.data.collections} />
        )}
      </div>
    </div>
  );
}
