// The visit history "Zuletzt angesehen" (D333): the last mails, persons, documents and Akten
// opened in this browser, newest first. Kept in localStorage only; nothing goes to the server.

import { useEffect, useSyncExternalStore } from "react";

export type VisitKind = "mail" | "person" | "document" | "akte";

export interface Visit {
  kind: VisitKind;
  id: number;
  /** What the entry is called: a mail's subject, a person's name, a file name, an Akte's title. */
  title: string;
  /** One quiet line below the title: sender and date, an address, the mail a file came with. */
  subtitle?: string;
  /** Where the entry leads, a path of this app. */
  path: string;
  /** When it was opened, milliseconds since the epoch. */
  at: number;
}

const STORAGE_KEY = "mailrobbe.history";
export const HISTORY_LIMIT = 100;

const listeners = new Set<() => void>();
let fallback: Visit[] = []; // when the browser keeps no storage
let cache: { raw: string | null; visits: Visit[] } = { raw: null, visits: [] };

const KINDS: readonly string[] = ["mail", "person", "document", "akte"];

function isVisit(value: unknown): value is Visit {
  if (value === null || typeof value !== "object") return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.kind === "string" &&
    KINDS.includes(v.kind) &&
    typeof v.id === "number" &&
    typeof v.title === "string" &&
    typeof v.path === "string" &&
    typeof v.at === "number" &&
    (v.subtitle === undefined || typeof v.subtitle === "string")
  );
}

/** The stored visits, newest first; the same array while the storage is unchanged. */
export function readHistory(): Visit[] {
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return fallback;
  }
  if (raw === cache.raw) return cache.visits;
  let visits: Visit[] = [];
  try {
    const parsed: unknown = JSON.parse(raw ?? "[]");
    if (Array.isArray(parsed)) visits = parsed.filter(isVisit);
  } catch {
    visits = []; // unreadable: an empty history
  }
  cache = { raw, visits };
  return visits;
}

function write(visits: Visit[]): void {
  fallback = visits;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(visits));
  } catch {
    // kept in memory for this page only
  }
  for (const listener of listeners) listener();
}

/** Puts a visit first; an earlier visit of the same entry is dropped, the list keeps 100. */
export function recordVisit(visit: Omit<Visit, "at"> & { at?: number }): void {
  const entry: Visit = { ...visit, at: visit.at ?? Date.now() };
  const rest = readHistory().filter((v) => !(v.kind === entry.kind && v.id === entry.id));
  write([entry, ...rest].slice(0, HISTORY_LIMIT));
}

export function removeVisit(kind: VisitKind, id: number): void {
  write(readHistory().filter((v) => !(v.kind === kind && v.id === id)));
}

export function clearHistory(): void {
  write([]);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

/** The visits, newest first, following every change in this and other tabs. */
export function useHistory(): Visit[] {
  return useSyncExternalStore(subscribe, readHistory, () => fallback);
}

/** Records the page's entry once it is known (pass null while loading). Pages of a mail, a
 *  person, a document and an Akte call this with what they show. */
export function useRecordVisit(visit: Omit<Visit, "at"> | null): void {
  const key = visit ? `${visit.kind}:${visit.id}:${visit.title}:${visit.subtitle ?? ""}` : "";
  useEffect(() => {
    if (visit) recordVisit(visit);
    // the key holds everything the entry shows
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}
