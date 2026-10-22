import { useMemo, type MouseEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { useBlockPage, useBlockSummary } from "../../api/queries";
import type { BlockInfo, BlockPage, BlockSummary } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { SearchIcon } from "../../components/icons";
import { Pagination, type PaginationProps } from "../../components/Pagination";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatDateTime, formatNumber } from "../../lib/format";
import { pageCount, rangeText } from "../../lib/paging";
import { DebouncedInput } from "../documents/DebouncedInput";
import { HiddenTabs } from "../hiding/HiddenTabs";
import { periodText } from "../keys/labels";
import { PENDING_TEXT } from "./choice";
import styles from "./BlocksPage.module.css";
import { firstLines, mailsText } from "./labels";
import {
  BLOCK_STATES,
  blockListHref,
  blockListSearch,
  blockPath,
  parseBlockListState,
  toBlockListParams,
  type BlockListState,
} from "./urlState";

const STATE_LABELS = { standard: "Standardblöcke", dismissed: "Zurückgenommen" } as const;

const blockCount = (count: number) => `${formatNumber(count)} ${count === 1 ? "Block" : "Blöcke"}`;

/** "Ausgeblendet · Standardblöcke" (D227): the figures of the last blocks step, the blocks with
 *  their text, mails, senders and period, those taken back on a tab of their own. */
export function BlocksPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = useMemo(() => parseBlockListState(searchParams), [searchParams]);
  const summary = useBlockSummary();
  const page = useBlockPage(toBlockListParams(state));

  const setState = (next: BlockListState) =>
    setSearchParams(blockListSearch(next), { preventScrollReset: true });
  // Typing replaces the entry instead of adding one per pause; the latest URL is the base, as
  // the timer fires after the render that started it.
  const search = (q: string) =>
    setSearchParams((current) => blockListSearch({ ...parseBlockListState(current), q, page: 1 }), {
      replace: true,
      preventScrollReset: true,
    });

  return (
    <main className={styles.page}>
      <title>Standardblöcke · Mailrobbe</title>
      <HiddenTabs />
      <p className={styles.lead}>
        Absätze, die in vielen Mails gleich am Ende stehen: Signaturen, Rechtshinweise, Werbezeilen.
        Die Suche lässt sie aus, das Mail-Detail zeigt sie eingeklappt. Im Mail-Detail lässt sich
        jeder Absatz von Hand als Standardblock markieren oder zurücknehmen.
      </p>
      {summary.data && <Figures summary={summary.data} />}

      <div className={styles.toolbar}>
        <div role="group" aria-label="Anzeigen" className={styles.segments}>
          {BLOCK_STATES.map((shown) => (
            <button
              key={shown}
              type="button"
              aria-pressed={state.state === shown}
              className={cx(styles.segment, state.state === shown && styles.active)}
              onClick={() => setState({ ...state, state: shown, page: 1 })}
            >
              {STATE_LABELS[shown]}
            </button>
          ))}
        </div>
        <div className={styles.search}>
          <SearchIcon className={styles.searchIcon} />
          <label htmlFor="block-search" className="sr-only">
            Block suchen
          </label>
          <DebouncedInput
            id="block-search"
            type="search"
            className={styles.searchInput}
            placeholder="Text des Blocks, auch Teil davon …"
            value={state.q}
            onCommit={search}
          />
        </div>
        <label htmlFor="block-sort" className="sr-only">
          Sortierung
        </label>
        <select
          id="block-sort"
          className={styles.sort}
          value={state.sort}
          onChange={(event) =>
            setState({ ...state, sort: event.target.value as BlockListState["sort"], page: 1 })
          }
        >
          <option value="mails">Meiste Mails</option>
          <option value="recent">Zuletzt verwendet</option>
        </select>
        {page.data && (
          <span className={styles.total} aria-live="polite">
            {state.q ? `${blockCount(page.data.total)} gefunden` : blockCount(page.data.total)}
          </span>
        )}
      </div>

      <Card className={styles.tableCard}>
        {page.isPending ? (
          <div className={styles.loading}>
            <Spinner label="Standardblöcke werden geladen" />
          </div>
        ) : page.isError ? (
          <ErrorState
            title="Die Standardblöcke konnten nicht geladen werden."
            actions={<Button onClick={() => void page.refetch()}>Erneut versuchen</Button>}
          >
            Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
          </ErrorState>
        ) : page.data.items.length === 0 ? (
          <EmptyList state={state} total={page.data.total} summary={summary.data} />
        ) : (
          <BlockTable items={page.data.items} stale={page.isPlaceholderData} />
        )}
      </Card>

      {page.data && page.data.items.length > 0 && (
        <Pagination {...blockPagination(state, page.data)} />
      )}
    </main>
  );
}

/** The figures of the last blocks step, and what the next run will do. */
function Figures({ summary }: { summary: BlockSummary }) {
  const computed = summary.computed_at;
  const tiles = [
    {
      label: "Standardblöcke",
      value: formatNumber(summary.blocks),
      sub: `${formatNumber(summary.detected)} erkannt · ${formatNumber(summary.marked)} von Hand`,
    },
    {
      label: "Zurückgenommen",
      value: formatNumber(summary.dismissed),
      sub: "erkannt, aber kein Standardblock",
    },
    {
      label: "Mails mit Standardblock",
      value: formatNumber(summary.mails),
      sub: "ohne Duplikate",
    },
    {
      label: "Schwelle",
      value: `ab ${mailsText(summary.min_mails)}`,
      sub: "am Ende der Mails, Absender mehrfach",
    },
    {
      label: "Berechnet",
      value: computed ? formatDateTime(computed) : "noch nie",
      sub:
        summary.waiting > 0
          ? `${mailsText(summary.waiting)} noch nicht zerlegt`
          : "alle Mails in Absätze zerlegt",
    },
  ];
  const later = [
    summary.pending > 0 &&
      `${formatNumber(summary.pending)} ${
        summary.pending === 1 ? "Entscheidung wirkt" : "Entscheidungen wirken"
      } beim nächsten Lauf.`,
    summary.waiting > 0 &&
      `${mailsText(summary.waiting)} ${
        summary.waiting === 1 ? "ist" : "sind"
      } noch nicht in Absätze zerlegt.`,
  ].filter(Boolean);
  return (
    <>
      <ul className={styles.tiles} aria-label="Zahlen des letzten Laufs">
        {tiles.map((tile) => (
          <li key={tile.label} className={styles.tile}>
            <span className={styles.tileLabel}>{tile.label}</span>
            <span className={styles.tileValue}>{tile.value}</span>
            <span className={styles.tileSub}>{tile.sub}</span>
          </li>
        ))}
      </ul>
      {later.length > 0 && (
        <p className={styles.pending} role="status">
          {later.join(" ")} „Import starten“ führt die Schritte aus; es liest nur die Datenbank.{" "}
          <Link to="/import">Zum Import</Link>
        </p>
      )}
    </>
  );
}

/** "1–50 von 178" */
/** The list pages by offset and knows its total, so every page has its number (D193). */
function blockPagination(state: BlockListState, page: BlockPage): PaginationProps {
  const total = { count: page.total, exact: true };
  const { pages } = pageCount(total, state.limit);
  const at = (number: number) => blockListHref({ ...state, page: number });
  return {
    range: rangeText(state.page, false, state.limit, page.items.length, total),
    prev: state.page > 1 ? at(state.page - 1) : null,
    next: state.page < pages ? at(state.page + 1) : null,
    first: state.page > 1 ? at(1) : null,
    last: state.page < pages ? at(pages) : null,
    numbers: { current: state.page, pages, more: false, href: at },
    size: { limit: state.limit, href: (limit) => blockListHref({ ...state, page: 1, limit }) },
  };
}

function EmptyList({
  state,
  total,
  summary,
}: {
  state: BlockListState;
  total: number;
  summary: BlockSummary | undefined;
}) {
  if (state.page > 1 && total > 0) {
    return (
      <EmptyState
        title="Diese Seite gibt es nicht mehr."
        actions={
          <Link to={blockListHref({ ...state, page: 1 })} className={buttonClass()}>
            Zur ersten Seite
          </Link>
        }
      />
    );
  }
  if (state.q) {
    return (
      <EmptyState
        title="Kein Block gefunden"
        actions={
          <Link to={blockListHref({ ...state, q: "", page: 1 })} className={buttonClass()}>
            Suche leeren
          </Link>
        }
      >
        {`Kein Block enthält „${state.q}“.`}
      </EmptyState>
    );
  }
  if (summary && summary.computed_at === null) {
    return (
      <EmptyState
        title="Noch keine Standardblöcke berechnet"
        actions={
          <Link to="/import" className={buttonClass()}>
            Zum Import
          </Link>
        }
      >
        Der nächste Lauf von „Import starten“ zerlegt die Mails in Absätze und sucht danach die
        Standardblöcke; er liest dafür nur die Datenbank.
      </EmptyState>
    );
  }
  if (state.state === "dismissed") {
    return (
      <EmptyState title="Kein Block zurückgenommen">
        Ein erkannter Block, den das Team mit „Kein Standardblock“ zurücknimmt, steht hier und lässt
        sich auf seiner Seite wiederherstellen.
      </EmptyState>
    );
  }
  return (
    <EmptyState title="Keine Standardblöcke gefunden">
      {summary ? `Kein Absatz steht am Ende von mindestens ${mailsText(summary.min_mails)}. ` : ""}
      Im Mail-Detail lässt sich jeder Absatz von Hand als Standardblock markieren.
    </EmptyState>
  );
}

function BlockTable({ items, stale }: { items: BlockInfo[]; stale: boolean }) {
  const navigate = useNavigate();

  function openRow(event: MouseEvent<HTMLTableRowElement>, hash: string) {
    const target = event.target as HTMLElement;
    if (target.closest("a, button, input, label") || window.getSelection()?.toString()) return;
    void navigate(blockPath(hash));
  }

  return (
    <div className={styles.scroll}>
      <table className={cx(styles.table, stale && styles.stale)}>
        <thead>
          <tr>
            <th>Block</th>
            <th className={styles.num}>Mails</th>
            <th className={styles.num}>Absender</th>
            <th>Zeitraum</th>
          </tr>
        </thead>
        <tbody>
          {items.map((block) => (
            <tr key={block.hash} onClick={(event) => openRow(event, block.hash)}>
              <td className={styles.blockCell}>
                <Link to={blockPath(block.hash)} className={styles.sample}>
                  {firstLines(block.sample)}
                </Link>
                {(!block.detected || block.pending) && (
                  <span className={styles.badges}>
                    {!block.detected && <span className={styles.badge}>von Hand</span>}
                    {block.pending && (
                      <span className={cx(styles.badge, styles.pendingBadge)}>{PENDING_TEXT}</span>
                    )}
                  </span>
                )}
              </td>
              <td className={cx(styles.num, styles.strong)}>{formatNumber(block.mails)}</td>
              <td className={styles.num}>{formatNumber(block.senders)}</td>
              <td className={styles.muted}>{periodText(block.first_date, block.last_date)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
