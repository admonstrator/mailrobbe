// Light or dark (D338): the choice of this browser, "system" following the operating system.
// The resolved theme stands as data-theme on <html>, which global.css reads.

import { useSyncExternalStore } from "react";

export type ThemeChoice = "light" | "dark" | "system";

const STORAGE_KEY = "mailrobbe.theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";
export const THEME_ORDER: readonly ThemeChoice[] = ["system", "light", "dark"];

const listeners = new Set<() => void>();
let fallback: ThemeChoice = "system"; // when the browser keeps no storage

export function readTheme(): ThemeChoice {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw === "light" || raw === "dark" ? raw : raw === null ? fallback : "system";
  } catch {
    return fallback;
  }
}

function systemDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(DARK_QUERY).matches;
}

/** Sets data-theme on <html> from the stored choice and the system. */
export function applyTheme(): void {
  const choice = readTheme();
  const dark = choice === "dark" || (choice === "system" && systemDark());
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

export function setTheme(choice: ThemeChoice): void {
  fallback = choice;
  try {
    window.localStorage.setItem(STORAGE_KEY, choice);
  } catch {
    // kept in memory for this page only
  }
  applyTheme();
  for (const listener of listeners) listener();
}

/** Applies the theme now and whenever the system or another tab changes it. Call once. */
export function watchTheme(): void {
  applyTheme();
  if (typeof window.matchMedia === "function") {
    window.matchMedia(DARK_QUERY).addEventListener("change", applyTheme);
  }
  window.addEventListener("storage", (event) => {
    if (event.key !== STORAGE_KEY) return;
    applyTheme();
    for (const listener of listeners) listener();
  });
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useTheme(): ThemeChoice {
  return useSyncExternalStore(subscribe, readTheme, () => "system");
}
