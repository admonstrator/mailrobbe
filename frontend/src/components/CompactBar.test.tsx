import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CompactBar, useScrolledPast } from "./CompactBar";

function Probe() {
  const [ref, past] = useScrolledPast<HTMLDivElement>();
  return <div ref={ref}>{past ? "vorbei" : "sichtbar"}</div>;
}

/** An IntersectionObserver that keeps its options and reports one element at a given top. */
function stubObserver() {
  const seen: { callback: IntersectionObserverCallback; options?: IntersectionObserverInit }[] = [];
  class Observer {
    constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
      seen.push({ callback, options });
    }
    observe() {}
    disconnect() {}
  }
  vi.stubGlobal("IntersectionObserver", Observer);
  return {
    seen,
    at(top: number, isIntersecting: boolean) {
      act(() =>
        seen[0].callback(
          [{ isIntersecting, boundingClientRect: { top } } as unknown as IntersectionObserverEntry],
          {} as IntersectionObserver,
        ),
      );
    },
  };
}

describe("useScrolledPast", () => {
  afterEach(() => document.documentElement.style.removeProperty("--sticky-top"));

  it("counts an element under the shell's sticky header as scrolled past", () => {
    document.documentElement.style.setProperty("--sticky-top", "56px");
    const observer = stubObserver();
    render(<Probe />);
    expect(observer.seen[0].options?.rootMargin).toBe("-56px 0px 0px 0px");

    observer.at(30, false);
    expect(screen.getByText("vorbei")).toBeTruthy();
    observer.at(120, true);
    expect(screen.getByText("sichtbar")).toBeTruthy();
    // Out of view below the window: not past.
    observer.at(2000, false);
    expect(screen.getByText("sichtbar")).toBeTruthy();
  });

  it("takes the window's top without a sticky header", () => {
    const observer = stubObserver();
    render(<Probe />);
    expect(observer.seen[0].options?.rootMargin).toBe("0px 0px 0px 0px");
    observer.at(30, false);
    expect(screen.getByText("sichtbar")).toBeTruthy();
    observer.at(-10, false);
    expect(screen.getByText("vorbei")).toBeTruthy();
  });
});

describe("CompactBar", () => {
  it("spans the white sheet inside the shell's main, else the window", () => {
    const rect = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({ left: 256, width: 1168 } as DOMRect);
    const { unmount } = render(
      <main>
        <CompactBar label="Kopfzeile">Betreff</CompactBar>
      </main>,
    );
    const bar = screen.getByRole("region", { name: "Kopfzeile" });
    expect(bar.style.left).toBe("256px");
    expect(bar.style.width).toBe("1168px");
    unmount();
    rect.mockRestore();

    render(<CompactBar label="Kopfzeile">Betreff</CompactBar>);
    expect(screen.getByRole("region", { name: "Kopfzeile" }).style.left).toBe("");
  });
});
