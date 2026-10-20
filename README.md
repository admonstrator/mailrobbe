# Mailspider

Mailspider liest große MBOX-Exporte ein (Zielgröße rund 400.000 Mails in etwa 70 Dateien), prüft jede Mail auf ihre DKIM-Signatur, ordnet sie den beteiligten Personen zu und macht alles in einer lokalen Web-Oberfläche durchsuchbar. Kernstück ist eine Beziehungskarte, die zeigt, wer mit wem wie oft kommuniziert.

Die Rohmails bleiben unverändert in den MBOX-Dateien, die read-only eingebunden werden. Die Datenbank (PostgreSQL) hält nur Metadaten, Byte-Offsets, den Volltextindex und Aggregationen.

## Dokumentation

- [docs/SPEC.md](docs/SPEC.md): Spezifikation mit Architektur, Datenmodell, API und Meilensteinen
- [docs/mockup/](docs/mockup/): klickbarer UI-Prototyp der fünf Screens (HTML-Datei im Browser öffnen)

## Stand

Im Aufbau. Gerüst, Datenbankschema und Testdaten-Generator entstehen in Meilenstein 1; die Startanleitung folgt mit diesem Meilenstein.
