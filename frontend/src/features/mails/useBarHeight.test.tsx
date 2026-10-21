import { act, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { useBarHeight } from "./useBarHeight";

function Page() {
  const bar = useBarHeight<HTMLDivElement>();
  return (
    <main data-testid="main">
      <div ref={bar} data-testid="bar" />
    </main>
  );
}

describe("useBarHeight", () => {
  it("keeps the sticky bar's height on its parent for the table's head", () => {
    const resized: (() => void)[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          resized.push(callback);
        }
        observe() {}
        disconnect() {}
      },
    );
    const { getByTestId, unmount } = render(<Page />);
    const main = getByTestId("main");
    Object.defineProperty(getByTestId("bar"), "offsetHeight", { value: 52, configurable: true });
    act(() => resized[0]());
    expect(main.style.getPropertyValue("--list-bar")).toBe("52px");

    Object.defineProperty(getByTestId("bar"), "offsetHeight", { value: 96, configurable: true });
    act(() => resized[0]());
    expect(main.style.getPropertyValue("--list-bar")).toBe("96px");
    unmount();
    expect(main.style.getPropertyValue("--list-bar")).toBe("");
  });

  it("leaves the property unset without a ResizeObserver", () => {
    vi.stubGlobal("ResizeObserver", undefined);
    const { getByTestId } = render(<Page />);
    expect(getByTestId("main").style.getPropertyValue("--list-bar")).toBe("");
  });
});
