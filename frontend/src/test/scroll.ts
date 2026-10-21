import { act } from "@testing-library/react";
import { vi } from "vitest";

/** Where an observed element is: scrolled out of the window at the top, in it, or below it. */
export type Place = "above" | "visible" | "below";

/** An IntersectionObserver for jsdom, which has none, stubbed until the test ends: place tells
 *  every observer where its elements now are, as the browser's would after scrolling. */
export function stubIntersectionObserver(): { place: (where: Place) => void } {
  const observers = new Set<{ callback: IntersectionObserverCallback; elements: Element[] }>();
  class Observer {
    private readonly entry: { callback: IntersectionObserverCallback; elements: Element[] };
    constructor(callback: IntersectionObserverCallback) {
      this.entry = { callback, elements: [] };
      observers.add(this.entry);
    }
    observe(element: Element) {
      this.entry.elements.push(element);
    }
    disconnect() {
      observers.delete(this.entry);
    }
  }
  vi.stubGlobal("IntersectionObserver", Observer);
  return {
    place(where) {
      const top = { above: -400, visible: 80, below: 2000 }[where];
      act(() => {
        for (const { callback, elements } of observers) {
          const entries = elements.map(
            (target) =>
              ({
                target,
                isIntersecting: where === "visible",
                boundingClientRect: { top },
              }) as unknown as IntersectionObserverEntry,
          );
          callback(entries, {} as IntersectionObserver);
        }
      });
    },
  };
}
