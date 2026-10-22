// Realistic API responses for tests, typed with the contract. Only type imports, so the file
// also loads in plain Node (type stripping) for screenshot scripts.

import type {
  AiJob,
  AiResultPage,
  AiSendLogPage,
  AiStatus,
  AiTaskPage,
  CalendarEventInfo,
  CertainMergePlan,
  CertainMergeResult,
  CollectionDetail,
  CollectionInfo,
  Contact,
  ContactPage,
  DkimJob,
  DkimKeyInfo,
  DkimKeysJob,
  DkimStatus,
  DocumentDetail,
  DocumentListItem,
  DocumentPage,
  DocumentSummary,
  DocumentText,
  EntityCount,
  EntityDetail,
  EntityFacets,
  EntityKind,
  EntityListItem,
  EntityPage,
  EntityRef,
  EntitySummary,
  MailEntity,
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
  KeyArchivePreview,
  MailDetail,
  MailHeaders,
  MailHits,
  MailListItem,
  MailNeighbors,
  MailPage,
  MailRaw,
  MailSignals,
  MailSummary,
  MailText,
  MboxFileInfo,
  MergeLogPage,
  MetadataValueCount,
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
  PersonEvents,
  PersonFigures,
  PersonMailCounts,
  PersonPage,
  PersonProfile,
  PersonRef,
  PersonSignals,
  PersonSummary,
  ScanResult,
  SelectorDetail,
  SelectorItem,
  SelectorSummary,
  SignalFacets,
  SignalGroup,
  SignalInfo,
  SignalKey,
  SignalOverview,
  SocialCard,
  SignalReason,
  Stats,
  StepProgress,
  SuggestionPage,
  TopicCluster,
  TopicClusters,
  TopicPeriod,
  TopicPeriods,
  TopicState,
  TopicTerm,
  TopicTerms,
  PasswordTryResult,
  DetailMap,
  EventPlaces,
  MapJob,
  MapStatus,
  PhotoDetail,
  PhotoList,
  PhotoListItem,
  PhotoPoint,
  PhotoPoints,
  PlaceMail,
  PlaceSummary,
  TextPlaces,
  TownLabel,
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
  dkim: {
    pass: 268410,
    consistent: 0,
    fail: 3117,
    no_key: 91204,
    unsigned: 49587,
    temp_error: 0,
    unchecked: 0,
  },
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
  near: { groups: 1840, mails: 4120, hidden: 2510 },
  events: { request: 312, reply: 148, cancel: 21 },
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
  dkim: {
    pass: 786,
    consistent: 0,
    fail: 9,
    no_key: 401,
    unsigned: 11,
    temp_error: 0,
    unchecked: 0,
  },
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
    near_count: 0,
    event: null,
    hits: null,
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
    { key: "subject", value: "Vertrag", raw: "subject:Vertrag", negated: false },
    {
      key: "to",
      value: "@stadtwerke-beispiel.example",
      raw: "to:@stadtwerke-beispiel.example",
      negated: false,
    },
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
        key_origin: "dns",
        key: null,
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
      metadata: {
        author: "Peter Hofmann",
        modified_by: null,
        software: "Microsoft Word für Microsoft 365",
        device: null,
        created: "2026-10-08T15:40:12Z",
        gps: false,
        latitude: null,
        longitude: null,
      },
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
      metadata: null,
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
  near_group: null,
  near: [],
  near_size: 0,
  events: [],
};

/** The hits of "Haftung" in mailDetail (D79): its text, its quoted part, two attachments. */
export const mailHits: MailHits = {
  words: ["Haftung"],
  stems: ["haftung"],
  in_mail: true,
  attachments: [
    {
      attachment_id: 901,
      in_name: false,
      snippet: "§ 6 Haftung: Die Haftung beider Seiten ist auf den Auftragswert begrenzt.",
      in_text: true,
    },
    { attachment_id: 902, in_name: false, snippet: null, in_text: true },
  ],
  whole_word: false,
  in_subject: false,
  in_body: true,
  counts: null,
};

export const noHits: MailHits = {
  words: [],
  stems: [],
  in_mail: false,
  attachments: [],
  whole_word: false,
  in_subject: false,
  in_body: false,
  counts: null,
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
    "> danke für den Entwurf. Zwei Punkte hätten wir noch zu § 4 und zur Haftung.",
    ">",
    "> Viele Grüße",
    "> Jonas Brandt",
  ].join("\n"),
  truncated: false,
  source: "text/plain",
  has_html: true,
  // as quotes.split_text cuts it (D151): the own words, then the quoted history
  segments: [
    { kind: "text", start: 0, end: 412, lines: 6, folded: false },
    { kind: "quote", start: 412, end: 626, lines: 5, folded: true },
  ],
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

/** mailDetail in a group of near duplicates (D153): the same text went to two more recipients
 *  one by one, one of those mails was imported twice, and one more mail is not listed. */
export const mailDetailNear: MailDetail = {
  ...mailDetail,
  near_group: 184180,
  near_size: 5,
  near: [
    {
      id: 184180,
      date: "2026-10-18T12:30:02Z",
      subject: mailDetail.subject,
      sender: people.anna,
      dkim_status: "pass",
      recipients: [people.miriam],
      recipient_count: 1,
      is_duplicate: false,
    },
    {
      id: 184231,
      date: "2026-10-18T12:30:02Z",
      subject: mailDetail.subject,
      sender: people.anna,
      dkim_status: "no_key",
      recipients: [people.miriam],
      recipient_count: 1,
      is_duplicate: true,
    },
    {
      id: 184184,
      date: "2026-10-18T12:31:40Z",
      subject: `AW: ${mailDetail.subject}`,
      sender: people.anna,
      dkim_status: "pass",
      recipients: [people.lukas, people.peter, people.thomas],
      recipient_count: 4,
      is_duplicate: false,
    },
  ],
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

/** The certain suggestions (D160); the uncertain ones are uncertainSuggestionPage. */
const suggestionCounts = { certain: 4, uncertain: 2_180 };

export const suggestionPage: SuggestionPage = {
  items: [
    {
      first: ps.peter,
      second: ps.peterPost,
      same_name: "peter hofmann",
      same_local_part: "p.hofmann",
      tier: "certain",
      reason: "name_and_local_part",
    },
    {
      first: ps.anna,
      second: ps.annaPost,
      same_name: "anna keller",
      same_local_part: null,
      tier: "certain",
      reason: "name_fits_addresses",
    },
    {
      first: ps.jonas,
      second: ps.jonasPrivate,
      same_name: "jonas brandt",
      same_local_part: null,
      tier: "certain",
      reason: "name_fits_addresses",
    },
  ],
  next_cursor: "suggestions-page-2",
  total: 4,
  counts: suggestionCounts,
  computed: true,
};

export const suggestionPage2: SuggestionPage = {
  items: [
    {
      first: ps.anna,
      second: ps.annaShort,
      same_name: "anna keller",
      same_local_part: "a.keller",
      tier: "certain",
      reason: "name_and_local_part",
    },
  ],
  next_cursor: null,
  total: 4,
  counts: suggestionCounts,
  computed: true,
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
    {
      person: ps.annaPost,
      same_name: "anna keller",
      same_local_part: null,
      tier: "certain",
      reason: "name_fits_addresses",
    },
    {
      person: ps.annaShort,
      same_name: null,
      same_local_part: "a.keller",
      tier: "uncertain",
      reason: "local_part",
    },
  ],
  suggestion_counts: { certain: 1, uncertain: 1 },
  merges: [],
  label: null,
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
  keys_job: null,
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
    consistent: 0,
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
    term_ids: [302, null, null, null],
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
    term_ids: [null, null, null],
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

/** What the social media image of the mail detail blacks out (D217). */
export const socialCard: SocialCard = {
  width: 1080,
  height: 1350,
  places: 9,
  redactions: [
    { kind: "participant", places: 4 },
    { kind: "contact", places: 3 },
    { kind: "name", places: 2 },
  ],
  lines: 18,
  truncated: false,
};

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
    protection: "locked",
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
  authors: [
    { value: "Peter Hofmann", documents: 412 },
    { value: "Anna Keller", documents: 233 },
    { value: "Buchhaltung", documents: 87 },
  ],
  programs: [
    { value: "Microsoft Word für Microsoft 365", documents: 3_120 },
    { value: "Canon EOS 80D Firmware 1.0.3", documents: 641 },
    { value: "LibreOffice/7.6.4.1$Linux_X86_64", documents: 95 },
  ],
  protection: { locked: 87, open: 12 },
};

export const documentSummaryFiltered: DocumentSummary = {
  total: 214,
  exact: true,
  kinds: { pdf: 151, spreadsheet: 63 } as DocumentSummary["kinds"],
  text_status: { text: 177, scanned: 37 } as DocumentSummary["text_status"],
  authors: [{ value: "Peter Hofmann", documents: 21 }],
  programs: [{ value: "Microsoft Word für Microsoft 365", documents: 34 }],
  protection: { locked: 3 },
};

/** The search within the facets "Autor" and "Programm" (D167): more than the top values. */
export const metadataValues: MetadataValueCount[] = [
  ...documentSummary.authors!,
  { value: "Peter Hofmann-Berg", documents: 4 },
  ...documentSummary.programs!,
  { value: "Microsoft Excel", documents: 1_870 },
];

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
  metadata: {
    status: "found",
    error: null,
    fields: {
      pdf: {
        version: "1.7",
        revisions: 3,
        title: "Rahmenvereinbarung 2026",
        author: "Peter Hofmann",
        creator: "Microsoft Word für Microsoft 365",
        producer: "Microsoft Word für Microsoft 365",
        creation_date: "2026-10-08T17:40:12+02:00",
        mod_date: "2026-10-09T08:02:51+02:00",
      },
      xmp: {
        creator: ["Peter Hofmann"],
        creator_tool: "Microsoft Word für Microsoft 365",
        document_id: "uuid:7D4E1F0C-1B6C-4D6E-9F2A-3C5B7A9E0D11",
        history_agents: ["Microsoft Word für Microsoft 365", "Adobe Acrobat Pro 24.1"],
        history_events: 2,
      },
      pdf_custom: { Abteilung: "Einkauf" },
    },
    summary: {
      author: "Peter Hofmann",
      modified_by: null,
      software: "Microsoft Word für Microsoft 365",
      device: null,
      created: "2026-10-08T15:40:12Z",
      gps: false,
      latitude: null,
      longitude: null,
    },
  },
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
  metadata: {
    status: "found",
    error: null,
    fields: {
      exif: {
        make: "Canon",
        model: "Canon EOS 80D",
        software: "Firmware Version 1.0.3",
        datetime_original: "2026-10-02T14:31:07+02:00",
        datetime_digitized: "2026-10-02T14:31:07",
        artist: "Sofia Brandt",
        body_serial_number: "032021001234",
        lens_model: "EF-S18-135mm f/3.5-5.6 IS USM",
      },
      gps: {
        latitude: 53.5438333,
        longitude: 9.9661667,
        altitude: 12.5,
        timestamp: "2026-10-02T12:31:05Z",
      },
    },
    summary: {
      author: "Sofia Brandt",
      modified_by: null,
      software: "Firmware Version 1.0.3",
      device: "Canon EOS 80D",
      created: "2026-10-02T12:31:07Z",
      gps: true,
      latitude: 53.5438333,
      longitude: 9.9661667,
    },
  },
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

/** An attachment's bytes as the download endpoint gives them (D76): enough of a PDF for the
 *  preview, which hands them to the viewer unread. */
export const attachmentBytes = new TextEncoder().encode("%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n");

/** A DOCX converted for its preview (D122): a whole document with its own policy. */
export const attachmentHtml = [
  "<!doctype html>",
  '<html lang="de"><head><meta charset="utf-8">',
  "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; img-src data:; style-src 'unsafe-inline'\">",
  "</head><body><h1>Protokoll der Vorstandssitzung</h1>",
  "<p>Die Spende über 12.500,00 EUR wird bestätigt.</p></body></html>",
].join("\n");

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

// Keys of deleted selectors (D100 to D104) ------------------------------------------------------
// s2019 at Nordlicht is resolved: a key reconstructed from two signatures verifies 412 of its
// signatures, and Lena Vogt added a key from the IT wiki that verifies none. 56 more names
// are open, so the list has two pages.

export const s2019Name = "s2019._domainkey.nordlicht-gmbh.example";

export const reconstructedKey: DkimKeyInfo = {
  id: 31,
  name: s2019Name,
  key_type: "rsa",
  bits: 2048,
  key_sha256: "9c1e5f0a7b3d4e2f8a6c0b1d9e7f5a3c2b4d6e8f0a1c3e5b7d9f2a4c6e8b0d1f",
  record: "v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAx3RkZ1",
  origin: "reconstructed",
  factorable: false,
  signatures: 412,
  evidence: [
    {
      id: 61,
      origin: "reconstructed",
      source: "reconstruction",
      lookup_id: 501,
      asked_at: "2026-10-21T09:38:00Z",
      observed_from: null,
      observed_to: null,
      reference: null,
      note: null,
      editor: null,
      raw_sha256: null,
      raw_size: null,
      signatures: [
        {
          mail_id: 152004,
          mail_sha256: "51d0c3a9e8f7b6a5c4d3e2f1a0b9c8d7e6f5a4b3c2d1e0f9a8b7c6d5e4f3a2b1",
          signature_index: 0,
        },
        {
          mail_id: null,
          mail_sha256: "07aa1e2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7",
          signature_index: 1,
        },
      ],
    },
  ],
};

export const manualKey: DkimKeyInfo = {
  id: 32,
  name: s2019Name,
  key_type: "rsa",
  bits: 1024,
  key_sha256: "4b7a2c9d0e1f3a5b7c9d1e3f5a7b9c1d3e5f7a9b1c3d5e7f9a1b3c5d7e9f1a3b",
  record: "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC5",
  origin: "documented",
  factorable: false,
  signatures: 0,
  evidence: [
    {
      id: 62,
      origin: "documented",
      source: "manual",
      lookup_id: 502,
      asked_at: "2026-10-21T10:15:00Z",
      observed_from: "2019-03-01T00:00:00Z",
      observed_to: null,
      reference: "https://wiki.nordlicht-gmbh.example/it/dkim",
      note: "Aus der IT-Dokumentation, Stand März 2019.",
      editor: "Lena Vogt",
      raw_sha256: "c0ffee1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
      raw_size: 48_213,
      signatures: [],
    },
  ],
};

export const selectorDetail: SelectorDetail = {
  name: s2019Name,
  domain: "nordlicht-gmbh.example",
  selector: "s2019",
  dns_status: "not_found",
  dns_record: null,
  dns_fetched_at: "2026-10-20T01:14:00Z",
  signatures: 415,
  mails: 415,
  statuses: { consistent: 412, no_key: 3 },
  rsa_signatures: 415,
  first_signed: "2019-02-11T08:00:00Z",
  last_signed: "2020-12-30T17:00:00Z",
  keys: [manualKey, reconstructedKey],
  lookups: [
    {
      id: 503,
      source: "zkemail",
      query: "https://archive.zk.email/api/key?domain=nordlicht-gmbh.example",
      domain: "nordlicht-gmbh.example",
      name: null,
      asked_at: "2026-10-21T10:30:00Z",
      outcome: "not_found",
      http_status: 200,
      raw_sha256: "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
      raw_size: 2,
      raw_type: "application/json",
      raw_name: null,
      message: null,
      tool_version: "0.10.0",
      editor: null,
      keys: 0,
    },
    {
      id: 502,
      source: "manual",
      query: s2019Name,
      domain: "nordlicht-gmbh.example",
      name: s2019Name,
      asked_at: "2026-10-21T10:15:00Z",
      outcome: "found",
      http_status: null,
      raw_sha256: manualKey.evidence[0].raw_sha256,
      raw_size: 48_213,
      raw_type: "application/pdf",
      raw_name: "dkim-2019.pdf",
      message: null,
      tool_version: "0.10.0",
      editor: "Lena Vogt",
      keys: 1,
    },
    {
      id: 501,
      source: "reconstruction",
      query: s2019Name,
      domain: "nordlicht-gmbh.example",
      name: s2019Name,
      asked_at: "2026-10-21T09:38:00Z",
      outcome: "found",
      http_status: null,
      raw_sha256: null,
      raw_size: null,
      raw_type: null,
      raw_name: null,
      message: "modulus from 2 signatures, e=65537",
      tool_version: "0.10.0",
      editor: null,
      keys: 1,
    },
  ],
  recent_mails: [
    {
      id: 170311,
      date: "2020-12-30T17:00:05Z",
      subject: "Jahresabschluss 2020 – Unterlagen",
      sender: anna,
      signature_index: 0,
      status: "consistent",
      reason: null,
      key_origin: "reconstructed",
      key_id: 31,
      signed_at: "2020-12-30T17:00:00Z",
    },
    {
      id: 169870,
      date: "2020-11-02T10:12:00Z",
      subject: "AW: Spendenquittungen",
      sender: lukas,
      signature_index: 0,
      status: "no_key",
      reason: "key_mismatch",
      key_origin: null,
      key_id: null,
      signed_at: "2020-11-02T10:11:58Z",
    },
    {
      id: 152004,
      date: "2019-02-11T08:00:04Z",
      subject: null,
      sender: null,
      signature_index: 1,
      status: "consistent",
      reason: null,
      key_origin: "reconstructed",
      key_id: 31,
      signed_at: "2019-02-11T08:00:00Z",
    },
  ],
};

const selectorItem = (
  selector: string,
  domain: string,
  mails: number,
  patch: Partial<SelectorItem> = {},
): SelectorItem => ({
  name: `${selector}._domainkey.${domain}`,
  domain,
  selector,
  signatures: mails,
  mails,
  statuses: { no_key: mails },
  rsa_signatures: mails,
  first_signed: "2016-04-02T09:00:00Z",
  last_signed: "2018-11-20T16:30:00Z",
  keys: 0,
  best_origin: null,
  dns_status: "not_found",
  ...patch,
});

/** Most mails first, as the API sorts them. */
export const selectorItems: SelectorItem[] = [
  selectorItem("s2019", "nordlicht-gmbh.example", 415, {
    statuses: selectorDetail.statuses,
    first_signed: selectorDetail.first_signed,
    last_signed: selectorDetail.last_signed,
    keys: 2,
    best_origin: "documented",
  }),
  ...Array.from({ length: 54 }, (_, index) =>
    selectorItem(`mx${index + 1}`, `archiv-${index + 1}.example`, 300 - index * 5),
  ),
  selectorItem("google", "stadtwerke-beispiel.example", 30, {
    statuses: { fail: 30 },
    dns_status: "found",
  }),
  selectorItem("k1", "verein-nord.example", 1, {
    rsa_signatures: 1,
    first_signed: "2017-06-01T12:00:00Z",
    last_signed: "2017-06-01T12:00:00Z",
    dns_status: null,
  }),
];

export const selectorSummary: SelectorSummary = {
  names_missing: 178,
  mails_missing: 8_622,
  reconstructable: 164,
  names_resolved: 12,
  mails_consistent: 5_336,
  keys: { dns: 0, observed: 3, documented: 1, reconstructed: 11 },
  factorable: 1,
  signatures: { dns: 190_412, observed: 140, documented: 0, reconstructed: 5_336 },
  lookups: { reconstruction: 12, archive_text: 1, manual: 1, zkemail: 4, dns: 0 },
  last_lookup_at: "2026-10-21T10:30:00Z",
};

/** A key archive on this machine, which is asked for reserved domains too (D102). */
export const archivePreview: KeyArchivePreview = {
  url: "http://127.0.0.1:8200",
  domains: [
    {
      domain: "nordlicht-gmbh.example",
      names: 4,
      mails: 6_210,
      last_asked_at: "2026-10-01T10:00:00Z",
    },
    { domain: "stadtwerke-beispiel.example", names: 2, mails: 1_904, last_asked_at: null },
    { domain: "verein-nord.example", names: 1, mails: 1, last_asked_at: null },
  ],
  skipped: [],
};

/** The public archive: every domain of a generated archive is reserved, so none goes out. */
export const archivePreviewPublic: KeyArchivePreview = {
  url: "https://archive.zk.email",
  domains: [],
  skipped: ["nordlicht-gmbh.example", "stadtwerke-beispiel.example"],
};

/** A reconstruction of every concerned name from the dashboard, half through. */
export const keysJobRunning: DkimKeysJob = {
  id: 11,
  kind: "dkim_keys",
  origin: "ui",
  status: "running",
  alive: true,
  stop_requested: false,
  started_at: "2026-10-21T09:30:00Z",
  updated_at: "2026-10-21T09:41:12Z",
  report_age_seconds: 1.4,
  finished_at: null,
  message: null,
  leftover: null,
  phase: "reconstruct",
  options: { task: "reconstruct", names: [], domains: [], workers: 4, archive_url: null },
  progress: {
    workers: 4,
    names: 164,
    keys_found: 37,
    factorable: 0,
    mails_checked: 0,
    mails_changed: 0,
    steps: [
      {
        key: "select",
        status: "done",
        unit: "names",
        done: 164,
        total: 164,
        started_at: "2026-10-21T09:30:00Z",
        seconds: 4,
        rate: null,
        eta_seconds: null,
      },
      {
        key: "reconstruct",
        status: "running",
        unit: "names",
        done: 41,
        total: 164,
        started_at: "2026-10-21T09:30:04Z",
        seconds: 668,
        rate: 0.06,
        eta_seconds: 2050,
      },
      ...["compare", "check", "edges", "person_stats", "suggestions", "global_stats"].map(
        waitingStep,
      ),
    ],
    database: null,
  },
};

export const keysJobDone: DkimKeysJob = {
  ...keysJobRunning,
  status: "done",
  alive: false,
  updated_at: "2026-10-21T10:02:40Z",
  finished_at: "2026-10-21T10:02:40Z",
  message: "152 keys for 164 names; 9212 of 9859 mails changed",
  phase: "aggregates",
  progress: {
    workers: 0,
    names: 164,
    keys_found: 152,
    factorable: 1,
    mails_checked: 9_859,
    mails_changed: 9_212,
    steps: [],
    database: null,
  },
};

/** A mail of s2019 whose first signature only the reconstructed key verifies; its second, from
 *  a list server, has lost its key. */
export const mailDetailKeys: MailDetail = {
  ...mailDetail,
  id: 170311,
  subject: "Jahresabschluss 2020 – Unterlagen",
  dkim: {
    status: "consistent",
    signatures: [
      {
        ...mailDetail.dkim.signatures[0],
        status: "consistent",
        domain: "nordlicht-gmbh.example",
        selector: "s2019",
        signed_at: "2020-12-30T17:00:00Z",
        dns_cached: true,
        dns_record: null,
        key_origin: "reconstructed",
        key: reconstructedKey,
      },
      {
        ...mailDetail.dkim.signatures[0],
        index: 1,
        status: "no_key",
        reason: "key_not_found",
        domain: "verteiler-nord.example",
        selector: "list",
        aligned: false,
        dns_record: null,
        key_origin: null,
        key: null,
      },
    ],
  },
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

// Entities (milestone 10) -----------------------------------------------------------------------
// What the texts mention: the themes' terms, amounts around a donation of 12.500 EUR to the
// account DE89 …, organisations, places and contact data of the generated corpus.

const entity = (
  id: number,
  kind: EntityKind,
  label: string,
  detail: string | null = null,
): EntityRef => ({ id, kind, label, detail });

export const entities = {
  spende: entity(302, "term", "Spende", "spenden"),
  barspende: entity(301, "term", "Barspende", "spenden"),
  waffe: entity(303, "term", "Waffe", "gewalt"),
  amount12500: entity(312, "amount", "12.500,00 EUR"),
  amount5000: entity(311, "amount", "5.000,00 EUR"),
  amountDem: entity(313, "amount", "20.000,00 DEM"),
  amount1000: entity(314, "amount", "1.000,00 EUR"),
  amount250: entity(315, "amount", "250,00 EUR"),
  amountChf: entity(316, "amount", "3.000,00 CHF"),
  amount750: entity(317, "amount", "750,00 EUR"),
  amount100000: entity(318, "amount", "100.000,00 EUR"),
  iban: entity(321, "iban", "DE89 3704 0044 0532 0130 00", "DE"),
  account: entity(322, "account", "1234567 (BLZ 370 400 44)"),
  nordstahl: entity(332, "organization", "Nordstahl GmbH & Co. KG"),
  freundeskreis: entity(331, "organization", "Freundeskreis Nord e.V."),
  meier: entity(341, "person", "Hans Meier"),
  koeln: entity(351, "place", "Köln", "city"),
  schweiz: entity(352, "place", "Schweiz", "country"),
  phone: entity(361, "phone", "+49 30 23125123", "DE"),
  kasse: entity(371, "email", "kasse@freundeskreis-nord.example"),
  url: entity(
    381,
    "url",
    "https://www.freundeskreis-nord.example/spenden",
    "www.freundeskreis-nord.example",
  ),
  domain: entity(382, "domain", "freundeskreis-nord.example"),
  date: entity(391, "date", "14.03.2019"),
};

const counted = (ref: EntityRef, mails: number): EntityCount => ({ entity: ref, mails });
const e = entities;

/** The facets without filters: entity.mails of the whole archive. Amounts fill their 8. */
export const entityFacets: EntityFacets = {
  kinds: {
    term: [counted(e.spende, 412), counted(e.barspende, 88), counted(e.waffe, 31)],
    amount: [
      counted(e.amount12500, 41),
      counted(e.amount5000, 37),
      counted(e.amountDem, 22),
      counted(e.amount1000, 19),
      counted(e.amount250, 15),
      counted(e.amountChf, 9),
      counted(e.amount750, 8),
      counted(e.amount100000, 3),
    ],
    iban: [counted(e.iban, 12)],
    account: [counted(e.account, 4)],
    organization: [counted(e.nordstahl, 140), counted(e.freundeskreis, 61)],
    person: [counted(e.meier, 6)],
    place: [counted(e.koeln, 230), counted(e.schweiz, 17)],
    phone: [counted(e.phone, 512)],
    email: [counted(e.kasse, 9)],
    url: [counted(e.url, 14)],
    domain: [counted(e.domain, 33)],
    date: [counted(e.date, 5)],
  },
  mails: null,
  sampled: false,
};

/** The facets of a filter, counted over its 1.207 mails. */
export const entityFacetsFiltered: EntityFacets = {
  kinds: {
    term: [counted(e.spende, 77), counted(e.barspende, 21)],
    amount: [counted(e.amount12500, 41), counted(e.amount5000, 12)],
    iban: [counted(e.iban, 12)],
  },
  mails: 1207,
  sampled: false,
};

/** "mehr" of the amounts: up to 50. */
export const entityFacetsAmounts: EntityFacets = {
  kinds: {
    amount: [
      ...(entityFacets.kinds.amount ?? []),
      counted(entity(319, "amount", "500,00 USD"), 2),
      counted(entity(320, "amount", "80,00 EUR"), 1),
    ],
  },
  mails: null,
  sampled: false,
};

export const entitySummary: EntitySummary = {
  kinds: {
    amount: 4210,
    iban: 96,
    account: 41,
    organization: 1830,
    person: 2650,
    place: 410,
    phone: 1203,
    email: 2290,
    url: 3120,
    domain: 640,
    date: 5900,
    term: 64,
  },
  mails_waiting: 12000,
  documents_waiting: 40,
};

function listed(
  ref: EntityRef,
  mails: number,
  extra: Partial<EntityListItem> = {},
): EntityListItem {
  return {
    ...ref,
    value: null,
    currency: null,
    mails,
    documents: 0,
    first_date: "2019-03-14T09:30:00Z",
    last_date: "2026-10-18T12:32:07Z",
    ...extra,
  };
}

export const entityItems: EntityListItem[] = [
  listed(e.phone, 512, { documents: 3 }),
  listed(e.spende, 412, { documents: 14 }),
  listed(e.koeln, 230),
  listed(e.nordstahl, 140, { documents: 6 }),
  listed(e.amount12500, 41, {
    value: 12500,
    currency: "EUR",
    documents: 2,
    first_date: "2019-03-14T09:30:00Z",
    last_date: "2019-03-14T09:30:00Z",
  }),
  listed(e.iban, 12, { documents: 2 }),
  listed(e.kasse, 9, { first_date: null, last_date: null }),
];

export const entityPage: EntityPage = {
  items: entityItems,
  next_cursor: "entities-page-2",
  prev_cursor: null,
};

/** The donation of 12.500 EUR: in mails and in the contract PDF. */
export const entityDetail: EntityDetail = {
  ...listed(e.amount12500, 41, {
    value: 12500,
    currency: "EUR",
    documents: 2,
    first_date: "2019-03-14T09:30:00Z",
    last_date: "2026-10-18T12:32:07Z",
  }),
  key: "EUR 12500.00",
  contexts: { cash: 3, donation: 12, receipt: 0 },
  years: [
    { year: 2019, mails: 4 },
    { year: 2021, mails: 9 },
    { year: 2026, mails: 28 },
  ],
  senders: [
    { person: anna, mails: 14 },
    { person: lukas, mails: 9 },
  ],
  sender_count: 7,
  recipients: [
    { person: jonas, mails: 20 },
    { person: miriam, mails: 8 },
  ],
  recipient_count: 2,
  related: [counted(e.iban, 11), counted(e.spende, 9), counted(e.freundeskreis, 6)],
  persons_sampled: false,
  samples: [
    {
      mail: {
        id: 183011,
        date: "2019-03-14T09:30:00Z",
        subject: "Spende Freundeskreis",
        sender: anna,
        dkim_status: "pass",
      },
      snippet: "wie besprochen geht die Spende über 12.500,00 EUR in bar an den Freundeskreis.",
      document_id: null,
      document_name: null,
    },
    {
      mail: {
        id: 183644,
        date: "2026-09-28T11:15:00Z",
        subject: "Vertrag Nordstahl: Änderungswünsche Einkauf",
        sender: lukas,
        dkim_status: "pass",
      },
      snippet: "§ 7 Zahlungen: Die Spende über 12.500,00 eur geht auf das Konto DE89 …",
      document_id: 5101,
      document_name: "Rahmenvereinbarung_2026_final.pdf",
    },
  ],
  archive_person: null,
};

/** An address in the text that is also a person of the archive; persons counted in a sample. */
export const entityDetailEmail: EntityDetail = {
  ...listed(e.kasse, 9),
  key: "kasse@freundeskreis-nord.example",
  contexts: { cash: 0, donation: 0, receipt: 0 },
  years: [{ year: 2019, mails: 9 }],
  senders: [{ person: anna, mails: 9 }],
  sender_count: 1,
  recipients: [],
  recipient_count: 0,
  related: [],
  persons_sampled: true,
  samples: [],
  archive_person: {
    person_id: 20,
    email: "kasse@freundeskreis-nord.example",
    name: "Kasse Freundeskreis",
  },
};

const mention = (ref: EntityRef, occurrences = 1, extra: Partial<MailEntity> = {}): MailEntity => ({
  entity: ref,
  occurrences,
  context: [],
  document_id: null,
  document_name: null,
  ...extra,
});

const contract = { document_id: 5101, document_name: "Rahmenvereinbarung_2026_final.pdf" };

/** What was found in the mail detail's mail (184221) and its contract PDF: 15 entities. */
export const mailEntities: MailEntity[] = [
  mention(e.nordstahl, 3),
  mention(e.amount12500, 1, { context: ["donation"] }),
  mention(e.amount12500, 2, { context: ["cash"], ...contract }),
  mention(e.iban, 1, { context: ["donation"], ...contract }),
  mention(e.spende, 2),
  mention(e.koeln),
  mention(e.phone),
  mention(e.domain, 2),
  mention(e.url),
  mention(e.kasse),
  mention(e.meier),
  mention(e.date),
  mention(e.freundeskreis),
  mention(e.schweiz),
  mention(e.amount5000),
  mention(e.barspende, 1, contract),
];

// Topics (milestone 13) ---------------------------------------------------------------------------

/** Computed at 14:05 Berlin time over 398,112 mails that are no duplicates. */
export const topicState: TopicState = {
  computed_at: "2026-10-21T12:05:00Z",
  mails: 398_112,
  terms: 18_234,
  clusters: 2,
};

export const topicStateNever: TopicState = {
  computed_at: null,
  mails: 0,
  terms: 0,
  clusters: 0,
};

/** A term in a scope of scope mails, a of them holding it, against an archive in which df
 *  mails hold it: the figures as the API derives them (D142). */
function topicTerm(
  label: string,
  a: number,
  scope: number,
  df: number,
  themes: string[] = [],
): TopicTerm {
  const share = a / scope;
  const restShare = (df - a) / (topicState.mails - scope);
  return {
    term: label.toLowerCase().replace(/ä/g, "a").replace(/ö/g, "o").replace(/ü/g, "u"),
    label,
    mails: a,
    share,
    rest_share: restShare,
    ratio: restShare > 0 ? share / restShare : null,
    score: Math.round(a * Math.log(share / Math.max(restShare, 1e-6)) * 10) / 10,
    themes,
  };
}

const october: TopicPeriod = {
  start: "2025-10-01",
  end: "2025-10-31",
  mails: 412,
  terms: [
    topicTerm("Spende", 37, 412, 1628, ["spenden"]),
    topicTerm("Mitgliederversammlung", 25, 412, 1100),
    topicTerm("Vorstandssitzung", 22, 412, 600),
    topicTerm("Barspende", 14, 412, 90, ["spenden"]),
    topicTerm("Satzungsänderung", 11, 412, 120),
    topicTerm("Kassenprüfung", 9, 412, 9),
    topicTerm("Rechenschaftsbericht", 8, 412, 70),
    topicTerm("Wahlkampf", 8, 412, 210),
    topicTerm("Plakate", 6, 412, 50),
    topicTerm("Landesparteitag", 5, 412, 140),
  ],
};

/** Months, newest first: October with ten terms (so "mehr" may find more), September with
 *  three, August with none. */
export const topicPeriods: TopicPeriods = {
  state: topicState,
  unit: "month",
  periods: [
    october,
    {
      start: "2025-09-01",
      end: "2025-09-30",
      mails: 388,
      terms: [
        topicTerm("Landesparteitag", 31, 388, 140),
        topicTerm("Delegierte", 18, 388, 160),
        topicTerm("Antragskommission", 7, 388, 12),
      ],
    },
    { start: "2025-08-01", end: "2025-08-31", mails: 95, terms: [] },
  ],
};

/** October alone with all the terms the phase kept. */
export const topicPeriodsMore: TopicPeriods = {
  state: topicState,
  unit: "month",
  periods: [
    {
      ...october,
      terms: [...october.terms, topicTerm("Flyer", 5, 412, 60), topicTerm("Druckerei", 4, 412, 30)],
    },
  ],
};

export const topicPeriodsQuarter: TopicPeriods = {
  state: topicState,
  unit: "quarter",
  periods: [
    {
      start: "2025-10-01",
      end: "2025-12-31",
      mails: 1204,
      terms: [topicTerm("Spende", 61, 1204, 1628, ["spenden"])],
    },
    {
      start: "2025-07-01",
      end: "2025-09-30",
      mails: 1350,
      terms: [topicTerm("Landesparteitag", 44, 1350, 140)],
    },
  ],
};

/** The years with one term each, the answer the screen reads the state from. */
export const topicPeriodsYear: TopicPeriods = {
  state: topicState,
  unit: "year",
  periods: [
    {
      start: "2025-01-01",
      end: "2025-12-31",
      mails: 4800,
      terms: [topicTerm("Landesparteitag", 120, 4800, 140)],
    },
    {
      start: "2024-01-01",
      end: "2024-12-31",
      mails: 5100,
      terms: [topicTerm("Wahlkampf", 160, 5100, 210)],
    },
  ],
};

/** Anna Keller's sent mails: every one counted. */
export const topicTerms: TopicTerms = {
  state: topicState,
  mails: 3412,
  counted: 3412,
  sampled: false,
  terms: [
    topicTerm("Rahmenvertrag", 212, 3412, 640),
    topicTerm("Wartung", 180, 3412, 900),
    topicTerm("Umspannwerk", 95, 3412, 140),
    topicTerm("Spende", 40, 3412, 1628, ["spenden"]),
    topicTerm("Kassenprüfung", 4, 3412, 4),
  ],
  common: [topicTerm("Nordlicht", 2100, 3412, 9000)],
  timed_out: false,
};

/** A large selection: counted over a sample, figures estimated. */
export const topicTermsSampled: TopicTerms = {
  ...topicTerms,
  mails: 48_210,
  counted: 5000,
  sampled: true,
  terms: [topicTerm("Rahmenvertrag", 2990, 48_210, 9000)],
  common: [],
};

export const topicTermsTimedOut: TopicTerms = {
  state: topicState,
  mails: null,
  counted: 0,
  sampled: false,
  terms: [],
  common: [],
  timed_out: true,
};

const cluster = (
  id: number,
  terms: [string, number, string[]?][],
  mails: number,
  months: [string, number][],
): TopicCluster => {
  const labels = terms.map(([label]) => label);
  return {
    id,
    label: labels.slice(0, 3).join(", "),
    query: labels.slice(0, 5).join(" or "),
    mails,
    first_date: `${months[0][0]}T08:14:00Z`,
    last_date: `${months[months.length - 1][0].slice(0, 8)}18T12:32:07Z`,
    terms: terms.map(([label, count, themes = []], index) => ({
      term: label.toLowerCase(),
      label,
      mails: count,
      weight: Math.round((10 - index) * 13.7) / 10,
      themes,
    })),
    months: months.map(([month, count]) => ({ month, mails: count })),
  };
};

/** Two clusters, most mails first, on the months of 2024 and 2025. */
export const topicClusters: TopicClusters = {
  state: topicState,
  clusters: [
    cluster(
      7,
      [
        ["Angebot", 1200],
        ["Preis", 900],
        ["Lieferung", 700],
        ["Rabatt", 300],
        ["Bestellung", 650],
        ["Lieferschein", 120],
      ],
      1840,
      [
        ["2024-01-01", 80],
        ["2024-02-01", 95],
        ["2024-06-01", 140],
        ["2025-03-01", 60],
        ["2025-10-01", 30],
      ],
    ),
    cluster(
      3,
      [
        ["Spende", 1628, ["spenden"]],
        ["Quittung", 410],
        ["Barzahlung", 120, ["spenden"]],
        ["Kasse", 380],
        ["Beleg", 300],
      ],
      640,
      [
        ["2024-11-01", 12],
        ["2025-09-01", 44],
        ["2025-10-01", 61],
      ],
    ),
  ],
};

// Signals (milestone 12, D130 to D139) ----------------------------------------------------------

const sender = (ref: PersonRef, mails: number) => ({ person: ref, mails });

function signalInfo(
  key: SignalKey,
  group: SignalGroup,
  mails: number,
  persons: number,
  senders: ReturnType<typeof sender>[] = [],
  theme: string | null = null,
): SignalInfo {
  return { key, group, theme, available: true, mails, persons, senders };
}

/** The overview after a signals phase with internal domains set: 409.880 mails without
 *  duplicates, every signal of the rules, three persons fallen silent. */
export const signalOverview: SignalOverview = {
  signals: [
    signalInfo("private", "addresses", 18240, 1210, [
      sender(anna, 412),
      sender(jonas, 288),
      sender(sofia, 201),
      sender(thomas, 190),
      sender(peter, 77),
    ]),
    signalInfo("internal_to_private", "addresses", 6120, 342, [
      sender(anna, 380),
      sender(lukas, 211),
      sender(jonas, 96),
    ]),
    signalInfo("private_to_internal", "addresses", 4877, 410, [
      sender(sofia, 201),
      sender(thomas, 190),
    ]),
    signalInfo("private_alias", "addresses", 1934, 61, [sender(anna, 160), sender(jonas, 18)]),
    signalInfo("bcc", "recipients", 9821, 803, [sender(anna, 290), sender(lukas, 102)]),
    signalInfo("many_recipients", "recipients", 3315, 122, [
      sender(billing, 1203),
      sender(lukas, 84),
    ]),
    signalInfo("forward", "recipients", 22408, 2103, [sender(anna, 512), sender(miriam, 230)]),
    signalInfo("forward_out", "recipients", 3127, 451, [sender(anna, 88), sender(peter, 41)]),
    signalInfo("night", "time", 15873, 1902, [sender(lukas, 340), sender(anna, 96)]),
    signalInfo("weekend", "time", 21190, 2410, [sender(lukas, 512), sender(anna, 233)]),
    signalInfo("term:spenden", "wording", 2210, 301, [sender(anna, 41)], "Spendenaffären"),
    signalInfo("term:gewalt", "wording", 412, 77, [], "Gewalt"),
  ],
  settings: {
    internal_domains: ["nordlicht-gmbh.example"],
    private_domains: 78,
    timezone: "Europe/Berlin",
    timezone_known: true,
    night_from: 22,
    night_to: 6,
    many_recipients: 25,
    forward_prefixes: ["Fwd", "Fw", "WG", "TR", "RV", "ENC", "Doorst", "VS", "VB"],
  },
  computed_at: "2026-10-20T01:14:00Z",
  outdated: false,
  mails: 409880,
  silent: [
    { person: lukas, since: "2025-07-01T00:00:00Z", mails: 214 },
    { person: katrin, since: "2025-07-01T00:00:00Z", mails: 31 },
    { person: mehmet, since: "2024-12-01T00:00:00Z", mails: 12 },
  ],
  silent_count: 3,
  sender_domains: [],
};

/** The overview of an archive imported before milestone 12: no phase ran, no internal domains,
 *  so the sender domains are offered as a help. */
export const signalOverviewNever: SignalOverview = {
  ...signalOverview,
  signals: signalOverview.signals.map((info) => ({
    ...info,
    available: !["internal_to_private", "private_to_internal", "private_alias"].includes(info.key),
    mails: 0,
    persons: 0,
    senders: [],
  })),
  settings: { ...signalOverview.settings, internal_domains: [] },
  computed_at: null,
  mails: 0,
  silent: [],
  silent_count: 0,
  sender_domains: stats.sender_domains.slice(0, 4),
};

/** The facets without filters: the last phase's figures. */
export const signalFacets: SignalFacets = {
  signals: Object.fromEntries(signalOverview.signals.map((info) => [info.key, info.mails])),
  mails: null,
  sampled: false,
};

/** The facets of a filter, counted over its 1.207 mails. */
export const signalFacetsFiltered: SignalFacets = {
  signals: { private: 31, bcc: 12, weekend: 140, "term:spenden": 77 },
  mails: 1207,
  sampled: false,
};

function reason(key: SignalKey, group: SignalGroup, extra: Partial<SignalReason> = {}) {
  return {
    key,
    group,
    theme: null,
    persons: [],
    local_time: null,
    recipients: null,
    forward_prefix: null,
    forwarded_mail: null,
    terms: [],
    ...extra,
  } satisfies SignalReason;
}

/** Why the mail detail's mail (184221) shows signals: Anna sent it on a Sunday with her private
 *  address in Bcc, and it names donations. */
export const mailSignals: MailSignals = {
  signals: [
    reason("private", "addresses", { persons: [annaPrivate] }),
    reason("internal_to_private", "addresses", { persons: [anna, annaPrivate] }),
    reason("private_alias", "addresses", { persons: [annaPrivate] }),
    reason("bcc", "recipients", { persons: [annaPrivate] }),
    reason("weekend", "time", { local_time: "2026-10-18T14:32:07+02:00" }),
    reason("term:spenden", "wording", {
      theme: "Spendenaffären",
      terms: [entities.spende, entities.barspende],
    }),
  ],
  timezone: "Europe/Berlin",
  computed_at: "2026-10-20T01:14:00Z",
};

/** The other shapes of a reason: recipients, forwards, an hour of the night in another zone. */
export const mailSignalsForward: MailSignals = {
  signals: [
    reason("many_recipients", "recipients", { recipients: 31 }),
    reason("forward", "recipients", { forward_prefix: "WG", forwarded_mail: "Angebot.eml" }),
    reason("forward_out", "recipients", {
      persons: [thomas],
      forward_prefix: "Fwd",
      forwarded_mail: "",
    }),
    reason("night", "time", { local_time: "2025-11-04T23:41:00-05:00" }),
  ],
  timezone: "America/New_York",
  computed_at: "2026-10-20T01:14:00Z",
};

const archiveShare = (key: SignalKey) =>
  (signalOverview.signals.find((info) => info.key === key)?.mails ?? 0) / signalOverview.mails;

function personCount(
  key: SignalKey,
  group: SignalGroup,
  mails: number,
  theme: string | null = null,
) {
  return { key, group, theme, mails, archive_share: archiveShare(key) };
}

/** The signals of Anna's 3.412 sent mails; she did not fall silent. */
export const personSignals: PersonSignals = {
  sent: 3412,
  signals: [
    personCount("private", "addresses", 412),
    personCount("internal_to_private", "addresses", 380),
    personCount("private_alias", "addresses", 160),
    personCount("bcc", "recipients", 290),
    personCount("forward", "recipients", 512),
    personCount("night", "time", 96),
    personCount("weekend", "time", 233),
    personCount("term:spenden", "wording", 41, "Spendenaffären"),
  ],
  silent_since: null,
  silent_mails: null,
};

// Search options (D171 to D177) -----------------------------------------------------------------

/** A list searched for "Neger" (D176): where the word occurs in each mail; the second is found
 *  through a file name only, the third through words that are not counted. */
export const hitsPage: MailPage = {
  ...mailPage,
  items: mailItems.map((mail, index) => ({
    ...mail,
    hits: [
      { subject: 1, body: 3, attachment: 2, filename: 2 },
      { subject: 0, body: 0, attachment: 0, filename: 2 },
      { subject: 0, body: 0, attachment: 0, filename: 0 },
    ][index] ?? { subject: 0, body: 1, attachment: 0, filename: 0 },
  })),
  query_terms: [{ key: "text", value: "Neger", raw: "Neger", negated: false }],
};

/** "Haftung" as a whole word in the list's places (D173, D176): the quoted "zur Haftung" of the
 *  mail's text, not its "Haftungsklausel", and twice in the contract's text. */
export const wholeWordHits: MailHits = {
  words: ["Haftung"],
  stems: [],
  in_mail: true,
  attachments: [
    {
      attachment_id: 901,
      in_name: false,
      snippet: "§ 6 Haftung: Die Haftung beider Seiten ist auf den Auftragswert begrenzt.",
      in_text: true,
    },
  ],
  whole_word: true,
  in_subject: false,
  in_body: true,
  counts: { subject: 0, body: 1, attachment: 2, filename: 0 },
};

// Calendar invitations (D154, D155) -------------------------------------------------------------

const EVENT_UID = "040000008200E00074C5B7101A82E00800000000B4D2A6F1@nordlicht-gmbh.example";

/** Anna's Outlook invitation to a weekly meeting, as the mail detail shows it: Jonas accepted,
 *  Miriam is optional and tentative, the room is no person. */
export const calendarEvent: CalendarEventInfo = {
  id: 901,
  mail_id: 184221,
  kind: "request",
  method: "REQUEST",
  uid: EVENT_UID,
  sequence: 0,
  status: "CONFIRMED",
  summary: "Abstimmung Rahmenvereinbarung 2026",
  location: "Besprechungsraum 3, Hafenstraße 12",
  description: "Agenda:\n1. Haftung\n2. Laufzeit und Kündigung",
  starts_local: "2026-10-27T10:00:00",
  ends_local: "2026-10-27T11:30:00",
  time_zone: "W. Europe Standard Time",
  starts_at: "2026-10-27T09:00:00Z",
  ends_at: "2026-10-27T10:30:00Z",
  all_day: false,
  recurrence: "FREQ=WEEKLY;BYDAY=TU;COUNT=6",
  organizer: {
    email: anna.email,
    name: "Anna Keller",
    role: "CHAIR",
    partstat: null,
    person: anna,
  },
  attendees: [
    {
      email: jonas.email,
      name: "Jonas Brandt",
      role: "REQ-PARTICIPANT",
      partstat: "ACCEPTED",
      person: jonas,
    },
    {
      email: miriam.email,
      name: "Dr. Miriam Steiner",
      role: "OPT-PARTICIPANT",
      partstat: "TENTATIVE",
      person: miriam,
    },
    {
      email: "raum.3@nordlicht-gmbh.example",
      name: "Besprechungsraum 3",
      role: "NON-PARTICIPANT",
      partstat: "NEEDS-ACTION",
      person: null,
    },
  ],
  uid_mails: 3,
};

/** The mails of the event's UID, newest first: two answers and the invitation. */
export const eventMailPage: MailPage = {
  items: [
    item(
      184236,
      "2026-10-21T08:12:00Z",
      jonas,
      [anna],
      "Angenommen: Abstimmung Rahmenvereinbarung 2026",
      "pass",
      { event: "reply" },
    ),
    item(
      184233,
      "2026-10-20T16:40:00Z",
      miriam,
      [anna],
      "Mit Vorbehalt angenommen: Abstimmung Rahmenvereinbarung 2026",
      "no_key",
      { event: "reply" },
    ),
    item(
      184221,
      "2026-10-18T12:32:07Z",
      anna,
      [jonas, miriam],
      "Einladung: Abstimmung Rahmenvereinbarung 2026",
      "pass",
      { event: "request" },
    ),
  ],
  next_cursor: null,
  prev_cursor: null,
  query_terms: [],
};

/** Anna's events: one she organised, a cancelled one she had accepted, an all-day one she has
 *  not answered. */
export const personEvents: PersonEvents = {
  items: [
    {
      event: { ...calendarEvent, attendees: [] },
      organizer: true,
      partstat: null,
      mail: {
        id: 184221,
        date: "2026-10-18T12:32:07Z",
        subject: "Einladung: Abstimmung Rahmenvereinbarung 2026",
        sender: anna,
        dkim_status: "pass",
      },
    },
    {
      event: {
        ...calendarEvent,
        id: 877,
        mail_id: 183950,
        kind: "cancel",
        method: "CANCEL",
        uid: "8f1c2a90-3b7e-4d1a-a5c2-6e0f9b8d7c11@stadtwerke-beispiel.example",
        sequence: 2,
        status: "CANCELLED",
        summary: "Jahresgespräch Stadtwerke",
        location: null,
        description: null,
        starts_local: "2026-09-15T13:00:00",
        ends_local: "2026-09-15T14:00:00",
        time_zone: "UTC",
        starts_at: "2026-09-15T13:00:00Z",
        ends_at: "2026-09-15T14:00:00Z",
        recurrence: null,
        organizer: { email: jonas.email, name: null, role: null, partstat: null, person: jonas },
        attendees: [],
        uid_mails: 4,
      },
      organizer: false,
      partstat: "ACCEPTED",
      mail: {
        id: 183950,
        date: "2026-09-10T07:02:00Z",
        subject: "Abgesagt: Jahresgespräch Stadtwerke",
        sender: jonas,
        dkim_status: "pass",
      },
    },
    {
      event: {
        ...calendarEvent,
        id: 512,
        mail_id: 181002,
        uid: "b7e94d02c1@verband.example",
        summary: "Verbandstag Nord",
        location: "Kiel",
        description: null,
        starts_local: "2026-06-04T00:00:00",
        ends_local: "2026-06-06T00:00:00",
        time_zone: null,
        starts_at: null,
        ends_at: null,
        all_day: true,
        recurrence: null,
        organizer: {
          email: "termine@verband.example",
          name: "Verband Nord",
          role: null,
          partstat: null,
          person: null,
        },
        attendees: [],
        uid_mails: 1,
      },
      organizer: false,
      partstat: null,
      mail: {
        id: 181002,
        date: "2026-05-02T09:30:00Z",
        subject: "Einladung: Verbandstag Nord",
        sender: null,
        dkim_status: "unsigned",
      },
    },
  ],
  total: 3,
};

// Alias tiers, merging every certain suggestion, the merge log (D160 to D163) -------------------

const refOf = (summary: PersonSummary): PersonRef => ({
  person_id: summary.id,
  email: summary.email,
  name: summary.name,
});

/** The uncertain suggestions: namesakes without shared contacts, a name alone, a local part
 *  alone. */
export const uncertainSuggestionPage: SuggestionPage = {
  items: [
    {
      first: summary(
        person(33, "Jonas Weber", "jonas.weber@baeckerei-nord.example"),
        figures(8, 6),
      ),
      second: summary(person(34, "Jonas Weber", "jonas.weber@kanzlei-sued.example"), figures(2, 1)),
      same_name: "jonas weber",
      same_local_part: "jonas.weber",
      tier: "uncertain",
      reason: "name_and_local_part_few_contacts",
    },
    {
      first: ps.anna,
      second: summary(person(31, "Anna Keller", "keller@schule-ost.example"), figures(5, 9)),
      same_name: "anna keller",
      same_local_part: null,
      tier: "uncertain",
      reason: "name",
    },
    {
      first: ps.lukas,
      second: summary(person(32, "L. Vogt", "lukas.vogt@mail.example"), figures(3, 4)),
      same_name: null,
      same_local_part: "lukas.vogt",
      tier: "uncertain",
      reason: "local_part",
    },
  ],
  next_cursor: "uncertain-page-2",
  total: 2_180,
  counts: { certain: 4, uncertain: 2_180 },
  computed: true,
};

export const certainMergePlan: CertainMergePlan = {
  merges: 290,
  persons: 312,
  left_out_groups: 4,
  left_out_persons: 27,
};

export const certainMergeResult: CertainMergeResult = { ...certainMergePlan, batch_id: 7 };

/** Two merges of run 7, one of them undone, and one merge of Anna's aliases on its own. */
export const mergeLogPage: MergeLogPage = {
  items: [
    {
      id: 42,
      target: refOf(ps.peter),
      moved: [refOf(ps.peterPost)],
      batch_id: 7,
      editor: "Lena Vogt",
      created_at: "2026-10-21T14:03:00Z",
      undone_at: null,
      undone_by: null,
    },
    {
      id: 41,
      target: refOf(ps.jonas),
      moved: [refOf(ps.jonasPrivate)],
      batch_id: 7,
      editor: "Lena Vogt",
      created_at: "2026-10-21T14:03:00Z",
      undone_at: "2026-10-21T14:10:00Z",
      undone_by: "Lena Vogt",
    },
    {
      id: 40,
      target: anna,
      moved: [annaWork, annaPrivate],
      batch_id: null,
      editor: null,
      created_at: "2026-10-20T09:12:00Z",
      undone_at: null,
      undone_by: null,
    },
  ],
  batches: [
    { id: 7, created_at: "2026-10-21T14:03:00Z", editor: "Lena Vogt", merges: 290, undone: 1 },
  ],
  next_cursor: null,
  total: 3,
};

// Protected and packed attachments (milestone 19, D230 to D239) ---------------------------------

const noMetadata: DocumentDetail["metadata"] = {
  status: "empty",
  error: null,
  fields: {},
  summary: null,
};

/** A spreadsheet that needs a password nobody has found yet; the imports tried 14. */
export const lockedDocument: DocumentDetail = {
  ...documentDetail,
  id: 5104,
  name: "Spendenliste_2019.xlsx",
  mime_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  kind: "spreadsheet",
  size: 48_213,
  sha256: documentItems[3].sha256,
  pages: null,
  text_status: "encrypted",
  extracted_at: "2026-10-20T01:22:00Z",
  mails: 2,
  attachments: 2,
  names: [{ name: "Spendenliste_2019.xlsx", attachments: 2 }],
  attachment_id: 9104,
  preview: null,
  metadata: noMetadata,
  protection: "locked",
  password_trial: true,
  password_tries: 14,
  password_tried_at: "2026-10-20T01:23:00Z",
  password: null,
  members: null,
  containers: [],
};

/** An offer opened with the password Miriam sent in the same thread a day later. */
export const openedDocument: DocumentDetail = {
  ...documentDetail,
  id: 5110,
  name: "Angebot_Nordstahl.pdf",
  size: 96_310,
  sha256: "c3".repeat(32),
  pages: 3,
  mails: 1,
  attachments: 1,
  names: [{ name: "Angebot_Nordstahl.pdf", attachments: 1 }],
  attachment_id: 9110,
  preview: "pdf",
  metadata: noMetadata,
  protection: "open",
  password_trial: true,
  password_tries: 3,
  password_tried_at: "2026-10-20T01:23:00Z",
  password: {
    value: "Sommer2019!",
    tier: "thread",
    found_at: "2026-10-20T01:23:00Z",
    found_by: null,
    finding: {
      id: 71,
      context: "das Kennwort für das Angebot lautet Sommer2019! – bitte nicht weitergeben.",
      mail: mailDetail.thread[1],
      recipients: [jonas, anna],
      document: null,
      editor: null,
      created_at: "2026-10-20T01:21:00Z",
    },
  },
  members: null,
  containers: [],
};

/** A ZIP whose entries became documents, but one needs a password and one was too large. */
export const containerDocument: DocumentDetail = {
  ...documentDetail,
  id: 5106,
  name: "Unterlagen.zip",
  mime_type: "application/zip",
  kind: "archive",
  size: 3_150_002,
  sha256: documentItems[5].sha256,
  pages: null,
  text_status: "unsupported",
  mails: 1,
  attachments: 1,
  names: [{ name: "Unterlagen.zip", attachments: 1 }],
  attachment_id: 9106,
  preview: null,
  metadata: noMetadata,
  protection: null,
  password_trial: false,
  password_tries: 0,
  password_tried_at: null,
  password: null,
  members: {
    status: "locked",
    error: null,
    entries: [
      {
        position: 0,
        path: "Vorstand/Protokoll_2019-03.docx",
        size: 31_744,
        status: "document",
        error: null,
        document_id: 5111,
        kind: "document",
        text_status: "text",
        protection: null,
      },
      {
        position: 1,
        path: "Vorstand/Gehaelter_2019.xlsx",
        size: 18_002,
        status: "locked",
        error: null,
        document_id: null,
        kind: null,
        text_status: null,
        protection: null,
      },
      {
        position: 2,
        path: "Video/Mitgliederversammlung.mp4",
        size: 812_000_000,
        status: "too_large",
        error: null,
        document_id: null,
        kind: null,
        text_status: null,
        protection: null,
      },
      {
        position: 3,
        path: "Scans/Beleg_017.pdf",
        size: 220_413,
        status: "document",
        error: null,
        document_id: 5112,
        kind: "pdf",
        text_status: "scanned",
        protection: null,
      },
    ],
  },
  containers: [],
};

/** The minutes found inside the ZIP. */
export const memberDocument: DocumentDetail = {
  ...documentDetail,
  id: 5111,
  name: "Protokoll_2019-03.docx",
  mime_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  kind: "document",
  size: 31_744,
  sha256: "d4".repeat(32),
  pages: null,
  mails: 1,
  attachments: 1,
  names: [{ name: "Protokoll_2019-03.docx", attachments: 1 }],
  attachment_id: 9111,
  preview: null,
  metadata: noMetadata,
  protection: null,
  password_trial: false,
  password_tries: 0,
  password_tried_at: null,
  password: null,
  members: null,
  containers: [
    { document_id: 5106, name: "Unterlagen.zip", path: "Vorstand/Protokoll_2019-03.docx" },
  ],
};

/** A password typed in on a locked document's page that opened nothing (D237). */
export const passwordTryMissed: PasswordTryResult = { tried: 1, opened: [], errors: 0 };

/** The same password tried on every locked document: two opened, one unreadable. */
export const passwordTryEverywhere: PasswordTryResult = {
  tried: 87,
  opened: [5110, 5106],
  errors: 1,
};

/** The overview once the attachments signals were computed (D238). */
export const signalOverviewAttachments: SignalOverview = {
  ...signalOverview,
  signals: [
    ...signalOverview.signals.filter((info) => info.group !== "wording"),
    signalInfo("encrypted_attachment", "attachments", 412, 96, [sender(jonas, 41)]),
    signalInfo("password_separate", "attachments", 38, 21, [sender(miriam, 6)]),
    signalInfo("encrypted_mail", "attachments", 7, 3),
    ...signalOverview.signals.filter((info) => info.group === "wording"),
  ],
};

/** A mail carrying a locked spreadsheet and holding the password of another mail's offer. */
export const mailSignalsAttachments: MailSignals = {
  signals: [
    reason("encrypted_attachment", "attachments", {
      documents: [{ id: 5104, name: "Spendenliste_2019.xlsx" }],
    }),
    reason("password_separate", "attachments", {
      documents: [
        { id: 5110, name: "Angebot_Nordstahl.pdf" },
        { id: 5106, name: null },
      ],
    }),
  ],
  timezone: "Europe/Berlin",
  computed_at: "2026-10-20T01:14:00Z",
};

// Places (milestone 20, D240 to D249) ---------------------------------------------------------

/** The towns the overview map labels (D244): capitals and the larger towns of the DACH lists. */
export const towns: TownLabel[] = [
  {
    name: "Berlin",
    lat: 52.52437,
    lon: 13.41053,
    population: 3_426_354,
    country: "DE",
    capital: true,
  },
  {
    name: "Wien",
    lat: 48.20849,
    lon: 16.37208,
    population: 1_691_468,
    country: "AT",
    capital: true,
  },
  { name: "Bern", lat: 46.94809, lon: 7.44744, population: 121_631, country: "CH", capital: true },
  { name: "Vaduz", lat: 47.14151, lon: 9.52154, population: 5_197, country: "LI", capital: true },
  {
    name: "Hamburg",
    lat: 53.57532,
    lon: 10.01534,
    population: 1_739_117,
    country: "DE",
    capital: false,
  },
  {
    name: "München",
    lat: 48.13743,
    lon: 11.57549,
    population: 1_260_391,
    country: "DE",
    capital: false,
  },
  { name: "Köln", lat: 50.93333, lon: 6.95, population: 963_395, country: "DE", capital: false },
  {
    name: "Frankfurt am Main",
    lat: 50.11552,
    lon: 8.68417,
    population: 650_000,
    country: "DE",
    capital: false,
  },
  { name: "Zürich", lat: 47.36667, lon: 8.55, population: 341_730, country: "CH", capital: false },
  {
    name: "Leipzig",
    lat: 51.33962,
    lon: 12.37129,
    population: 504_971,
    country: "DE",
    capital: false,
  },
  {
    name: "Dresden",
    lat: 51.05089,
    lon: 13.73832,
    population: 486_854,
    country: "DE",
    capital: false,
  },
  {
    name: "Hannover",
    lat: 52.37052,
    lon: 9.73322,
    population: 515_140,
    country: "DE",
    capital: false,
  },
  { name: "Graz", lat: 47.06667, lon: 15.45, population: 222_326, country: "AT", capital: false },
  {
    name: "Erfurt",
    lat: 50.9787,
    lon: 11.03283,
    population: 203_254,
    country: "DE",
    capital: false,
  },
  {
    name: "Weimar",
    lat: 50.9803,
    lon: 11.32903,
    population: 64_726,
    country: "DE",
    capital: false,
  },
  {
    name: "Lübeck",
    lat: 53.86893,
    lon: 10.68729,
    population: 212_207,
    country: "DE",
    capital: false,
  },
];

/** Photos around a town, spread on a small spiral so that they bundle when zoomed out. */
function photosAround(first: number, count: number, lat: number, lon: number): PhotoPoint[] {
  return Array.from({ length: count }, (_, index) => ({
    id: first + index,
    lat: Math.round((lat + 0.004 * index * Math.cos(index * 2.4)) * 1e5) / 1e5,
    lon: Math.round((lon + 0.006 * index * Math.sin(index * 2.4)) * 1e5) / 1e5,
  }));
}

/** The photo of the document page (imageDocument) and the one near Weimar the panels open. */
export const hamburgPhoto: PhotoPoint = { id: 5105, lat: 53.5438333, lon: 9.9661667 };
export const weimarPhoto: PhotoPoint = { id: 5107, lat: 50.99512, lon: 11.35201 };

export const photoPoints: PhotoPoints = {
  points: [
    hamburgPhoto,
    weimarPhoto,
    ...photosAround(6001, 38, 53.55, 10.0),
    ...photosAround(6101, 24, 52.52, 13.4),
    ...photosAround(6201, 12, 50.98, 11.33),
    ...photosAround(6301, 17, 48.14, 11.58),
    ...photosAround(6401, 6, 47.37, 8.54),
    ...photosAround(6501, 4, 48.21, 16.37),
    { id: 6601, lat: 54.3233, lon: 10.1228 },
    { id: 6602, lat: 51.0504, lon: 13.7373 },
  ],
  total: 105,
  truncated: false,
};

/** More photos than the map draws (PHOTO_POINT_LIMIT). */
export const photoPointsTruncated: PhotoPoints = { ...photoPoints, total: 23_456, truncated: true };

const placeMail = (
  id: number,
  date: string,
  subject: string,
  sender: PersonRef,
  recipients: PersonRef[],
  recipient_count = recipients.length,
): PlaceMail => ({ id, date, subject, sender, recipients, recipient_count });

export const photoDetail: PhotoDetail = {
  document_id: 5107,
  attachment_id: 9107,
  name: "IMG_3310.jpg",
  mime_type: "image/jpeg",
  preview: "image",
  latitude: 50.99512,
  longitude: 11.35201,
  altitude: 236.5,
  taken_at: "2026-06-14T09:12:44Z",
  taken_text: null,
  device: "Apple iPhone 13 mini",
  nearest: {
    name: "Weimar",
    region: "Thüringen",
    country: "DE",
    distance_km: 2.3,
    direction: "NO",
  },
  mails: [
    placeMail(184060, "2026-06-14T18:40:00Z", "Fotos vom Ortstermin", sofia, [anna, jonas]),
    placeMail(184071, "2026-06-16T08:02:00Z", "WG: Fotos vom Ortstermin", anna, [peter], 3),
  ],
  mail_count: 2,
};

/** A photo whose file gives a time without a zone and no device. */
export const photoDetailLocal: PhotoDetail = {
  ...photoDetail,
  document_id: 5105,
  attachment_id: 9105,
  name: "IMG_2041.jpg",
  latitude: 53.5438333,
  longitude: 9.9661667,
  altitude: null,
  taken_at: null,
  taken_text: "2026-10-02T14:31:07",
  device: null,
  nearest: {
    name: "Hamburg",
    region: "Hamburg",
    country: "DE",
    distance_km: 0.3,
    direction: null,
  },
  mails: [placeMail(184221, "2026-10-02T15:10:00Z", "Bilder vom Hafen", sofia, [anna])],
  mail_count: 1,
};

const listedPhoto = (
  document_id: number,
  name: string,
  latitude: number,
  longitude: number,
  taken_at: string | null,
  distance_km: number | null,
): PhotoListItem => ({
  document_id,
  attachment_id: document_id + 4000,
  name,
  latitude,
  longitude,
  taken_at,
  device: "Apple iPhone 13 mini",
  distance_km,
  first_mail: null,
});

/** "Fotos im Umkreis" of photoDetail: itself first, then the nearest. */
export const photosNearby: PhotoList = {
  items: [
    listedPhoto(5107, "IMG_3310.jpg", 50.99512, 11.35201, "2026-06-14T09:12:44Z", 0),
    listedPhoto(6201, "IMG_3311.jpg", 50.98, 11.33, "2026-06-14T09:14:02Z", 1.8),
    listedPhoto(6202, "IMG_3315.jpg", 50.9828, 11.3352, "2026-06-14T09:31:40Z", 2.0),
  ],
  total: 3,
  truncated: false,
};

/** "Fotos dieses Geräts" of photoDetail, by capture time. */
export const photosOfDevice: PhotoList = {
  items: [
    listedPhoto(6101, "IMG_2980.jpg", 52.52, 13.4, "2026-04-02T16:20:00Z", null),
    listedPhoto(5107, "IMG_3310.jpg", 50.99512, 11.35201, "2026-06-14T09:12:44Z", null),
    listedPhoto(6202, "IMG_3315.jpg", 50.9828, 11.3352, "2026-06-14T09:31:40Z", null),
  ],
  total: 3,
  truncated: false,
};

export const textPlaces: TextPlaces = {
  places: [
    {
      entity_id: 353,
      label: "Berlin",
      place: "Berlin, DE",
      detail: "city",
      lat: 52.52437,
      lon: 13.41053,
      mails: 412,
    },
    {
      entity_id: 351,
      label: "Köln",
      place: "Köln, Nordrhein-Westfalen, DE",
      detail: "city",
      lat: 50.93333,
      lon: 6.95,
      mails: 188,
    },
    {
      entity_id: 354,
      label: "Frankfurt",
      place: "Frankfurt am Main, Hessen, DE",
      detail: "city",
      lat: 50.11552,
      lon: 8.68417,
      mails: 96,
    },
    {
      entity_id: 355,
      label: "Wien",
      place: "Wien, AT",
      detail: "city",
      lat: 48.20849,
      lon: 16.37208,
      mails: 41,
    },
    {
      entity_id: 352,
      label: "Schweiz",
      place: "Schweiz",
      detail: "country",
      lat: 46.80237,
      lon: 8.22667,
      mails: 23,
    },
    {
      entity_id: 356,
      label: "Weimar",
      place: "Weimar, Thüringen, DE",
      detail: "city",
      lat: 50.9803,
      lon: 11.32903,
      mails: 9,
    },
  ],
  total: 6,
  exact: true,
};

/** More places than the map draws, counted over a sample (D87). */
export const textPlacesSampled: TextPlaces = { ...textPlaces, total: 2_345, exact: false };

export const eventPlaces: EventPlaces = {
  places: [
    {
      lat: 53.55073,
      lon: 9.99302,
      place: "Hamburg, DE",
      locations: ["Hamburg, Hotel am Hafen, Saal 2", "20457 Hamburg"],
      events: 3,
      first: "2026-03-10T09:00:00Z",
      last: "2026-09-22T13:00:00Z",
      samples: [
        {
          event_id: 902,
          mail_id: 184190,
          kind: "request",
          summary: "Abstimmung Rahmenvereinbarung",
          location: "Hamburg, Hotel am Hafen, Saal 2",
          starts_at: "2026-09-22T13:00:00Z",
          starts_local: null,
          all_day: false,
          uid: "040000008200E00074C5B7101A82E008",
        },
        {
          event_id: 901,
          mail_id: 184133,
          kind: "cancel",
          summary: "Workshop Netzausbau",
          location: "20457 Hamburg",
          starts_at: null,
          starts_local: "2026-03-10T09:00:00",
          all_day: false,
          uid: null,
        },
      ],
    },
    {
      lat: 48.13743,
      lon: 11.57549,
      place: "München, Bayern, DE",
      locations: ["München"],
      events: 1,
      first: "2026-05-04T00:00:00Z",
      last: "2026-05-04T00:00:00Z",
      samples: [
        {
          event_id: 903,
          mail_id: 184071,
          kind: "request",
          summary: "Messe Energie",
          location: "München",
          starts_at: null,
          starts_local: "2026-05-04",
          all_day: true,
          uid: null,
        },
      ],
    },
  ],
  total: 2,
};

export const placeSummary: PlaceSummary = {
  photos: 105,
  photos_dated: 98,
  devices: [
    { device: "Apple iPhone 13 mini", photos: 61 },
    { device: "Canon EOS 80D", photos: 38 },
    { device: "Samsung SM-G991B", photos: 6 },
  ],
  texts: { found: 1_204, ambiguous: 37, unknown: 212, waiting: 0 },
  events: { found: 18, ambiguous: 1, unknown: 9, waiting: 0 },
  outdated: false,
  computed_at: "2026-10-21T02:10:00Z",
};

const MB = 1024 ** 2;
const GB = 1024 ** 3;

/** The map status without a detail map, downloads offered (D245). */
export const mapStatus: MapStatus = {
  offered: true,
  source_host: "build.protomaps.com",
  detail_map: null,
  partial: null,
  regions: [
    {
      key: "de",
      bbox: [5.87, 47.27, 15.04, 55.06],
      sizes: { overview: 210 * MB, streets: 3.5 * GB, full: 7.2 * GB },
    },
    {
      key: "at",
      bbox: [9.53, 46.37, 17.16, 49.02],
      sizes: { overview: 60 * MB, streets: 1.1 * GB, full: 2.2 * GB },
    },
    {
      key: "ch",
      bbox: [5.96, 45.82, 10.49, 47.81],
      sizes: { overview: 40 * MB, streets: 0.7 * GB, full: 1.5 * GB },
    },
    {
      key: "dach",
      bbox: [5.87, 45.82, 17.16, 55.06],
      sizes: { overview: 300 * MB, streets: 5.2 * GB, full: 10.8 * GB },
    },
  ],
  details: [
    { key: "overview", max_zoom: 10 },
    { key: "streets", max_zoom: 14 },
    { key: "full", max_zoom: 15 },
  ],
  size_hints_build: "2026-10-22",
  free_bytes: 120 * GB,
  job: null,
};

/** The server offers no downloads (MAILROBBE_MAP_SOURCE=off). */
export const mapStatusOff: MapStatus = { ...mapStatus, offered: false, source_host: null };

export const detailMap: DetailMap = {
  url: "/api/map/tiles/detail.pmtiles",
  region: "de",
  bbox: [5.87, 47.27, 15.04, 55.06],
  detail: "streets",
  max_zoom: 14,
  build: "20261021",
  source_url: "https://build.protomaps.com/20261021.pmtiles",
  size: 3.4 * GB,
  tiles: 1_604_221,
  downloaded_at: "2026-10-22T06:40:00Z",
};

export const mapStatusDetail: MapStatus = { ...mapStatus, detail_map: detailMap };

/** A download of Germany with streets while it runs (D246). */
export const mapJobRunning: MapJob = {
  id: 21,
  kind: "map",
  origin: "ui",
  status: "running",
  alive: true,
  stop_requested: false,
  started_at: "2026-10-22T08:00:00Z",
  updated_at: "2026-10-22T08:21:12Z",
  report_age_seconds: 1.2,
  finished_at: null,
  message: null,
  leftover: null,
  phase: "download",
  options: {
    region: "de",
    detail: "streets",
    bbox: [5.87, 47.27, 15.04, 55.06],
    max_zoom: 14,
    source: "protomaps",
  },
  progress: {
    source_url: "https://build.protomaps.com/20261021.pmtiles",
    build: "20261021",
    tiles: 612_400,
    bytes_total: 3.4 * GB,
    bytes_done: 1.3 * GB,
    continued_bytes: 0,
    steps: [
      {
        key: "directories",
        status: "done",
        unit: null,
        done: 0,
        total: null,
        started_at: "2026-10-22T08:00:00Z",
        seconds: 41,
        rate: null,
        eta_seconds: null,
      },
      {
        key: "tiles",
        status: "running",
        unit: "bytes",
        done: 1.3 * GB,
        total: 3.4 * GB,
        started_at: "2026-10-22T08:00:41Z",
        seconds: 1231,
        rate: 1.1 * MB,
        eta_seconds: 1960,
      },
      waitingStep("finish"),
    ],
    database: null,
  },
};

export const mapStatusRunning: MapStatus = { ...mapStatus, job: mapJobRunning };

/** A download stopped halfway: the same choice continues it. */
export const mapStatusPartial: MapStatus = {
  ...mapStatus,
  partial: {
    region: "at",
    bbox: [9.53, 46.37, 17.16, 49.02],
    detail: "full",
    build: "20261021",
    bytes_done: 0.9 * GB,
    bytes_total: 2.2 * GB,
  },
  job: {
    ...mapJobRunning,
    id: 20,
    status: "stopped",
    alive: false,
    finished_at: "2026-10-22T07:30:00Z",
    options: { ...mapJobRunning.options, region: "at", detail: "full", max_zoom: 15 },
  },
};

/** The latest download failed after its retries. */
export const mapStatusFailed: MapStatus = {
  ...mapStatus,
  job: {
    ...mapJobRunning,
    id: 19,
    status: "failed",
    alive: false,
    finished_at: "2026-10-22T07:10:00Z",
    message: "range request failed three times: HTTP 503 from build.protomaps.com",
  },
};

// AI and OCR (milestone 15) ---------------------------------------------------------------------

const aiDefaults: AiStatus["defaults"] = {
  kinds: ["ocr"],
  ocr_engine: "auto",
  vision_model: "qwen2.5vl:7b",
  max_pages: 50,
  languages: "deu+eng",
  uncertain: 60,
  concurrency: 1,
  tesseract_workers: 4,
  vision_url: "http://host.docker.internal:11434",
  vision_remote: false,
};

const aiQueueEmpty = { waiting: 0, running: 0, done: 0, failed: 0, cancelled: 0 };

/** The AI page with a local vision model, two work lists and some queued tasks, no run. */
export const aiStatus: AiStatus = {
  enabled: true,
  vision: true,
  tesseract: true,
  ocr_languages: "deu+eng",
  services: [
    {
      capability: "vision",
      url: "http://host.docker.internal:11434",
      model: "qwen2.5vl:7b",
      protocol: "auto",
      locality: "local",
      refused: null,
      key: false,
    },
  ],
  allow_remote: false,
  remote_token_budget: 0,
  ocr_engine: "auto",
  queue: {
    ocr: { waiting: 12, running: 0, done: 31, failed: 2, cancelled: 1 },
    transcribe: aiQueueEmpty,
    summarize: aiQueueEmpty,
  },
  work_lists: [
    {
      key: "scanned",
      documents: 214,
      pages: 1_380,
      without_pages: 3,
      bytes: 412_000_000,
      estimates: [
        { engine: "tesseract", model: "", seconds: 5_520, estimated: true, seconds_per_page: 4 },
        {
          engine: "vision",
          model: "qwen2.5vl:7b",
          seconds: 55_200,
          estimated: true,
          seconds_per_page: 40,
        },
      ],
      engine: "tesseract",
    },
    {
      key: "images",
      documents: 0,
      pages: 0,
      without_pages: 0,
      bytes: 0,
      estimates: [],
      engine: "vision",
    },
  ],
  remote_used: false,
  job: null,
  defaults: aiDefaults,
};

/** A remote vision service the settings refuse (D181). */
export const aiStatusRemoteRefused: AiStatus = {
  ...aiStatus,
  vision: false,
  services: [
    {
      capability: "vision",
      url: "https://api.vision.example/v1",
      model: "reader-large",
      protocol: "openai",
      locality: "remote",
      refused: "remote service without MAILROBBE_AI_ALLOW_REMOTE",
      key: true,
    },
  ],
};

export const aiJobRunning: AiJob = {
  id: 41,
  kind: "ai",
  origin: "ui",
  status: "running",
  alive: true,
  stop_requested: false,
  started_at: "2026-10-22T08:00:00Z",
  updated_at: "2026-10-22T08:10:00Z",
  report_age_seconds: 1,
  finished_at: null,
  message: null,
  leftover: null,
  phase: "ocr",
  options: aiDefaults,
  progress: {
    steps: [
      doneStep("check", 2),
      {
        ...waitingStep("ocr"),
        status: "running",
        unit: "pages",
        done: 37,
        total: 120,
        started_at: "2026-10-22T08:00:02Z",
        seconds: 598,
        rate: 0.06,
        eta_seconds: 1_380,
      },
      waitingStep("entities"),
      waitingStep("signals"),
    ],
    database: null,
    queued: 9,
    done: 3,
    no_text: 1,
    failed: 0,
    tokens_in: 0,
    tokens_out: 0,
    current: "Scan_20180306_7499.pdf",
    unreachable_since: null,
  },
};

export const aiStatusRunning: AiStatus = {
  ...aiStatus,
  queue: { ...aiStatus.queue, ocr: { ...aiStatus.queue.ocr, waiting: 9, running: 1 } },
  job: aiJobRunning,
};

export const aiTaskPage: AiTaskPage = {
  items: [
    {
      id: 301,
      kind: "ocr",
      document: { id: 5150, name: "Scan_20180306_7499.pdf", kind: "pdf", pages: 3 },
      engine: "auto",
      priority: 1,
      status: "waiting",
      attempts: 0,
      error: null,
      queued_by: "Mara",
      queued_at: "2026-10-22T07:50:00Z",
      started_at: null,
      finished_at: null,
      pages_read: 0,
      pages_total: 3,
      result_id: null,
    },
    {
      id: 298,
      kind: "ocr",
      document: { id: 5151, name: "Quittung_Spende.jpg", kind: "image", pages: null },
      engine: "vision",
      priority: 0,
      status: "failed",
      attempts: 3,
      error: "service did not answer within 120 s",
      queued_by: null,
      queued_at: "2026-10-21T19:00:00Z",
      started_at: "2026-10-21T19:05:00Z",
      finished_at: "2026-10-21T19:11:00Z",
      pages_read: 0,
      pages_total: null,
      result_id: null,
    },
  ],
  next_cursor: null,
};

export const aiResultPage: AiResultPage = {
  items: [
    {
      id: 77,
      kind: "ocr",
      document: { id: 5150, name: "Scan_20180306_7499.pdf", kind: "pdf", pages: 3 },
      engine: "mixed",
      model: "qwen2.5vl:7b",
      remote: false,
      pages_read: 3,
      pages_text: 2,
      pages_total: 3,
      uncertain: [2],
      failed: [3],
      characters: 2_841,
      seconds: 64,
      state: "valid",
      created_at: "2026-10-21T18:30:00Z",
      job_id: 40,
      discarded_by: null,
      discarded_at: null,
    },
  ],
  next_cursor: null,
};

export const aiSendLogPage: AiSendLogPage = {
  items: [
    {
      id: 5,
      sent_at: "2026-10-21T18:29:00Z",
      service_url: "https://api.vision.example/v1",
      kind: "ocr",
      document: { id: 5150, name: "Scan_20180306_7499.pdf", kind: "pdf", pages: 3 },
      bytes: 412_331,
      job_id: 40,
    },
  ],
  next_cursor: null,
  total: 1,
};

/** A scan whose text an AI run recognised: two of three pages, one uncertain, one failed. */
export const ocrDocument: DocumentDetail = {
  ...documentDetail,
  id: 5150,
  name: "Scan_20180306_7499.pdf",
  size: 2_400_000,
  pages: 3,
  text_status: "text",
  text_origin: "ocr",
  ocr_readable: true,
  ai: {
    result: {
      id: 77,
      engine: "mixed",
      model: "qwen2.5vl:7b",
      remote: false,
      created_at: "2026-10-21T18:30:00Z",
      pages_total: 3,
      pages_read: 3,
      pages_text: 2,
      uncertain: [2],
      failed: [3],
      characters: 2_841,
    },
    task: null,
  },
  metadata: { status: "empty", error: null, fields: {}, summary: null },
};

/** The same scan before any run: no text, OCR can read it. */
export const scannedDocument: DocumentDetail = {
  ...ocrDocument,
  id: 5152,
  name: "Scan_20190411_0012.pdf",
  text_status: "scanned",
  text_origin: "extracted",
  ai: { result: null, task: null },
};
