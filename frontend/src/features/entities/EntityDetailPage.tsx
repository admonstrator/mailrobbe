import { Link, useParams } from "react-router";

import { ApiError } from "../../api/client";
import { useEntity, useThemes } from "../../api/queries";
import type { EntityDetail, EntitySample, ThemeInfo } from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { ErrorState } from "../../components/ErrorState";
import { FigureRow, type Figure } from "../../components/FigureRow";
import { HelpMark } from "../../components/HelpMark";
import { PersonLink, personPath } from "../../components/PersonLink";
import { Spinner } from "../../components/Spinner";
import { formatDate, formatDateTime, formatNumber } from "../../lib/format";
import { highlightParts } from "../../lib/highlight";
import { personName } from "../../lib/person";
import { documentName } from "../documents/labels";
import { documentPath } from "../documents/urlState";
import styles from "./EntityDetailPage.module.css";
import { EntityIcon } from "./EntityIcon";
import { EntityContexts, EntityPersons, EntityRelated } from "./EntitySide";
import { EntityExtras } from "./EntityTable";
import {
  CONTEXT_LINK_LABELS,
  ENTITY_CONTEXTS,
  hasContexts,
  KIND_LABELS,
  mailsText,
  themeOf,
} from "./labels";
import {
  DEFAULT_ENTITY_LIST_STATE,
  entityListHref,
  entityMailsHref,
  entityYearHref,
} from "./urlState";

/** The entity page (D88): what it is, how often and when it is mentioned, by whom, next to
 *  what, and its earliest mentions; every figure leads to the mail list. */
export function EntityDetailPage() {
  const { id } = useParams();
  if (!id || !/^\d+$/.test(id)) {
    return (
      <div className={styles.page}>
        <EntityNotFound />
      </div>
    );
  }
  return <EntityView key={id} id={Number(id)} />;
}

function EntityView({ id }: { id: number }) {
  const detail = useEntity(id);
  const label = detail.data?.label;
  return (
    <div className={styles.page}>
      <title>{`${label ?? "Entität"} · Entitäten · Mailrobbe`}</title>
      <nav aria-label="Pfad" className={styles.breadcrumb}>
        <Link to="/entitaeten">Entitäten</Link>
        {label && (
          <>
            <span aria-hidden="true">›</span>
            <span className={styles.crumb}>{label}</span>
          </>
        )}
      </nav>
      {detail.isPending ? (
        <div className={styles.loading}>
          <Spinner label="Entität wird geladen" />
        </div>
      ) : detail.isError ? (
        detail.error instanceof ApiError && detail.error.code === "not_found" ? (
          <EntityNotFound id={id} />
        ) : (
          <div className={styles.message}>
            <ErrorState
              title="Die Entität konnte nicht geladen werden."
              actions={<Button onClick={() => void detail.refetch()}>Erneut versuchen</Button>}
            >
              Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
            </ErrorState>
          </div>
        )
      ) : (
        <EntityContent entity={detail.data} />
      )}
    </div>
  );
}

function EntityContent({ entity }: { entity: EntityDetail }) {
  const themes = useThemes();
  return (
    <div className={styles.columns}>
      <div className={styles.main}>
        <EntityHeader entity={entity} themes={themes.data} />
        <EntityFigures entity={entity} />
        <EntityYears entity={entity} />
        <EntitySamples entity={entity} />
      </div>
      <aside className={styles.side} aria-label="Zur Entität">
        {hasContexts(entity.kind) && <EntityContexts entity={entity} />}
        <EntityPersons
          id="entity-senders-title"
          title="Absender"
          persons={entity.senders}
          total={entity.sender_count}
          sampled={entity.persons_sampled}
          empty="Kein Absender bekannt."
        />
        <EntityPersons
          id="entity-recipients-title"
          title="Empfänger"
          persons={entity.recipients}
          total={entity.recipient_count}
          sampled={entity.persons_sampled}
          empty="Kein Empfänger bekannt."
        />
        <EntityRelated entity={entity} themes={themes.data} />
      </aside>
    </div>
  );
}

let currencyNames: Intl.DisplayNames | null | undefined;

/** "Euro", "Deutsche Mark" for the codes of amounts (D81); the code where the browser knows no
 *  name. */
function currencyName(code: string): string {
  if (currencyNames === undefined) {
    try {
      currencyNames = new Intl.DisplayNames(["de"], { type: "currency" });
    } catch {
      currencyNames = null;
    }
  }
  try {
    return currencyNames?.of(code) ?? code;
  } catch {
    return code;
  }
}

/** Kind, label and what else identifies it, the archive's person behind it, and the ways into
 *  the mail list: all mentioning mails, and for amounts those next to a context (D86). */
function EntityHeader({
  entity,
  themes,
}: {
  entity: EntityDetail;
  themes: ThemeInfo[] | undefined;
}) {
  const theme = themeOf(entity, themes);
  const contexts =
    entity.kind === "amount" ? ENTITY_CONTEXTS.filter((key) => entity.contexts[key] > 0) : [];
  // The normalised key where it tells more than the label: "EUR 12500.00" under
  // "12.500,00 EUR", not a term's theme or an IBAN without its spaces.
  const bare = (text: string) => text.toLocaleLowerCase("de").replace(/[^\p{L}\p{N}]/gu, "");
  const keyDiffers = entity.kind !== "term" && bare(entity.key) !== bare(entity.label);
  const person = entity.archive_person;

  return (
    <section className={styles.header}>
      <div className={styles.identity}>
        <span className={styles.marker}>
          <EntityIcon kind={entity.kind} size={22} />
        </span>
        <div className={styles.titles}>
          <p className={styles.kind}>
            {KIND_LABELS[entity.kind].one}
            {entity.kind === "amount" && entity.currency && ` in ${currencyName(entity.currency)}`}
          </p>
          <h1 className={styles.label}>{entity.label}</h1>
          <p className={styles.meta}>
            <EntityExtras entity={entity} themes={themes} />
            {theme && (
              <Link
                to={entityListHref({
                  ...DEFAULT_ENTITY_LIST_STATE,
                  tab: "term",
                  detail: theme.key,
                })}
              >
                Alle Begriffe des Themas
              </Link>
            )}
            {keyDiffers && (
              <span className={styles.key} title="Normalisierte Form, unter der es gezählt wird">
                {entity.key}
              </span>
            )}
          </p>
        </div>
      </div>
      {person && (
        <p className={styles.person}>
          {"Im Archiv: "}
          <Link to={personPath(person.person_id)}>
            {person.label?.name || person.name
              ? `${personName(person)} (${person.email})`
              : person.email}
          </Link>
        </p>
      )}
      <div className={styles.actions}>
        <Link to={entityMailsHref([entity.id])} className={buttonClass("primary")}>
          In der Mailliste zeigen
        </Link>
        {contexts.map((key) => (
          <Link
            key={key}
            to={entityMailsHref([entity.id], { amount_context: [key] })}
            className={buttonClass()}
          >
            {CONTEXT_LINK_LABELS[key]}
          </Link>
        ))}
      </div>
    </section>
  );
}

interface Tile {
  label: string;
  value: string;
  sub: string;
}

function dateTile(label: string, iso: string | null): Tile {
  if (!iso) return { label, value: "–", sub: "unbekannt" };
  return { label, value: formatDate(iso), sub: formatDateTime(iso).slice(-5) + " Uhr" };
}

/** The figures of D85: mentioning mails without duplicates, documents, first and last mention;
 *  what each counts and the time of day in its tooltip. */
function EntityFigures({ entity }: { entity: EntityDetail }) {
  const tiles: Tile[] = [
    { label: "Mails", value: formatNumber(entity.mails), sub: "ohne Duplikate" },
    { label: "Dokumente", value: formatNumber(entity.documents), sub: "Anhänge, die es erwähnen" },
    dateTile("Erste Erwähnung", entity.first_date),
    dateTile("Letzte Erwähnung", entity.last_date),
  ];
  const figures: Figure[] = tiles.map(({ label, value, sub }) => ({ label, value, title: sub }));
  return <FigureRow figures={figures} />;
}

/** Mentioning mails per UTC year as bars; each year opens its mails in the mail list. */
function EntityYears({ entity }: { entity: EntityDetail }) {
  const { years } = entity;
  const max = Math.max(1, ...years.map((year) => year.mails));
  return (
    <section className={styles.section} aria-labelledby="entity-years-title">
      <div className={styles.cardHead}>
        <h2 id="entity-years-title" className={styles.sectionTitle}>
          Mails pro Jahr
        </h2>
        {years.length > 0 && <HelpMark text="Ein Klick auf ein Jahr öffnet dessen Mails." />}
      </div>
      {years.length === 0 ? (
        <p className={styles.hint}>Keine datierten Mails.</p>
      ) : (
        <ol
          className={styles.years}
          style={{ gridTemplateColumns: `repeat(${years.length}, minmax(0, 1fr))` }}
        >
          {years.map(({ year, mails }) => (
            <li key={year}>
              <Link
                to={entityYearHref(entity.id, year)}
                className={styles.year}
                aria-label={`${year}: ${mailsText(mails)}`}
                title={`${year}: ${mailsText(mails)}`}
              >
                <span className={styles.yearCount}>{formatNumber(mails)}</span>
                <span className={styles.bar}>
                  <span
                    style={{ height: `${(mails / max) * 100}%`, minHeight: mails > 0 ? 2 : 0 }}
                  />
                </span>
                <span className={styles.yearLabel}>{year}</span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/** The earliest mentions with the text around them; the label is marked where it stands as
 *  written (D88). */
function EntitySamples({ entity }: { entity: EntityDetail }) {
  return (
    <section className={styles.section} aria-labelledby="entity-samples-title">
      <div className={styles.cardHead}>
        <h2 id="entity-samples-title" className={styles.sectionTitle}>
          Früheste Erwähnungen
        </h2>
        <Link to={entityMailsHref([entity.id], { sort: "date_asc" })} className={styles.all}>
          Alle in der Mailliste
        </Link>
      </div>
      {entity.samples.length === 0 ? (
        <p className={styles.hint}>Keine Mail mit diesem Eintrag gefunden.</p>
      ) : (
        <ol className={styles.samples}>
          {entity.samples.map((sample) => (
            <Sample
              key={`${sample.mail.id}-${sample.document_id}`}
              sample={sample}
              label={entity.label}
            />
          ))}
        </ol>
      )}
    </section>
  );
}

function Sample({ sample, label }: { sample: EntitySample; label: string }) {
  const { mail } = sample;
  return (
    <li className={styles.sample}>
      <span className={styles.sampleHead}>
        {mail.date && <span className={styles.muted}>{formatDateTime(mail.date)}</span>}
        {mail.sender ? (
          <PersonLink person={mail.sender} className={styles.sender} />
        ) : (
          <span className={styles.muted}>(unbekannt)</span>
        )}
      </span>
      <Link to={`/mails/${mail.id}`} className={mail.subject ? styles.subject : styles.muted}>
        {mail.subject || "(kein Betreff)"}
      </Link>
      {sample.snippet && (
        <span className={styles.snippet}>
          {highlightParts(sample.snippet, [label]).map((part, index) =>
            part.mark ? <mark key={index}>{part.text}</mark> : part.text,
          )}
        </span>
      )}
      {sample.document_id !== null && (
        <span className={styles.source}>
          {"im Anhang "}
          <Link to={documentPath(sample.document_id)}>{documentName(sample.document_name)}</Link>
        </span>
      )}
    </li>
  );
}

function EntityNotFound({ id }: { id?: number }) {
  return (
    <div className={styles.message}>
      <ErrorState
        title="Diese Entität gibt es nicht."
        actions={
          <Link to="/entitaeten" className={buttonClass()}>
            Zu den Entitäten
          </Link>
        }
      >
        {id === undefined
          ? "Die Adresse nennt keine gültige Nummer."
          : `Im Archiv gibt es keine Entität mit der Nummer #${id}. Was nicht mehr erwähnt wird, entfällt beim nächsten Import.`}
      </ErrorState>
    </div>
  );
}
