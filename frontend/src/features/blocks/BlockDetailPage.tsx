import { useState } from "react";
import { Link, useParams } from "react-router";

import { ApiError } from "../../api/client";
import { useBlock, useSaveBlockOverride } from "../../api/queries";
import {
  BLOCK_HASH_PATTERN,
  BLOCK_SAMPLE_LIMIT,
  type BlockDetail,
  type BlockInfo,
} from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { EditorDialog } from "../../components/EditorDialog";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { PersonLink } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { useEditor } from "../../lib/editor";
import { formatDate, formatNumber } from "../../lib/format";
import { DEFAULT_LIST_STATE, listSearch, withFilters } from "../mails/listState";
import { HiddenTabs } from "../hiding/HiddenTabs";
import { Figures } from "../import/PageHead";
import styles from "./BlockDetailPage.module.css";
import { blockStanding, nextChoice, pendingText, useEditorOnce } from "./choice";
import { mailsText } from "./labels";
import { BLOCKS_PATH, blockMailsHref } from "./urlState";

/** A standard block's page (D227): its whole sample, its figures, the senders and domains that
 *  use it (a sign of who belongs to an organisation), its mails, and the team's choice. */
export function BlockDetailPage() {
  const { hash } = useParams();
  if (!hash || !BLOCK_HASH_PATTERN.test(hash)) {
    return (
      <main className={styles.page}>
        <title>Standardblock · Mailrobbe</title>
        <HiddenTabs />
        <BlockNotFound />
      </main>
    );
  }
  return <BlockView key={hash} hash={hash} />;
}

function BlockView({ hash }: { hash: string }) {
  const detail = useBlock(hash);
  return (
    <main className={styles.page}>
      <title>Standardblock · Mailrobbe</title>
      <HiddenTabs />
      <nav aria-label="Pfad" className={styles.breadcrumb}>
        <Link to={BLOCKS_PATH}>Standardblöcke</Link>
        <span aria-hidden="true">›</span>
        <code className={styles.hash}>{hash}</code>
      </nav>
      {detail.isPending ? (
        <div className={styles.loading}>
          <Spinner label="Standardblock wird geladen" />
        </div>
      ) : detail.isError ? (
        detail.error instanceof ApiError && detail.error.code === "not_found" ? (
          <BlockNotFound />
        ) : (
          <ErrorState
            title="Der Standardblock konnte nicht geladen werden."
            actions={<Button onClick={() => void detail.refetch()}>Erneut versuchen</Button>}
          >
            Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
          </ErrorState>
        )
      ) : (
        <BlockContent detail={detail.data} />
      )}
    </main>
  );
}

function BlockNotFound() {
  return (
    <EmptyState
      title="Diesen Standardblock gibt es nicht"
      actions={
        <Link to={BLOCKS_PATH} className={buttonClass()}>
          Alle Standardblöcke
        </Link>
      }
    >
      Weder der letzte Lauf noch eine Entscheidung des Teams kennt diesen Absatz. Ein Block
      entfällt, wenn er nach einem Lauf in zu wenigen Mails steht.
    </EmptyState>
  );
}

function BlockContent({ detail }: { detail: BlockDetail }) {
  const { block, senders, domains } = detail;
  return (
    <div className={styles.columns}>
      <div className={styles.main}>
        <BlockHead block={block} />
        <Figures
          label="Zahlen des Blocks"
          items={[
            {
              value: formatNumber(block.mails),
              label: "Mails",
              sub: "ohne Duplikate, auch zitiert",
            },
            {
              value: formatNumber(block.senders),
              label: "Absender",
              sub: "der Mails mit dem Block",
            },
            {
              value: block.first_date ? formatDate(block.first_date) : "–",
              label: "zuerst",
              sub: "älteste Mail",
            },
            {
              value: block.last_date ? formatDate(block.last_date) : "–",
              label: "zuletzt",
              sub: "neueste Mail",
            },
          ]}
        />
        <section className={styles.block} aria-labelledby="block-sample-title">
          <h2 id="block-sample-title" className={styles.blockTitle}>
            Text
          </h2>
          <pre className={styles.sample}>{block.sample}</pre>
          {block.sample.length >= BLOCK_SAMPLE_LIMIT && (
            <p className={styles.note}>
              {`Gekürzt auf die ersten ${formatNumber(BLOCK_SAMPLE_LIMIT)} Zeichen.`}
            </p>
          )}
          <p className={styles.note}>
            So steht der Block in einer seiner Mails. Gezählt wird er auch, wo er zitiert ist oder
            sich nur in Groß- und Kleinschreibung, Leerraum und Zitatzeichen unterscheidet.
          </p>
        </section>
      </div>
      <aside className={styles.side} aria-label="Zum Block">
        <section className={styles.sideBlock} aria-labelledby="block-senders-title">
          <h2 id="block-senders-title" className={styles.sideTitle}>
            {`Absender (${formatNumber(block.senders)})`}
          </h2>
          {senders.length === 0 ? (
            <p className={styles.note}>Kein Absender bekannt.</p>
          ) : (
            <ul className={styles.list}>
              {senders.map(({ person, mails }) => (
                <li key={person.person_id} className={styles.row}>
                  <PersonLink person={person} className={styles.name} />
                  <span className={styles.count} title={`${mailsText(mails)} mit dem Block`}>
                    {formatNumber(mails)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {senders.length < block.senders && (
            <p className={styles.note}>
              {`Die ${formatNumber(senders.length)} mit den meisten Mails.`}
            </p>
          )}
        </section>
        <section className={styles.sideBlock} aria-labelledby="block-domains-title">
          <h2 id="block-domains-title" className={styles.sideTitle}>
            Domains der Absender
          </h2>
          {domains.length === 0 ? (
            <p className={styles.note}>Keine Domain bekannt.</p>
          ) : (
            <ul className={styles.list}>
              {domains.map(({ domain, mails }) => (
                <li key={domain} className={styles.row}>
                  <Link
                    to={`/mails?${listSearch(
                      withFilters(DEFAULT_LIST_STATE, {
                        block: block.hash,
                        sender_domain: [domain],
                      }),
                    )}`}
                    className={styles.name}
                    title={`Mails von ${domain} mit dem Block`}
                  >
                    {domain}
                  </Link>
                  <span className={styles.count}>{formatNumber(mails)}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </aside>
    </div>
  );
}

/** What the block is, the way to its mails, and the team's choice with its note. */
function BlockHead({ block }: { block: BlockInfo }) {
  const save = useSaveBlockOverride();
  const editor = useEditor();
  const once = useEditorOnce();
  const [editorDialog, setEditorDialog] = useState(false);
  const standing = blockStanding(block);
  const choice = nextChoice(standing);

  return (
    <section className={styles.head} aria-labelledby="block-title">
      <div className={styles.titles}>
        <h2 id="block-title" className={styles.title}>
          {titleOf(block)}
        </h2>
        <p className={styles.meta}>{stateText(block)}</p>
      </div>
      <div className={styles.actions}>
        <Link to={blockMailsHref(block.hash)} className={buttonClass("primary")}>
          {`Mails mit diesem Block (${formatNumber(block.mails)})`}
        </Link>
        <Button
          disabled={save.isPending}
          onClick={() =>
            once.run(() => save.mutate({ hash: block.hash, standard: choice.standard }))
          }
        >
          {choice.label}
        </Button>
      </div>
      {standing.pending ? (
        <p className={styles.pending} role="status">
          {`${pendingText(standing.expected)}. `}
          <Link to="/import">Zum Import</Link>
        </p>
      ) : (
        <p className={styles.note}>
          Eine Änderung wirkt beim nächsten Lauf von „Import starten“; bis dahin bleibt jede Mail,
          wie sie ist.
        </p>
      )}
      {save.isError && (
        <p className={styles.error} role="alert">
          Die Entscheidung konnte nicht gespeichert werden.
        </p>
      )}
      <p className={styles.note}>
        {editor ? (
          <>
            Entscheidungen werden gespeichert als <strong>{editor}</strong>.
          </>
        ) : (
          "Entscheidungen werden ohne Namen gespeichert."
        )}{" "}
        <Button variant="link" size="xs" onClick={() => setEditorDialog(true)}>
          {editor ? "Namen ändern" : "Namen eintragen"}
        </Button>
      </p>
      {once.dialog}
      {editorDialog && <EditorDialog onClose={() => setEditorDialog(false)} />}
    </section>
  );
}

function titleOf(block: BlockInfo): string {
  if (block.standard) return "Standardblock";
  return block.detected ? "Zurückgenommener Standardblock" : "Absatz";
}

/** How the block came to be what it is, as the last run applied it. */
function stateText(block: BlockInfo): string {
  if (block.standard && block.detected) {
    return "Erkannt: steht am Ende vieler Mails, deren Absender ihn mehrfach verwenden.";
  }
  if (block.standard) return "Von Hand als Standardblock markiert.";
  if (block.detected) {
    return "Erkannt, aber vom Team zurückgenommen: die Suche und das Mail-Detail zeigen ihn wie anderen Text.";
  }
  return "Kein Standardblock: die Suche und das Mail-Detail zeigen ihn wie anderen Text.";
}
