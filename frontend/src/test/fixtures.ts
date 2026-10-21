// Realistic API responses for tests, typed with the contract. Only type imports, so the file
// also loads in plain Node (type stripping) for screenshot scripts.

import type {
  DkimStatus,
  MailDetail,
  MailHeaders,
  MailListItem,
  MailNeighbors,
  MailPage,
  MailRaw,
  MailSummary,
  MailText,
  MboxFileInfo,
  PersonRef,
  Stats,
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
    { has_attachments: true, thread_id: 184001, size: 188_416 },
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
    { flagged: true },
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
    },
    {
      id: 902,
      filename: "Aenderungsprotokoll.xlsx",
      mime_type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      size: 14_336,
      sha256: "5c07e2b9a4d13f8e6b0a7c9d2e4f61a3b5c7d9e0f1a2b3c4d5e6f708192a3b4c",
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
  note: { flagged: false, note: "", updated_at: null },
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
