// The active filters above the table: one chip per search term and per sidebar filter, each
// with the list state that removing it leads to.

import type { PersonRole, QueryKey, QueryTerm } from "../../api/types";
import { DKIM_FILTER_LABELS } from "../../lib/dkim";
import { formatDay } from "../../lib/format";
import { withFilters, type ListState } from "./listState";
import { removeTerm } from "./queryText";

export interface FilterChip {
  id: string;
  label: string;
  next: ListState;
}

/** Display names for ids the list state carries. */
export interface ChipNames {
  person: (id: number) => string;
  mboxFile: (id: number) => string;
  document?: (id: number) => string;
}

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
    label: TERM_LABELS[term.key](term.value),
    next: withFilters(state, { q: removeTerm(state.q, term.raw) }),
  }));
  if (state.q && known.length === 0) {
    chips.push({ id: "q", label: `Suche: „${state.q}“`, next: withFilters(state, { q: "" }) });
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
  if (state.document !== null) {
    chips.push({
      id: "document",
      label: `Dokument: ${names.document?.(state.document) ?? `#${state.document}`}`,
      next: withFilters(state, { document: null }),
    });
  }
  return chips;
}
