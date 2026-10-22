// Which blocks of a detail page are folded: kept in this browser per block, so a block folded
// once stays folded on every mail until it is opened again.

import { useSyncExternalStore } from "react";

const STORAGE_KEY = "mailrobbe.folds";

const listeners = new Set<() => void>();
let fallback: Record<string, boolean> = {}; // when the browser keeps no storage

function readFolds(): Record<string, boolean> {
  let stored: string | null;
  try {
    stored = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return fallback;
  }
  try {
    const folds: unknown = JSON.parse(stored ?? "{}");
    if (folds === null || typeof folds !== "object" || Array.isArray(folds)) return {};
    return Object.fromEntries(
      Object.entries(folds).filter((entry): entry is [string, boolean] => {
        return typeof entry[1] === "boolean";
      }),
    );
  } catch {
    return {}; // unreadable: every block as it starts
  }
}

/** Whether the block is open: as last set in this browser, else `byDefault`. */
function isOpen(id: string, byDefault: boolean): boolean {
  return readFolds()[id] ?? byDefault;
}

export function setFoldOpen(id: string, open: boolean): void {
  const folds = { ...readFolds(), [id]: open };
  fallback = folds;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(folds));
  } catch {
    // kept in memory for this page only
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

/** The block's open state and the way to change it; every block of the same id follows. */
export function useFold(id: string, byDefault: boolean): [boolean, (open: boolean) => void] {
  const open = useSyncExternalStore(
    subscribe,
    () => isOpen(id, byDefault),
    () => byDefault,
  );
  return [open, (next: boolean) => setFoldOpen(id, next)];
}
