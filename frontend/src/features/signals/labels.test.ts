import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { MAIL_SIGNAL_KINDS, type SignalSettings } from "../../api/types";
import { signalOverview } from "../../test/fixtures";
import {
  formatLocalTime,
  GROUP_NAMES,
  joinList,
  personSignalHref,
  shareText,
  SIGNAL_NAMES,
  signalAnchor,
  signalMailsHref,
  signalName,
  signalRule,
  signalTimelineHref,
  silentMonth,
} from "./labels";

// The backend's names, read from signals/model.py so the screens and the CSV name a signal alike.
const here = dirname(fileURLToPath(import.meta.url));
const model = readFileSync(join(here, "../../../../src/mailrobbe/signals/model.py"), "utf8");
const enums = readFileSync(join(here, "../../../../src/mailrobbe/enums.py"), "utf8");

function backendLabels(): Record<string, string> {
  const kinds = enums.split("class SignalKind(StrEnum):")[1].split(/\n\S/)[0];
  const values = Object.fromEntries(
    [...kinds.matchAll(/^ {4}([A-Z_]+) = "([a-z_]+)"/gm)].map((match) => [match[1], match[2]]),
  );
  const labels = model.split("LABELS: dict[SignalKind, str] = {")[1].split("\n}")[0];
  return Object.fromEntries(
    [...labels.matchAll(/SignalKind\.([A-Z_]+): "([^"]+)"/g)].map((match) => [
      values[match[1]],
      match[2],
    ]),
  );
}

const settings: SignalSettings = signalOverview.settings;
const KEYS = [...MAIL_SIGNAL_KINDS, "silent"] as const;

describe("signal names", () => {
  it("are the backend's for every kind and silent", () => {
    expect(SIGNAL_NAMES).toEqual(backendLabels());
    expect(Object.keys(SIGNAL_NAMES).sort()).toEqual([...KEYS].sort());
  });

  it("name a word field by its theme, or by its key while the name is unknown", () => {
    expect(signalName("term:spenden", "Spendenaffären")).toBe("Wortfeld Spendenaffären");
    expect(signalName("term:spenden")).toBe("Wortfeld spenden");
    expect(signalName("term:spenden", null)).toBe("Wortfeld spenden");
    expect(signalName("bcc", "ignored")).toBe("Blindkopie (Bcc)");
  });

  it("have a German name per group", () => {
    expect(Object.values(GROUP_NAMES)).toEqual([
      "Adressen",
      "Empfänger und Weiterleitungen",
      "Uhrzeit",
      "Wortfelder",
      "Personen",
    ]);
  });
});

describe("signal rules", () => {
  it("say every rule in one sentence, in neutral words", () => {
    for (const key of [...KEYS, "term:gewalt" as const]) {
      const rule = signalRule(key, settings);
      expect(rule).toMatch(/^[A-ZÄÖÜ].*\.$/);
      expect(rule).not.toMatch(/verdacht|verdächtig|risiko|score/i);
    }
    for (const name of Object.values(SIGNAL_NAMES)) {
      expect(name).not.toMatch(/verdacht|verdächtig|risiko|score/i);
    }
  });

  it("retell the settings: hours, zone, threshold, prefixes, providers", () => {
    expect(signalRule("night", settings)).toBe("Gesendet zwischen 22 und 6 Uhr (Europe/Berlin).");
    expect(signalRule("night", { ...settings, night_from: 0, night_to: 5 })).toBe(
      "Gesendet zwischen 0 und 5 Uhr (Europe/Berlin).",
    );
    expect(signalRule("weekend", { ...settings, timezone: "Europe/Zurich" })).toBe(
      "Gesendet an einem Samstag oder Sonntag (Europe/Zurich).",
    );
    expect(signalRule("many_recipients", settings)).toBe(
      "An mindestens 25 verschiedene Adressen in An, Cc und Bcc zusammen.",
    );
    expect(signalRule("forward", { ...settings, forward_prefixes: ["Fwd", "WG"] })).toBe(
      "Der Betreff beginnt mit Fwd: oder WG:, auch hinter Listen-Tags und Re: oder AW:, oder eine Mail hängt als Anhang an.",
    );
    expect(signalRule("private", settings)).toContain("(Liste mit 78 Domains)");
  });

  it("leave out what needs internal domains while there are none", () => {
    expect(signalRule("forward_out", settings)).toContain("außerhalb der internen Domains");
    expect(signalRule("forward_out", { ...settings, internal_domains: [] })).toBe(
      "Eine Weiterleitung an eine private Adresse.",
    );
  });
});

describe("signal texts and links", () => {
  it("show the local time as its string says, not in the browser's zone", () => {
    expect(formatLocalTime("2026-10-18T14:32:07+02:00")).toBe("So, 18.10.2026 14:32");
    // 23:41 in New York is 05:41 the next day in Berlin, the tests' zone.
    expect(formatLocalTime("2025-11-04T23:41:00-05:00")).toBe("Di, 04.11.2025 23:41");
    expect(formatLocalTime("gestern")).toBe("gestern");
  });

  it("give shares like the other screens, and a hint for the tiny ones", () => {
    expect(shareText(18240, 409880)).toBe("4,5\u00a0%");
    expect(shareText(3, 409880)).toBe("unter 0,1\u00a0%");
    expect(shareText(0, 409880)).toBe("0,0\u00a0%");
    expect(shareText(5, 0)).toBeNull();
  });

  it("name the month a silence began, in UTC", () => {
    expect(silentMonth("2025-07-01T00:00:00Z")).toBe("Juli 2025");
    expect(silentMonth("2024-12-01T00:00:00+00:00")).toBe("Dezember 2024");
  });

  it("lead to the mail list, a person's mails and the timeline with the signal", () => {
    expect(signalMailsHref("night")).toBe("/mails?signal=night");
    expect(signalMailsHref("term:spenden")).toBe("/mails?signal=term%3Aspenden");
    expect(personSignalHref(11, "bcc")).toBe("/mails?person=11&person_role=sent&signal=bcc");
    expect(signalTimelineHref("weekend")).toBe("/zeitachse?signal=weekend");
    expect(signalAnchor("term:spenden")).toBe("signal-term-spenden");
    expect(joinList(["a", "b", "c"])).toBe("a, b und c");
  });
});
