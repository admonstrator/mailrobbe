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
    { key: "subject" as const, value: "Vertrag", raw: "subject:Vertrag", negated: false },
    {
      key: "to" as const,
      value: "@stadtwerke-beispiel.example",
      raw: "to:@stadtwerke-beispiel.example",
      negated: false,
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

  it("names the thread by its first mail's subject, else by its id, and drops it", () => {
    const thread: ListState = { ...DEFAULT_LIST_STATE, thread: 184001, cursor: "abc", page: 2 };
    const [named] = filterChips(thread, [], {
      ...names,
      thread: (id) => (id === 184001 ? "Vertragsentwurf Rahmenvereinbarung 2026" : undefined),
    });
    expect(named.id).toBe("thread");
    expect(named.label).toBe("Thread: Vertragsentwurf Rahmenvereinbarung 2026");
    expect(named.next.thread).toBeNull();
    expect(named.next.cursor).toBeNull();
    expect(named.next.page).toBe(1);
    expect(filterChips(thread, [], names).map((chip) => chip.label)).toEqual(["Thread #184001"]);
  });

  it("names entities by kind and label, the term's theme by colour, amounts in German (D86)", () => {
    const entities: ChipNames = {
      ...names,
      entity: (id) =>
        id === 302
          ? { ref: { id, kind: "term", label: "Spende", detail: "spenden" }, color: "green" }
          : id === 312
            ? { ref: { id, kind: "amount", label: "12.500,00 EUR", detail: null } }
            : undefined,
    };
    const amounts: ListState = {
      ...DEFAULT_LIST_STATE,
      entity: [302, 312, 999],
      amount_min: 10000.5,
      amount_context: ["cash", "receipt"],
    };
    const chips = filterChips(amounts, [], entities);
    expect(chips.map((chip) => [chip.label, chip.color])).toEqual([
      ["Themenbegriff: Spende", "green"],
      ["Betrag: 12.500,00 EUR", undefined],
      ["Entität #999", undefined],
      ["Betrag ab 10.000,5", undefined],
      ["Betrag: Bargeld", undefined],
      ["Betrag: Quittung", undefined],
    ]);
    const byId = Object.fromEntries(chips.map((chip) => [chip.id, chip.next]));
    expect(byId["entity-312"].entity).toEqual([302, 999]);
    expect(byId.amount_min.amount_min).toBeNull();
    expect(byId["amount_context-cash"].amount_context).toEqual(["receipt"]);
  });

  it("shows q as one chip while its terms are unknown", () => {
    const chips = filterChips({ ...DEFAULT_LIST_STATE, q: "after:2026-13-01" }, [], names);
    expect(chips.map((chip) => chip.label)).toEqual(["Suche: „after:2026-13-01“"]);
    expect(chips[0].next.q).toBe("");
    const stale = filterChips({ ...DEFAULT_LIST_STATE, q: "neu" }, terms, names);
    expect(stale.map((chip) => chip.label)).toEqual(["Suche: „neu“"]);
  });

  it("names the search options after the terms and drops each alone (D177)", () => {
    const options: ListState = {
      ...DEFAULT_LIST_STATE,
      q: "Neger",
      scope: ["subject", "body"],
      whole_word: true,
      min_hits: 3,
      dkim: ["pass"],
      cursor: "abc",
      page: 2,
    };
    const neger = [{ key: "text" as const, value: "Neger", raw: "Neger", negated: false }];
    const chips = filterChips(options, neger, names);
    expect(chips.map((chip) => chip.label)).toEqual([
      "Volltext: „Neger“",
      "Nur in: Betreff, Mailtext",
      "Ganzes Wort",
      "Mindestens 3 Treffer",
      "DKIM: Gültig",
    ]);
    const byId = Object.fromEntries(chips.map((chip) => [chip.id, chip.next]));
    expect(byId.scope).toEqual({ ...options, scope: [], cursor: null, page: 1 });
    expect(byId.whole_word).toEqual({ ...options, whole_word: false, cursor: null, page: 1 });
    expect(byId.min_hits).toEqual({ ...options, min_hits: null, cursor: null, page: 1 });
    expect(
      filterChips({ ...DEFAULT_LIST_STATE, scope: ["filename"], min_hits: 1200 }, [], names).map(
        (chip) => chip.label,
      ),
    ).toEqual(["Nur in: Dateiname", "Mindestens 1.200 Treffer"]);
  });

  it("names the parties of roles and between (D340)", () => {
    const q = "recipient:.ru bcc:@partei.example -between:anna,.at";
    const terms = [
      { key: "recipient" as const, value: ".ru", raw: "recipient:.ru", negated: false },
      { key: "bcc" as const, value: "@partei.example", raw: "bcc:@partei.example", negated: false },
      { key: "between" as const, value: "anna,.at", raw: "-between:anna,.at", negated: true },
    ];
    expect(filterChips({ ...DEFAULT_LIST_STATE, q }, terms, names).map((c) => c.label)).toEqual([
      "An, Cc oder Bcc: .ru",
      "bcc: @partei.example",
      "Nicht Zwischen anna und .at",
    ]);
  });

  it("reads a minus as an exclusion, and removing it drops it from q (D175)", () => {
    const q = 'Neger -datei:NEG -from:anna -has:attachment -negere -"in Ordnung" betreff:Neger';
    const terms = [
      { key: "text" as const, value: "Neger", raw: "Neger", negated: false },
      { key: "in_filename" as const, value: "NEG", raw: "-datei:NEG", negated: true },
      { key: "from" as const, value: "anna", raw: "-from:anna", negated: true },
      { key: "has" as const, value: "attachment", raw: "-has:attachment", negated: true },
      { key: "text" as const, value: "-negere", raw: "-negere", negated: false },
      { key: "text" as const, value: "-in Ordnung", raw: '-"in Ordnung"', negated: false },
      { key: "in_subject" as const, value: "Neger", raw: "betreff:Neger", negated: false },
    ];
    const chips = filterChips({ ...DEFAULT_LIST_STATE, q }, terms, names);
    expect(chips.map((chip) => chip.label)).toEqual([
      "Volltext: „Neger“",
      "Nicht im Dateinamen: „NEG“",
      "Nicht from: anna",
      "Nicht mit Anhang",
      "Ohne: „negere“",
      "Ohne: „in Ordnung“",
      "Im Betreff: „Neger“",
    ]);
    expect(chips[1].next.q).toBe(
      'Neger -from:anna -has:attachment -negere -"in Ordnung" betreff:Neger',
    );
    expect(chips[4].next.q).toBe(
      'Neger -datei:NEG -from:anna -has:attachment -"in Ordnung" betreff:Neger',
    );
    // A lone minus is no exclusion of anything.
    const minus = [{ key: "text" as const, value: "-", raw: "-", negated: false }];
    expect(filterChips({ ...DEFAULT_LIST_STATE, q: "-" }, minus, names)[0].label).toBe(
      "Volltext: „-“",
    );
  });

  it("names each signal of the filter, a word field by its theme, and drops it alone (D136)", () => {
    const state: ListState = {
      ...DEFAULT_LIST_STATE,
      signal: ["night", "term:spenden"],
      cursor: "abc",
      page: 2,
    };
    const chips = filterChips(state, [], {
      ...names,
      signal: (key) =>
        key === "term:spenden"
          ? { name: "Wortfeld Spendenaffären", color: "green" }
          : { name: key === "night" ? "Nachts" : key },
    });
    expect(chips.map((chip) => [chip.label, chip.color])).toEqual([
      ["Signal: Nachts", undefined],
      ["Signal: Wortfeld Spendenaffären", "green"],
    ]);
    const night = chips[0].next;
    expect(night.signal).toEqual(["term:spenden"]);
    expect(night.cursor).toBeNull();
    expect(night.page).toBe(1);
    // Without names (the timeline's chips) the German name, a word field by its key.
    expect(filterChips(state, [], names).map((chip) => chip.label)).toEqual([
      "Signal: Nachts",
      "Signal: Wortfeld spenden",
    ]);
  });

  it("names each AI tag by its label and each theme by its name, and drops it alone (D309)", () => {
    const state: ListState = {
      ...DEFAULT_LIST_STATE,
      ai_tag: [12, 99],
      ai_theme: ["spenden", "unbekannt"],
      cursor: "abc",
      page: 2,
    };
    const chips = filterChips(state, [], {
      ...names,
      aiTag: (id) => (id === 12 ? "Spende" : undefined),
      aiTheme: (key) =>
        key === "spenden" ? { name: "Spendenaffären", color: "green" } : undefined,
    });
    expect(chips.map((chip) => [chip.label, chip.color])).toEqual([
      ["KI-Schlagwort: Spende", undefined],
      ["KI-Schlagwort #99", undefined],
      ["KI-Thema: Spendenaffären", "green"],
      ["KI-Thema: unbekannt", undefined],
    ]);
    expect(chips[0].next).toMatchObject({ ai_tag: [99], ai_theme: state.ai_theme, page: 1 });
    expect(chips[0].next.cursor).toBeNull();
    expect(chips[2].next).toMatchObject({ ai_tag: state.ai_tag, ai_theme: ["unbekannt"] });
    // Without names (the timeline's chips) by id and key.
    expect(filterChips(state, [], names).map((chip) => chip.label)).toEqual([
      "KI-Schlagwort #12",
      "KI-Schlagwort #99",
      "KI-Thema: spenden",
      "KI-Thema: unbekannt",
    ]);
  });
});
