// The editor's name (D54): asked for once, kept in this browser and sent with every write as
// X-Mailrobbe-Editor, so notes and marks have an author. No account, no password.

import { useSyncExternalStore } from "react";

export const EDITOR_HEADER = "X-Mailrobbe-Editor";
export const EDITOR_LIMIT = 100;
const STORAGE_KEY = "mailrobbe.editor";

const listeners = new Set<() => void>();
let fallback = ""; // when the browser keeps no storage (private window, blocked site data)

export function getEditor(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? fallback;
  } catch {
    return fallback;
  }
}

/** Stores the name, trimmed and cut to EDITOR_LIMIT; an empty name forgets it. */
export function setEditor(name: string): void {
  const value = name.trim().replace(/\s+/g, " ").slice(0, EDITOR_LIMIT);
  fallback = value;
  try {
    if (value) window.localStorage.setItem(STORAGE_KEY, value);
    else window.localStorage.removeItem(STORAGE_KEY);
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

/** The current editor name ("" when none is set), updated when it changes in any tab. */
export function useEditor(): string {
  return useSyncExternalStore(subscribe, getEditor, () => "");
}

/** Header value of the name: percent-encoded, since header values are Latin-1. */
export function editorHeader(name: string): string {
  return encodeURIComponent(name);
}
