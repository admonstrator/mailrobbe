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
  KEY_ORIGIN_LABELS,
  KEY_ORIGIN_TEXTS,
  KEY_ORIGINS,
  KEY_SOURCE_LABELS,
  keyName,
  selectorPath,
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

  it("cover every key origin and lookup source of the backend", () => {
    const origins = enumValues("KeyOrigin");
    expect(origins).toEqual(["dns", "observed", "documented", "reconstructed"]);
    expect([...KEY_ORIGINS]).toEqual(origins);
    expect(Object.keys(KEY_ORIGIN_LABELS)).toEqual(origins);
    expect(Object.keys(KEY_ORIGIN_TEXTS)).toEqual(origins);
    const sources = enumValues("KeyLookupSource");
    expect(Object.keys(KEY_SOURCE_LABELS).sort()).toEqual([...sources].sort());
  });

  it("name a signature's selector page", () => {
    expect(keyName("S2019", "Nordlicht-GmbH.example")).toBe(
      "s2019._domainkey.nordlicht-gmbh.example",
    );
    expect(keyName(null, "nordlicht-gmbh.example")).toBeNull();
    expect(selectorPath("s2019._domainkey.nordlicht-gmbh.example")).toBe(
      "/import/selektoren/s2019._domainkey.nordlicht-gmbh.example",
    );
    expect(selectorPath("a/b._domainkey.x.example")).toBe(
      "/import/selektoren/a%2Fb._domainkey.x.example",
    );
  });

  it("label the statuses in German", () => {
    expect(DKIM_STATUS_LABELS.pass).toBe("DKIM gültig");
    expect(DKIM_FILTER_LABELS.no_key).toBe("Schlüssel nicht abrufbar");
    expect(DKIM_REASON_TEXTS.key_not_found).toBe("Schlüssel nicht im DNS (Selector gelöscht)");
    expect(dkimKey(null)).toBe("unchecked");
    expect(dkimKey("fail")).toBe("fail");
  });
});
