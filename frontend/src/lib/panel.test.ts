import { beforeEach, describe, expect, it } from "vitest";

import { clampSize, readPanelLayout, setPanelLayout } from "./panel";

describe("panel layout", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("starts at the right with the default sizes", () => {
    expect(readPanelLayout()).toEqual({ place: "right", width: null, height: null });
  });

  it("keeps a change and the parts not changed", () => {
    setPanelLayout({ width: 600 });
    setPanelLayout({ place: "bottom", height: 300 });
    expect(readPanelLayout()).toEqual({ place: "bottom", width: 600, height: 300 });
  });

  it("reads an unreadable storage as the default", () => {
    window.localStorage.setItem("mailrobbe.panel", '{"place":"left","width":-4');
    expect(readPanelLayout().place).toBe("right");
    window.localStorage.setItem("mailrobbe.panel", '{"place":"left","width":-4}');
    expect(readPanelLayout()).toEqual({ place: "right", width: null, height: null });
  });

  it("keeps a dragged size within its limits", () => {
    expect(clampSize(100, 320, 900)).toBe(320);
    expect(clampSize(1200, 320, 900)).toBe(900);
    expect(clampSize(500.4, 320, 900)).toBe(500);
    expect(clampSize(500, 320, 200)).toBe(320); // too narrow a window: the minimum
  });
});
