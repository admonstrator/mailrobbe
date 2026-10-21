import { useState } from "react";
import { Link } from "react-router";

import { useMailEntities, useThemes } from "../../api/queries";
import type { EntityContextKey, EntityRef, MailEntity, ThemeInfo } from "../../api/types";
import { Button } from "../../components/Button";
import { Card, CardTitle } from "../../components/Card";
import { Spinner } from "../../components/Spinner";
import { formatNumber } from "../../lib/format";
import { TAG_PALETTE } from "../../lib/research";
import { documentName } from "../documents/labels";
import { documentPath } from "../documents/urlState";
import { EntityIcon } from "../entities/EntityIcon";
import {
  CONTEXT_LABELS,
  ENTITY_CONTEXTS,
  ENTITY_GROUPS,
  ENTITY_KINDS,
  GROUP_KINDS,
  GROUP_LABELS,
  groupOf,
  themeOf,
  type EntityGroup,
} from "../entities/labels";
import { entityMailsHref, entityPath } from "../entities/urlState";
import styles from "./EntitiesCard.module.css";

/** Entries shown before "alle N zeigen". */
const COLLAPSED = 12;

/** One entity of the mail: its mentions in the mail's text and in its attachments together. */
export interface FoundEntity {
  entity: EntityRef;
  occurrences: number;
  context: EntityContextKey[];
  inText: boolean;
  documents: { id: number; name: string | null }[];
}

/** The mentions of a mail as one entry per entity, by kind group and kind, else in the order the
 *  API gave them. */
export function foundEntities(mentions: MailEntity[]): FoundEntity[] {
  const byId = new Map<number, FoundEntity>();
  for (const mention of mentions) {
    const found = byId.get(mention.entity.id) ?? {
      entity: mention.entity,
      occurrences: 0,
      context: [],
      inText: false,
      documents: [],
    };
    found.occurrences += mention.occurrences;
    found.context = ENTITY_CONTEXTS.filter(
      (key) => found.context.includes(key) || mention.context.includes(key),
    );
    if (mention.document_id === null) found.inText = true;
    else found.documents.push({ id: mention.document_id, name: mention.document_name });
    byId.set(mention.entity.id, found);
  }
  const rank = (found: FoundEntity) =>
    ENTITY_GROUPS.indexOf(groupOf(found.entity.kind)) * 100 +
    ENTITY_KINDS.indexOf(found.entity.kind);
  return [...byId.values()].sort((a, b) => rank(a) - rank(b));
}

/** "Erkannt in dieser Mail" (D89): what was found in the subject, the text and the attachments'
 *  texts, by kind; each entry links to its entity page and to the mails mentioning it. */
export function EntitiesCard({ mailId }: { mailId: number }) {
  const mentions = useMailEntities(mailId);
  const themes = useThemes();
  const [all, setAll] = useState(false);
  const found = mentions.data ? foundEntities(mentions.data) : [];
  const shown = all ? found : found.slice(0, COLLAPSED);

  return (
    <Card variant="side" aria-labelledby="mail-entities-title">
      <CardTitle id="mail-entities-title" variant="caps">
        {found.length > 0
          ? `Erkannt in dieser Mail (${formatNumber(found.length)})`
          : "Erkannt in dieser Mail"}
      </CardTitle>
      {mentions.isPending ? (
        <Spinner label="Entitäten werden geladen" />
      ) : mentions.isError ? (
        <div className={styles.error} role="alert">
          <span>Konnte nicht geladen werden.</span>
          <Button variant="link" size="xs" onClick={() => void mentions.refetch()}>
            Erneut versuchen
          </Button>
        </div>
      ) : found.length === 0 ? (
        <p className={styles.empty}>Nichts erkannt.</p>
      ) : (
        <>
          {ENTITY_GROUPS.map((group) => (
            <EntityGroupList
              key={group}
              group={group}
              found={shown.filter((entry) => GROUP_KINDS[group].includes(entry.entity.kind))}
              themes={themes.data}
            />
          ))}
          {found.length > COLLAPSED && (
            <button type="button" className={styles.more} onClick={() => setAll(!all)}>
              {all ? "Weniger zeigen" : `alle ${formatNumber(found.length)} zeigen`}
            </button>
          )}
        </>
      )}
    </Card>
  );
}

function EntityGroupList({
  group,
  found,
  themes,
}: {
  group: EntityGroup;
  found: FoundEntity[];
  themes: ThemeInfo[] | undefined;
}) {
  if (found.length === 0) return null;
  return (
    <div className={styles.group}>
      <h3 className={styles.groupTitle}>
        <EntityIcon kind={GROUP_KINDS[group][0]} size={13} />
        {GROUP_LABELS[group]}
      </h3>
      <ul className={styles.list}>
        {found.map((entry) => (
          <Entry key={entry.entity.id} entry={entry} theme={themeOf(entry.entity, themes)} />
        ))}
      </ul>
    </div>
  );
}

function Entry({ entry, theme }: { entry: FoundEntity; theme: ThemeInfo | undefined }) {
  const { entity, occurrences, context, inText, documents } = entry;
  return (
    <li className={styles.item}>
      <span className={styles.line}>
        {theme && (
          <span
            className={styles.dot}
            style={{ background: TAG_PALETTE[theme.color].text }}
            title={theme.name}
            aria-hidden="true"
          />
        )}
        <Link to={entityPath(entity.id)} className={styles.label}>
          {entity.label}
        </Link>
        {occurrences > 1 && (
          <span className={styles.occurrences} title={`${formatNumber(occurrences)}-mal erwähnt`}>
            {`${formatNumber(occurrences)}×`}
          </span>
        )}
        {context.map((key) => (
          <span key={key} className={styles.context}>
            {CONTEXT_LABELS[key]}
          </span>
        ))}
        <Link
          to={entityMailsHref([entity.id])}
          className={styles.mails}
          aria-label={`Mails mit ${entity.label}`}
          title="Alle Mails, die es erwähnen"
        >
          Mails
        </Link>
      </span>
      {documents.map((document) => (
        <span key={document.id} className={styles.source}>
          {inText ? "auch im Anhang " : "im Anhang "}
          <Link to={documentPath(document.id)}>{documentName(document.name)}</Link>
        </span>
      ))}
    </li>
  );
}
