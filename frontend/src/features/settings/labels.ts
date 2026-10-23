// The German texts of the page "Einstellungen" (D313): its groups and every setting's label, unit
// and help. A setting the server sends that is not listed here shows under "Weitere" by its name.

export interface SettingText {
  label: string;
  unit?: string;
  help?: string;
  choices?: Record<string, string>;
}

export interface SettingGroup {
  id: string;
  title: string;
  note?: string;
  settings: Record<string, SettingText>;
}

const SERVICE_PROTOCOLS = { auto: "automatisch", openai: "OpenAI-kompatibel", ollama: "Ollama" };

function service(what: string): Record<string, SettingText> {
  return {
    [`ai_${what}_url`]: { label: "Adresse" },
    [`ai_${what}_model`]: { label: "Modell", help: "Der Name, unter dem der Dienst es führt." },
    [`ai_${what}_key`]: { label: "API-Schlüssel", help: "Nur, wenn der Dienst einen verlangt." },
    [`ai_${what}_protocol`]: { label: "Protokoll", choices: SERVICE_PROTOCOLS },
  };
}

export const GROUPS: SettingGroup[] = [
  {
    id: "archive",
    title: "Archiv und Signale",
    note: "Filter und Listen folgen sofort. Signale und Standardblöcke rechnet der nächste „Import starten“ neu.",
    settings: {
      internal_domains: {
        label: "Eigene Domains",
        help: "Die Domains der Organisation, durch Kommas getrennt; Subdomains zählen mit. Leer: kein Filter „Nur extern ↔ intern“ und keine internen Signale.",
      },
      private_domains: {
        label: "Private Mail-Anbieter",
        help: "Zusätzlich zur eingebauten Liste, durch Kommas getrennt.",
      },
      timezone: {
        label: "Zeitzone",
        help: "Für Nachtstunden und Wochenenden, etwa Europe/Berlin.",
      },
      block_min_mails: {
        label: "Standardblock ab",
        unit: "Mails",
        help: "So viele Mails müssen denselben Absatz am Ende tragen.",
      },
    },
  },
  {
    id: "ai-text",
    title: "KI: Textmodell",
    note: "Für „Zusammenfassen“: ein Sprachmodell auf diesem Rechner, etwa LM Studio unter http://host.docker.internal:1234/v1 oder Ollama unter http://host.docker.internal:11434. Ohne Adresse gibt es kein „Zusammenfassen“.",
    settings: {
      ...service("text"),
      ai_text_reasoning: {
        label: "Nachdenken",
        choices: { off: "aus", low: "kurz", medium: "mittel", high: "gründlich" },
        help: "Ob das Modell vor der Antwort nachdenkt. Aus ist am schnellsten; mit Nachdenken braucht es mehr Kontext und deutlich mehr Zeit. Wirkt nur bei Modellen, die nachdenken können.",
      },
      ai_context_tokens: {
        label: "Kontext",
        unit: "Token",
        help: "So groß, wie das Modell geladen ist (LM Studio: „Context Length“, Ollama: num_ctx). Längere Texte werden in Teilen zusammengefasst.",
      },
    },
  },
  {
    id: "ai-vision",
    title: "KI: Bildmodell",
    note: "Liest Scans und Fotos. Ohne Adresse erkennt Tesseract den Text allein.",
    settings: service("vision"),
  },
  {
    id: "ai-runs",
    title: "KI: Anfragen",
    note: "Dienste außerhalb dieses Rechners und seines Netzes bleiben gesperrt, solange die .env sie nicht erlaubt (MAILROBBE_AI_ALLOW_REMOTE).",
    settings: {
      ai_concurrency: { label: "Gleichzeitig", unit: "Anfragen je Dienst" },
      ai_timeout: { label: "Zeitlimit", unit: "s je Anfrage" },
    },
  },
  {
    id: "ocr",
    title: "Texterkennung",
    settings: {
      ai_ocr_engine: {
        label: "Verfahren",
        choices: { auto: "automatisch", tesseract: "nur Tesseract", vision: "nur Bildmodell" },
        help: "Automatisch: Scans mit Tesseract, Fotos mit dem Bildmodell, unsichere Seiten noch einmal mit dem Bildmodell.",
      },
      ai_ocr_max_pages: {
        label: "Seiten",
        unit: "je Dokument und Durchgang",
        help: "Der Rest lässt sich fortsetzen.",
      },
      ai_ocr_languages: { label: "Sprachen", help: "Für Tesseract, etwa deu+eng." },
      ai_ocr_uncertain: {
        label: "Unsicher unter",
        unit: "von 100",
        help: "Seiten, bei denen sich Tesseract im Mittel weniger sicher ist, liest das Bildmodell noch einmal.",
      },
    },
  },
  {
    id: "transcribe",
    title: "Transkription",
    settings: {
      ai_transcribe_max_minutes: { label: "Höchstens", unit: "Minuten je Aufnahme" },
      ai_transcribe_threads: {
        label: "CPU-Threads",
        help: "0: so viele wie Kerne, höchstens vier.",
      },
      ai_transcribe_uncertain: {
        label: "Unsicher unter",
        help: "Zeilen mit geringerer Wahrscheinlichkeit (0 bis 1) werden markiert.",
      },
    },
  },
  {
    id: "import",
    title: "Import",
    note: "Gilt ab dem nächsten Start. Das Import-Dashboard kann sie für einen einzelnen Start ändern.",
    settings: {
      import_workers: {
        label: "Parallele Worker",
        help: "So viele Seiten liest auch Tesseract bei der Texterkennung gleichzeitig.",
      },
      import_attachment_hash_limit: {
        label: "Hash für Anhänge bis",
        unit: "MB",
        help: "Größere Anhänge bekommen nur Metadaten, keinen SHA-256.",
      },
      import_max_mail_size: {
        label: "Mails vollständig bis",
        unit: "MB",
        help: "Größere Mails kommen nur mit ihren Kopfzeilen ins Archiv.",
      },
    },
  },
  {
    id: "attachments",
    title: "Anhänge und Archive",
    note: "Gilt ab dem nächsten Import.",
    settings: {
      attachment_text_max_size: { label: "Text lesen bis", unit: "MB" },
      attachment_text_timeout: { label: "Zeitlimit", unit: "s je Datei" },
      attachment_text_memory: { label: "Speicher", unit: "MB je Datei" },
      archive_max_members: {
        label: "Einträge je Archiv",
        help: "ZIP, 7z und angehängte Mails werden bis zu dieser Grenze ausgepackt.",
      },
      archive_max_size: { label: "Ausgepackt höchstens", unit: "MB" },
      password_seconds: { label: "Kennwörter probieren", unit: "s je Stufe" },
    },
  },
  {
    id: "previews",
    title: "Vorschau",
    settings: {
      preview_max_size: { label: "Vorschau bis", unit: "MB" },
      preview_timeout: { label: "Zeitlimit", unit: "s je Umwandlung" },
      preview_memory: { label: "Speicher", unit: "MB je Umwandlung" },
      preview_workers: { label: "Gleichzeitige Umwandlungen" },
    },
  },
  {
    id: "dkim",
    title: "DKIM",
    settings: {
      dkim_offline: {
        label: "Ohne DNS prüfen",
        help: "Schlüssel, die nicht im Cache liegen, ergeben einen vorübergehenden Fehler.",
      },
      dkim_dns_timeout: { label: "DNS-Zeitlimit", unit: "s je Name" },
      dkim_nameservers: {
        label: "DNS-Resolver",
        help: "IP-Adressen, durch Kommas getrennt. Leer: der Resolver des Systems.",
      },
      dkim_key_archive_url: {
        label: "Schlüsselarchiv",
        help: "Das ZK-Email-Archiv für Schlüssel gelöschter Selektoren, gefragt nur auf Knopfdruck; „off“ schaltet es ab.",
      },
      dkim_key_archive_timeout: { label: "Zeitlimit Schlüsselarchiv", unit: "s je Anfrage" },
    },
  },
  {
    id: "map",
    title: "Detailkarte",
    settings: {
      map_source: {
        label: "Quelle",
        help: "„protomaps“ (der neueste Tagesstand), die https-Adresse einer PMTiles-Datei oder „off“.",
      },
      map_timeout: { label: "Zeitlimit", unit: "s je Anfrage" },
    },
  },
  {
    id: "interface",
    title: "Oberfläche",
    settings: {
      api_count_timeout: {
        label: "Zeit für Trefferzahlen",
        unit: "s",
        help: "Danach nennt eine gefilterte Liste eine Mindestzahl.",
      },
      stats_max_age: { label: "Kennzahlen neu nach", unit: "s" },
    },
  },
];

export const SOURCE_LABELS = { env: "aus .env", default: "Standard" } as const;
