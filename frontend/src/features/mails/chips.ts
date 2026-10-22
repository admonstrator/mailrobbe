// The active filters above the table: one chip per search term and per sidebar filter, each
// with the list state that removing it leads to.

import type {
  EntityRef,
  EventKey,
  PersonRole,
  QueryKey,
  QueryTerm,
  SearchField,
  SignalKey,
  TagColor,
  TagRef,
} from "../../api/types";
import { DKIM_FILTER_LABELS } from "../../lib/dkim";
import { formatDay, formatNumber } from "../../lib/format";
import { REVIEW_LABELS } from "../../lib/research";
import { CONTEXT_LABELS, KIND_LABELS } from "../entities/labels";
import { signalName } from "../signals/labels";
import { withFilters, type ListState } from "./listState";
import { removeTerm } from "./queryText";

export interface FilterChip {
  id: string;
  label: string;
  next: ListState;
  /** A tag's colour, shown as a dot. */
  color?: TagColor;
}

/** Display names for ids the list state carries; undefined for an id not known (any more). */
export interface ChipNames {
  person: (id: number) => string;
  mboxFile: (id: number) => string;
  tag: (id: number) => TagRef | undefined;
  collection: (id: number) => string | undefined;
  document?: (id: number) => string;
  thread?: (id: number) => string | undefined;
  /** An entity of the filter (D86) and, for a theme's term, the theme's colour. */
  entity?: (id: number) => { ref: EntityRef; color?: TagColor } | undefined;
  /** A signal's name (D136) and, for a theme's word field, the theme's colour; without it the
   *  name of a term signal is its theme key. */
  signal?: (key: SignalKey) => { name: string; color?: TagColor };
  /** The summary of a calendar event (D155), by its UID. */
  event?: (uid: string) => string | undefined;
  /** An AI tag's label (D309), by its id. */
  aiTag?: (id: number) => string | undefined;
  /** A theme's name and colour (D309), by its key. */
  aiTheme?: (key: string) => { name: string; color?: TagColor } | undefined;
}

/** The kinds of calendar mails (D155), also in the filter column and the detail card. */
export const EVENT_LABELS: Record<EventKey, string> = {
  request: "Einladung",
  reply: "Antwort",
  cancel: "Absage",
};

const day = (value: string) => (/^\d{4}-\d{2}-\d{2}$/.test(value) ? formatDay(value) : value);

const TERM_LABELS: Record<QueryKey, (value: string) => string> = {
  text: (value) => `Volltext: „${value}“`,
  from: (value) => `from: ${value}`,
  to: (value) => `to: ${value}`,
  cc: (value) => `cc: ${value}`,
  subject: (value) => `Betreff: „${value}“`,
  domain: (value) => `Domain: ${value}`,
  has: () => "Mit Anhang",
  dkim: (value) => `DKIM: ${DKIM_FILTER_LABELS[value as keyof typeof DKIM_FILTER_LABELS] ?? value}`,
  before: (value) => `vor ${day(value)}`,
  after: (value) => `ab ${day(value)}`,
  message_id: (value) => `Message-ID: ${value}`,
  in_subject: (value) => `Im Betreff: „${value}“`,
  in_body: (value) => `Im Mailtext: „${value}“`,
  in_attachment: (value) => `Im Anhangstext: „${value}“`,
  in_filename: (value) => `Im Dateinamen: „${value}“`,
  near: (value) => `Nah beieinander: „${value}“`,
};

/** A term as its chip names it: a minus before an operator reads "Nicht …" (D175), before a
 *  free word "Ohne: …", since the full text search leaves out what it excludes. */
function termLabel(term: QueryTerm): string {
  if (term.key === "text" && term.value.length > 1 && term.value.startsWith("-")) {
    return `Ohne: „${term.value.slice(1)}“`;
  }
  const label =
    term.key === "near" && term.distance
      ? `${TERM_LABELS.near(term.value)} (höchstens ${formatNumber(term.distance)} Wörter dazwischen)`
      : TERM_LABELS[term.key](term.value);
  return term.negated
    ? `Nicht ${label.replace(/^(Mit|Im) /, (word) => word.toLowerCase())}`
    : label;
}

/** The places of q's free words (D171), as the filter column and the chips name them. */
export const SEARCH_FIELD_LABELS: Record<SearchField, string> = {
  subject: "Betreff",
  body: "Mailtext",
  attachment: "Anhangstext",
  filename: "Dateiname",
};

/** The tabs of a person's mail list (D32), also in the person's chip. */
export const PERSON_ROLE_LABELS: Record<PersonRole, string> = {
  sent: "Gesendet",
  received: "Empfangen",
  cc: "Nur Cc",
};

const BOOLEAN_LABELS = [
  ["has_attachment", "Mit Anhang"],
  ["in_thread", "Teil eines Threads"],
  ["external", "Nur extern ↔ intern"],
  ["hide_duplicates", "Ohne Doppelte"],
  ["flagged", "Nur markierte"],
  ["has_note", "Mit Notiz"],
  ["collapse_near", "Dubletten zusammengefasst"],
] as const;

function shortList(values: string[]): string {
  return values.length > 2
    ? `${values.slice(0, 2).join(", ")} +${values.length - 2}`
    : values.join(", ");
}

/** The chips of state. terms are the page's query_terms; those that no longer occur in q (a page
 *  still loading for a new query) are left out, and q gets one chip of its own while no term is
 *  known. */
export function filterChips(state: ListState, terms: QueryTerm[], names: ChipNames): FilterChip[] {
  const known = terms.filter((term) => state.q.includes(term.raw));
  const chips: FilterChip[] = known.map((term, index) => ({
    id: `term-${index}`,
    label: termLabel(term),
    next: withFilters(state, { q: removeTerm(state.q, term.raw) }),
  }));
  if (state.q && known.length === 0) {
    chips.push({ id: "q", label: `Suche: „${state.q}“`, next: withFilters(state, { q: "" }) });
  }
  // The search options (D177), next to the words they act on.
  if (state.scope.length) {
    chips.push({
      id: "scope",
      label: `Nur in: ${state.scope.map((key) => SEARCH_FIELD_LABELS[key]).join(", ")}`,
      next: withFilters(state, { scope: [] }),
    });
  }
  if (state.whole_word) {
    chips.push({
      id: "whole_word",
      label: "Ganzes Wort",
      next: withFilters(state, { whole_word: false }),
    });
  }
  if (state.min_hits !== null) {
    chips.push({
      id: "min_hits",
      label: `Mindestens ${formatNumber(state.min_hits)} Treffer`,
      next: withFilters(state, { min_hits: null }),
    });
  }
  // Milestone 18: the parts of the text searched (D226), hidden mails (D222), a paragraph (D227).
  if (state.body_part !== "clean") {
    chips.push({
      id: "body_part",
      label: state.body_part === "own" ? "Nur selbst Geschriebenes" : "Auch Standardblöcke",
      next: withFilters(state, { body_part: "clean" }),
    });
  }
  if (state.include_hidden) {
    chips.push({
      id: "include_hidden",
      label: "Mit ausgeblendeten Mails",
      next: withFilters(state, { include_hidden: false }),
    });
  }
  if (state.block) {
    chips.push({
      id: "block",
      label: "Enthält einen Standardblock",
      next: withFilters(state, { block: null }),
    });
  }
  if (state.dkim.length) {
    chips.push({
      id: "dkim",
      label: `DKIM: ${state.dkim.map((key) => DKIM_FILTER_LABELS[key]).join(", ")}`,
      next: withFilters(state, { dkim: [] }),
    });
  }
  if (state.sender_domain.length) {
    chips.push({
      id: "sender_domain",
      label: `Absender-Domain: ${shortList(state.sender_domain)}`,
      next: withFilters(state, { sender_domain: [] }),
    });
  }
  if (state.date_from || state.date_to) {
    const from = state.date_from && formatDay(state.date_from);
    const to = state.date_to && formatDay(state.date_to);
    chips.push({
      id: "date",
      label: from && to ? `Zeitraum: ${from} – ${to}` : from ? `ab ${from}` : `bis ${to}`,
      next: withFilters(state, { date_from: null, date_to: null }),
    });
  }
  for (const [key, label] of BOOLEAN_LABELS) {
    if (state[key]) chips.push({ id: key, label, next: withFilters(state, { [key]: false }) });
  }
  if (state.mbox_file !== null) {
    chips.push({
      id: "mbox_file",
      label: `MBOX-Datei: ${names.mboxFile(state.mbox_file)}`,
      next: withFilters(state, { mbox_file: null }),
    });
  }
  for (const id of state.person) {
    const role = state.person_role ? ` · ${PERSON_ROLE_LABELS[state.person_role]}` : "";
    chips.push({
      id: `person-${id}`,
      label: `Person: ${names.person(id)}${role}`,
      next: withFilters(state, {
        person: state.person.filter((other) => other !== id),
        person_role: null,
      }),
    });
  }
  if (state.between.length) {
    chips.push({
      id: "between",
      label: `Zwischen ${state.between.map(names.person).join(" und ")}`,
      next: withFilters(state, { between: [] }),
    });
  }
  if (state.review.length) {
    chips.push({
      id: "review",
      label: `Status: ${state.review.map((key) => REVIEW_LABELS[key]).join(", ")}`,
      next: withFilters(state, { review: [] }),
    });
  }
  for (const id of state.tag) {
    const tag = names.tag(id);
    chips.push({
      id: `tag-${id}`,
      label: tag ? `Schlagwort: ${tag.name}` : `Schlagwort #${id}`,
      color: tag?.color,
      next: withFilters(state, { tag: state.tag.filter((other) => other !== id) }),
    });
  }
  for (const id of state.collection) {
    const name = names.collection(id);
    chips.push({
      id: `collection-${id}`,
      label: name ? `Akte: ${name}` : `Akte #${id}`,
      next: withFilters(state, { collection: state.collection.filter((other) => other !== id) }),
    });
  }
  if (state.document !== null) {
    chips.push({
      id: "document",
      label: `Dokument: ${names.document?.(state.document) ?? `#${state.document}`}`,
      next: withFilters(state, { document: null }),
    });
  }
  if (state.thread !== null) {
    const name = names.thread?.(state.thread);
    chips.push({
      id: "thread",
      label: name ? `Thread: ${name}` : `Thread #${state.thread}`,
      next: withFilters(state, { thread: null }),
    });
  }
  for (const id of state.entity) {
    const entity = names.entity?.(id);
    chips.push({
      id: `entity-${id}`,
      label: entity ? `${KIND_LABELS[entity.ref.kind].one}: ${entity.ref.label}` : `Entität #${id}`,
      color: entity?.color,
      next: withFilters(state, { entity: state.entity.filter((other) => other !== id) }),
    });
  }
  if (state.amount_min !== null) {
    chips.push({
      id: "amount_min",
      label: `Betrag ab ${formatNumber(state.amount_min)}`,
      next: withFilters(state, { amount_min: null }),
    });
  }
  for (const key of state.amount_context) {
    chips.push({
      id: `amount_context-${key}`,
      label: `Betrag: ${CONTEXT_LABELS[key]}`,
      next: withFilters(state, {
        amount_context: state.amount_context.filter((other) => other !== key),
      }),
    });
  }
  for (const key of state.signal) {
    const signal = names.signal?.(key);
    chips.push({
      id: `signal-${key}`,
      label: `Signal: ${signal?.name ?? signalName(key)}`,
      color: signal?.color,
      next: withFilters(state, { signal: state.signal.filter((other) => other !== key) }),
    });
  }
  if (state.near_group !== null) {
    chips.push({
      id: "near_group",
      label: "Nahezu gleiche Mails",
      next: withFilters(state, { near_group: null }),
    });
  }
  if (state.event.length) {
    chips.push({
      id: "event",
      label: `Termine: ${state.event.map((key) => EVENT_LABELS[key]).join(", ")}`,
      next: withFilters(state, { event: [] }),
    });
  }
  if (state.event_uid) {
    const summary = names.event?.(state.event_uid);
    chips.push({
      id: "event_uid",
      label: summary ? `Termin: ${summary}` : "Ein Termin",
      next: withFilters(state, { event_uid: null }),
    });
  }
  // Milestone 17 (D309): what the summaries say, machine made (D311).
  for (const id of state.ai_tag) {
    const label = names.aiTag?.(id);
    chips.push({
      id: `ai_tag-${id}`,
      label: label ? `KI-Schlagwort: ${label}` : `KI-Schlagwort #${id}`,
      next: withFilters(state, { ai_tag: state.ai_tag.filter((other) => other !== id) }),
    });
  }
  for (const key of state.ai_theme) {
    const theme = names.aiTheme?.(key);
    chips.push({
      id: `ai_theme-${key}`,
      label: `KI-Thema: ${theme?.name ?? key}`,
      color: theme?.color,
      next: withFilters(state, { ai_theme: state.ai_theme.filter((other) => other !== key) }),
    });
  }
  // The view of the page "Orte" (D248).
  if (state.photo_area) {
    chips.push({
      id: "photo_area",
      label: "Fotos im Kartenausschnitt",
      next: withFilters(state, { photo_area: null }),
    });
  }
  return chips;
}
