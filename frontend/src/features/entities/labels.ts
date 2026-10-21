// German names of the entities (D80 to D89): kinds singular and plural, the groups the list's
// tabs and the facets show, the contexts of amounts and accounts, and the small texts beside an
// entity. The one place the screens, the facets, the chips and the mail detail take them from.

import type { EntityContextKey, EntityKind, EntityRef, ThemeInfo } from "../../api/types";
import { formatNumber } from "../../lib/format";

/** Every kind, in the order the screens list them. */
export const ENTITY_KINDS: readonly EntityKind[] = [
  "amount",
  "iban",
  "account",
  "organization",
  "person",
  "place",
  "phone",
  "email",
  "url",
  "domain",
  "date",
  "term",
];

export const KIND_LABELS: Record<EntityKind, { one: string; many: string }> = {
  amount: { one: "Betrag", many: "Beträge" },
  iban: { one: "IBAN", many: "IBANs" },
  account: { one: "Kontonummer", many: "Kontonummern" },
  organization: { one: "Organisation", many: "Organisationen" },
  person: { one: "Person im Text", many: "Personen im Text" },
  place: { one: "Ort", many: "Orte" },
  phone: { one: "Telefonnummer", many: "Telefonnummern" },
  email: { one: "E-Mail-Adresse", many: "E-Mail-Adressen im Text" },
  url: { one: "Link", many: "Links" },
  domain: { one: "Domain", many: "Domains" },
  date: { one: "Datum", many: "Daten im Text" },
  term: { one: "Themenbegriff", many: "Themenbegriffe" },
};

/** The kinds shown together: a tab of the entity list, a block of the facets and of the mail
 *  detail's card. Accounts are IBANs and account numbers, Web is links and their domains. */
export type EntityGroup =
  | "amount"
  | "accounts"
  | "organization"
  | "person"
  | "place"
  | "phone"
  | "email"
  | "web"
  | "date"
  | "term";

export const GROUP_KINDS: Record<EntityGroup, readonly EntityKind[]> = {
  amount: ["amount"],
  accounts: ["iban", "account"],
  organization: ["organization"],
  person: ["person"],
  place: ["place"],
  phone: ["phone"],
  email: ["email"],
  web: ["url", "domain"],
  date: ["date"],
  term: ["term"],
};

export const GROUP_LABELS: Record<EntityGroup, string> = {
  amount: "Beträge",
  accounts: "Konten",
  organization: "Organisationen",
  person: "Personen",
  place: "Orte",
  phone: "Telefon",
  email: "E-Mail",
  web: "Web",
  date: "Daten",
  term: "Themenbegriffe",
};

/** The groups in kind order: the tabs of the entity list and the blocks of the mail detail. */
export const ENTITY_GROUPS: readonly EntityGroup[] = [
  "amount",
  "accounts",
  "organization",
  "person",
  "place",
  "phone",
  "email",
  "web",
  "date",
  "term",
];

/** The facets beside the mail list start with the signposts of the research: the themes' terms,
 *  then money (D64, D82); contact data and dates come last. */
export const FACET_GROUPS: readonly EntityGroup[] = [
  "term",
  "amount",
  "accounts",
  "organization",
  "person",
  "place",
  "web",
  "email",
  "phone",
  "date",
];

export function groupOf(kind: EntityKind): EntityGroup {
  return ENTITY_GROUPS.find((group) => GROUP_KINDS[group].includes(kind)) ?? "term";
}

export const ENTITY_CONTEXTS: readonly EntityContextKey[] = ["cash", "donation", "receipt"];

export const CONTEXT_LABELS: Record<EntityContextKey, string> = {
  cash: "Bargeld",
  donation: "Spende",
  receipt: "Quittung",
};

/** The entity page's buttons to the mail list with one context (D86). */
export const CONTEXT_LINK_LABELS: Record<EntityContextKey, string> = {
  cash: "Nur Mails mit Bargeld-Bezug",
  donation: "Nur Mails mit Spenden-Bezug",
  receipt: "Nur Mails mit Quittungs-Bezug",
};

/** Kinds that carry contexts (D82). */
export function hasContexts(kind: EntityKind): boolean {
  return kind === "amount" || kind === "iban" || kind === "account";
}

/** The theme of a term (its detail is the theme's key, D83); undefined for other kinds or while
 *  the themes load. */
export function themeOf(
  entity: Pick<EntityRef, "kind" | "detail">,
  themes: ThemeInfo[] | undefined,
): ThemeInfo | undefined {
  if (entity.kind !== "term" || !entity.detail) return undefined;
  return themes?.find((theme) => theme.key === entity.detail);
}

let regionNames: Intl.DisplayNames | null | undefined;

/** "Deutschland" for "DE": the country of an IBAN or a phone number; the code itself where the
 *  browser knows no name. */
export function countryName(code: string): string {
  if (regionNames === undefined) {
    try {
      regionNames = new Intl.DisplayNames(["de"], { type: "region" });
    } catch {
      regionNames = null;
    }
  }
  try {
    return regionNames?.of(code.toUpperCase()) ?? code;
  } catch {
    return code;
  }
}

/** The country code an entity's detail names, for IBANs and phone numbers. */
export function countryOf(entity: Pick<EntityRef, "kind" | "detail">): string | null {
  return (entity.kind === "iban" || entity.kind === "phone") && entity.detail
    ? entity.detail
    : null;
}

/** "1 Mail", "1.024 Mails" */
export function mailsText(mails: number): string {
  return `${formatNumber(mails)} ${mails === 1 ? "Mail" : "Mails"}`;
}

/** "1 Dokument", "3 Dokumente" */
export function documentsText(documents: number): string {
  return `${formatNumber(documents)} ${documents === 1 ? "Dokument" : "Dokumente"}`;
}

/** "Entitäten werden beim nächsten Import ergänzt: 12.000 Mails und 40 Dokumente sind noch nicht
 *  ausgewertet." Null when nothing waits. */
export function waitingText(mails: number, documents: number): string | null {
  const parts = [mails > 0 && mailsText(mails), documents > 0 && documentsText(documents)].filter(
    Boolean,
  );
  if (parts.length === 0) return null;
  const verb = parts.length === 1 && (mails === 1 || documents === 1) ? "ist" : "sind";
  return `Entitäten werden beim nächsten Import ergänzt: ${parts.join(" und ")} ${verb} noch nicht ausgewertet.`;
}
