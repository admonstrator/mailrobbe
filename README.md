# Mailrobbe

Mailrobbe liest große MBOX-Exporte ein (Zielgröße rund 400.000 Mails in etwa 70 Dateien), prüft jede Mail auf ihre DKIM-Signatur, ordnet sie den beteiligten Personen zu und macht alles in einer lokalen Web-Oberfläche durchsuchbar. Kernstück ist eine Beziehungskarte, die zeigt, wer mit wem wie oft kommuniziert.

Die Rohmails bleiben unverändert in den MBOX-Dateien, die read-only eingebunden werden. Die Datenbank (PostgreSQL) hält nur Metadaten, Byte-Offsets, den Volltextindex und Aggregationen.

## Schnellstart

Voraussetzung ist Docker (Docker Desktop unter macOS oder Docker Engine unter Linux).

```sh
docker compose up -d --build
curl http://127.0.0.1:8000/api/health
```

Das startet PostgreSQL 16 und das Backend, das beim Start das Datenbankschema anlegt bzw. aktualisiert und unter http://127.0.0.1:8000 die Web-Oberfläche ausliefert. Die MBOX-Dateien werden aus `./data/mbox` gelesen, schreibgeschützt eingebunden als `/data/mbox`. Ein anderes Verzeichnis lässt sich in einer `.env`-Datei neben `docker-compose.yml` festlegen:

```sh
MAILROBBE_MBOX_HOST_DIR=/Volumes/Archiv/mbox
```

## Testdaten

Echte Mails braucht es für die Entwicklung nicht. Der Generator schreibt synthetische MBOX-Dateien mit realistischen Kommunikationsmustern, teils echten DKIM-Signaturen und absichtlich eingebauten Störfällen:

```sh
uv run mailrobbe generate --mails 10000          # mit lokalem Python und uv
docker compose run --rm generator --mails 10000   # ohne lokales Python
```

Die Dateien landen in `data/mbox/` (Standard: Teildateien zu je höchstens 128 MB), dazu unter `data/mbox/_generator/` ein Manifest mit dem erwarteten Ergebnis jeder Mail, die DNS-Override-Tabelle für die DKIM-Prüfung und die Testschlüssel. 10.000 Mails ergeben rund 1,1 GB und brauchen auf vier Kernen etwa 20 Sekunden; 400.000 Mails ergeben mit den Voreinstellungen rund 35 GB, mit den Parametern des Lasttests ([docs/LOADTEST.md](docs/LOADTEST.md)) 8,9 GB in gut 6 Minuten. Die Anhänge sind echte Dokumente: PDFs mit und ohne Textebene, verschlüsselte und beschädigte PDFs, DOCX, XLSX, PPTX, ODT, CSV und ZIP. Sie wandern weitergeleitet und erneut angehängt zwischen den Mails, und das Manifest nennt je Anhang Hash, Art, erwarteten Textstatus und ein Markierwort aus seinem Text. Gleiche Parameter und gleicher `--seed` ergeben bytegleiche MBOX-Dateien und Manifeste. `--help` zeigt alle Parameter (Personen, Domains, Zeitraum, Anhänge, Dateigröße, DKIM-Anteil, Fehler- und Duplikatquote, Seed, Prozesse).

## Import

Der Import läuft am bequemsten über das Dashboard unter http://127.0.0.1:8000/import: „Import starten“, „Pausieren“, „Import fortsetzen“, „Verzeichnis neu scannen“ und die DKIM-Nachprüfung, dazu Fortschritt je Datei, Durchsatz, Restzeit, Fehlerprotokoll, DKIM-Ergebnis und Datenbankgröße live. Die Einstellungen im Dashboard (Worker, Anhang-Limit, DNS-Resolver) gelten für den nächsten Start von dort. Auf der Kommandozeile geht dasselbe:

```sh
docker compose run --rm backend mailrobbe import   # liest /data/mbox im Container
uv run mailrobbe import --dir data/mbox            # mit lokalem Python und uv
```

Das Dashboard zeigt auch einen Import, der auf der Kommandozeile läuft, und kann ihn pausieren. Es läuft immer nur ein Import oder eine DKIM-Prüfung gleichzeitig. Ein Import, den das Dashboard gestartet hat, schreibt seine Ausgabe in `docker compose logs backend`; stoppt der Container, pausiert er sauber und setzt beim nächsten Start fort.

Der Importer liest jede MBOX-Datei unterhalb des Verzeichnisses (erkannt am Inhalt, nicht an der Endung) in einem eigenen Worker-Prozess, sequenziell und in großen Blöcken. Je Mail speichert er Kopfdaten, Byte-Offset und Länge in der MBOX-Datei, SHA-256, Personen, Anhänge (Name, Typ, Größe, Hash) und den Text für die Volltextsuche; die Rohmail selbst bleibt in der Datei. Die DKIM-Prüfung läuft dabei mit. Am Ende markiert er Duplikate, bildet Threads aus Message-ID, In-Reply-To und References, setzt die Anzeigenamen der Personen und berechnet die Kanten der Beziehungskarte, die Kennzahlen je Person und die Alias-Vorschläge.

Zum Schluss liest der Import die Anhänge aus. Jeder Inhalt (gleicher SHA-256) wird nur einmal gelesen, auch wenn er in vielen Mails steckt. Text kommt aus PDF, Word (DOCX), Excel (XLSX), PowerPoint (PPTX), OpenDocument (ODT, ODS, ODP), RTF, CSV, Text, HTML, XML, JSON, Kalendereinträgen, Visitenkarten und angehängten Mails; von ZIP-Archiven die Dateinamen darin. Tabellen gibt er Zelle für Zelle so wieder, wie sie in der Datei stehen, Beträge und IBANs also unverändert. Gescannte PDFs ohne Textebene, verschlüsselte und beschädigte Dateien werden erkannt und gezählt. Bilder, Audio, Video und alte Office-Formate (DOC, XLS, PPT) bleiben ohne Text. Jedes Dokument wird in einem eigenen Prozess gelesen, der nach `MAILROBBE_ATTACHMENT_TEXT_TIMEOUT` (60 s) abgebrochen wird; bis dahin gelesener Text bleibt erhalten. Unter Linux und in Docker darf er höchstens `MAILROBBE_ATTACHMENT_TEXT_MEMORY` (1 GB) zusätzlich belegen. Dokumente über `MAILROBBE_ATTACHMENT_TEXT_MAX_SIZE` (50 MB) liest er gar nicht. Pausieren und Fortsetzen gelten auch hier. Bei einem Archiv, das vor Meilenstein 9 eingelesen wurde, wertet der nächste Import die Anhänge aus, ohne die Mails neu einzulesen.

- Worker: `--workers` oder `MAILROBBE_IMPORT_WORKERS`, Standard min(8, CPU-Kerne). Jeder Worker braucht normal rund 200 MB, bei sehr großen Mails bis etwa 1 GB.
- Fortsetzen: „Pausieren“ im Dashboard oder Ctrl-C beendet die laufenden Stapel sauber, ein zweites Ctrl-C (mindestens eine Sekunde später) bricht sofort ab. Der nächste Aufruf macht in beiden Fällen dort weiter, wo zuletzt gespeichert wurde, und speichert keine Mail doppelt. Gewachsene Dateien werden ab ihrem Ende fortgesetzt, veränderte neu eingelesen. Ein Archiv, das vor Meilenstein 6 eingelesen wurde, bekommt beim nächsten Import zuerst die Kopfzeilen für Verteiler und Automaten nachgelesen; Notizen, Zusammenführungen und DKIM-Ergebnisse bleiben.
- Fehler: Kaputte Mails halten den Import nicht auf. Jedes Problem (Trennzeile, Zeichensatz, Datum, Adressen, Größe, DKIM, Lesefehler) landet mit Datei und Byte-Position in der Tabelle `import_error`; die Zusammenfassung am Ende zählt sie nach Art.
- Grenzen: Mails über 128 MB werden nur mit ihren Kopfdaten übernommen, Anhänge über 50 MB nicht gehasht (`MAILROBBE_IMPORT_MAX_MAIL_SIZE`, `MAILROBBE_IMPORT_ATTACHMENT_HASH_LIMIT`).
- Exit-Status: 0 fertig, 1 eine Datei endete mit Fehler oder der Import konnte nicht starten, 130 unterbrochen.

Im Lasttest las der Import 400.000 Testmails (8,9 GB) mit vier Workern in gut 4 Minuten, etwa 1.550 Mails/s, der Nachlauf dauerte 83 Sekunden; Listen, Filter, Mail-Detail und Profile antworteten danach meist in 10 bis 60 ms, die Karte in 0,25 bis 0,5 Sekunden. Die echten Mails sind rund dreißigmal so groß, dort bestimmt das Lesen über den Bind-Mount die Dauer; Messwerte, Ablauf und Grenzen stehen in [docs/LOADTEST.md](docs/LOADTEST.md).

## DKIM-Prüfung

Mailrobbe prüft jede DKIM-Signatur einer Mail und speichert das Ergebnis je Signatur: gültig, ungültig (mit Grund, etwa geänderter Body), Schlüssel fehlt, unsigniert oder DNS-Fehler. Die Schlüssel kommen aus dem DNS und werden in der Datenbank zwischengespeichert, so dass jeder Selector nur einmal abgefragt wird. Bei den Testdaten des Generators liest Mailrobbe die DNS-Override-Tabelle aus `data/mbox/_generator/` automatisch, die erfundenen Domains gehen nie ins Netz.

Nachprüfen lässt sich jederzeit, etwa nachdem ein Schlüssel wieder erreichbar ist:

```sh
docker compose run --rm backend mailrobbe dkim             # ungeprüfte Mails, "Schlüssel fehlt" und DNS-Fehler
docker compose run --rm backend mailrobbe dkim --all       # alle Mails
docker compose run --rm backend mailrobbe dkim --mail 4711 # einzelne Mails
```

Den ersten der drei Aufrufe startet auch die Schaltfläche „DKIM für „Schlüssel fehlt“ neu prüfen“ im Dashboard.

Ohne Netz: `MAILROBBE_DKIM_OFFLINE=1` (oder `--offline`) nutzt nur den Cache; was dort fehlt, bekommt den Status DNS-Fehler und wird beim nächsten Nachprüfen erneut gefragt. Weitere Einstellungen: `MAILROBBE_DKIM_DNS_TIMEOUT` (Sekunden je Schlüssel, Standard 5), `MAILROBBE_DKIM_NAMESERVERS` (kommagetrennte IP-Adressen, Standard: System-Resolver), `MAILROBBE_DKIM_DNS_OVERRIDE` (eigene Override-Tabelle). Abgelaufene Signaturen gelten als gültig, wenn die Kryptografie stimmt; die Begründung steht in [docs/DECISIONS.md](docs/DECISIONS.md).

## Web-Oberfläche

Nach dem Import zeigt http://127.0.0.1:8000 die Mailliste. Alles läuft lokal: keine externen Schriften, Skripte oder Bilder.

- **Mailliste**: Suche, Filterspalte (Zeitraum, DKIM-Status, Absender-Domain, Anhang, Thread, Duplikate, markierte Mails, MBOX-Datei), Kennzahlen zum aktuellen Filter, Sortierung nach Datum, Seiten zu je 50 Mails mit Zurück/Weiter, CSV-Export aller Treffer (Semikolon, öffnet direkt in Excel). Filter und Suche stehen in der Adresszeile, Links lassen sich also aufheben und teilen.
- **Mail-Detail**: Vor/Zurück innerhalb der Treffer (auch mit den Pfeiltasten), Kopfdaten mit Quelle (Datei, Offset, Größe) und SHA-256, DKIM-Prüfung je Signatur mit Grund, DNS-Record und „Neu prüfen“, Text, HTML, alle Header und Rohmail werden erst beim Öffnen aus der MBOX-Datei gelesen, Anhänge, Beteiligte, Thread, EML-Download, Markierung und Notiz. HTML-Mails laufen in einem abgeschotteten Rahmen ohne Skripte und ohne Nachladen von außen.
- **Suche**: `from:anna@`, `to:@beispiel.de`, `cc:keller`, `subject:Vertrag`, `domain:beispiel.de`, `has:attachment`, `dkim:fail` (auch `pass`, `no_key`, `unsigned`, `temp_error`, `unchecked`), `after:2024-01-01`, `before:2025-01-01`, Anführungszeichen für Phrasen, eine `<message-id@host>` findet genau diese Mail; der Rest ist Volltext (deutsche Wortstämme). Adressen und Betreff finden auch Teilwörter. Der Volltext durchsucht auch die Texte der Anhänge. Eine Mail, die nur über einen Anhang gefunden wurde, trägt das Zeichen „im Anhang“.
- **Personen**: alle Personen mit Mails, Gesendet, Empfangen, Kontakten, letzter Mail und DKIM-Anteil, sortiert nach Mails, Name oder letzter Mail. Die Suche findet Teile von Adressen und Anzeigenamen, auch die der Aliase.
- **Personenprofil**: Kennzahlen, Top-Kontakte, Aktivität pro Jahr, Anzeigenamen und Adressen der Person, darunter alle ihre Mails nach Rolle (Gesendet, Empfangen, Nur Cc), Jahr und Kontakt. Ein Klick auf ein Jahr oder einen Kontakt filtert die Liste; Vor/Zurück im Mail-Detail bleibt in diesen Mails.
- **Aliase**: Mailrobbe führt Adressen nie von selbst zusammen. Es schlägt Adressen vor, die denselben Anzeigenamen (auch „Nachname, Vorname“) oder denselben Teil vor dem @ haben, im Reiter „Alias-Vorschläge“ und im Profil. „Zusammenführen“ macht eine Adresse zum Alias einer Person, ihre Mails zählen dann dort; „Lösen“ im Profil nimmt das zurück, „Verwerfen“ blendet einen Vorschlag dauerhaft aus. Ein Zusammenführen dauert meist rund 0,2 Sekunden; bei 400.000 Mails und den aktivsten Personen (über 40.000 Mails) sind es zwei bis drei.
- **Anhänge** (`/anhaenge`): jedes Dokument einmal, auch wenn es in vielen Mails steckt, mit Volltextsuche über Text und Dateinamen (Fundstelle im Text hervorgehoben). Filter: Dateiname, Art, Textstatus (darunter „Gescannt (ohne Text)“ für eine spätere Texterkennung), Zeitraum, Person als Absender oder Empfänger, „in mehreren Mails“ und intern/extern. Sortiert wird nach erstem Auftauchen, Zahl der Mails oder Größe. Die Dokumentseite zeigt, wer das Dokument wann an wen geschickt hat, als Mailliste mit der ältesten Mail zuerst. Dazu kommen die Dateinamen, unter denen es lief, die häufigsten Absender und Empfänger, der ausgelesene Text, der Download und bei Bildern eine Vorschau. Im Mail-Detail führt jeder Anhang zu seinem Dokument und zum Download. Downloads liest Mailrobbe bei jedem Abruf aus der MBOX-Datei, prüft sie gegen den Hash und liefert sie immer als Datei aus, nie zum Anzeigen im Browser.
- **Zugriffsschutz**: ohne Login, solange nichts eingestellt ist. `MAILROBBE_BASIC_AUTH_USER` und `MAILROBBE_BASIC_AUTH_PASSWORD` in der `.env` schalten HTTP Basic Auth ein (nur `/api/health` bleibt für den Container-Healthcheck offen).
- **Intern/extern**: Mit `MAILROBBE_INTERNAL_DOMAINS=firma.de,firma.ch` erscheint der Filter „Nur extern ↔ intern“ (Mails, bei denen eine Seite intern und die andere extern ist; Subdomains zählen als intern).
- **Beziehungskarte** (`/karte`): wer mit wem wie oft geschrieben hat, als Ausschnitt um eine oder mehrere Personen (bis Tiefe 3), als die aktivsten Personen des Archivs oder zwischen zwei Domains. Mindestanzahl Mails je Verbindung, Zeitraum in ganzen Jahren, nur DKIM-gültige Mails, Cc mitzählen, Verteiler und Automaten ausblenden; Knoten lassen sich aufklappen und ausblenden, ein Klick auf eine Verbindung öffnet die Mails zwischen beiden. Vier Layouts, Einfärben nach Domain, Pfeile in Senderichtung, Zeitverlauf Jahr für Jahr, Export als PNG, SVG und GraphML. Mehr als 2.000 Personen zeichnet die Karte nicht; die Vorschau neben der Schwelle sagt vorher, wie groß der Ausschnitt wird. Auch dieser Zustand steht in der Adresszeile.
- **Zahlen**: Gesamtzahlen und die Zähler neben den Filtern werden nach jedem Import und jeder DKIM-Nachprüfung neu berechnet, sonst spätestens alle fünf Minuten. Die Zahlen je Person entstehen am Ende jedes Imports und jeder DKIM-Nachprüfung, nach einem Zusammenführen sofort für die betroffenen Personen; die Personen eines laufenden Imports erscheinen also erst, wenn er fertig ist. Trefferzahlen eines Filters sind exakt, solange die Zählung höchstens zwei Sekunden dauert (`MAILROBBE_API_COUNT_TIMEOUT`), sonst steht dort „mehr als 10.000“.

- **Import** (`/import`): das Dashboard aus dem Abschnitt Import, mit Fehlerprotokoll nach Art und Datei.

Entwicklung am Frontend: siehe [CLAUDE.md](CLAUDE.md) (`frontend/`, Node 22).

## Beziehungskarte und Gephi

Die Karte liest die Tabelle `edge`: je Personenpaar die Mails in beide Richtungen (To und Bcc), die Cc-Mails, dieselben Zahlen nur für DKIM-gültige Mails und den Zeitraum, dazu dieselben Zähler je Jahr. Der Importer und `mailrobbe dkim` berechnen sie am Ende neu, das Zusammenführen und Trennen von Adressen nur für die betroffenen Personen. Verteiler (Mailinglisten, Sammeladressen) und Automaten (noreply, Benachrichtigungen, Newsletter) erkennt Mailrobbe an List-Id, Auto-Submitted und Precedence sowie am Verhalten der Adresse. Diese Kopfzeilen speichert der Importer ab Meilenstein 6; bei einem Archiv, das vorher eingelesen wurde, liest der nächste Import sie nach.

```sh
docker compose run --rm backend mailrobbe graph refresh                     # Kanten von Hand neu berechnen
docker compose run --rm -T backend mailrobbe graph export - > mailrobbe.graphml  # ganze Kantentabelle für Gephi
docker compose run --rm -T backend mailrobbe graph export --min-mails 5 - > mailrobbe-5.graphml
```

Der Export enthält jede Person mit Name, Adresse, Domain, Art und Mailzahl und jede Verbindung mit Gewicht, beiden Richtungen, Cc, erster und letzter Mail. In Gephi lässt er sich direkt öffnen (ungerichtet, Gewicht in `weight`). Der Download in der Karte enthält nur den gezeigten Ausschnitt.

## Annahmen zur Hardware

Ausgelegt für macOS oder Linux mit etwa 10 GB RAM für Datenbank und Importer zusammen. Die Voreinstellungen in `docker-compose.yml` (u. a. `shared_buffers` 2 GB, Importer-Worker = min(8, CPU-Kerne)) lassen sich über `.env` anpassen.

## Dokumentation

- [docs/SPEC.md](docs/SPEC.md): Spezifikation mit Architektur, Datenmodell, API und Meilensteinen
- [docs/mockup/](docs/mockup/): klickbarer UI-Prototyp der fünf Screens (HTML-Datei im Browser öffnen)
- [docs/DECISIONS.md](docs/DECISIONS.md): getroffene Entscheidungen (Frontend, Aliase, HTML, Zugriff, Export, Arbeitsweise, Hardware, DKIM, Import, Mailliste und Detail, Personen und Aliase, Beziehungskarte, Import-Dashboard)
- [docs/LOADTEST.md](docs/LOADTEST.md): Lasttest mit 400.000 Mails, Ablauf für die Zielmaschine und Messwerte
- [CLAUDE.md](CLAUDE.md): Entwicklungshinweise (Befehle, Konventionen, Tests)

## Stand

Meilenstein 1 (Gerüst, Datenbankschema, Testdaten-Generator), Meilenstein 2 (Importer mit Fortsetzen, Duplikaten und Threads), Meilenstein 3 (DKIM-Prüfung mit DNS-Cache und Nachprüf-Befehl), Meilenstein 4 (API, Mailliste und Mail-Detail), Meilenstein 5 (Personen, Personenprofil, Alias-Vorschläge und Zusammenführen), Meilenstein 6 (Beziehungskarte mit GraphML-Export), Meilenstein 7 (Import-Dashboard und Lasttest mit 400.000 Mails), Meilenstein 8 (Rechercheakte) und Meilenstein 9 (Anhänge mit Volltext, Dokumentliste und Dokumentseite) sind fertig. Den Lasttest aus [docs/LOADTEST.md](docs/LOADTEST.md) gibt es für die Auswertung der Anhänge noch nicht. Offen ist die Abnahme mit dem echten Archiv auf der Zielmaschine.
