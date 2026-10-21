import { describe, expect, it } from "vitest";

import { filterChips, type ChipNames } from "./chips";
import { DEFAULT_LIST_STATE, type ListState } from "./listState";
import { invalidTerm, removeTerm } from "./queryText";

describe("removeTerm", () => {
  it("cuts the term out of q and normalises spaces", () => {
    expect(removeTerm("subject:Vertrag  to:@x.example   Rahmen", "to:@x.example")).toBe(
      "subject:Vertrag Rahmen",
    );
    expect(removeTerm('subject:"finale Fassung" Vertrag', 'subject:"finale Fassung"')).toBe(
      "Vertrag",
    );
    expect(removeTerm("Vertrag", "Vertrag")).toBe("");
    expect(removeTerm("a b", "c")).toBe("a b");
  });
});

describe("invalidTerm", () => {
  it("finds the operator term the message names", () => {
    expect(invalidTerm("invalid date in 'after:2026-13-01'", "Vertrag after:2026-13-01")).toBe(
      "after:2026-13-01",
    );
    expect(invalidTerm("unknown value: has:anhang", "a has:anhang")).toBe("has:anhang");
  });

  it("prefers the longest token, so a short one inside a word does not win", () => {
    expect(invalidTerm("bad term dkim:maybe", "d:x dkim:maybe")).toBe("dkim:maybe");
  });

  it("falls back to quoted text, then to the message", () => {
    expect(invalidTerm("cannot parse 'xyz'", "")).toBe("xyz");
    expect(invalidTerm("cannot parse", "")).toBe("cannot parse");
  });
});

describe("filterChips", () => {
  const names: ChipNames = {
    person: (id) => `Person ${id}`,
    mboxFile: () => "export.mbox",
    tag: (id) => (id === 2 ? { id, name: "Spendenaffären", color: "green" } : undefined),
    collection: (id) => (id === 1 ? "Story Nordstahl" : undefined),
  };
  const state: ListState = {
    ...DEFAULT_LIST_STATE,
    q: "subject:Vertrag to:@stadtwerke-beispiel.example",
    dkim: ["pass", "fail"],
    date_from: "2014-01-01",
    has_attachment: true,
    person: [11],
    between: [11, 12],
    cursor: "abc",
    page: 2,
  };
  const terms = [
    { key: "subject" as const, value: "Vertrag", raw: "subject:Vertrag" },
    {
      key: "to" as const,
      value: "@stadtwerke-beispiel.example",
      raw: "to:@stadtwerke-beispiel.example",
    },
  ];

  it("labels search terms and sidebar filters like the mockup", () => {
    expect(filterChips(state, terms, names).map((chip) => chip.label)).toEqual([
      "Betreff: „Vertrag“",
      "to: @stadtwerke-beispiel.example",
      "DKIM: Gültig, Ungültig",
      "ab 01.01.2014",
      "Mit Anhang",
      "Person: Person 11",
      "Zwischen Person 11 und Person 12",
    ]);
  });

  it("leads to the state without that filter, on the first page", () => {
    const [subject, , dkim, date] = filterChips(state, terms, names);
    expect(subject.next.q).toBe("to:@stadtwerke-beispiel.example");
    expect(subject.next.cursor).toBeNull();
    expect(subject.next.page).toBe(1);
    expect(dkim.next.dkim).toEqual([]);
    expect(date.next.date_from).toBeNull();
  });

  it("names the person's role and drops it with the person", () => {
    const [chip] = filterChips(
      { ...DEFAULT_LIST_STATE, person: [11], person_role: "sent" },
      [],
      names,
    );
    expect(chip.label).toBe("Person: Person 11 · Gesendet");
    expect(chip.next.person).toEqual([]);
    expect(chip.next.person_role).toBeNull();
  });

  it("names research filters, with the tag's colour and unknown ids by number", () => {
    const research: ListState = {
      ...DEFAULT_LIST_STATE,
      review: ["unreviewed", "relevant"],
      tag: [2, 12],
      collection: [1, 3],
      has_note: true,
      flagged: true,
    };
    const chips = filterChips(research, [], names);
    expect(chips.map((chip) => [chip.label, chip.color])).toEqual([
      ["Nur markierte", undefined],
      ["Mit Notiz", undefined],
      ["Status: Ungesichtet, Relevant", undefined],
      ["Schlagwort: Spendenaffären", "green"],
      ["Schlagwort #12", undefined],
      ["Akte: Story Nordstahl", undefined],
      ["Akte #3", undefined],
    ]);
    const byId = Object.fromEntries(chips.map((chip) => [chip.id, chip.next]));
    expect(byId.review.review).toEqual([]);
    expect(byId["tag-2"].tag).toEqual([12]);
    expect(byId["collection-3"].collection).toEqual([1]);
    expect(byId.has_note.has_note).toBe(false);
  });

  it("shows q as one chip while its terms are unknown", () => {
    const chips = filterChips({ ...DEFAULT_LIST_STATE, q: "after:2026-13-01" }, [], names);
    expect(chips.map((chip) => chip.label)).toEqual(["Suche: „after:2026-13-01“"]);
    expect(chips[0].next.q).toBe("");
    const stale = filterChips({ ...DEFAULT_LIST_STATE, q: "neu" }, terms, names);
    expect(stale.map((chip) => chip.label)).toEqual(["Suche: „neu“"]);
  });
});
