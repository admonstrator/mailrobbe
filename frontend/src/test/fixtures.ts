// Realistic API responses for tests, typed with the contract. Only type imports, so the file
// also loads in plain Node (type stripping) for screenshot scripts.

import type {
  CollectionDetail,
  CollectionInfo,
  Contact,
  ContactPage,
  DkimJob,
  DkimStatus,
  DocumentDetail,
  DocumentListItem,
  DocumentPage,
  DocumentSummary,
  DocumentText,
  ExportInfo,
  Graph,
  GraphEdge,
  GraphNode,
  GraphSize,
  ImportErrorItem,
  ImportErrorKind,
  ImportErrorPage,
  ImportJob,
  ImportOptions,
  ImportStatus,
  ImportSummary,
  ImportTotals,
  MailDetail,
  MailHeaders,
  MailListItem,
  MailNeighbors,
  MailPage,
  MailRaw,
  MailSummary,
  MailText,
  MboxFileInfo,
  NotePage,
  ParticipationRole,
  PermalinkTarget,
  ResearchOverview,
  SavedSearch,
  TagInfo,
  ThemeInfo,
  FirstMentions,
  Timeline,
  TimelineSeries,
  PersonFigures,
  PersonMailCounts,
  PersonPage,
  PersonProfile,
  PersonRef,
  PersonSummary,
  ScanResult,
  Stats,
  StepProgress,
  SuggestionPage,
} from "../api/types";

const person = (person_id: number, name: string | null, email: string): PersonRef => ({
  person_id,
  name,
  email,
});

export const people = {
  anna: person(11, "Anna Keller", "anna.keller@nordlicht-gmbh.example"),
  jonas: person(12, "Jonas Brandt", "j.brandt@stadtwerke-beispiel.example"),
  miriam: person(13, "Dr. Miriam Steiner", "steiner@kanzlei-muster.example"),
  lukas: person(14, "Lukas Vogt", "lukas.vogt@nordlicht-gmbh.example"),
  peter: person(15, "Peter Hofmann", "p.hofmann@stadtwerke-beispiel.example"),
  sofia: person(16, "Sofia Lindqvist", "sofia.lindqvist@mail.example"),
  billing: person(17, "Rechnungswesen Nordlicht", "buchhaltung@nordlicht-gmbh.example"),
  thomas: person(18, "Thomas Weber", "t.weber@post.example"),
  purchasing: person(19, "Verteiler Einkauf", "einkauf@nordlicht-gmbh.example"),
};

export const stats: Stats = {
  mails: 412318,
  persons: 8942,
  domains: 1284,
  date_min: "2014-03-02T07:11:00Z",
  date_max: "2026-10-18T12:32:07Z",
  dkim: { pass: 268410, fail: 3117, no_key: 91204, unsigned: 49587, temp_error: 0, unchecked: 0 },
  sender_domains: [
    { domain: "nordlicht-gmbh.example", mails: 88120 },
    { domain: "stadtwerke-beispiel.example", mails: 41933 },
    { domain: "kanzlei-muster.example", mails: 22806 },
    { domain: "mail.example", mails: 19472 },
    { domain: "post.example", mails: 11058 },
    { domain: "lieferant-nordstahl.example", mails: 9120 },
    { domain: "verband.example", mails: 4411 },
    { domain: "newsletter.example", mails: 3900 },
    { domain: "bank.example", mails: 2210 },
    { domain: "behoerde.example", mails: 1022 },
  ],
  sender_domain_count: 1284,
  mbox_files: 72,
  internal_domains: ["nordlicht-gmbh.example"],
  importer: { running: true, files_total: 72, files_done: 51, progress: 0.713 },
  updated_at: "2026-10-20T01:14:00Z",
};

export const mboxFiles: MboxFileInfo[] = [
  "export-2019-Q1.mbox",
  "export-2019-Q2.mbox",
  "export-2019-Q3.mbox",
  "export-2026-Q4.mbox",
].map((path, index) => ({
  id: index + 1,
  path,
  size_bytes: 4_294_967_296,
  status: "done",
  mails_parsed: 5800,
  bytes_done: 4_294_967_296,
  error_count: 0,
  worker_id: null,
  started_at: "2026-10-19T22:00:00Z",
  finished_at: "2026-10-19T23:10:00Z",
}));

/** The archive without filters: the figures of global_stats. */
export const summaryAll: MailSummary = {
  total: 412318,
  exact: true,
  dkim: stats.dkim,
  persons: 8942,
  domains: 1284,
  date_min: stats.date_min,
  date_max: stats.date_max,
};

export const summaryFiltered: MailSummary = {
  total: 1207,
  exact: true,
  dkim: { pass: 786, fail: 9, no_key: 401, unsigned: 11, temp_error: 0, unchecked: 0 },
  persons: 214,
  domains: 38,
  date_min: "2019-01-14T08:03:00Z",
  date_max: "2026-10-18T12:32:07Z",
};

function item(
  id: number,
  date: string,
  sender: PersonRef,
  recipients: PersonRef[],
  subject: string | null,
  dkim_status: DkimStatus | null,
  extra: Partial<MailListItem> = {},
): MailListItem {
  return {
    id,
    date,
    subject,
    dkim_status,
    has_attachments: false,
    sender,
    recipients: recipients.slice(0, 3),
    recipient_count: recipients.length,
    thread_id: null,
    is_duplicate: false,
    flagged: false,
    size: 48_213,
    mbox_file_id: 4,
    person_role: null,
    review: null,
    tags: [],
    notes: 0,
    attachment_match: false,
    ...extra,
  };
}

const { anna, jonas, miriam, lukas, peter, sofia, billing, thomas, purchasing } = people;

export const mailItems: MailListItem[] = [
  item(
    184221,
    "2026-10-18T12:32:07Z",
    anna,
    [jonas, peter, miriam],
    "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung",
    "pass",
    {
      has_attachments: true,
      thread_id: 184001,
      size: 188_416,
      review: "relevant",
      tags: [2, 1],
      notes: 2,
    },
  ),
  item(
    184190,
    "2026-10-17T07:05:00Z",
    jonas,
    [anna],
    "Re: Vertragsentwurf Rahmenvereinbarung 2026",
    "pass",
    { thread_id: 184001 },
  ),
  item(
    184133,
    "2026-10-15T15:48:00Z",
    miriam,
    [anna, lukas],
    "Prüfung Vertragsklauseln §§ 4–7",
    "no_key",
    { has_attachments: true, thread_id: 184001 },
  ),
  item(
    184102,
    "2026-10-14T09:20:00Z",
    lukas,
    [purchasing, ...Array.from({ length: 11 }, () => anna)],
    "WG: Vertrag Lieferant Nordstahl – Unterschrift",
    "fail",
    { flagged: true, review: "seen" },
  ),
  item(
    184077,
    "2026-10-12T06:11:00Z",
    peter,
    [jonas],
    "Vertrag Wartung Umspannwerk Süd",
    "unsigned",
  ),
  item(
    184001,
    "2026-10-09T14:02:00Z",
    anna,
    [miriam],
    "Vertragsentwurf – bitte um Rückmeldung bis Freitag",
    "pass",
    { has_attachments: true, thread_id: 184001 },
  ),
  item(183950, "2026-10-07T19:44:00Z", sofia, [anna], "Fragen zum Vertrag (privat)", "pass"),
  item(
    183870,
    "2026-10-03T08:37:00Z",
    jonas,
    [peter, anna],
    "AW: Vertrag Wartung Umspannwerk Süd",
    "no_key",
  ),
  item(
    183801,
    "2026-10-01T04:00:00Z",
    billing,
    [jonas],
    "Vertrag 2024-118: Rechnung 3. Quartal",
    "pass",
    { has_attachments: true, is_duplicate: true },
  ),
  item(
    183644,
    "2026-09-28T11:15:00Z",
    lukas,
    [anna],
    "Vertrag Nordstahl: Änderungswünsche Einkauf",
    "pass",
  ),
  item(183590, "2026-09-25T17:58:00Z", thomas, [jonas], "Vertrag gekündigt?", null),
  item(183512, "2026-09-22T13:30:00Z", miriam, [anna], null, "temp_error", {
    has_attachments: true,
  }),
];

export const mailPage: MailPage = {
  items: mailItems,
  next_cursor: "cursor-page-2",
  prev_cursor: null,
  query_terms: [],
};

export const filteredQuery = "subject:Vertrag to:@stadtwerke-beispiel.example";

export const filteredPage: MailPage = {
  ...mailPage,
  query_terms: [
    { key: "subject", value: "Vertrag", raw: "subject:Vertrag" },
    { key: "to", value: "@stadtwerke-beispiel.example", raw: "to:@stadtwerke-beispiel.example" },
  ],
};

export const neighbors: MailNeighbors = { prev_id: null, next_id: 184190, position: 1 };

export const mailDetail: MailDetail = {
  id: 184221,
  subject: "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung",
  date: "2026-10-18T12:32:07Z",
  message_id: "<a8f31c7e-4d2b-4b1a-9e77-20261018123207@nordlicht-gmbh.example>",
  in_reply_to: "<CAJx9Qv=8f2d@stadtwerke-beispiel.example>",
  in_reply_to_id: 184190,
  reference_ids: ["<CAJx9Qv=8f2d@stadtwerke-beispiel.example>"],
  source: {
    mbox_file_id: 4,
    path: "export-2026-Q4.mbox",
    byte_offset: 1_883_204_117,
    byte_length: 188_416,
  },
  raw_sha256: "3f9a6b0de1c24f8a9b7e5d3c2a1f0e9d8c7b6a5f4e3d2c1b0a9f8e7d6c5bc21e",
  has_attachments: true,
  dkim: {
    status: "pass",
    signatures: [
      {
        index: 0,
        status: "pass",
        reason: null,
        domain: "nordlicht-gmbh.example",
        selector: "mail2025",
        algorithm: "rsa-sha256",
        key_bits: 2048,
        signed_headers: [
          "from",
          "to",
          "cc",
          "subject",
          "date",
          "message-id",
          "mime-version",
          "content-type",
        ],
        body_hash_ok: true,
        signed_at: "2026-10-18T12:32:09Z",
        aligned: true,
        checked_at: "2026-10-20T01:14:00Z",
        dns_cached: true,
        dns_record: "v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAu1Q",
        dns_fetched_at: "2026-10-19T13:00:00Z",
        dns_ttl: 43200,
      },
    ],
  },
  participants: [
    { ...anna, role: "from", mails: null, contacts: null, mails_with_sender: null },
    { ...jonas, role: "to", mails: null, contacts: null, mails_with_sender: null },
    { ...peter, role: "to", mails: null, contacts: null, mails_with_sender: null },
    { ...miriam, role: "cc", mails: null, contacts: null, mails_with_sender: null },
  ],
  attachments: [
    {
      id: 901,
      filename: "Rahmenvereinbarung_2026_final.pdf",
      mime_type: "application/pdf",
      size: 172_032,
      sha256: "91ab44c0d2e8f1a37b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f40",
      document_id: 5101,
      kind: "pdf",
      text_status: "text",
      pages: 14,
      document_mails: 6,
      preview: "pdf",
    },
    {
      id: 902,
      filename: "Aenderungsprotokoll.xlsx",
      mime_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      size: 14_336,
      sha256: "5c07e2b9a4d13f8e6b0a7c9d2e4f61a3b5c7d9e0f1a2b3c4d5e6f708192a3b4c",
      document_id: 5102,
      kind: "spreadsheet",
      text_status: "text",
      pages: 2,
      document_mails: 1,
      preview: null,
    },
  ],
  thread_id: 184001,
  thread: [
    {
      id: 184001,
      date: "2026-10-09T14:02:00Z",
      subject: "Vertragsentwurf Rahmenvereinbarung 2026",
      sender: jonas,
      dkim_status: "pass",
    },
    {
      id: 184133,
      date: "2026-10-15T15:48:00Z",
      subject: "Re: Prüfung Vertragsklauseln §§ 4–7",
      sender: miriam,
      dkim_status: "no_key",
    },
    {
      id: 184190,
      date: "2026-10-17T07:05:00Z",
      subject: "Re: Vertragsentwurf Rahmenvereinbarung 2026",
      sender: jonas,
      dkim_status: "pass",
    },
    {
      id: 184221,
      date: "2026-10-18T12:32:07Z",
      subject: "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung",
      sender: anna,
      dkim_status: "pass",
    },
  ],
  thread_size: 4,
  duplicate_of: null,
  duplicates: [],
  research: {
    mark: {
      flagged: false,
      flagged_by: null,
      flagged_at: null,
      review: "relevant",
      review_by: "Lena Vogt",
      review_at: "2026-10-20T14:02:00Z",
    },
    tags: [
      { id: 2, name: "Spendenaffären", color: "green" },
      { id: 1, name: "Vertrag Nordstahl", color: "blue" },
    ],
    collections: [{ id: 1, name: "Story Nordstahl" }],
    notes: [
      {
        id: 11,
        body: "Erste Erwähnung der Rahmenvereinbarung, Anlage fehlt.",
        author: "Lena Vogt",
        created_at: "2026-10-20T14:05:00Z",
        updated_at: "2026-10-20T14:05:00Z",
      },
      {
        id: 12,
        body: "Anlage liegt in Mail 184133, Abgleich mit Rechtsabteilung.",
        author: null,
        created_at: "2026-10-21T07:40:00Z",
        updated_at: "2026-10-21T07:52:00Z",
      },
    ],
  },
};

export const mailText: MailText = {
  text: [
    "Hallo Herr Brandt, hallo Herr Hofmann,",
    "",
    "anbei die finale Fassung der Rahmenvereinbarung 2026. Die Änderungen aus der Besprechung vom 14.10. sind eingearbeitet, Frau Dr. Steiner hat die Haftungsklausel in § 6 noch einmal geprüft (siehe Cc).",
    "",
    "Wenn von Ihrer Seite keine weiteren Anmerkungen kommen, würden wir die Unterschrift für den 24.10. vorschlagen.",
    "",
    "Viele Grüße",
    "Anna Keller",
    "Leitung Einkauf · Nordlicht GmbH",
    "",
    "Am 17.10.2026 um 09:05 schrieb Jonas Brandt <j.brandt@stadtwerke-beispiel.example>:",
    "> Hallo Frau Keller,",
    ">",
    "> danke für den Entwurf. Zwei Punkte hätten wir noch zu § 4.",
    ">",
    "> Viele Grüße",
    "> Jonas Brandt",
  ].join("\n"),
  truncated: false,
  source: "text/plain",
  has_html: true,
};

export const mailHeaders: MailHeaders = {
  headers: [
    { name: "Return-Path", value: "<anna.keller@nordlicht-gmbh.example>" },
    {
      name: "DKIM-Signature",
      value:
        "v=1; a=rsa-sha256; c=relaxed/relaxed; d=nordlicht-gmbh.example; s=mail2025; t=1792326729; h=from:to:cc:subject:date:message-id:mime-version:content-type; bh=Jf7xQ2W0n5yV1kq8u3s9ZcR4tP6mL0aB=; b=mB0rT4vXk9Q2w7Yp1sD8fG3hJ6kL0zXcV5bN2mQ4rT7yU1iO9pA",
    },
    { name: "From", value: "Anna Keller <anna.keller@nordlicht-gmbh.example>" },
    {
      name: "To",
      value:
        "Jonas Brandt <j.brandt@stadtwerke-beispiel.example>, Peter Hofmann <p.hofmann@stadtwerke-beispiel.example>",
    },
    { name: "Cc", value: "Dr. Miriam Steiner <steiner@kanzlei-muster.example>" },
    { name: "Subject", value: "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung" },
    { name: "Date", value: "Sat, 18 Oct 2026 14:32:07 +0200" },
    {
      name: "Message-ID",
      value: "<a8f31c7e-4d2b-4b1a-9e77-20261018123207@nordlicht-gmbh.example>",
    },
    { name: "In-Reply-To", value: "<CAJx9Qv=8f2d@stadtwerke-beispiel.example>" },
    { name: "MIME-Version", value: "1.0" },
    { name: "Content-Type", value: 'multipart/mixed; boundary="b1_6f0e"' },
  ],
};

export const mailRaw: MailRaw = {
  raw: [
    ...mailHeaders.headers.map((header) => `${header.name}: ${header.value}`),
    "",
    "--b1_6f0e",
    "Content-Type: text/plain; charset=utf-8",
    "",
    mailText.text,
  ].join("\n"),
  truncated: false,
  size: 188_416,
};

// Persons (milestone 5) -----------------------------------------------------------------------
// Anna Keller (11) with two aliases, eleven years of mail, ten top contacts and two open alias
// suggestions, as in the mockup's profile.

export const otherPeople = {
  annaWork: person(21, "Anna Keller", "a.keller@nordlicht-gmbh.example"),
  annaPrivate: person(22, "Anna Keller", "annakeller78@mail.example"),
  annaPost: person(23, "Anna Keller", "keller.anna@post.example"),
  annaShort: person(24, "A. Keller", "a.keller@mail.example"),
  jonasPrivate: person(25, "Jonas Brandt", "jonas.brandt@mail.example"),
  peterPost: person(26, "Peter Hofmann", "p.hofmann@post.example"),
  katrin: person(27, "Katrin Albers", "k.albers@verband.example"),
  mehmet: person(28, "Mehmet Yilmaz", "m.yilmaz@lieferant-nordstahl.example"),
  noreply: person(29, null, "noreply@bank.example"),
};

const domainOf = (ref: PersonRef) => ref.email.split("@")[1];

function figures(
  sent: number,
  received: number,
  extra: Partial<PersonFigures> = {},
): PersonFigures {
  return {
    mails: sent + received,
    sent,
    received,
    cc_only: Math.round(received / 6),
    contacts: Math.max(1, Math.round((sent + received) / 40)),
    first_date: "2016-03-11T08:14:00Z",
    last_date: "2026-10-18T12:32:07Z",
    dkim_pass_ratio: 0.93,
    ...extra,
  };
}

function summary(ref: PersonRef, figures: PersonFigures, aliases = 0): PersonSummary {
  return {
    id: ref.person_id,
    name: ref.name,
    email: ref.email,
    domain: domainOf(ref),
    aliases,
    figures,
  };
}

export const annaFigures: PersonFigures = {
  mails: 11318,
  sent: 3412,
  received: 7906,
  cc_only: 1204,
  contacts: 214,
  first_date: "2016-03-11T08:14:00Z",
  last_date: "2026-10-18T12:32:07Z",
  dkim_pass_ratio: 0.978,
};

const { annaWork, annaPrivate, annaPost, annaShort, jonasPrivate, peterPost } = otherPeople;
const { katrin, mehmet, noreply } = otherPeople;

export const personSummaries = {
  anna: summary(anna, annaFigures, 2),
  jonas: summary(jonas, figures(2210, 3190, { last_date: "2026-10-17T07:05:00Z" })),
  lukas: summary(lukas, figures(1480, 2402, { last_date: "2026-10-14T09:20:00Z" })),
  miriam: summary(miriam, figures(902, 1311, { dkim_pass_ratio: 0.412 })),
  billing: summary(billing, figures(1720, 12, { dkim_pass_ratio: 1 })),
  peter: summary(peter, figures(611, 984, { last_date: "2026-10-12T06:11:00Z" })),
  sofia: summary(sofia, figures(204, 377, { first_date: "2019-05-02T18:00:00Z" })),
  thomas: summary(thomas, figures(88, 140, { dkim_pass_ratio: null })),
  purchasing: summary(purchasing, figures(0, 1460, { dkim_pass_ratio: null })),
  katrin: summary(katrin, figures(61, 95, { last_date: "2025-06-30T10:00:00Z" })),
  mehmet: summary(mehmet, figures(40, 52, { last_date: "2024-11-08T13:45:00Z" })),
  noreply: summary(noreply, figures(420, 0, { contacts: 1, dkim_pass_ratio: 0.998 })),
  annaPost: summary(annaPost, figures(34, 62, { first_date: "2021-02-01T09:00:00Z" })),
  annaShort: summary(annaShort, figures(12, 19, { first_date: "2023-07-14T16:30:00Z" })),
  jonasPrivate: summary(jonasPrivate, figures(18, 25)),
  peterPost: summary(peterPost, figures(9, 14, { dkim_pass_ratio: null })),
};

const ps = personSummaries;

export const personPage: PersonPage = {
  items: [
    ps.anna,
    ps.jonas,
    ps.lukas,
    ps.miriam,
    ps.billing,
    ps.peter,
    ps.purchasing,
    ps.sofia,
    ps.noreply,
    ps.thomas,
    ps.katrin,
    ps.mehmet,
  ],
  next_cursor: "persons-page-2",
  prev_cursor: null,
  total: 1710,
};

export const suggestionPage: SuggestionPage = {
  items: [
    {
      first: ps.peter,
      second: ps.peterPost,
      same_name: "peter hofmann",
      same_local_part: "p.hofmann",
    },
    { first: ps.anna, second: ps.annaPost, same_name: "anna keller", same_local_part: null },
    { first: ps.jonas, second: ps.jonasPrivate, same_name: "jonas brandt", same_local_part: null },
  ],
  next_cursor: "suggestions-page-2",
  total: 4,
};

export const suggestionPage2: SuggestionPage = {
  items: [{ first: ps.anna, second: ps.annaShort, same_name: null, same_local_part: "a.keller" }],
  next_cursor: null,
  total: 4,
};

function contact(
  ref: PersonRef,
  sent: number,
  received: number,
  cc: number,
  last_date = "2026-10-18T12:32:07Z",
): Contact {
  return {
    person: ref,
    domain: domainOf(ref),
    mails: sent + received + cc,
    sent,
    received,
    cc,
    first_date: "2016-04-02T09:12:00Z",
    last_date,
  };
}

export const topContacts: Contact[] = [
  contact(jonas, 160, 181, 47),
  contact(lukas, 121, 150, 34, "2026-10-14T09:20:00Z"),
  contact(miriam, 40, 45, 12, "2026-10-15T15:48:00Z"),
  contact(billing, 2, 80, 2, "2026-10-01T04:00:00Z"),
  contact(peter, 25, 24, 12, "2026-10-12T06:11:00Z"),
  contact(sofia, 20, 25, 2, "2026-10-07T19:44:00Z"),
  contact(thomas, 11, 14, 6, "2026-09-25T17:58:00Z"),
  contact(purchasing, 0, 28, 0, "2026-10-14T09:20:00Z"),
  contact(katrin, 8, 9, 2, "2025-06-30T10:00:00Z"),
  contact(mehmet, 5, 6, 1, "2024-11-08T13:45:00Z"),
];

export const contactPage: ContactPage = {
  items: topContacts,
  next_cursor: "contacts-page-2",
  total: 214,
};

export const contactPage2: ContactPage = {
  items: [contact(annaPost, 4, 3, 0, "2025-01-20T08:00:00Z"), contact(noreply, 0, 9, 0)],
  next_cursor: null,
  total: 214,
};

const YEARS: [number, number, number][] = [
  [2016, 96, 210],
  [2017, 241, 528],
  [2018, 302, 694],
  [2019, 318, 803],
  [2020, 412, 1002],
  [2021, 371, 868],
  [2022, 356, 905],
  [2023, 455, 1100],
  [2024, 367, 788],
  [2025, 312, 614],
  [2026, 182, 394],
];

export const annaProfile: PersonProfile = {
  id: anna.person_id,
  name: anna.name,
  email: anna.email,
  domain: domainOf(anna),
  aliases: [
    { person_id: annaWork.person_id, email: annaWork.email, name: annaWork.name, mails: 1840 },
    {
      person_id: annaPrivate.person_id,
      email: annaPrivate.email,
      name: annaPrivate.name,
      mails: 312,
    },
  ],
  display_names: [
    { name: "Anna Keller", mails: 3201 },
    { name: "Keller, Anna", mails: 188 },
    { name: "Nordlicht Einkauf", mails: 23 },
  ],
  figures: annaFigures,
  years: YEARS.map(([year, sent, received]) => ({ year, sent, received })),
  top_contacts: topContacts,
  suggestions: [
    { person: ps.annaPost, same_name: "anna keller", same_local_part: null },
    { person: ps.annaShort, same_name: null, same_local_part: "a.keller" },
  ],
};

/** Anna's profile after merging keller.anna@post.example (23) into her. */
export const mergedProfile: PersonProfile = {
  ...annaProfile,
  aliases: [
    ...annaProfile.aliases,
    { person_id: annaPost.person_id, email: annaPost.email, name: annaPost.name, mails: 96 },
  ],
  suggestions: annaProfile.suggestions.filter(
    (candidate) => candidate.person.id !== annaPost.person_id,
  ),
};

/** Tab counts for a chosen year or contact; Cc ran out of time. */
export const personMailCounts: PersonMailCounts = {
  all: 1555,
  sent: 455,
  received: 1100,
  cc: null,
};

const roleOfAnna = (mail: MailListItem): ParticipationRole | null =>
  mail.sender?.person_id === anna.person_id
    ? "from"
    : mail.recipients.some((ref) => ref.person_id === anna.person_id)
      ? "to"
      : null;

/** Anna's mails as GET /api/mails?person=11 answers them, with her role in each. */
export const personMailPage: MailPage = {
  items: mailItems.flatMap((mail) => {
    const role = mail.id === 183870 ? "cc" : roleOfAnna(mail);
    return role ? [{ ...mail, person_role: role }] : [];
  }),
  next_cursor: "person-mails-2",
  prev_cursor: null,
  query_terms: [],
};

// Relationship map: Anna's ego network of the mockup ("4 · Beziehungskarte").

const graphNode = (
  person: PersonRef,
  mails: number,
  contacts: number,
  extra: Partial<GraphNode> = {},
): GraphNode => ({
  id: person.person_id,
  name: person.name,
  email: person.email,
  domain: person.email.split("@")[1],
  kind: null,
  mails,
  contacts,
  center: false,
  ...extra,
});

const graphEdge = (
  a: PersonRef,
  b: PersonRef,
  a_to_b: number,
  b_to_a: number,
  cc = 0,
): GraphEdge => ({
  source: a.person_id,
  target: b.person_id,
  a_to_b,
  b_to_a,
  cc,
  weight: a_to_b + b_to_a,
});

const graphEdges: GraphEdge[] = [
  graphEdge(anna, jonas, 210, 178, 12),
  graphEdge(anna, lukas, 160, 145),
  graphEdge(jonas, peter, 140, 120),
  graphEdge(anna, purchasing, 120, 0),
  graphEdge(anna, miriam, 52, 45, 30),
  graphEdge(anna, billing, 14, 70),
  graphEdge(anna, peter, 33, 28),
  graphEdge(lukas, purchasing, 48, 0),
  graphEdge(anna, sofia, 21, 26),
  graphEdge(anna, thomas, 9, 22),
  graphEdge(jonas, miriam, 12, 9),
  graphEdge(lukas, billing, 6, 4),
];

export const graph: Graph = {
  nodes: [
    graphNode(anna, 11_318, 214, { center: true }),
    graphNode(jonas, 2_210, 58),
    graphNode(lukas, 1_733, 41),
    graphNode(peter, 904, 23),
    graphNode(miriam, 610, 17),
    graphNode(purchasing, 512, 9, { kind: "list" }),
    graphNode(billing, 288, 12),
    graphNode(sofia, 97, 4),
    graphNode(thomas, 61, 6),
  ],
  edges: graphEdges,
  mails: graphEdges.reduce((sum, edge) => sum + edge.weight, 0),
  centers: [11],
  edge_table: { pairs: 34_912, refreshed_at: "2026-10-21T01:20:00Z" },
};

export const graphSize: GraphSize = { nodes: 9, edges: 12, mails: graph.mails, too_large: false };

export const personSearch: PersonPage = {
  items: [
    {
      id: miriam.person_id,
      name: miriam.name,
      email: miriam.email,
      domain: "kanzlei-muster.example",
      aliases: 1,
      figures: {
        mails: 1_820,
        sent: 610,
        received: 1_002,
        cc_only: 208,
        contacts: 64,
        first_date: "2016-02-01T08:00:00Z",
        last_date: "2026-10-15T15:48:00Z",
        dkim_pass_ratio: 0.42,
      },
    },
    {
      id: 21,
      name: "Stefan Steinbach",
      email: "s.steinbach@verband.example",
      domain: "verband.example",
      aliases: 0,
      figures: {
        mails: 233,
        sent: 101,
        received: 120,
        cc_only: 12,
        contacts: 19,
        first_date: "2019-05-02T10:00:00Z",
        last_date: "2025-12-01T09:30:00Z",
        dkim_pass_ratio: 0.9,
      },
    },
  ],
  next_cursor: null,
  prev_cursor: null,
  total: 2,
};

// Import dashboard: 72 quarterly exports of about 4 GB as in the mockup, 48 done, 8 running,
// 1 failed and 15 waiting. Times are UTC; the tests show them in Europe/Berlin (UTC+2).

const GIB = 1024 ** 3;
const MIB = 1024 ** 2;
/** How far the running files (W1 to W8) and the failed one got. */
const RUNNING_DONE = [0.82, 0.64, 0.41, 0.18, 0.93, 0.55, 0.27, 0.07];
const FAILED_DONE = 0.53;
const FAILED_INDEX = 56; // export-2022-Q1.mbox

const exportPaths = Array.from(
  { length: 72 },
  (_, index) => `export-${2008 + Math.floor(index / 4)}-Q${(index % 4) + 1}.mbox`,
);
const fileId = (index: number) => 101 + index;

function exportFile(index: number, error_count: number): MboxFileInfo {
  const size = Math.round((3.75 + ((index * 37) % 50) / 100) * GIB);
  const mails = Math.round(size / (700 * 1024));
  const minutes = (n: number) => new Date(Date.UTC(2026, 9, 19, 23, 2) + n * 60_000).toISOString();
  const file: MboxFileInfo = {
    id: fileId(index),
    path: exportPaths[index],
    size_bytes: size,
    status: "pending",
    mails_parsed: 0,
    bytes_done: 0,
    error_count,
    worker_id: null,
    started_at: null,
    finished_at: null,
  };
  if (index < 48) {
    return {
      ...file,
      status: "done",
      mails_parsed: mails,
      bytes_done: size,
      started_at: minutes(index * 2),
      finished_at: minutes(index * 2 + 16),
    };
  }
  const running = index < 56;
  if (!running && index !== FAILED_INDEX) return file;
  const fraction = running ? RUNNING_DONE[index - 48] : FAILED_DONE;
  return {
    ...file,
    status: running ? "running" : "error",
    worker_id: running ? index - 47 : null,
    mails_parsed: Math.round(mails * fraction),
    bytes_done: Math.floor(size * fraction),
    started_at: minutes(80 + index - 48),
    finished_at: running ? null : "2026-10-20T01:11:42Z",
  };
}

function importError(
  id: number,
  created_at: string,
  index: number,
  byte_offset: number,
  kind: ImportErrorKind,
  message: string,
): ImportErrorItem {
  const path = exportPaths[index];
  return { id, mbox_file_id: fileId(index), path, byte_offset, kind, message, created_at };
}

const ERROR_MESSAGES: [ImportErrorKind, string][] = [
  ["separator", "From_ line without an empty line before it"],
  ["encoding", "undecodable bytes in charset windows-1252; decoded heuristically"],
  ["date", "Date header not RFC 5322: 'Montag, 32. Mai 2022'; date of the From_ line used"],
  ["message_id", "Message-ID missing"],
  ["address", "unparseable address in Cc: 'Einkauf <einkauf@>'"],
  ["encoding", "unknown charset x-mac-roman in Subject; decoded heuristically"],
  ["separator", "data before the first From_ line"],
  ["parse", "multipart boundary never closed; stored what was read"],
];

/** Every import error, newest first: 53 in the file that failed, a few in others. */
export const importErrors: ImportErrorItem[] = [
  importError(
    958,
    "2026-10-20T01:11:42Z",
    FAILED_INDEX,
    2_104_881_900,
    "io",
    "[Errno 5] Input/output error while reading at byte 2104881900",
  ),
  importError(
    957,
    "2026-10-20T01:09:10Z",
    49,
    1_204_117_002,
    "encoding",
    "header declares iso-8859-1 but holds UTF-8; decoded heuristically",
  ),
  importError(
    956,
    "2026-10-20T00:58:33Z",
    52,
    381_220_114,
    "dkim",
    "dkim.verify raised KeyError('b') for signature 1",
  ),
  importError(
    955,
    "2026-10-20T00:41:07Z",
    FAILED_INDEX,
    1_998_004_311,
    "too_large",
    "mail of 212.0 MiB above the limit of 128.0 MiB; headers only",
  ),
  ...Array.from({ length: 54 }, (_, n) => {
    const [kind, message] = ERROR_MESSAGES[n % ERROR_MESSAGES.length];
    const at = new Date(Date.UTC(2026, 9, 20, 0, 40, 51) - n * 9_000).toISOString();
    const index = n === 20 ? 9 : n === 31 || n === 32 ? 24 : FAILED_INDEX;
    return importError(954 - n, at, index, 1_900_000_000 - n * 35_431_337, kind, message);
  }),
];

export const importFiles: MboxFileInfo[] = exportPaths.map((_, index) =>
  exportFile(index, importErrors.filter((error) => error.mbox_file_id === fileId(index)).length),
);

/** The sums of ImportStatus.totals over these files. */
export function importTotals(files: MboxFileInfo[]): ImportTotals {
  const sum = (pick: (file: MboxFileInfo) => number) =>
    files.reduce((total, file) => total + pick(file), 0);
  const count = (status: MboxFileInfo["status"]) => sum((file) => Number(file.status === status));
  const size = sum((file) => file.size_bytes);
  const done = sum((file) => file.bytes_done);
  const mails = sum((file) => file.mails_parsed);
  return {
    files: files.length,
    done: count("done"),
    running: count("running"),
    pending: count("pending"),
    paused: count("paused"),
    error: count("error"),
    size_bytes: size,
    bytes_done: done,
    mails_parsed: mails,
    mails_estimated: done === 0 ? null : Math.round((mails * size) / done),
    error_count: sum((file) => file.error_count),
  };
}

export const importDefaults: ImportOptions = {
  workers: 8,
  attachment_hash_limit: 50 * MIB,
  max_mail_size: 128 * MIB,
  dkim_nameservers: "1.1.1.1, 9.9.9.9",
  dkim_offline: false,
  mbox_dir: "/data/mbox",
  text_max_size: 50 * MIB,
  text_timeout: 60,
};

export function waitingStep(key: string): StepProgress {
  return {
    key,
    status: "waiting",
    unit: null,
    done: 0,
    total: null,
    started_at: null,
    seconds: 0,
    rate: null,
    eta_seconds: null,
  };
}

export function doneStep(key: string, seconds: number): StepProgress {
  return { ...waitingStep(key), status: "done", started_at: "2026-10-20T01:14:00Z", seconds };
}

export const importJob: ImportJob = {
  id: 7,
  kind: "import",
  origin: "ui",
  status: "running",
  alive: true,
  stop_requested: false,
  started_at: "2026-10-19T23:02:00Z",
  updated_at: "2026-10-20T01:14:02Z",
  report_age_seconds: 1.2,
  finished_at: null,
  message: null,
  leftover: null,
  phase: "import",
  options: importDefaults,
  progress: {
    workers: 8,
    files_queued: 25,
    files_finished: 1,
    mails_imported: 41_318,
    bytes_imported: 28 * GIB,
    mails_per_second: 1_420.4,
    dkim_per_second: 1_396.8,
    bytes_per_second: 13.4 * MIB,
    eta_seconds: 6_012,
    steps: [
      { ...doneStep("scan", 4), started_at: "2026-10-19T23:02:00Z" },
      { ...waitingStep("headers"), status: "skipped" },
      {
        key: "import",
        status: "running",
        unit: "bytes",
        done: 28 * GIB,
        total: 108 * GIB,
        started_at: "2026-10-19T23:02:04Z",
        seconds: 7_918,
        rate: 13.4 * MIB,
        eta_seconds: 6_012,
      },
      ...["duplicates", "threads", "names", "documents"].map(waitingStep),
      ...["edges", "person_stats", "suggestions", "global_stats", "attachments"].map(waitingStep),
    ],
    database: null,
  },
};

/** The latest DKIM run, which ended before the import started. */
export const dkimJobDone: DkimJob = {
  id: 6,
  kind: "dkim",
  origin: "cli",
  status: "done",
  alive: false,
  stop_requested: false,
  started_at: "2026-10-19T21:40:00Z",
  updated_at: "2026-10-19T21:52:10Z",
  report_age_seconds: 12_000,
  finished_at: "2026-10-19T21:52:10Z",
  message: "checked 18204 mails",
  leftover: null,
  phase: "aggregates",
  options: {
    statuses: ["unchecked", "no_key", "temp_error"],
    mail_ids: [],
    workers: 8,
    offline: false,
  },
  progress: {
    workers: 0,
    selected: 18_204,
    checked: 18_201,
    skipped: 3,
    mails_per_second: 0,
    eta_seconds: null,
    steps: [
      { ...doneStep("check", 712), unit: "mails", done: 18_204, total: 18_204 },
      ...["edges", "person_stats", "suggestions", "global_stats"].map((key) => doneStep(key, 3)),
    ],
    database: null,
  },
};

/** A DKIM run of D13 from the dashboard, a fifth through. */
export const dkimJobRunning: DkimJob = {
  ...dkimJobDone,
  id: 8,
  origin: "ui",
  status: "running",
  alive: true,
  started_at: "2026-10-20T01:20:00Z",
  updated_at: "2026-10-20T01:20:40Z",
  report_age_seconds: 0.8,
  finished_at: null,
  message: null,
  phase: "check",
  progress: {
    workers: 8,
    selected: 64_790,
    checked: 12_408,
    skipped: 0,
    mails_per_second: 311.6,
    eta_seconds: 168,
    steps: [
      {
        key: "check",
        status: "running",
        unit: "mails",
        done: 12_408,
        total: 64_790,
        started_at: "2026-10-20T01:20:00Z",
        seconds: 40,
        rate: 311.6,
        eta_seconds: 168,
      },
      ...["edges", "person_stats", "suggestions", "global_stats"].map(waitingStep),
    ],
    database: null,
  },
};

/** An import with 8 workers, as in the mockup. */
export const importStatus: ImportStatus = {
  mbox_dir: "/data/mbox",
  mbox_dir_ok: true,
  totals: importTotals(importFiles),
  files: importFiles,
  import_job: importJob,
  dkim_job: dkimJobDone,
  defaults: importDefaults,
};

const pausedFiles = importFiles.map((file) =>
  file.status === "running" ? { ...file, status: "paused" as const, worker_id: null } : file,
);

/** The same import after "Pausieren". */
export const importStatusPaused: ImportStatus = {
  ...importStatus,
  totals: importTotals(pausedFiles),
  files: pausedFiles,
  import_job: {
    ...importJob,
    status: "stopped",
    alive: false,
    stop_requested: true,
    updated_at: "2026-10-20T01:15:12Z",
    finished_at: "2026-10-20T01:15:12Z",
    report_age_seconds: 40,
    message: "stopped on request; 8 files paused",
    progress: {
      ...importJob.progress,
      workers: 0,
      eta_seconds: null,
      steps: importJob.progress.steps.map((step) =>
        step.status === "running"
          ? { ...step, status: "stopped", seconds: 7_988, rate: null, eta_seconds: null }
          : step,
      ),
    },
  },
};

/** A new installation: nothing scanned, no run yet. */
export const importStatusEmpty: ImportStatus = {
  ...importStatus,
  totals: importTotals([]),
  files: [],
  import_job: null,
  dkim_job: null,
};

export const importSummary: ImportSummary = {
  db_size_bytes: Math.round(9.8 * GIB),
  raw_size_bytes: importStatus.totals.size_bytes,
  fulltext_index_bytes: Math.round(4.1 * GIB),
  dns_cache: { found: 6_218, not_found: 412, temp_error: 3 },
  dns_hit_ratio: 0.994,
  persons: 8_942,
  open_suggestions: 312,
  edge_table: { pairs: 61_207, refreshed_at: "2026-10-20T01:10:05Z" },
  duplicates: 1_912,
  dkim: {
    pass: 190_412,
    fail: 2_203,
    no_key: 64_790,
    unsigned: 35_341,
    temp_error: 0,
    unchecked: 0,
  },
  fail_reasons: [
    { reason: "body_hash_mismatch", mails: 1_640 },
    { reason: "signature_mismatch", mails: 380 },
    { reason: "key_revoked", mails: 183 },
    { reason: "key_too_short", mails: 12 },
  ],
  updated_at: "2026-10-20T01:12:30Z",
  attachments: 118_204,
  documents: {
    pending: 0,
    text: 41_380,
    empty: 212,
    scanned: 6_904,
    encrypted: 87,
    unsupported: 30_116,
    too_large: 14,
    failed: 391,
    timeout: 6,
    unreadable: 0,
  },
};

/** A rescan that found two new files, a changed one and one it cannot read. */
export const scanResult: ScanResult = {
  files: 74,
  pending: 19,
  new: ["export-2026-Q1.mbox", "export-2026-Q2.mbox"],
  replaced: [{ path: "export-2019-Q4.mbox", reason: "first MiB changed" }],
  missing: [],
  unreadable: [{ path: "export-2026-Q3.mbox", reason: "[Errno 13] Permission denied" }],
};

/** /api/import/errors over importErrors: filtered, newest first; the cursor is an offset. */
export function importErrorPage(search: URLSearchParams): ImportErrorPage {
  const kind = search.get("kind");
  const file = search.get("mbox_file");
  const matches = importErrors.filter(
    (error) =>
      (kind === null || error.kind === kind) &&
      (file === null || error.mbox_file_id === Number(file)),
  );
  const start = Number(search.get("cursor") ?? 0);
  const end = start + Number(search.get("limit") ?? 50);
  const kinds: ImportErrorPage["kinds"] = {};
  for (const error of importErrors) kinds[error.kind] = (kinds[error.kind] ?? 0) + 1;
  return {
    items: matches.slice(start, end),
    next_cursor: end < matches.length ? String(end) : null,
    total: matches.length,
    kinds,
  };
}

// Research file (milestone 8) -------------------------------------------------------------------

export const tags: TagInfo[] = [
  {
    id: 2,
    name: "Spendenaffären",
    color: "green",
    description: "Spenden, Finanzierung und Geldflüsse.",
    mails: 37,
    created_by: null,
    created_at: "2026-10-20T09:00:00Z",
  },
  {
    id: 1,
    name: "Vertrag Nordstahl",
    color: "blue",
    description: "",
    mails: 12,
    created_by: "Lena Vogt",
    created_at: "2026-10-19T16:30:00Z",
  },
];

export const collections: CollectionInfo[] = [
  {
    id: 1,
    name: "Story Nordstahl",
    description: "Vergabe des Rahmenvertrags an Nordstahl und die Rolle der Einkaufsleitung.",
    mails: 24,
    created_by: "Lena Vogt",
    created_at: "2026-10-19T16:00:00Z",
    updated_at: "2026-10-21T07:52:00Z",
  },
];

export const searches: SavedSearch[] = [
  {
    id: 3,
    name: "Spendenaffären: Bargeld, Stückelung, Strohleute",
    query: "q=Barspende+or+Barzahlung+or+Bargeld",
    collection_id: null,
    created_by: null,
    created_at: "2026-10-20T09:00:00Z",
    updated_at: "2026-10-20T09:00:00Z",
  },
  {
    id: 4,
    name: "Nordstahl an Einkauf",
    query: "q=from%3Anordstahl&sort=date_asc",
    collection_id: 1,
    created_by: "Lena Vogt",
    created_at: "2026-10-19T16:10:00Z",
    updated_at: "2026-10-19T16:10:00Z",
  },
];

export const research: ResearchOverview = {
  tags: [tags[1], tags[0]].sort((a, b) => a.name.localeCompare(b.name)),
  collections,
  searches,
  review: { unreviewed: 49_310, seen: 412, relevant: 61, irrelevant: 217 },
  flagged: 9,
  notes: 23,
  starter_missing: 22,
};

export const themes: ThemeInfo[] = [
  {
    key: "spenden",
    name: "Spendenaffären",
    color: "green",
    description: "Spenden, Finanzierung und Geldflüsse.",
    terms: ["Spende", "Barspende", "Spendenquittung", "in bar"],
    searches: [
      {
        name: "Spendenaffären: Bargeld, Stückelung, Strohleute",
        query: "q=Barspende+or+Barzahlung+or+Bargeld",
      },
    ],
  },
  {
    key: "gewalt",
    name: "Gewalt",
    color: "amber",
    description: "Gewaltaufrufe, Drohungen, Waffen.",
    terms: ["Waffe", "Drohung", "Feindesliste"],
    searches: [{ name: "Gewalt: Waffen und Bewaffnung", query: "q=Waffe+or+Munition" }],
  },
];

export const collectionDetail: CollectionDetail = {
  ...collections[0],
  date_min: "2026-09-02T08:14:00Z",
  date_max: "2026-10-18T12:32:07Z",
  missing: 1,
  persons: [
    { person: people.anna, mails: 18 },
    { person: people.lukas, mails: 9 },
    { person: people.purchasing, mails: 4 },
  ],
  searches: [searches[1]],
};

export const notePage: NotePage = {
  items: [
    {
      ...mailDetail.research.notes[1],
      mail_sha256: mailDetail.raw_sha256,
      mail: {
        id: mailDetail.id,
        subject: mailDetail.subject,
        date: mailDetail.date,
        sender: people.anna,
      },
    },
    {
      id: 7,
      body: "Absender taucht nach März nicht mehr auf.",
      author: "Jan Brehm",
      created_at: "2026-10-19T11:20:00Z",
      updated_at: "2026-10-19T11:20:00Z",
      mail_sha256: "b".repeat(64),
      mail: { id: null, subject: null, date: null, sender: null },
    },
  ],
  next_cursor: null,
  total: 2,
};

export const exports: ExportInfo[] = [
  {
    id: 3,
    label: "Story Nordstahl",
    mails: 24,
    include_research: false,
    created_by: "Lena Vogt",
    created_at: "2026-10-21T08:10:00Z",
    manifest_sha256: "4f1c9a0e".repeat(8),
    downloaded_at: "2026-10-21T08:10:20Z",
    download_url: "/api/exports/3/download",
  },
];

export const permalink: PermalinkTarget = {
  mail_id: mailDetail.id,
  raw_sha256: mailDetail.raw_sha256,
};

const moreTag = (id: number, name: string, color: TagInfo["color"], mails: number): TagInfo => ({
  ...tags[0],
  id,
  name,
  color,
  description: "",
  mails,
});

/** The research overview with seven tags, more than the filter column lists at first; the mail
 *  of mailDetail carries neither "Gewalt" (3) nor the others it adds. */
export const researchWithTags: ResearchOverview = {
  ...research,
  tags: [
    ...tags,
    moreTag(3, "Gewalt", "amber", 8),
    moreTag(4, "Rassismus", "red", 5),
    moreTag(5, "Verschleierung", "violet", 19),
    moreTag(6, "Für Anwalt", "pink", 4),
    moreTag(7, "Prüfen", "gray", 41),
  ].sort((a, b) => a.name.localeCompare(b.name)),
  collections: [...collections, { ...collections[0], id: 2, name: "Spenden 2024", mails: 61 }],
};

// Attachments and documents (milestone 9) ------------------------------------------------------
// The contract PDF of the mail detail (document 5101) travels in six mails; beside it a
// spreadsheet, a scan, an encrypted list, a photo, an archive, an attached mail and two documents
// whose text could not be read (yet).

function documentItem(
  id: number,
  name: string | null,
  kind: DocumentListItem["kind"],
  mime_type: string,
  extra: Partial<DocumentListItem> = {},
): DocumentListItem {
  return {
    id,
    name,
    names: 1,
    kind,
    mime_type,
    size: 48_213,
    sha256: String(id).padStart(64, "a"),
    pages: null,
    text_status: "text",
    mails: 1,
    first_date: "2026-10-01T04:00:00Z",
    last_date: "2026-10-01T04:00:00Z",
    first_sender: billing,
    snippet: null,
    ...extra,
  };
}

export const documentItems: DocumentListItem[] = [
  documentItem(5101, "Rahmenvereinbarung_2026_final.pdf", "pdf", "application/pdf", {
    names: 3,
    size: 172_032,
    sha256: "91ab44c0d2e8f1a37b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f40",
    pages: 14,
    mails: 6,
    first_date: "2026-09-28T11:15:00Z",
    last_date: "2026-10-18T12:32:07Z",
    first_sender: lukas,
    snippet:
      "§ 7 Zahlungen: Die Spende über 12.500,00 EUR geht auf das Konto DE89 3704 0044 0532 0130 00; weitere Spenden nach Absprache.",
  }),
  documentItem(
    5102,
    "Aenderungsprotokoll.xlsx",
    "spreadsheet",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    { size: 14_336, pages: 2, first_sender: anna, first_date: "2026-10-18T12:32:07Z" },
  ),
  documentItem(5103, "Scan_Vorstandssitzung_2019-03.pdf", "pdf", "application/pdf", {
    size: 2_411_724,
    pages: 6,
    text_status: "scanned",
    mails: 4,
    first_date: "2019-03-14T09:30:00Z",
    last_date: "2024-02-02T15:00:00Z",
    first_sender: miriam,
  }),
  documentItem(5104, "Spendenliste_2019.xlsx", "spreadsheet", "application/octet-stream", {
    text_status: "encrypted",
    mails: 2,
    first_sender: jonas,
  }),
  documentItem(5105, "IMG_2041.jpg", "image", "image/jpeg", {
    size: 1_204_224,
    text_status: "unsupported",
    mails: 3,
    first_sender: sofia,
  }),
  documentItem(5106, "Unterlagen.zip", "archive", "application/zip", { size: 3_150_002 }),
  documentItem(5107, null, "email", "message/rfc822", { size: 22_118, first_sender: null }),
  documentItem(
    5108,
    "Kalkulation.ods",
    "spreadsheet",
    "application/vnd.oasis.opendocument.spreadsheet",
    { text_status: "failed" },
  ),
  documentItem(5109, "Mitgliederliste.docx", "document", "application/msword", {
    text_status: "pending",
  }),
];

export const documentPage: DocumentPage = {
  items: documentItems,
  next_cursor: "documents-page-2",
  prev_cursor: null,
};

/** Every document of the archive, as the dashboard counts them by text status. */
export const documentSummary: DocumentSummary = {
  total: 79_110,
  exact: true,
  kinds: {
    pdf: 21_904,
    document: 9_877,
    spreadsheet: 6_120,
    presentation: 1_032,
    text: 4_511,
    email: 2_208,
    image: 29_877,
    archive: 1_604,
    media: 412,
    other: 1_565,
  },
  // Only the statuses present, as the API sends them.
  text_status: {
    text: 41_380,
    empty: 212,
    scanned: 6_904,
    encrypted: 87,
    unsupported: 30_116,
    too_large: 14,
    failed: 391,
    timeout: 6,
  } as DocumentSummary["text_status"],
};

export const documentSummaryFiltered: DocumentSummary = {
  total: 214,
  exact: true,
  kinds: { pdf: 151, spreadsheet: 63 } as DocumentSummary["kinds"],
  text_status: { text: 177, scanned: 37 } as DocumentSummary["text_status"],
};

export const documentDetail: DocumentDetail = {
  id: 5101,
  name: "Rahmenvereinbarung_2026_final.pdf",
  mime_type: "application/pdf",
  kind: "pdf",
  size: 172_032,
  sha256: "91ab44c0d2e8f1a37b6c5d4e3f2a1b0c9d8e7f6a5b4c3d2e1f0a9b8c7d6e5f40",
  pages: 14,
  text_status: "text",
  text_error: null,
  text_truncated: false,
  extracted_at: "2026-10-20T01:20:00Z",
  mails: 6,
  attachments: 7,
  first_date: "2026-09-28T11:15:00Z",
  last_date: "2026-10-18T12:32:07Z",
  first_mail: {
    id: 183644,
    date: "2026-09-28T11:15:00Z",
    subject: "Vertrag Nordstahl: Änderungswünsche Einkauf",
    sender: lukas,
    dkim_status: "pass",
  },
  names: [
    { name: "Rahmenvereinbarung_2026_final.pdf", attachments: 4 },
    { name: "Rahmenvereinbarung 2026.pdf", attachments: 2 },
    { name: "RV2026_unterschrieben.pdf", attachments: 1 },
  ],
  senders: [
    { person: anna, mails: 3 },
    { person: lukas, mails: 2 },
    { person: miriam, mails: 1 },
  ],
  sender_count: 3,
  recipients: [jonas, peter, miriam, anna, lukas, purchasing, billing, thomas, sofia].map(
    (person, index) => ({ person, mails: Math.max(1, 5 - index) }),
  ),
  recipient_count: 14,
  attachment_id: 901,
  preview: null,
};

/** A photo: no text, shown as a preview. */
export const imageDocument: DocumentDetail = {
  ...documentDetail,
  id: 5105,
  name: "IMG_2041.jpg",
  mime_type: "image/jpeg",
  kind: "image",
  size: 1_204_224,
  sha256: documentItems[4].sha256,
  pages: null,
  text_status: "unsupported",
  extracted_at: "2026-10-20T01:21:00Z",
  mails: 3,
  attachments: 3,
  names: [{ name: "IMG_2041.jpg", attachments: 3 }],
  senders: [{ person: sofia, mails: 3 }],
  sender_count: 1,
  recipients: [{ person: anna, mails: 3 }],
  recipient_count: 1,
  attachment_id: 9105,
  preview: "image",
};

export const documentText: DocumentText = {
  text: [
    "RAHMENVEREINBARUNG 2026",
    "zwischen der Nordlicht GmbH und der Stadtwerke Beispiel AG",
    "",
    "§ 1 Gegenstand",
    "Die Vereinbarung regelt die Lieferung und Wartung der Umspannwerke Nord und Süd.",
    "",
    "§ 7 Zahlungen",
    "Die Spende über 12.500,00 EUR geht auf das Konto DE89 3704 0044 0532 0130 00.",
  ].join("\n"),
  truncated: false,
  text_status: "text",
};

/** The mails carrying document 5101, oldest first. */
export const documentMailPage: MailPage = {
  items: [
    item(
      183644,
      "2026-09-28T11:15:00Z",
      lukas,
      [anna],
      "Vertrag Nordstahl: Änderungswünsche Einkauf",
      "pass",
      { has_attachments: true },
    ),
    item(
      184001,
      "2026-10-09T14:02:00Z",
      anna,
      [miriam],
      "Vertragsentwurf – bitte um Rückmeldung bis Freitag",
      "pass",
      { has_attachments: true, thread_id: 184001 },
    ),
    item(
      184102,
      "2026-10-14T09:20:00Z",
      lukas,
      [purchasing, jonas, peter],
      "WG: Vertrag Lieferant Nordstahl – Unterschrift",
      "fail",
      { has_attachments: true },
    ),
    item(
      184133,
      "2026-10-15T15:48:00Z",
      miriam,
      [anna, lukas],
      "Prüfung Vertragsklauseln §§ 4–7",
      "no_key",
      { has_attachments: true, thread_id: 184001 },
    ),
    item(
      184190,
      "2026-10-17T07:05:00Z",
      anna,
      [jonas],
      "AW: Prüfung Vertragsklauseln §§ 4–7",
      "pass",
      { has_attachments: true, thread_id: 184001 },
    ),
    item(
      184221,
      "2026-10-18T12:32:07Z",
      anna,
      [jonas, peter, miriam],
      "Vertragsentwurf Rahmenvereinbarung 2026 – finale Fassung",
      "pass",
      { has_attachments: true, thread_id: 184001 },
    ),
  ],
  next_cursor: null,
  prev_cursor: null,
  query_terms: [],
};

// Timeline (D90 to D94) -----------------------------------------------------------------------

/** First days of the 36 months from January 2023 to December 2025. */
const MONTH_STARTS = Array.from({ length: 36 }, (_, index) => {
  const month = String((index % 12) + 1).padStart(2, "0");
  return `${2023 + Math.floor(index / 12)}-${month}-01`;
});

/** Monthly counts around base, with some months set and nothing from `until` on. */
function monthly(base: number, set: Record<number, number> = {}, until = 36): number[] {
  return MONTH_STARTS.map((_, index) =>
    index >= until ? 0 : (set[index] ?? base + ((index * 7) % 5) * Math.ceil(base / 10)),
  );
}

function timelineSeries(
  key: string,
  label: string | null,
  counts: number[],
  extra: Partial<TimelineSeries> = {},
): TimelineSeries {
  return {
    key,
    label,
    person: null,
    thread_id: null,
    term: null,
    counts,
    total: counts.reduce((sum, count) => sum + count, 0),
    outliers: [],
    silent_from: null,
    ...extra,
  };
}

const allMonths = timelineSeries("all", null, monthly(1100, { 14: 4300, 26: 240 }), {
  outliers: [
    { index: 14, kind: "high", expected: 1215.5 },
    { index: 26, kind: "low", expected: 1180 },
  ],
});

/** The whole archive by month: one month far above, one far below the moving mean. */
export const timelineAll: Timeline = {
  bucket: "month",
  coarsened: false,
  starts: MONTH_STARTS,
  total: allMonths,
  series: [],
  undated: 214,
  archive_end: "2025-12-30",
  timed_out: false,
};

/** Split by person: Anna, Jonas, and Lukas, who falls silent in July 2025. */
export const timelineByPerson: Timeline = {
  ...timelineAll,
  series: [
    timelineSeries("person:11", people.anna.name, monthly(90, { 14: 380 }), {
      person: people.anna,
      outliers: [{ index: 14, kind: "high", expected: 99 }],
    }),
    timelineSeries("person:12", people.jonas.name, monthly(40), { person: people.jonas }),
    timelineSeries("person:14", people.lukas.name, monthly(25, {}, 30), {
      person: people.lukas,
      silent_from: "2025-07-01",
    }),
  ],
};

export const timelineByThread: Timeline = {
  ...timelineAll,
  series: [
    timelineSeries(
      "thread:184001",
      "Rahmenvertrag Stadtwerke 2024",
      monthly(0, { 12: 8, 13: 21, 14: 34, 15: 6 }),
      {
        thread_id: 184001,
      },
    ),
    timelineSeries("thread:183977", null, monthly(0, { 20: 4, 21: 9 }), { thread_id: 183977 }),
  ],
};

export const timelineByTerm: Timeline = {
  ...timelineAll,
  series: [
    timelineSeries("term:0", "Spende", monthly(3, { 14: 41 }), {
      term: "Spende",
      outliers: [{ index: 14, kind: "high", expected: 4.5 }],
    }),
    timelineSeries("term:1", '"schwarze Kasse"', monthly(0, { 13: 2, 14: 9, 15: 3 }), {
      term: '"schwarze Kasse"',
    }),
  ],
};

/** Anna's mails by month (person=11): silent since October 2025. */
export const timelineAnna: Timeline = {
  ...timelineAll,
  total: timelineSeries("all", null, monthly(95, {}, 33), { silent_from: "2025-10-01" }),
  undated: 3,
};

export const firstMentions: FirstMentions = {
  items: [
    {
      person: people.lukas,
      kind: null,
      role: "from",
      date: "2023-02-14T09:12:00Z",
      mail_id: 183001,
      subject: "Spende des Fördervereins",
      mails: 12,
    },
    {
      person: people.anna,
      kind: null,
      role: "to",
      date: "2023-02-14T09:12:00Z",
      mail_id: 183001,
      subject: "Spende des Fördervereins",
      mails: 31,
    },
    {
      person: people.miriam,
      kind: null,
      role: "cc",
      date: "2023-05-02T16:40:00Z",
      mail_id: 183410,
      subject: "AW: Quittung ohne Betrag",
      mails: 4,
    },
    {
      person: people.jonas,
      kind: null,
      role: "from",
      date: "2024-03-11T07:55:00Z",
      mail_id: 184001,
      subject: "Rahmenvertrag Stadtwerke 2024",
      mails: 9,
    },
  ],
  persons: 4,
  timed_out: false,
};
