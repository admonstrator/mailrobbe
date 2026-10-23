import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { ApiError, apiGet } from "../../api/client";
import {
  queryKeys,
  useDocument,
  useMailDetail,
  useMboxFiles,
  useResearch,
  useStats,
  useTopicTerms,
} from "../../api/queries";
import {
  MAX_TOPIC_SELECTION_TERMS,
  TOPIC_SELECTION_TERMS,
  type PersonProfile,
  type PersonRole,
  type ThemeInfo,
  type TopicTerm,
  type TopicTerms,
} from "../../api/types";
import { Button, buttonClass } from "../../components/Button";
import { Card } from "../../components/Card";
import { Chip } from "../../components/Chip";
import { EmptyState } from "../../components/EmptyState";
import { ErrorState } from "../../components/ErrorState";
import { SearchIcon } from "../../components/icons";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatNumber, utcDay } from "../../lib/format";
import { TAG_PALETTE } from "../../lib/research";
import { filterChips, PERSON_ROLE_LABELS } from "../mails/chips";
import { useEntityChipNames } from "../mails/EntityFacets";
import { DateField } from "../mails/FilterColumn";
import { toFilters, withFilters, type FilterPatch, type ListState } from "../mails/listState";
import { invalidTerm } from "../mails/queryText";
import { personLabel } from "../persons/labels";
import { ColorChip } from "../research/ColorChip";
import { PersonPicker } from "../timeline/PersonPicker";
import { formatRatio, formatShare, mailsText, termFigures, themesOf } from "./labels";
import { Segments } from "../../components/Segments";
import styles from "./SelectionView.module.css";
import { TermChip, TermList } from "./TermChip";
import {
  hasSelection,
  termMailsHref,
  termTimelineHref,
  topicsHref,
  type TopicsState,
} from "./urlState";

/** Names of the selection's persons by their profiles, which also name persons that came with a
 *  link, in one query (under the persons' prefix, so a merge renames them); a person whose
 *  profile cannot be read keeps its number. */
function usePersonNames(ids: number[]): Record<number, string> {
  const names = useQuery({
    queryKey: [...queryKeys.persons, "names", ids],
    queryFn: async ({ signal }) => {
      const profiles = await Promise.all(
        ids.map((id) =>
          apiGet<PersonProfile>(`/api/persons/${id}`, undefined, signal).catch(() => null),
        ),
      );
      return Object.fromEntries(
        profiles.flatMap((profile, index) => (profile ? [[ids[index], personLabel(profile)]] : [])),
      ) as Record<number, string>;
    },
    enabled: ids.length > 0,
    placeholderData: keepPreviousData,
  });
  return names.data ?? {};
}

type RoleChoice = PersonRole | "all";

/** Auswahl (D144): the terms of the mails of any filter of the mail list, counted on request,
 *  with a person, its role, a Zeitraum and the search text to set here. */
export function SelectionView({
  state,
  onChange,
  themes,
}: {
  state: TopicsState;
  onChange: (next: TopicsState) => void;
  themes: ThemeInfo[] | undefined;
}) {
  const list = state.list;
  const selected = hasSelection(list);
  const [limit, setLimit] = useState(TOPIC_SELECTION_TERMS);
  const filters = toFilters(list);
  const terms = useTopicTerms(
    limit === TOPIC_SELECTION_TERMS ? filters : { ...filters, limit },
    selected,
  );
  const change = (patch: FilterPatch) => onChange({ ...state, list: withFilters(list, patch) });

  return (
    <div className={styles.view}>
      <Controls list={list} onChange={change} />
      <Chips state={state} onChange={onChange} />
      <Card className={styles.card}>
        {!selected ? (
          <EmptyState
            title="Wählen Sie eine Person, einen Zeitraum oder eine Suche"
            actions={
              <Link to={topicsHref({ ...state, view: "periods" })} className={buttonClass()}>
                Zu den Zeiträumen
              </Link>
            }
          >
            Begriffe heben sich nur gegen den Rest des Archivs ab, das ganze Archiv nicht gegen sich
            selbst. Die Zeiträume zeigen es Monat für Monat.
          </EmptyState>
        ) : terms.isPending ? (
          <div className={styles.loading}>
            <Spinner label="Begriffe werden gezählt" />
          </div>
        ) : terms.isError ? (
          <TermsError
            error={terms.error}
            list={list}
            onChange={change}
            onRetry={() => void terms.refetch()}
          />
        ) : (
          <Result
            data={terms.data}
            list={list}
            themes={themes}
            stale={terms.isPlaceholderData}
            more={
              terms.data.terms.length >= limit && limit < MAX_TOPIC_SELECTION_TERMS
                ? () => setLimit(MAX_TOPIC_SELECTION_TERMS)
                : null
            }
          />
        )}
      </Card>
    </div>
  );
}

/** Search, person, role and Zeitraum: the filters most selections need, set on the screen. */
function Controls({ list, onChange }: { list: ListState; onChange: (patch: FilterPatch) => void }) {
  const stats = useStats();
  const dayMin = stats.data?.date_min ? utcDay(stats.data.date_min) : undefined;
  const dayMax = stats.data?.date_max ? utcDay(stats.data.date_max) : undefined;
  const role = list.person_role;
  const roles: [RoleChoice, string][] = [
    ["sent", PERSON_ROLE_LABELS.sent],
    ...(role && role !== "sent" ? [[role, PERSON_ROLE_LABELS[role]] as [RoleChoice, string]] : []),
    ["all", "Alle Rollen"],
  ];

  function onSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onChange({ q: String(new FormData(event.currentTarget).get("q") ?? "").trim() });
  }

  return (
    <div className={styles.controls}>
      <form role="search" className={styles.field} onSubmit={onSearch}>
        <label htmlFor="topics-search" className={styles.label}>
          Suchtext
        </label>
        <div className={styles.search}>
          <SearchIcon className={styles.searchIcon} />
          <input
            key={list.q}
            id="topics-search"
            name="q"
            type="search"
            defaultValue={list.q}
            placeholder="wie in der Mailliste, z. B. Spende oder from:kasse@ …"
            autoComplete="off"
            spellCheck={false}
            className={styles.searchInput}
          />
        </div>
      </form>
      <div className={styles.field}>
        <span className={styles.label} aria-hidden="true">
          Person
        </span>
        <PersonPicker
          chosen={list.person}
          disabled={false}
          onPick={(person) => {
            const persons = [...list.person, person.id];
            // A role holds for one person only (D32); the person's own words are in its sent mails.
            onChange({ person: persons, person_role: persons.length === 1 ? "sent" : null });
          }}
        />
      </div>
      {list.person.length === 1 && (
        <Segments<RoleChoice>
          label="Rolle"
          options={roles}
          value={role ?? "all"}
          onChange={(choice) => onChange({ person_role: choice === "all" ? null : choice })}
        />
      )}
      <div className={styles.dates} role="group" aria-label="Zeitraum">
        <DateField
          id="topics-date-from"
          label="Zeitraum von"
          value={list.date_from}
          min={dayMin}
          max={list.date_to ?? dayMax}
          onCommit={(date_from) => onChange({ date_from })}
        />
        <DateField
          id="topics-date-to"
          label="bis"
          value={list.date_to}
          min={list.date_from ?? dayMin}
          max={dayMax}
          onCommit={(date_to) => onChange({ date_to })}
        />
      </div>
    </div>
  );
}

/** The selection's filters as the mail list shows them, each removable. */
function Chips({ state, onChange }: { state: TopicsState; onChange: (next: TopicsState) => void }) {
  const list = state.list;
  const persons = usePersonNames([...new Set([...list.person, ...list.between])]);
  const mboxFiles = useMboxFiles();
  const research = useResearch();
  const filtered = useDocument(list.document ?? 0, list.document !== null);
  const threadMail = useMailDetail(list.thread ?? 0, list.thread !== null);
  const entityNames = useEntityChipNames(list.entity);
  const chips = filterChips(list, [], {
    person: (id) => persons[id] ?? `#${id}`,
    mboxFile: (id) => mboxFiles.data?.find((file) => file.id === id)?.path ?? `Datei #${id}`,
    tag: (id) => research.data?.tags.find((tag) => tag.id === id),
    collection: (id) => research.data?.collections.find((other) => other.id === id)?.name,
    document: (id) =>
      filtered.data?.id === id ? (filtered.data.name ?? "(ohne Dateinamen)") : `#${id}`,
    thread: (id) =>
      threadMail.data?.id === id ? threadMail.data.subject || "(kein Betreff)" : undefined,
    entity: entityNames,
  });
  if (chips.length === 0) return null;
  return (
    <div className={styles.chips} aria-label="Auswahl">
      {chips.map((chip) => (
        <Chip
          key={chip.id}
          label={chip.label}
          color={chip.color && TAG_PALETTE[chip.color].text}
          onRemove={() => onChange({ ...state, list: chip.next })}
        />
      ))}
    </div>
  );
}

/** "Gezählt über 5.000 von 48.210 Mails, Zahlen geschätzt", or the selection's mails against
 *  the rest of the archive. */
function scopeText(data: TopicTerms): string {
  if (data.sampled && data.mails !== null) {
    return `Gezählt über ${formatNumber(data.counted)} von ${formatNumber(data.mails)} Mails, Zahlen geschätzt`;
  }
  const mails = data.mails ?? data.counted;
  const rest = Math.max(0, data.state.mails - mails);
  return `${mailsText(mails)} dieser Auswahl, ohne Duplikate, verglichen mit den übrigen ${formatNumber(rest)} Mails des Archivs`;
}

function Result({
  data,
  list,
  themes,
  stale,
  more,
}: {
  data: TopicTerms;
  list: ListState;
  themes: ThemeInfo[] | undefined;
  stale: boolean;
  more: (() => void) | null;
}) {
  if (data.timed_out) {
    return (
      <EmptyState title="Die Zählung hat zu lange gedauert.">
        Grenzen Sie die Auswahl ein, etwa mit einem Zeitraum oder einer Person.
      </EmptyState>
    );
  }
  if (data.mails === 0) {
    return (
      <EmptyState title="Keine Mails in dieser Auswahl">
        Die Begriffe zählen Mails ohne Duplikate, aus Betreff und Text.
      </EmptyState>
    );
  }
  const estimated = data.sampled;
  return (
    <div className={cx(styles.result, stale && styles.stale)}>
      <p className={cx(styles.scope, estimated && styles.sampled)} role="status">
        {scopeText(data)}
      </p>
      {data.terms.length === 0 ? (
        <p className={styles.none}>
          Kein Wort ist in dieser Auswahl in mindestens 3 Mails und mindestens doppelt so häufig wie
          im übrigen Archiv.
        </p>
      ) : (
        <TermTable terms={data.terms} list={list} themes={themes} />
      )}
      {more && (
        <Button variant="link" size="sm" className={styles.moreButton} onClick={more}>
          Weitere Begriffe zeigen
        </Button>
      )}
      {data.common.length > 0 && (
        <section className={styles.common} aria-labelledby="topics-common">
          <h3 id="topics-common" className={styles.commonTitle}>
            In mehr als der Hälfte dieser Mails, oft Signatur, Grußformel oder Fußzeile
          </h3>
          <TermList label="Häufige Begriffe">
            {data.common.map((term) => (
              <TermChip
                key={term.term}
                label={term.label}
                mails={term.mails}
                href={termMailsHref(list, term.label)}
                figures={termFigures(term, data.mails, estimated)}
                themes={themesOf(term.themes, themes)}
                muted
              />
            ))}
          </TermList>
        </section>
      )}
    </div>
  );
}

/** The terms that stand out, with every figure in a column of its own (D142). */
function TermTable({
  terms,
  list,
  themes,
}: {
  terms: TopicTerm[];
  list: ListState;
  themes: ThemeInfo[] | undefined;
}) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Begriff</th>
            <th scope="col" className={styles.number}>
              Mails
            </th>
            <th scope="col" className={styles.number}>
              Anteil hier
            </th>
            <th scope="col" className={styles.number}>
              im übrigen Archiv
            </th>
            <th scope="col">Häufigkeit</th>
            <th scope="col">
              <span className="sr-only">Zeitachse</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {terms.map((term) => (
            <tr key={term.term}>
              <td>
                <span className={styles.term}>
                  <Link to={termMailsHref(list, term.label)} className={styles.termLink}>
                    {term.label}
                  </Link>
                  {themesOf(term.themes, themes).map((theme) => (
                    <ColorChip key={theme.key} color={theme.color}>
                      {theme.name}
                    </ColorChip>
                  ))}
                </span>
              </td>
              <td className={styles.number}>{formatNumber(term.mails)}</td>
              <td className={styles.number}>{formatShare(term.share)}</td>
              <td className={styles.number}>{formatShare(term.rest_share)}</td>
              <td>{formatRatio(term.ratio)}</td>
              <td className={styles.timeline}>
                <Link
                  to={termTimelineHref(list, [term.label])}
                  aria-label={`Zeitachse: ${term.label}`}
                >
                  Zeitachse
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TermsError({
  error,
  list,
  onChange,
  onRetry,
}: {
  error: Error;
  list: ListState;
  onChange: (patch: FilterPatch) => void;
  onRetry: () => void;
}) {
  const code = error instanceof ApiError ? error.code : null;
  if (code === "invalid_query") {
    return (
      <ErrorState
        title={`Suche nicht verstanden: ${invalidTerm(error.message, list.q)}`}
        actions={<Button onClick={() => onChange({ q: "" })}>Suche leeren</Button>}
      >
        Suchoperatoren brauchen einen gültigen Wert, zum Beispiel after:2024-01-31, dkim:fail oder
        has:attachment.
      </ErrorState>
    );
  }
  if (code === "invalid_filter" || (error instanceof ApiError && error.status === 422)) {
    return (
      <ErrorState
        title="Diese Filter lassen sich nicht anwenden."
        actions={
          <Link to="/themen?view=selection" className={buttonClass()}>
            Filter zurücksetzen
          </Link>
        }
      >
        Die Adresse enthält eine Filterkombination, die Mailrobbe nicht auswerten kann.
      </ErrorState>
    );
  }
  return (
    <ErrorState
      title="Die Begriffe konnten nicht gezählt werden."
      actions={<Button onClick={onRetry}>Erneut versuchen</Button>}
    >
      Der Server ist nicht erreichbar oder hat einen Fehler gemeldet.
    </ErrorState>
  );
}
