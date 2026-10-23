import { beforeEach, describe, expect, it } from "vitest";

import { applyTheme, readTheme, setTheme } from "./theme";

describe("theme", () => {
  beforeEach(() => {
    window.localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("follows the system until a choice is stored", () => {
    expect(readTheme()).toBe("system");
    applyTheme();
    expect(document.documentElement.dataset.theme).toBe("light"); // jsdom: no dark system
  });

  it("sets data-theme from the choice", () => {
    setTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(readTheme()).toBe("dark");
    setTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("reads an unknown stored value as the system", () => {
    window.localStorage.setItem("mailrobbe.theme", "sepia");
    expect(readTheme()).toBe("system");
  });
});
