import { beforeEach, describe, expect, it } from "vitest";

import { clearHistory, HISTORY_LIMIT, readHistory, recordVisit, removeVisit } from "./history";

describe("history", () => {
  beforeEach(() => {
    window.localStorage.clear();
    clearHistory();
  });

  it("puts the newest visit first and drops an earlier visit of the same entry", () => {
    recordVisit({ kind: "mail", id: 1, title: "A", path: "/mails/1", at: 1 });
    recordVisit({ kind: "person", id: 1, title: "B", path: "/personen/1", at: 2 });
    recordVisit({ kind: "mail", id: 1, title: "A", path: "/mails/1", at: 3 });
    expect(readHistory().map((v) => `${v.kind}:${v.at}`)).toEqual(["mail:3", "person:2"]);
  });

  it("keeps at most the limit", () => {
    for (let i = 0; i < HISTORY_LIMIT + 5; i++) {
      recordVisit({ kind: "mail", id: i, title: String(i), path: `/mails/${i}`, at: i });
    }
    expect(readHistory()).toHaveLength(HISTORY_LIMIT);
    expect(readHistory()[0].id).toBe(HISTORY_LIMIT + 4);
  });

  it("removes one entry and clears all", () => {
    recordVisit({ kind: "akte", id: 2, title: "X", path: "/akten/2" });
    recordVisit({ kind: "document", id: 3, title: "Y", path: "/anhaenge/3" });
    removeVisit("akte", 2);
    expect(readHistory().map((v) => v.kind)).toEqual(["document"]);
    clearHistory();
    expect(readHistory()).toEqual([]);
  });

  it("ignores unreadable storage", () => {
    window.localStorage.setItem("mailrobbe.history", "{kaputt");
    expect(readHistory()).toEqual([]);
    window.localStorage.setItem("mailrobbe.history", JSON.stringify([{ kind: "x" }]));
    expect(readHistory()).toEqual([]);
  });
});
