import { useLayoutEffect, useRef, useState, useSyncExternalStore, type RefObject } from "react";
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

/** From this width the facets are a column right of the table, which keeps its 900 px beside the
 *  filter column; below it they are a block above the table that can be folded away. */
export const FACETS_COLUMN_QUERY = "(min-width: 1500px)";

function subscribeWidth(onChange: () => void): () => void {
  if (typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia(FACETS_COLUMN_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function columnWide(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(FACETS_COLUMN_QUERY).matches;
}

const STORAGE_KEY = "mailrobbe.facets";

function loadOpen(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== "closed";
  } catch {
    return true; // storage blocked: open
  }
}

function saveOpen(open: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, open ? "open" : "closed");
  } catch {
    // storage blocked: the choice lasts until reload
  }
}

/** "in allen Mails", "in 1.234 Treffern", "in 10.000 von 23.456 Treffern (Stichprobe)" (D87). */
export function facetScope(facets: Facets, total: number | null): string {
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

/** The entities most mentioned in the list's mails, per kind group (D87), beside the table or
 *  above it, depending on the width. Mounted at both places; each renders only at its widths. */
export function EntityFacets({
  state,
  onChange,
  placement,
}: {
  state: ListState;
  onChange: (next: ListState) => void;
  placement: "column" | "top";
}) {
  const wide = useSyncExternalStore(subscribeWidth, columnWide, () => false);
  if (wide !== (placement === "column")) return null;
  return <FacetPanel state={state} onChange={onChange} placement={placement} />;
}

function FacetPanel({
  state,
  onChange,
  placement,
}: {
  state: ListState;
  onChange: (next: ListState) => void;
  placement: "column" | "top";
}) {
  const [open, setOpen] = useState(loadOpen);
  const shown = placement === "column" || open;
  const filters = toFilters(state);
  const facets = useEntityFacets(filters, shown);
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
    <section
      className={cx(styles.panel, styles[placement], !shown && styles.closed)}
      aria-labelledby={`facets-title-${placement}`}
    >
      <div className={styles.head}>
        <h2 id={`facets-title-${placement}`} className={styles.title}>
          Entitäten
        </h2>
        {shown && facets.data && (
          <span className={styles.scope}>{facetScope(facets.data, total)}</span>
        )}
        <span className={styles.headLinks}>
          <Link to="/entitaeten" className={styles.all}>
            Alle Entitäten
          </Link>
          {placement === "top" && (
            <Button
              variant="link"
              size="xs"
              aria-expanded={open}
              onClick={() => {
                setOpen(!open);
                saveOpen(!open);
              }}
            >
              {open ? "Ausblenden" : "Einblenden"}
            </Button>
          )}
        </span>
      </div>
      {shown &&
        (facets.isPending ? (
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
                placement={placement}
                facets={facets.data}
                filters={filters}
                selected={state.entity}
                themes={themes.data}
                onToggle={toggle}
              />
            ))}
          </div>
        ))}
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

/** Whether the element's content is taller than the element: chips the one-line clip hides.
 *  Measured when the content or the size changes; false where the browser cannot tell (tests). */
function useClipped(ref: RefObject<HTMLElement | null>, active: boolean, content: string): boolean {
  const [clipped, setClipped] = useState(false);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!active || !element) return;
    const measure = () => setClipped(element.scrollHeight > element.clientHeight + 1);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [ref, active, content]);
  return active && clipped;
}

/** One kind group: its top entities, and up to MAX_FACET_LIMIT on request ("mehr"). Above the
 *  table a group is one line; "mehr" opens it, and asks for more when there may be more. */
function FacetGroup({
  group,
  placement,
  facets,
  filters,
  selected,
  themes,
  onToggle,
}: {
  group: EntityGroup;
  placement: "column" | "top";
  facets: Facets;
  filters: MailFilters;
  selected: number[];
  themes: ThemeInfo[] | undefined;
  onToggle: (id: number) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const chips = useRef<HTMLUListElement>(null);
  const clip = placement === "top" && !expanded;
  const base = groupEntries(facets, group, FACET_LIMIT);
  const clipped = useClipped(
    chips,
    clip,
    base.entries.map(({ entity, mails }) => `${entity.id}:${mails}`).join(),
  );
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
      <h3 id={titleId} className={styles.groupTitle}>
        <EntityIcon kind={GROUP_KINDS[group][0]} size={13} />
        {GROUP_LABELS[group]}
      </h3>
      <ul ref={chips} className={cx(styles.chips, clip && styles.clipped)}>
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
      {(base.more || expanded || clipped) && (
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
