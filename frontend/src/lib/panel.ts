// Where the preview panel stands and how large it is (D337): at the right of a list or along the
// bottom, dragged wider or taller by its edge. Kept in this browser's localStorage, like the
// sidebar's state; the same for the mail list and the attachment list.

import { useSyncExternalStore } from "react";

export type PanelPlace = "right" | "bottom";

export interface PanelLayout {
  place: PanelPlace;
  /** Width at the right, in pixels; null is --panel-width. */
  width: number | null;
  /** Height along the bottom, in pixels; null is 45 % of the window. */
  height: number | null;
}

const STORAGE_KEY = "mailrobbe.panel";
const DEFAULT: PanelLayout = { place: "right", width: null, height: null };

const listeners = new Set<() => void>();
let fallback: PanelLayout = DEFAULT; // when the browser keeps no storage
let cache: { raw: string | null; layout: PanelLayout } = { raw: null, layout: DEFAULT };

function size(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

/** The stored layout; the same object while the storage is unchanged. */
export function readPanelLayout(): PanelLayout {
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return fallback;
  }
  if (raw === cache.raw) return cache.layout;
  let layout = DEFAULT;
  try {
    const parsed = JSON.parse(raw ?? "{}") as Record<string, unknown> | null;
    if (parsed && typeof parsed === "object") {
      layout = {
        place: parsed.place === "bottom" ? "bottom" : "right",
        width: size(parsed.width),
        height: size(parsed.height),
      };
    }
  } catch {
    layout = DEFAULT; // unreadable: the default
  }
  cache = { raw, layout };
  return layout;
}

/** Changes part of the layout and tells every panel. */
export function setPanelLayout(change: Partial<PanelLayout>): void {
  const layout = { ...readPanelLayout(), ...change };
  fallback = layout;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
  } catch {
    // kept in memory for this page only
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const storage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY) listener();
  };
  window.addEventListener("storage", storage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", storage);
  };
}

export function usePanelLayout(): PanelLayout {
  return useSyncExternalStore(subscribe, readPanelLayout, () => DEFAULT);
}

/** Keeps a dragged size between a minimum and a maximum. */
export function clampSize(value: number, min: number, max: number): number {
  return Math.round(Math.min(Math.max(value, min), Math.max(min, max)));
}
