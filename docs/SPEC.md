# Mailspider – Projektübergabe und Spezifikation

Stand: 20.10.2026. Dieses Dokument fasst Ziel, Rahmenbedingungen, Architektur und UI-Anforderungen zusammen, so dass ein Entwickler oder Agent das Projekt ohne Vorwissen aufsetzen kann.

Das UI-Mockup (5 Screens, klickbarer Prototyp) liegt als heruntergeladene HTML-Dateien vor und sollte unter `docs/mockup/` im Projekt abgelegt werden. Online-Version: https://claude.ai/artifact/34WndZqaGZp7ZeEzC9zvez

---

## 1. Ziel

Eine lokal laufende Software, die große MBOX-Exporte einliest, jede Mail auf DKIM-Signatur prüft, Mails nach Personen (Absender, Empfänger, Cc, Bcc) kategorisiert und das Ganze in einer Web-UI durchsuchbar macht. Kernfeature ist eine Beziehungskarte: ein Graph, der zeigt, welche Personen miteinander kommunizieren und wie oft.

## 2. Rahmenbedingungen (vom Auftraggeber vorgegeben)

| Punkt | Wert |
|---|---|
| Anzahl Mails | ca. 400.000 |
| Gesamtgröße | ca. 280 GB |
| Format | mehrere MBOX-Dateien, je ca. 4 GB (ca. 70 Dateien), Inhalt im EML-Format |
| Speicherort | Bind-Mount in die Container, read-only |
| Datenbank | nur Metadaten, Offsets und Index. Die Rohmails werden NICHT in die DB kopiert. |
| Testdaten | keine vorhanden. Ein Generator für synthetische MBOX-Dateien ist Teil des Projekts. |
| Infrastruktur | Docker ist verfügbar und soll für die Datenbank genutzt werden |
| Leitsatz | Die UI muss mit 400.000 Mails klarkommen. Jede Ansicht muss bei dieser Menge schnell bleiben. |

## 3. Architektur

### 3.1 Stack

- **Backend**: Python 3.12+, FastAPI, SQLAlchemy oder asyncpg, Pydantic
- **Datenbank**: PostgreSQL 16 in Docker, Volltextsuche über `tsvector` (optional pg_trgm für Teilstring-Suche in Adressen)
- **Importer**: Python-CLI, Multiprocessing mit einem Worker-Pool, pro Worker eine MBOX-Datei oder ein Byte-Bereich
- **DKIM**: Python-Paket `dkimpy` plus eigener DNS-Resolver mit Cache (`dnspython`)
- **Frontend**: Single-Page-App, ausgeliefert vom Backend. Graph mit **Cytoscape.js** (alternativ Sigma.js bei >5.000 Knoten). Tabellen mit serverseitiger Paginierung.
- **Betrieb**: `docker compose up` startet Postgres, Backend und Frontend. Der Importer läuft als eigener Service oder als CLI-Befehl im Backend-Container.

### 3.2 Datenfluss

```
/data/mbox/*.mbox  (Bind-Mount, ro)
        │
        ▼
  Importer (N Worker)
   ├─ MBOX-Splitting über "From "-Separator, merkt sich Byte-Offset und Länge je Mail
   ├─ Header-Parsing (From, To, Cc, Bcc, Date, Subject, Message-ID, In-Reply-To, References)
   ├─ Body: Text-Teil extrahieren für Volltextindex, HTML nur referenzieren
   ├─ Anhänge: nur Metadaten (Name, MIME-Typ, Größe, SHA-256 bis Limit)
   ├─ Duplikaterkennung: Message-ID + SHA-256 der Rohmail
   ├─ DKIM-Prüfung mit DNS-Cache
   └─ Personen-Normalisierung (Adresse lowercase, Display-Namen sammeln)
        │
        ▼
  PostgreSQL (Metadaten, Offsets, Volltext, Aggregationstabellen)
        │
        ▼
  FastAPI (REST/JSON) ──► Web-UI
        │
        └─ Mail-Detail: Body on-demand aus MBOX via (datei, offset, länge)
```

### 3.3 Datenmodell (Kern)

```
mbox_file        id, path, size_bytes, sha256_head, status, mails_parsed, bytes_done, error_count
mail             id, mbox_file_id, offset, length, message_id, in_reply_to, thread_id,
                 subject, date_utc, raw_sha256, has_attachments, body_text (nur Text, gekürzt),
                 tsv (tsvector), dkim_status (enum), is_duplicate_of
mail_header      mail_id, name, value           (optional, nur für "alle Header"-Ansicht, sonst aus MBOX lesen)
person           id, canonical_email, display_name, domain, merged_into (Alias-Zusammenführung)
person_email     person_id, email, display_names jsonb (Name → Häufigkeit)
participation    mail_id, person_id, role (from|to|cc|bcc)   PK (mail_id, person_id, role)
attachment       id, mail_id, filename, mime_type, size_bytes, sha256
dkim_result      mail_id, status (pass|fail|no_key|unsigned|temp_error), domain, selector,
                 algorithm, key_bits, signed_headers, body_hash_ok, signed_at, aligned,
                 reason, checked_at, dns_cached
dns_cache        name, record, fetched_at, ttl, status
import_error     id, mbox_file_id, offset, kind, message, created_at
```

Aggregationstabellen (periodisch oder nach Import aktualisiert, Grundlage für alle Kennzahlen und den Graphen):

```
edge             person_a, person_b, mails_a_to_b, mails_b_to_a, mails_cc, first_date, last_date
                 (person_a < person_b, Index auf beiden Spalten und auf Summe)
edge_year        person_a, person_b, year, count       (für Zeitverlauf im Graphen)
person_stats     person_id, sent, received, cc_only, contacts, first_date, last_date, dkim_pass_ratio
person_year      person_id, year, sent, received
global_stats     key, value                            (Mails gesamt, DKIM-Verteilung, Domains ...)
```

Wichtige Indizes: `mail(date_utc)`, `mail(message_id)`, `participation(person_id, role)`, `mail USING gin(tsv)`, `person(canonical_email)`, `person(domain)`.

### 3.4 DKIM-Prüfung

- Status-Werte: **pass** (gültig), **fail** (ungültig), **no_key** (Selector im DNS nicht mehr vorhanden, bei alten Mails sehr häufig), **unsigned** (kein DKIM-Header), **temp_error** (DNS-Timeout, wird später erneut versucht).
- Pro Mail speichern: Domain (d=), Selector (s=), Algorithmus, Schlüssellänge, signierte Header (h=), Body-Hash übereinstimmend ja/nein, Signaturzeitpunkt (t=), Alignment (From-Domain == d=), Fehlergrund bei fail.
- DNS-Lookups cachen (Tabelle `dns_cache`), Negativantworten ebenfalls. Bei 400.000 Mails gibt es nur wenige tausend verschiedene Domain/Selector-Paare.
- Mehrere DKIM-Signaturen pro Mail sind möglich. Alle prüfen, das beste Ergebnis als `mail.dkim_status` übernehmen, alle Einzelergebnisse in `dkim_result` behalten.
- Funktion "Neu prüfen" für einzelne Mails und für alle Mails mit Status `no_key` oder `temp_error`.

### 3.5 Importer-Anforderungen

- Idempotent und wiederaufnehmbar: Fortschritt pro Datei als Byte-Offset speichern. Nach Abbruch beim letzten verarbeiteten Offset weitermachen.
- Streaming, nie eine ganze 4-GB-Datei in den Speicher laden.
- Robust gegen kaputte Mails: fehlerhafte Encodings heuristisch dekodieren, kaputte `From `-Separatoren erkennen, nie den gesamten Import abbrechen. Jeder Fehler landet in `import_error` mit Datei und Offset.
- Anhänge über einem Limit (Vorschlag 50 MB) werden nicht gehasht, nur Metadaten.
- Zielwert Durchsatz: >1.000 Mails/s Parsing bei 8 Workern, damit der Vollimport in wenigen Stunden fertig ist.
- Fortschritt, Durchsatz und Fehler müssen über eine API für das Import-Dashboard abrufbar sein.

### 3.6 Testdaten-Generator

Eigenes CLI-Skript, das MBOX-Dateien erzeugt:

- Parameter: Anzahl Mails, Anzahl Personen, Anzahl Domains, Zeitraum, Anteil mit Anhängen, Zielgröße pro Datei.
- Realistische Kommunikationsmuster: wenige stark vernetzte Personen, viele mit wenigen Mails, Threads mit Re:/AW:, Verteilerlisten, Cc-Ketten.
- DKIM: einen eigenen Testschlüssel erzeugen und damit einen Teil der Mails tatsächlich signieren. Für die Prüfung einen Mock-Resolver oder eine konfigurierbare DNS-Override-Tabelle vorsehen, damit `pass`, `fail` (Body manipulieren), `no_key` und `unsigned` alle getestet werden können.
- Absichtlich eingebaute Störfälle: kaputte Encodings, fehlende Message-IDs, Duplikate, sehr große Anhänge, mehrteilige MIME-Strukturen.
- Für die Entwicklung reichen 10.000 bis 50.000 Mails, für Lasttests 400.000.

## 4. API (Skizze)

```
GET  /api/mails?q=&from=&to=&dkim=&domain=&date_from=&date_to=&has_attachment=&mbox=&sort=&cursor=&limit=
GET  /api/mails/{id}                    Metadaten, DKIM, Beteiligte, Thread, Anhänge
GET  /api/mails/{id}/body?format=text|html|headers|raw   on-demand aus MBOX
GET  /api/mails/{id}/eml                Download
POST /api/mails/{id}/dkim/recheck
GET  /api/mails/between?a=&b=           alle Mails zwischen zwei Personen
GET  /api/persons?q=&sort=&cursor=
GET  /api/persons/{id}                  Profil, Stats, Top-Kontakte, Aktivität pro Jahr
GET  /api/persons/{id}/mails?role=all|sent|received|cc&year=&with=&cursor=
POST /api/persons/merge                 Alias-Zusammenführung
GET  /api/graph?mode=ego|top|domains&center=&depth=&min_edge=&date_from=&date_to=&dkim_only=&hide_lists=&limit=
GET  /api/stats                          globale Kennzahlen
GET  /api/import/status                  Dateien, Fortschritt, Durchsatz, Worker
GET  /api/import/errors
POST /api/import/start|pause|rescan
```

Suchsyntax im Freitextfeld: `from:`, `to:`, `cc:`, `subject:`, `domain:`, `has:attachment`, `dkim:pass|fail|no_key|unsigned`, `before:`, `after:`, Rest ist Volltext.

## 5. Web-UI: Screens und Features (entspricht dem Mockup)

### 5.1 Mailliste (Mockup: Main / "1 · Mailliste")

- Kopfzeile: Logo, Navigation (Mails, Personen, Karte, Import), globale Suche mit Operatoren, Gesamtzahlen, Import-Status-Indikator.
- Filter-Spalte: Zeitraum, DKIM-Status (4 Checkboxen mit Zählern), Absender-Domain (Top-Liste mit Zählern, "alle Domains"), Mit Anhang, Teil eines Threads, Nur extern↔intern, Doppelte ausblenden, MBOX-Datei.
- Kennzahlen-Kacheln: Mails im Filter, DKIM-gültig-Quote, Schlüssel-fehlt-Anzahl, Personen/Domains.
- Aktive Filter als Chips, Trefferzahl, Sortierung, Spaltenwahl, CSV-Export.
- Tabelle: DKIM-Ampel, Von (Name + Adresse, klickbar → Profil), An (+N), Betreff (klickbar → Detail), Anhang-Icon, Datum.
- Paginierung: Cursor-basiert, 50 pro Seite. Trefferzahl darf geschätzt sein, wenn exakte Zählung zu langsam ist.

### 5.2 Mail-Detail (Mockup: Mail / "2 · Mail-Detail")

- Vor/Zurück innerhalb der aktuellen Trefferliste.
- Betreff, DKIM-Badge, Metadaten-Raster: Von, Datum, An, Cc, Message-ID, In-Reply-To (klickbar), Quelle (MBOX-Datei, Offset, Größe), interne ID und Hash.
- DKIM-Box: Ergebnis, Domain, Selector, Algorithmus, signierte Header, Body-Hash, Signaturzeit, Alignment, Prüfzeitpunkt, Cache-Hinweis, "Neu prüfen", aufklappbar: DKIM-Signature-Header und DNS-Record.
- Body-Tabs: Text, HTML (sandboxed iframe, keine externen Ressourcen), Alle Header, Rohmail. Body wird erst beim Öffnen gelesen. Zitierter Verlauf einklappbar.
- Anhänge mit MIME-Typ, Größe, Hash.
- Seitenleiste: Beteiligte (klickbar → Profil, mit Kennzahlen und Mailanzahl mit dem Absender), "Diese N im Graphen zeigen", Thread-Ansicht, Aktionen (EML-Download, Rohmail, alle Mails zwischen zwei Personen, Markieren/Notiz).

### 5.3 Personenprofil (Mockup: Person / "3 · Personenprofil")

- Kopf: Initialen, Name, Adresse, Domain, Alias-Adressen, "Adresse zusammenführen", gesammelte Display-Namen mit Häufigkeit.
- Buttons: Im Graphen zeigen, Alle Mails exportieren.
- Kennzahlen: Gesendet, Empfangen, Kontakte, DKIM-gültig-Quote der gesendeten Mails, erste und letzte Mail.
- Top-Kontakte als Balkenliste (klickbar → Profil), Aktivität pro Jahr (gesendet/empfangen, Klick filtert die Liste).
- Mailliste der Person mit Tabs (Alle, Gesendet, Empfangen, Nur Cc), Filter nach Kontakt und Jahr, Rolle pro Zeile.

### 5.4 Beziehungskarte (Mockup: Graph / "4 · Beziehungskarte")

- Linke Spalte: Ausschnitt-Modus (Ego-Netzwerk um Person(en) mit Tiefe 1–3, Top-N nach Mailvolumen, zwei Domains gegenüber), Zentrum-Personen als Chips, Mindestanzahl Mails pro Kante (Slider, zeigt resultierende Knoten/Kanten), Zeitraum, Zeitverlauf abspielen (Jahr für Jahr), Optionen (nach Domain einfärben, nur DKIM-gültige Mails zählen, Verteiler/Automaten ausblenden, Richtung als Pfeile, Cc mitzählen), Layout (Force, Domain-Cluster, Kreis, hierarchisch), "Karte zeichnen", Export PNG/SVG und GraphML.
- Kopfzeile der Karte: Knoten/Kanten/Mails im Ausschnitt, Legende der Domainfarben, Zoom-Buttons, Einpassen.
- Karte: Knotengröße = Mails gesamt, Kantenstärke = Mails zwischen beiden, Kantenlabels bei starken Kanten, ausgewählter Knoten hervorgehoben mit seinen Kanten.
- Rechtes Panel zum ausgewählten Knoten: Kennzahlen, Verbindungen mit Richtung (→/←), Klick öffnet die Mails zwischen beiden, Profil öffnen, Nachbarn aufklappen, Knoten ausblenden.
- Serverseitig: Graph kommt aus der `edge`-Tabelle, nie aus Einzelmails. Harte Obergrenze 2.000 Knoten pro Ansicht, der Server lehnt größere Anfragen mit Hinweis ab.

### 5.5 Import-Dashboard (Mockup: Import / "5 · Import-Dashboard")

- Gesamtfortschritt, Worker-Anzahl, Quelle (Bind-Mount), Restzeit, Durchsatz Parsing und DKIM, Duplikate, Fehler.
- Kennzahlen: DB-Größe, Volltextindex, DNS-Cache mit Trefferquote, Personen und offene Alias-Vorschläge, Kantentabelle.
- Tabelle MBOX-Dateien: Größe, Mails, Fortschritt (Byte-Offset), Status (Fertig/Läuft mit Worker-ID/Wartet/Fehler), Fehleranzahl.
- DKIM-Verteilung mit häufigsten Fail-Gründen, Fehlerprotokoll mit Datei und Offset, Einstellungen (Worker, DNS-Resolver, Anhang-Limit, Volltext an/aus).
- Buttons: Pausieren, DKIM für "Schlüssel fehlt" neu prüfen, Verzeichnis neu scannen.

## 6. Regeln für Performance bei 400.000 Mails

1. Keine Ansicht lädt mehr als eine Seite Mails. Suche, Sortierung, Zählung laufen in Postgres.
2. Bodys und Rohheader werden nie in Listen geladen, nur im Detail und on-demand aus der MBOX.
3. Alle Kennzahlen, Top-Listen und der Graph lesen aus Aggregationstabellen, nicht aus `mail` oder `participation`.
4. Der Graph hat immer einen Schwellwert oder ein Ego-Netzwerk. Niemals "alle Knoten".
5. Volltextsuche über `tsvector` mit GIN-Index. Adress-Teilstringsuche über pg_trgm.
6. Exakte Trefferzählung nur bis zu einem Limit, darüber geschätzt ("mehr als 10.000").
7. Importer und UI dürfen gleichzeitig laufen. Aggregationen werden inkrementell oder alle paar Minuten aktualisiert.

## 7. Design-Vorgaben aus dem Mockup

- Heller, neutraler Look. Schrift Inter, Monospace JetBrains Mono für Adressen, IDs und Offsets.
- Farben: Hintergrund `#F6F7F9`, Fläche `#FFFFFF`, Rahmen `#E3E6EB`, Text `#16181D`, gedämpft `#5B6270`, Akzent `#1D5BD6`.
- DKIM-Ampel: gültig `#16A34A`, ungültig `#DC2626`, Schlüssel fehlt `#D97706`, unsigniert `#9CA3AF`.
- Domain-Farben im Graphen aus einer festen Palette mit ausreichend Helligkeitsunterschied.
- Deutschsprachige UI.

## 8. Vorgeschlagene Meilensteine

1. **Gerüst**: Docker Compose (Postgres, Backend), Schema-Migrationen, Testdaten-Generator mit 10.000 Mails.
2. **Importer**: MBOX-Streaming, Parsing, Personen, Duplikate, Offsets, Wiederaufnahme, Fehlerprotokoll.
3. **DKIM**: Prüfung, DNS-Cache, Mock-Resolver für Tests, Recheck-Funktion.
4. **API + Mailliste + Mail-Detail**.
5. **Personenprofil + Aggregationstabellen**.
6. **Beziehungskarte** mit Ego-Netzwerk, Top-N, Schwellwert, Export.
7. **Import-Dashboard**, dann Lasttest mit 400.000 generierten Mails.

## 9. Offene Punkte

- Alias-Zusammenführung: nur manuell oder auch automatische Vorschläge (gleicher Display-Name, ähnliche Adresse)?
- Bcc ist in exportierten Mails meist nicht enthalten. Rolle trotzdem vorsehen.
- HTML-Bodys: nur sandboxed anzeigen oder zusätzlich bereinigt indexieren?
- Zugriffsschutz der Web-UI (lokal ohne Login, oder Basic Auth)?
- Soll es einen Export des ganzen Graphen für Gephi geben, oder reicht der aktuelle Ausschnitt?
