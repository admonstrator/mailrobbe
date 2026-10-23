import { useState } from "react";
import { Link } from "react-router";

import {
  useEntityFacets,
  useEntityRefs,
  useEntitySummary,
  useMailSummary,
  useThemes,
} from "../../api/queries";
import {
  FACET_LIMIT,
  MAX_FACET_LIMIT,
  type EntityCount,
  type EntityFacets as Facets,
  type MailFilters,
  type ThemeInfo,
} from "../../api/types";
import { Button } from "../../components/Button";
import { Spinner } from "../../components/Spinner";
import { cx } from "../../lib/cx";
import { formatNumber } from "../../lib/format";
import { TAG_PALETTE } from "../../lib/research";
import { EntityIcon } from "../entities/EntityIcon";
import {
  FACET_GROUPS,
  GROUP_KINDS,
  GROUP_LABELS,
  KIND_LABELS,
  mailsText,
  themeOf,
  type EntityGroup,
} from "../entities/labels";
import { entityPath } from "../entities/urlState";
import type { ChipNames } from "./chips";
import styles from "./EntityFacets.module.css";
import { toFilters, withFilters, type ListState } from "./listState";

/** "in allen Mails", "in 1.234 Treffern", "in 10.000 von 23.456 Treffern (Stichprobe)" (D87). */
export function facetScope(
  facets: Pick<Facets, "mails" | "sampled">,
  total: number | null,
): string {
  if (facets.mails === null) return "in allen Mails";
  const counted = formatNumber(facets.mails);
  if (!facets.sampled) return `in ${counted} ${facets.mails === 1 ? "Treffer" : "Treffern"}`;
  return `in ${counted} von ${total === null ? "mehr" : formatNumber(total)} Treffern (Stichprobe)`;
}

/** The entities of a group, most mails first, from the lists of its kinds. */
function groupEntries(facets: Facets | undefined, group: EntityGroup, limit: number) {
  const lists = GROUP_KINDS[group].map((kind) => facets?.kinds[kind] ?? []);
  const entries = lists.flat().sort((a, b) => b.mails - a.mails);
  // More may exist where a kind gave as many as were asked for.
  const more = entries.length > limit || lists.some((list) => list.length >= limit);
  return { entries: entries.slice(0, limit), more };
}

/** The entities most mentioned in the list's mails, per kind group (D87), in the panel
 *  "Einblicke" beside the list (D335). A click adds an entity to the filter, a second one takes
 *  it out again. */
export function EntityFacets({
  state,
  onChange,
}: {
  state: ListState;
  onChange: (next: ListState) => void;
}) {
  const filters = toFilters(state);
  const facets = useEntityFacets(filters);
  const summary = useMailSummary(filters);
  const themes = useThemes();
  const total = summary.data?.exact ? summary.data.total : null;
  const toggle = (id: number) =>
    onChange(
      withFilters(state, {
        entity: state.entity.includes(id)
          ? state.entity.filter((other) => other !== id)
          : [...state.entity, id],
      }),
    );
  // No hits: the list says so, and there is nothing to count.
  if (facets.data?.mails === 0 && !facets.isPlaceholderData) return null;

  return (
    <section className={styles.panel} aria-labelledby="facets-title">
      <div className={styles.head}>
        <h3 id="facets-title" className={styles.title}>
          Entitäten
        </h3>
        <span className={styles.headLinks}>
          <Link to="/entitaeten" className={styles.all}>
            Alle Entitäten
          </Link>
        </span>
        {facets.data && <span className={styles.scope}>{facetScope(facets.data, total)}</span>}
      </div>
      {facets.isPending ? (
        <div className={styles.state}>
          <Spinner label="Entitäten werden geladen" />
        </div>
      ) : facets.isError ? (
        <div className={styles.state} role="alert">
          <span>Die Entitäten konnten nicht geladen werden.</span>
          <Button size="xs" onClick={() => void facets.refetch()}>
            Erneut versuchen
          </Button>
        </div>
      ) : Object.keys(facets.data.kinds).length === 0 ? (
        <NoEntities />
      ) : (
        <div className={cx(styles.groups, facets.isPlaceholderData && styles.stale)}>
          {FACET_GROUPS.map((group) => (
            <FacetGroup
              key={group}
              group={group}
              facets={facets.data}
              filters={filters}
              selected={state.entity}
              themes={themes.data}
              onToggle={toggle}
            />
          ))}
        </div>
      )}
    </section>
  );
}

/** Nothing found: after an import without the entities phase, the next import scans the mails. */
function NoEntities() {
  const summary = useEntitySummary();
  const waiting = summary.data?.mails_waiting ?? 0;
  return (
    <div className={styles.empty}>
      <p className={styles.emptyTitle}>Keine Entitäten erkannt</p>
      {waiting > 0 && (
        <p className={styles.hint}>
          {`Sie erscheinen nach dem nächsten Import: ${mailsText(waiting)} ${waiting === 1 ? "ist" : "sind"} noch nicht ausgewertet.`}
        </p>
      )}
    </div>
  );
}

/** One kind group: its top entities, and up to MAX_FACET_LIMIT on request ("mehr"). */
function FacetGroup({
  group,
  facets,
  filters,
  selected,
  themes,
  onToggle,
}: {
  group: EntityGroup;
  facets: Facets;
  filters: MailFilters;
  selected: number[];
  themes: ThemeInfo[] | undefined;
  onToggle: (id: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const base = groupEntries(facets, group, FACET_LIMIT);
  const more = useEntityFacets(
    { ...filters, kind: [...GROUP_KINDS[group]], limit: MAX_FACET_LIMIT },
    expanded && base.more,
  );
  if (base.entries.length === 0) return null;
  const all = expanded && more.data ? groupEntries(more.data, group, MAX_FACET_LIMIT) : null;
  const entries = all && all.entries.length > 0 ? all.entries : base.entries;
  const titleId = `facet-${group}`;

  return (
    <div className={styles.group} role="group" aria-labelledby={titleId}>
      <h4 id={titleId} className={styles.groupTitle}>
        <EntityIcon kind={GROUP_KINDS[group][0]} size={13} />
        {GROUP_LABELS[group]}
      </h4>
      <ul className={styles.chips}>
        {entries.map((count) => (
          <FacetChip
            key={count.entity.id}
            count={count}
            theme={themeOf(count.entity, themes)}
            selected={selected.includes(count.entity.id)}
            onToggle={onToggle}
          />
        ))}
      </ul>
      {(base.more || expanded) && (
        <button
          type="button"
          className={styles.more}
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {!expanded ? "mehr" : more.isFetching ? "lädt …" : "weniger"}
        </button>
      )}
    </div>
  );
}

function FacetChip({
  count: { entity, mails },
  theme,
  selected,
  onToggle,
}: {
  count: EntityCount;
  theme: ThemeInfo | undefined;
  selected: boolean;
  onToggle: (id: number) => void;
}) {
  const kind = KIND_LABELS[entity.kind].one;
  return (
    <li className={cx(styles.chip, selected && styles.selected)}>
      <button
        type="button"
        className={styles.toggle}
        aria-pressed={selected}
        title={
          selected
            ? `${kind}${theme ? ` · ${theme.name}` : ""} · im Filter; Klick nimmt es heraus`
            : `${kind}${theme ? ` · ${theme.name}` : ""} · ${mailsText(mails)}; Klick grenzt die Liste ein`
        }
        onClick={() => onToggle(entity.id)}
      >
        {theme && (
          <span
            className={styles.dot}
            style={{ background: TAG_PALETTE[theme.color].text }}
            aria-hidden="true"
          />
        )}
        <span className={styles.label}>{entity.label}</span>{" "}
        <span className={styles.count}>{formatNumber(mails)}</span>
      </button>
      <Link
        to={entityPath(entity.id)}
        className={styles.open}
        aria-label={`Seite von ${entity.label}`}
        title={`Seite von ${entity.label}`}
      >
        ›
      </Link>
    </li>
  );
}

/** Names for the chips of the entity filter (D86): kind and label of each id, asked for in one
 *  request, and a term's theme colour; undefined while they load. */
export function useEntityChipNames(ids: number[]): NonNullable<ChipNames["entity"]> {
  const refs = useEntityRefs(ids);
  const themes = useThemes();
  return (id) => {
    const ref = refs.data?.find((other) => other.id === id);
    return ref && { ref, color: themeOf(ref, themes.data)?.color };
  };
}
