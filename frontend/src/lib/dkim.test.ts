import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import {
  DKIM_FILTER_LABELS,
  DKIM_KEYS,
  DKIM_REASON_TEXTS,
  DKIM_STATUS_LABELS,
  dkimKey,
} from "./dkim";

// The backend's vocabulary, read from the Python enums so a new status or reason code there
// cannot go without a German text here.
const here = dirname(fileURLToPath(import.meta.url));
const enums = readFileSync(join(here, "../../../src/mailrobbe/enums.py"), "utf8");

function enumValues(name: string): string[] {
  const body = enums.split(`class ${name}(StrEnum):`)[1].split(/\n\S/)[0];
  return [...body.matchAll(/^ {4}[A-Z_]+ = "([a-z_]+)"/gm)].map((match) => match[1]);
}

describe("DKIM texts", () => {
  it("cover every status of the backend plus unchecked", () => {
    const statuses = enumValues("DkimStatus");
    expect(statuses).toHaveLength(6);
    const keys = [...statuses, "unchecked"].sort();
    expect([...DKIM_KEYS].sort()).toEqual(keys);
    expect(Object.keys(DKIM_FILTER_LABELS).sort()).toEqual(keys);
    expect(Object.keys(DKIM_STATUS_LABELS).sort()).toEqual(keys);
  });

  it("cover every reason code of the backend", () => {
    const reasons = enumValues("DkimReason");
    expect(reasons).toHaveLength(13);
    expect(Object.keys(DKIM_REASON_TEXTS).sort()).toEqual([...reasons].sort());
    for (const text of Object.values(DKIM_REASON_TEXTS)) expect(text.trim()).not.toBe("");
  });

  it("label the statuses in German", () => {
    expect(DKIM_STATUS_LABELS.pass).toBe("DKIM gültig");
    expect(DKIM_FILTER_LABELS.no_key).toBe("Schlüssel nicht abrufbar");
    expect(DKIM_REASON_TEXTS.key_not_found).toBe("Schlüssel nicht im DNS (Selector gelöscht)");
    expect(dkimKey(null)).toBe("unchecked");
    expect(dkimKey("fail")).toBe("fail");
  });
});
