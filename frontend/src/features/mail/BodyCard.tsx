import { useMemo, useState, type ReactNode, type Ref } from "react";

import { useMailBody } from "../../api/queries";
import type { MailHeaders, MailRaw, MailText } from "../../api/types";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { ErrorState } from "../../components/ErrorState";
import { MarkedParts, markWords, type SearchMarks } from "../../components/Highlighted";
import { Spinner } from "../../components/Spinner";
import { Tabs, tabPanelProps, type TabItem } from "../../components/Tabs";
import { formatBytes, formatNumber } from "../../lib/format";
import { markCount } from "../../lib/highlight";
import { splitQuoted } from "../../lib/quote";
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

function TextView({ data, marks }: { data: MailText; marks?: SearchMarks }) {
  // null: as the hits suggest, open when only the quoted part holds a search word
  const [showQuoted, setShowQuoted] = useState<boolean | null>(null);
  const split = useMemo(() => splitQuoted(data.text), [data.text]);
  const parts = useMemo(() => {
    const mark = (text: string) => markWords(text, marks);
    return split
      ? { body: mark(split.body), quoted: mark(split.quoted) }
      : { body: mark(data.text), quoted: [] };
  }, [data.text, split, marks]);
  if (data.source === "none" || !data.text.trim()) {
    return <p className={styles.note}>Diese Mail enthält keinen Text.</p>;
  }
  const inBody = markCount(parts.body);
  const inQuoted = markCount(parts.quoted);
  const open = showQuoted ?? (inBody === 0 && inQuoted > 0);
  return (
    <>
      {(data.source === "text/html" || inBody + inQuoted > 0) && (
        <p className={styles.note}>
          {data.source === "text/html" && "aus HTML umgewandelt"}
          {data.source === "text/html" && inBody + inQuoted > 0 && " · "}
          {inBody + inQuoted > 0 && `${places(inBody + inQuoted)} markiert`}
        </p>
      )}
      <div className={styles.text}>
        <MarkedParts parts={parts.body} />
      </div>
      {split && (
        <>
          <div className={styles.quoteToggle}>
            <button
              type="button"
              className={styles.linkButton}
              aria-expanded={open}
              onClick={() => setShowQuoted(!open)}
            >
              {open
                ? "Zitierten Verlauf ausblenden"
                : `Zitierten Verlauf einblenden (${formatNumber(split.quotedLines)} Zeilen${
                    inQuoted > 0 ? `, ${places(inQuoted)}` : ""
                  })`}
            </button>
          </div>
          {open && (
            <div className={`${styles.text} ${styles.quoted}`}>
              <MarkedParts parts={parts.quoted} />
            </div>
          )}
        </>
      )}
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
