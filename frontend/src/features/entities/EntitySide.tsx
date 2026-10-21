import { Link } from "react-router";

import { FACET_MAILS, type EntityDetail, type PersonCount, type ThemeInfo } from "../../api/types";
import { Card, CardTitle } from "../../components/Card";
import { personPath } from "../../components/PersonLink";
import { formatNumber } from "../../lib/format";
import { TAG_PALETTE } from "../../lib/research";
import { personLabel } from "../persons/labels";
import { EntityIcon } from "./EntityIcon";
import styles from "./EntitySide.module.css";
import { CONTEXT_LABELS, ENTITY_CONTEXTS, KIND_LABELS, mailsText, themeOf } from "./labels";
import { entityMailsHref, entityPath } from "./urlState";

const SAMPLED = `gezählt über ${formatNumber(FACET_MAILS)} der Mails`;

/** "Die 10 häufigsten von 37, gezählt über 10.000 der Mails." when the list is cut or counted
 *  over a part of the mails; null when it is complete. */
function partText(shown: number, total: number, sampled: boolean): string | null {
  const parts = [
    shown < total && `die ${formatNumber(shown)} häufigsten von ${formatNumber(total)}`,
    sampled && SAMPLED,
  ].filter(Boolean);
  if (parts.length === 0) return null;
  const text = parts.join(", ");
  return `${text[0].toUpperCase()}${text.slice(1)}.`;
}

/** Mentioning mails per context of an amount, IBAN or account number (D82). */
export function EntityContexts({ entity }: { entity: EntityDetail }) {
  return (
    <Card variant="side" aria-labelledby="entity-contexts-title">
      <CardTitle id="entity-contexts-title" variant="caps">
        Im Zusammenhang mit
      </CardTitle>
      <ul className={styles.list}>
        {ENTITY_CONTEXTS.map((key) => (
          <li key={key} className={styles.row}>
            <span>{CONTEXT_LABELS[key]}</span>
            <span
              className={styles.count}
              title={`${mailsText(entity.contexts[key])} mit diesem Zusammenhang`}
            >
              {formatNumber(entity.contexts[key])}
            </span>
          </li>
        ))}
      </ul>
      <p className={styles.note}>
        Mails, in denen ein Wort des Zusammenhangs im selben Satz steht.
      </p>
    </Card>
  );
}

/** The senders or the recipients of the mentioning mails who had it most (root persons). */
export function EntityPersons({
  id,
  title,
  persons,
  total,
  sampled,
  empty,
}: {
  id: string;
  title: string;
  persons: PersonCount[];
  total: number;
  sampled: boolean;
  empty: string;
}) {
  return (
    <Card variant="side" aria-labelledby={id}>
      <CardTitle id={id} variant="caps">
        {`${title} (${formatNumber(total)})`}
      </CardTitle>
      {persons.length === 0 ? (
        <p className={styles.note}>{empty}</p>
      ) : (
        <ul className={styles.list}>
          {persons.map(({ person, mails }) => (
            <li key={person.person_id} className={styles.row}>
              <Link to={personPath(person.person_id)} className={styles.name} title={person.email}>
                {personLabel(person)}
              </Link>
              <span className={styles.count} title={`${mailsText(mails)} mit diesem Eintrag`}>
                {formatNumber(mails)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {persons.length > 0 && partText(persons.length, total, sampled) && (
        <p className={styles.note}>{partText(persons.length, total, sampled)}</p>
      )}
    </Card>
  );
}

/** "Gemeinsam erwähnt": the entities mentioned in the same mails most often, each with its page
 *  and the mail list of both. */
export function EntityRelated({
  entity,
  themes,
}: {
  entity: EntityDetail;
  themes: ThemeInfo[] | undefined;
}) {
  return (
    <Card variant="side" aria-labelledby="entity-related-title">
      <CardTitle id="entity-related-title" variant="caps">
        Gemeinsam erwähnt
      </CardTitle>
      {entity.related.length === 0 ? (
        <p className={styles.note}>Nichts anderes in denselben Mails erkannt.</p>
      ) : (
        <ul className={styles.related}>
          {entity.related.map(({ entity: other, mails }) => {
            const theme = themeOf(other, themes);
            return (
              <li key={other.id} className={styles.relatedItem}>
                <Link
                  to={entityPath(other.id)}
                  className={styles.chip}
                  title={`${other.label} · ${KIND_LABELS[other.kind].one}${theme ? ` · ${theme.name}` : ""}: in ${mailsText(mails)} zusammen erwähnt`}
                >
                  <EntityIcon kind={other.kind} size={12} />
                  {theme && (
                    <span
                      className={styles.dot}
                      style={{ background: TAG_PALETTE[theme.color].text }}
                      aria-hidden="true"
                    />
                  )}
                  <span className={styles.chipLabel}>{other.label}</span>{" "}
                  <span className={styles.chipCount}>{formatNumber(mails)}</span>
                </Link>
                <Link
                  to={entityMailsHref([entity.id, other.id])}
                  className={styles.both}
                  aria-label={`Mails mit beiden: ${entity.label} und ${other.label}`}
                  title="Mails, die beide erwähnen, in der Mailliste"
                >
                  Mails mit beiden
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      {entity.related.length > 0 && entity.persons_sampled && (
        <p className={styles.note}>{partText(0, 0, true)}</p>
      )}
    </Card>
  );
}
