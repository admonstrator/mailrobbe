# Mailrobbe

Mailrobbe liest große MBOX-Exporte ein (Zielgröße rund 400.000 Mails in etwa 70 Dateien), prüft jede Mail auf ihre DKIM-Signatur, ordnet sie den beteiligten Personen zu und macht alles in einer lokalen Web-Oberfläche durchsuchbar. Kernstück ist eine Beziehungskarte, die zeigt, wer mit wem wie oft kommuniziert.

Die Rohmails bleiben unverändert in den MBOX-Dateien, die read-only eingebunden werden. Die Datenbank (PostgreSQL) hält nur Metadaten, Byte-Offsets, den Volltextindex und Aggregationen.

## Schnellstart

Voraussetzung ist Docker (Docker Desktop unter macOS oder Docker Engine unter Linux).

```sh
docker compose up -d --build
curl http://127.0.0.1:8000/api/health
```

Das startet PostgreSQL 16 und das Backend, das beim Start das Datenbankschema anlegt bzw. aktualisiert. Die MBOX-Dateien werden aus `./data/mbox` gelesen, schreibgeschützt eingebunden als `/data/mbox`. Ein anderes Verzeichnis lässt sich in einer `.env`-Datei neben `docker-compose.yml` festlegen:

```sh
MAILROBBE_MBOX_HOST_DIR=/Volumes/Archiv/mbox
```

## Testdaten

Echte Mails braucht es für die Entwicklung nicht. Der Generator schreibt synthetische MBOX-Dateien mit realistischen Kommunikationsmustern, teils echten DKIM-Signaturen und absichtlich eingebauten Störfällen:

```sh
uv run mailrobbe generate --mails 10000          # mit lokalem Python und uv
docker compose run --rm generator --mails 10000   # ohne lokales Python
```

Die Dateien landen in `data/mbox/` (Standard: Teildateien zu je höchstens 128 MB), dazu unter `data/mbox/_generator/` ein Manifest mit dem erwarteten Ergebnis jeder Mail, die DNS-Override-Tabelle für die DKIM-Prüfung und die Testschlüssel. 10.000 Mails ergeben rund 1,1 GB und brauchen auf vier Kernen etwa 20 Sekunden; 400.000 Mails für den Lasttest ergeben rund 35 GB, hochgerechnet in 10 bis 15 Minuten. Gleiche Parameter und gleicher `--seed` ergeben bytegleiche MBOX-Dateien und Manifeste. `--help` zeigt alle Parameter (Personen, Domains, Zeitraum, Anhänge, Dateigröße, DKIM-Anteil, Fehler- und Duplikatquote, Seed, Prozesse).

## Annahmen zur Hardware

Ausgelegt für macOS oder Linux mit etwa 10 GB RAM für Datenbank und Importer zusammen. Die Voreinstellungen in `docker-compose.yml` (u. a. `shared_buffers` 2 GB, Importer-Worker = min(8, CPU-Kerne)) lassen sich über `.env` anpassen.

## Dokumentation

- [docs/SPEC.md](docs/SPEC.md): Spezifikation mit Architektur, Datenmodell, API und Meilensteinen
- [docs/mockup/](docs/mockup/): klickbarer UI-Prototyp der fünf Screens (HTML-Datei im Browser öffnen)
- [docs/DECISIONS.md](docs/DECISIONS.md): getroffene Entscheidungen (Frontend, Aliase, HTML, Zugriff, Export, Arbeitsweise, Hardware)
- [CLAUDE.md](CLAUDE.md): Entwicklungshinweise (Befehle, Konventionen, Tests)

## Stand

Meilenstein 1: Gerüst, Datenbankschema und Testdaten-Generator. Importer, DKIM-Prüfung und Web-Oberfläche folgen in den nächsten Meilensteinen.
