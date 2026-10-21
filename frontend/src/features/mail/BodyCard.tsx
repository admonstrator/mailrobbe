import { useMemo, useState, type ReactNode, type Ref } from "react";

import { useMailBody } from "../../api/queries";
import type { MailHeaders, MailRaw, MailText, SegmentKind, TextSegment } from "../../api/types";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { ErrorState } from "../../components/ErrorState";
import { MarkedParts, markWords, type SearchMarks } from "../../components/Highlighted";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps, type TabItem } from "../../components/Tabs";
import { formatBytes, formatNumber } from "../../lib/format";
import { markCount, type TextPart } from "../../lib/highlight";
import styles from "./BodyCard.module.css";
import { sourceErrorText } from "./errors";

export type BodyTab = "text" | "html" | "headers" | "raw";

const ID_PREFIX = "body";

/** The mail's content in four views, each read from the MBOX file when first opened (D22); the
 *  text view marks the search words (D79). */
export function BodyCard({
  mailId,
  tab,
  onTab,
  marks,
  ref,
}: {
  mailId: number;
  tab: BodyTab;
  onTab: (tab: BodyTab) => void;
  marks?: SearchMarks;
  ref?: Ref<HTMLElement>;
}) {
  // The text view is the default, and it tells whether there is an HTML part to show.
  const text = useMailBody(mailId, "text", true);
  const headers = useMailBody(mailId, "headers", tab === "headers");
  const raw = useMailBody(mailId, "raw", tab === "raw");
  const hasHtml = text.data?.has_html ?? false;

  const tabs: TabItem<BodyTab>[] = [
    { id: "text", label: "Text" },
    {
      id: "html",
      label: "HTML (sandboxed)",
      disabled: !hasHtml,
      title: text.data && !hasHtml ? "Diese Mail hat keinen HTML-Teil." : undefined,
    },
    { id: "headers", label: "Alle Header" },
    { id: "raw", label: "Rohmail" },
  ];

  return (
    <Card ref={ref} className={styles.card} aria-label="Inhalt">
      <Tabs
        items={tabs}
        active={tab}
        onSelect={onTab}
        idPrefix={ID_PREFIX}
        label="Ansicht"
        end="Body wird on-demand aus der MBOX gelesen"
      />
      <div {...tabPanelProps(ID_PREFIX, tab)} className={styles.panel}>
        {tab === "text" && (
          <Loaded query={text}>{(data) => <TextView data={data} marks={marks} />}</Loaded>
        )}
        {tab === "html" && (
          <iframe
            className={styles.html}
            title="HTML-Ansicht der Mail"
            sandbox=""
            referrerPolicy="no-referrer"
            src={`/api/mails/${mailId}/body?format=html`}
          />
        )}
        {tab === "headers" && (
          <Loaded query={headers}>{(data) => <HeaderTable data={data} />}</Loaded>
        )}
        {tab === "raw" && (
          <Loaded query={raw}>{(data) => <RawView data={data} mailId={mailId} />}</Loaded>
        )}
      </div>
    </Card>
  );
}

/** Spinner, the source error, or the loaded view. */
function Loaded<T>({
  query,
  children,
}: {
  query: { data: T | undefined; error: Error | null; refetch: () => unknown };
  children: (data: T) => ReactNode;
}) {
  if (query.data !== undefined) return children(query.data);
  if (query.error) {
    return (
      <ErrorState
        title={sourceErrorText(query.error)}
        actions={<Button onClick={() => void query.refetch()}>Erneut versuchen</Button>}
      />
    );
  }
  return (
    <div className={styles.loading}>
      <Spinner label="Wird aus der MBOX-Datei gelesen" />
    </div>
  );
}

const places = (count: number) =>
  count === 1 ? "1 Fundstelle" : `${formatNumber(count)} Fundstellen`;

const lineCount = (count: number) => (count === 1 ? "1 Zeile" : `${formatNumber(count)} Zeilen`);

type FoldKind = Exclude<SegmentKind, "text">;

/** The name of each kind of segment that can start folded (D151), on its toggle. */
const FOLD_LABELS: Record<FoldKind, string> = {
  quote: "Zitat",
  original: "Ursprüngliche Nachricht",
  forward: "Weitergeleitete Nachricht",
  signature: "Signatur",
};

/** A stretch of a block's text: the own words, or what is quoted (shown muted). */
interface Run {
  quoted: boolean;
  parts: TextPart[];
}

interface Block {
  fold: FoldKind | null; // null: shown as written, the own words and what starts open
  lines: number; // of a folded segment
  runs: Run[];
}

/** The blocks the text view shows: each segment that starts folded on its own, the segments
 *  between them together as written, blank lines at a block's ends left out. Without segments
 *  the text is one block. */
function textBlocks(
  text: string,
  segments: TextSegment[],
  mark: (shown: string) => TextPart[],
): Block[] {
  if (!segments.length) {
    return [{ fold: null, lines: 0, runs: [{ quoted: false, parts: mark(text.trimEnd()) }] }];
  }
  // The server counts characters as Python does, in code points; JavaScript counts UTF-16 units,
  // which differ after a character beyond the BMP, such as an emoji.
  const chars = /[\uD800-\uDFFF]/.test(text) ? Array.from(text) : null;
  const slice = (start: number, end: number) =>
    chars ? chars.slice(start, end).join("") : text.slice(start, end);
  const blocks: Block[] = [];
  const add = (fold: FoldKind | null, lines: number, members: TextSegment[]) => {
    // Open, only a quote is muted: a forward that is the whole text is the content.
    const pieces = members.map((segment) => ({
      quoted: fold !== null || segment.kind === "quote",
      text: slice(segment.start, segment.end),
    }));
    while (pieces.length && !pieces[0].text.trim()) pieces.shift();
    while (pieces.length && !pieces[pieces.length - 1].text.trim()) pieces.pop();
    if (!pieces.length) return;
    pieces[0].text = pieces[0].text.replace(/^([ \t]*\r?\n)+/, "");
    pieces[pieces.length - 1].text = pieces[pieces.length - 1].text.trimEnd();
    const runs = pieces.map(({ quoted, text }) => ({ quoted, parts: mark(text) }));
    blocks.push({ fold, lines, runs });
  };
  let open: TextSegment[] = [];
  for (const segment of segments) {
    if (segment.kind !== "text" && segment.folded) {
      add(null, 0, open);
      open = [];
      add(segment.kind, segment.lines, [segment]);
    } else {
      open.push(segment);
    }
  }
  add(null, 0, open);
  return blocks;
}

/** A block's text, its quoted runs muted. */
function BlockText({ runs }: { runs: Run[] }) {
  return runs.map((run, index) =>
    run.quoted ? (
      <span key={index} className={styles.quoted}>
        <MarkedParts parts={run.parts} />
      </span>
    ) : (
      <MarkedParts key={index} parts={run.parts} />
    ),
  );
}

/** The text with quotes, originals, forwards and signatures folded as the server's segments say
 *  (D151); a folded block holding a search word opens itself (D79). */
function TextView({ data, marks }: { data: MailText; marks?: SearchMarks }) {
  // the blocks opened or closed by hand, by index; the others as the hits suggest
  const [toggled, setToggled] = useState<Record<number, boolean>>({});
  const blocks = useMemo(() => {
    const mark = (text: string) => markWords(text, marks);
    return textBlocks(data.text, data.segments, mark);
  }, [data.text, data.segments, marks]);
  if (data.source === "none" || !data.text.trim()) {
    return <p className={styles.note}>Diese Mail enthält keinen Text.</p>;
  }
  const hits = blocks.map((block) =>
    block.runs.reduce((sum, run) => sum + markCount(run.parts), 0),
  );
  const total = hits.reduce((sum, count) => sum + count, 0);
  return (
    <>
      {(data.source === "text/html" || total > 0) && (
        <p className={styles.note}>
          {data.source === "text/html" && "aus HTML umgewandelt"}
          {data.source === "text/html" && total > 0 && " · "}
          {total > 0 && `${places(total)} markiert`}
        </p>
      )}
      {blocks.map(({ fold, lines, runs }, index) => {
        if (fold === null) {
          return (
            <div key={index} className={styles.text}>
              <BlockText runs={runs} />
            </div>
          );
        }
        const open = toggled[index] ?? hits[index] > 0;
        const counts = lineCount(lines) + (hits[index] > 0 ? `, ${places(hits[index])}` : "");
        return (
          <div key={index} className={styles.fold}>
            <div className={styles.quoteToggle}>
              <button
                type="button"
                className={styles.linkButton}
                aria-expanded={open}
                onClick={() => setToggled({ ...toggled, [index]: !open })}
              >
                {`${FOLD_LABELS[fold]} ${open ? "ausblenden" : "einblenden"} (${counts})`}
              </button>
            </div>
            {open && (
              <div className={styles.text}>
                <BlockText runs={runs} />
              </div>
            )}
          </div>
        );
      })}
      {data.truncated && (
        <p className={styles.note}>
          Der Text ist sehr lang und hier gekürzt; die EML-Datei enthält ihn vollständig.
        </p>
      )}
    </>
  );
}

function HeaderTable({ data }: { data: MailHeaders }) {
  return (
    <div className={styles.headersScroll}>
      <table className={styles.headers}>
        <tbody>
          {data.headers.map((header, index) => (
            <tr key={index}>
              <th scope="row">{header.name}</th>
              <td>{header.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RawView({ data, mailId }: { data: MailRaw; mailId: number }) {
  return (
    <>
      {data.truncated && (
        <p className={styles.note}>
          Die Mail ist {formatBytes(data.size)} groß und hier gekürzt.{" "}
          <a href={`/api/mails/${mailId}/eml`} download>
            Vollständig als EML herunterladen
          </a>
        </p>
      )}
      <pre className={styles.raw}>{data.raw}</pre>
    </>
  );
}
