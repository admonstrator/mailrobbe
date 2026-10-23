import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { readPanelLayout } from "../lib/panel";
import { SidePanel } from "./SidePanel";

describe("SidePanel", () => {
  beforeEach(() => {
    window.localStorage.clear();
    // jsdom has no ResizeObserver; the panel along the bottom watches the list's width with one.
    vi.stubGlobal(
      "ResizeObserver",
      class {
        observe() {}
        disconnect() {}
      },
    );
  });

  it("closes on Esc", () => {
    const onClose = vi.fn();
    render(
      <SidePanel label="Vorschau" onClose={onClose}>
        Inhalt
      </SidePanel>,
    );
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("moves a movable panel down and back, and resizes it by keyboard", () => {
    render(
      <div>
        <SidePanel label="Vorschau" onClose={() => undefined} movable>
          Inhalt
        </SidePanel>
      </div>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Vorschau unten anzeigen" }));
    expect(readPanelLayout().place).toBe("bottom");
    const edge = screen.getByRole("separator", { name: "Höhe der Vorschau ändern" });
    const before = readPanelLayout().height ?? Math.round(window.innerHeight * 0.45);
    fireEvent.keyDown(edge, { key: "ArrowUp" });
    expect(readPanelLayout().height).toBe(before + 32);
    fireEvent.click(screen.getByRole("button", { name: "Vorschau rechts anzeigen" }));
    expect(readPanelLayout().place).toBe("right");
    expect(screen.getByRole("separator", { name: "Breite der Vorschau ändern" })).toBeTruthy();
  });

  it("shows neither edge nor place button on a panel that does not move", () => {
    render(
      <SidePanel label="Einblicke" onClose={() => undefined}>
        Inhalt
      </SidePanel>,
    );
    expect(screen.queryByRole("separator")).toBeNull();
    expect(screen.queryByRole("button", { name: /Vorschau/ })).toBeNull();
  });
});
