import { Fragment, useMemo, useState, type ReactNode, type Ref } from "react";
import { Link } from "react-router";

import { useMailBody, useSaveBlockOverride } from "../../api/queries";
import type {
  BlockInfo,
  MailHeaders,
  MailRaw,
  MailText,
  SegmentKind,
  TextParagraph,
  TextSegment,
} from "../../api/types";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { ErrorState } from "../../components/ErrorState";
import { MarkedParts, markWords, type SearchMarks } from "../../components/Highlighted";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps, type TabItem } from "../../components/Tabs";
import { formatBytes, formatNumber } from "../../lib/format";
import { markCount, type TextPart } from "../../lib/highlight";
import {
  blockStanding,
  paragraphStanding,
  useEditorOnce,
  type BlockStanding,
} from "../blocks/choice";
import { mailsText } from "../blocks/labels";
import { blockPath } from "../blocks/urlState";
import styles from "./BodyCard.module.css";
import { sourceErrorText } from "./errors";
import { MenuParagraph, PendingNote } from "./ParagraphMenu";

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
      label: "HTML",
      disabled: !hasHtml,
      title: text.data && !hasHtml ? "Diese Mail hat keinen HTML-Teil." : undefined,
    },
    { id: "headers", label: "Alle Header" },
    { id: "raw", label: "Rohmail" },
  ];

  return (
    <Card ref={ref} className={styles.card} aria-label="Inhalt">
      <Tabs items={tabs} active={tab} onSelect={onTab} idPrefix={ID_PREFIX} label="Ansicht" />
      <div {...tabPanelProps(ID_PREFIX, tab)} className={styles.panel}>
        {tab === "text" && (
          <Loaded query={text}>
            {(data) => (
              <div className={styles.textScroll}>
                <TextView data={data} marks={marks} />
              </div>
            )}
          </Loaded>
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
  standard: "Standardblock",
};

/** A stretch of a block's text: the own words, or what is quoted (shown muted); a paragraph that
 *  counts (D224) is a stretch of its own, with the paragraph menu at its start. */
interface Run {
  quoted: boolean;
  parts: TextPart[];
  paragraph: TextParagraph | null;
  sample: string; // the paragraph as shown, which a choice of the team sends
}

/** What the text view shows, in order: the segments between the folded ones together as written
 *  (fold null), or a segment that starts folded. A folded quote, original, forward or signature
 *  holds the standard blocks cut out of it (D227), each folded again inside it. */
interface Block {
  fold: FoldKind | null;
  lines: number; // of a folded segment, the standard blocks inside it included
  hash: string | null; // of a standard block
  items: (Run | Block)[];
}

const isBlock = (item: Run | Block): item is Block => "items" in item;

/** A block's items before the search words are marked. */
interface Piece {
  quoted: boolean;
  text: string;
  paragraph: TextParagraph | null;
  sample: string;
}

interface Draft {
  fold: FoldKind | null;
  lines: number;
  hash: string | null;
  items: (Piece | Draft)[];
}

const isDraft = (item: Piece | Draft): item is Draft => "items" in item;

/** The blocks the text view shows: each segment that starts folded on its own with the standard
 *  blocks cut out of it, a standard block of the open text on its own, the segments between them
 *  together as written. Blank lines at the ends of a block and beside a fold inside it are left
 *  out, three or more in a row are one. Without segments the text is one block. */
function textBlocks(
  text: string,
  segments: TextSegment[],
  paragraphs: TextParagraph[],
  mark: (shown: string) => TextPart[],
): Block[] {
  if (!segments.length) {
    const run = {
      quoted: false,
      parts: mark(fewerBlankLines(text.trimEnd())),
      paragraph: null,
      sample: "",
    };
    return [{ fold: null, lines: 0, hash: null, items: [run] }];
  }
  // The server counts characters as Python does, in code points; JavaScript counts UTF-16 units,
  // which differ after a character beyond the BMP, such as an emoji.
  const chars = /[\uD800-\uDFFF]/.test(text) ? Array.from(text) : null;
  const slice = (start: number, end: number) =>
    chars ? chars.slice(start, end).join("") : text.slice(start, end);
  let next = 0; // the first paragraph not placed yet; both lists are in text order
  const piecesOf = (segment: TextSegment, quoted: boolean): Piece[] => {
    const pieces: Piece[] = [];
    let position = segment.start;
    while (next < paragraphs.length && paragraphs[next].start < segment.end) {
      const paragraph = paragraphs[next++];
      if (paragraph.start < position) continue;
      if (paragraph.start > position) {
        pieces.push({
          quoted,
          text: slice(position, paragraph.start),
          paragraph: null,
          sample: "",
        });
      }
      const end = Math.min(paragraph.end, segment.end);
      const sample = slice(paragraph.start, paragraph.end);
      pieces.push({ quoted, text: slice(paragraph.start, end), paragraph, sample });
      position = end;
    }
    if (position < segment.end) {
      pieces.push({ quoted, text: slice(position, segment.end), paragraph: null, sample: "" });
    }
    return pieces;
  };

  const drafts: Draft[] = [];
  let open: Piece[] = [];
  let group: Draft | null = null; // the folded segment a standard block after it may belong to
  let cut = false; // the group ends in a standard block, so a piece of its kind continues it
  const flush = () => {
    if (open.length) drafts.push({ fold: null, lines: 0, hash: null, items: open });
    open = [];
  };
  for (const segment of segments) {
    if (segment.kind === "standard") {
      const hash = segment.block ?? null;
      const inner = {
        fold: segment.kind,
        lines: segment.lines,
        hash,
        items: piecesOf(segment, true),
      };
      // A quote's own paragraphs are quoted lines; anything else after it is the own text.
      if (group && (group.fold !== "quote" || /^\s*>/.test(slice(segment.start, segment.end)))) {
        group.items.push(inner);
        group.lines += segment.lines;
        cut = true;
      } else {
        flush();
        group = null;
        drafts.push(inner);
      }
      continue;
    }
    if (segment.kind !== "text" && segment.folded) {
      if (group && cut && group.fold === segment.kind) {
        group.items.push(...piecesOf(segment, true));
        group.lines += segment.lines;
      } else {
        flush();
        group = {
          fold: segment.kind,
          lines: segment.lines,
          hash: null,
          items: piecesOf(segment, true),
        };
        drafts.push(group);
      }
      cut = false;
      continue;
    }
    group = null;
    cut = false;
    // Open, only a quote is muted: a forward that is the whole text is the content.
    open.push(...piecesOf(segment, segment.kind === "quote"));
  }
  flush();

  const finish = (draft: Draft): Block | null => {
    const items: (Run | Block)[] = [];
    for (const item of tidy(draft.items)) {
      if (isDraft(item)) {
        const inner = finish(item);
        if (inner) items.push(inner);
      } else {
        const { quoted, paragraph, sample } = item;
        items.push({ quoted, parts: mark(fewerBlankLines(item.text)), paragraph, sample });
      }
    }
    return items.length ? { fold: draft.fold, lines: draft.lines, hash: draft.hash, items } : null;
  };
  return drafts.map(finish).filter((block) => block !== null);
}

// three or more blank lines in a row; a line of nothing but white space counts as blank
const BLANK_LINES = /\r?\n(?:[^\S\r\n]*\r?\n){3,}/g;

/** text with every run of three or more blank lines shown as one; only the view, the offsets,
 *  the paragraphs and their samples keep the text as written. A run never crosses two pieces,
 *  since a blank line belongs to the segment above it and a paragraph ends before its line
 *  break. */
const fewerBlankLines = (text: string) => text.replace(BLANK_LINES, "\n\n");

/** items without blank pieces at the ends, and without the blank lines of a piece at the
 *  block's ends or beside a fold inside it. */
function tidy(items: (Piece | Draft)[]): (Piece | Draft)[] {
  const blank = (item: Piece | Draft) => !isDraft(item) && !item.text.trim();
  const kept = [...items];
  while (kept.length && blank(kept[0])) kept.shift();
  while (kept.length && blank(kept[kept.length - 1])) kept.pop();
  return kept
    .map((item, index) => {
      if (isDraft(item)) return item;
      let shown = item.text;
      if (index === 0 || isDraft(kept[index - 1])) shown = shown.replace(/^([ \t]*\r?\n)+/, "");
      if (index === kept.length - 1 || isDraft(kept[index + 1])) shown = shown.trimEnd();
      return { ...item, text: shown };
    })
    .filter((item) => isDraft(item) || item.text);
}

/** The search words marked in a block, the folds inside it included. */
function hitsOf(block: Block): number {
  return block.items.reduce(
    (sum, item) => sum + (isBlock(item) ? hitsOf(item) : markCount(item.parts)),
    0,
  );
}

/** A block's items as the text view lays them out: the runs between two folds together. */
function layout(items: (Run | Block)[]): (Run[] | Block)[] {
  const laid: (Run[] | Block)[] = [];
  for (const item of items) {
    const last = laid[laid.length - 1];
    if (isBlock(item)) laid.push(item);
    else if (Array.isArray(last)) last.push(item);
    else laid.push([item]);
  }
  return laid;
}

/** What the parts of the text view share: the folds opened or closed by hand, and the team's
 *  choice about each paragraph. */
interface View {
  toggled: Record<string, boolean>;
  toggle: (place: string, open: boolean) => void;
  paragraph: (hash: string) => TextParagraph | undefined;
  standing: (paragraph: TextParagraph) => BlockStanding;
  busy: (hash: string) => boolean;
  failed: (hash: string) => boolean;
  choose: (run: Run, standard: boolean) => void;
}

/** A block's text, its quoted runs muted, each paragraph with its menu; noted: the fold around
 *  it tells a pending choice already. */
function BlockText({ runs, view, noted }: { runs: Run[]; view: View; noted: boolean }) {
  return runs.map((run, index) => {
    const content = <MarkedParts parts={run.parts} />;
    const { paragraph } = run;
    const shown = paragraph ? (
      <MenuParagraph
        paragraph={paragraph}
        standing={view.standing(paragraph)}
        busy={view.busy(paragraph.hash)}
        failed={view.failed(paragraph.hash)}
        noted={noted}
        onChoose={(standard) => view.choose(run, standard)}
      >
        {content}
      </MenuParagraph>
    ) : (
      content
    );
    return run.quoted ? (
      <span key={index} className={styles.quoted}>
        {shown}
      </span>
    ) : (
      <Fragment key={index}>{shown}</Fragment>
    );
  });
}

/** A block's items: its text and the folds inside it, place naming each fold. */
function BlockItems({
  items,
  place,
  view,
  noted = false,
}: {
  items: (Run | Block)[];
  place: string;
  view: View;
  noted?: boolean;
}) {
  return layout(items).map((laid, index) =>
    Array.isArray(laid) ? (
      <div key={index} className={styles.text}>
        <BlockText runs={laid} view={view} noted={noted} />
      </div>
    ) : laid.fold === null ? null : (
      <Fold key={index} fold={laid.fold} block={laid} place={`${place}.${index}`} view={view} />
    ),
  );
}

/** A segment that starts folded (D151) with its toggle; a standard block's toggle leads to its
 *  page and tells a pending choice (D227). A fold holding a search word opens itself (D79). */
function Fold({
  fold,
  block,
  place,
  view,
}: {
  fold: FoldKind;
  block: Block;
  place: string;
  view: View;
}) {
  const hits = hitsOf(block);
  const open = view.toggled[place] ?? hits > 0;
  const counts = lineCount(block.lines) + (hits > 0 ? `, ${places(hits)}` : "");
  const paragraph = block.hash === null ? undefined : view.paragraph(block.hash);
  const standing = paragraph && view.standing(paragraph);
  return (
    <div className={styles.fold}>
      <div className={styles.quoteToggle}>
        <button
          type="button"
          className={styles.linkButton}
          aria-expanded={open}
          onClick={() => view.toggle(place, open)}
        >
          {`${FOLD_LABELS[fold]} ${open ? "ausblenden" : "einblenden"} (${counts})`}
        </button>
        {block.hash !== null && (
          <>
            <span aria-hidden="true">{" · "}</span>
            <Link to={blockPath(block.hash)} className={styles.blockLink}>
              {standing && standing.mails > 0 ? `in ${mailsText(standing.mails)}` : "zum Block"}
            </Link>
          </>
        )}
        {standing?.pending && <PendingNote expected={standing.expected} />}
      </div>
      {open && (
        <BlockItems items={block.items} place={place} view={view} noted={block.hash !== null} />
      )}
    </div>
  );
}

/** The text with quotes, originals, forwards, signatures and standard blocks folded as the
 *  server's segments say (D151, D227); a folded block holding a search word opens itself (D79).
 *  Every paragraph can be marked as a standard block or taken back (D225). */
export function TextView({ data, marks }: { data: MailText; marks?: SearchMarks }) {
  // the folds opened or closed by hand, by their place ("2", "2.1" for one inside it); the
  // others as the hits suggest
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  // the answers to the choices made here, which know what the text's paragraphs do not
  const [answers, setAnswers] = useState<Record<string, BlockInfo>>({});
  const save = useSaveBlockOverride();
  const editor = useEditorOnce();
  const blocks = useMemo(() => {
    const mark = (text: string) => markWords(text, marks);
    return textBlocks(data.text, data.segments, data.paragraphs ?? [], mark);
  }, [data.text, data.segments, data.paragraphs, marks]);
  const known = useMemo(
    () => new Map((data.paragraphs ?? []).map((paragraph) => [paragraph.hash, paragraph])),
    [data.paragraphs],
  );
  if (data.source === "none" || !data.text.trim()) {
    return <p className={styles.note}>Diese Mail enthält keinen Text.</p>;
  }
  const total = blocks.reduce((sum, block) => sum + hitsOf(block), 0);
  const saving = (hash: string) => save.variables?.hash === hash;
  const view: View = {
    toggled,
    toggle: (place, open) => setToggled({ ...toggled, [place]: !open }),
    paragraph: (hash) => known.get(hash),
    standing: (paragraph) => {
      const answer = answers[paragraph.hash];
      return answer ? blockStanding(answer) : paragraphStanding(paragraph);
    },
    busy: (hash) => save.isPending && saving(hash),
    failed: (hash) => save.isError && saving(hash),
    choose: (run, standard) => {
      const { paragraph, sample } = run;
      if (!paragraph) return;
      editor.run(() =>
        save.mutate(
          { hash: paragraph.hash, standard, sample },
          { onSuccess: (block) => setAnswers((current) => ({ ...current, [block.hash]: block })) },
        ),
      );
    },
  };
  return (
    <>
      {(data.source === "text/html" || total > 0) && (
        <p className={styles.note}>
          {data.source === "text/html" && "aus HTML umgewandelt"}
          {data.source === "text/html" && total > 0 && " · "}
          {total > 0 && `${places(total)} markiert`}
        </p>
      )}
      {blocks.map((block, index) =>
        block.fold === null ? (
          <BlockItems key={index} items={block.items} place={String(index)} view={view} />
        ) : (
          <Fold key={index} fold={block.fold} block={block} place={String(index)} view={view} />
        ),
      )}
      {data.truncated && (
        <p className={styles.note}>
          Der Text ist sehr lang und hier gekürzt; die EML-Datei enthält ihn vollständig.
        </p>
      )}
      {editor.dialog}
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
