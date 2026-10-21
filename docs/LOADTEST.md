# Lasttest

Meilenstein 7 prüft, ob Mailrobbe ein Archiv in der Zielgröße von rund 400.000 Mails trägt: Import über das Dashboard, Pause und Fortsetzen, Nachlauf, Header-Nachlesen älterer Importe, DKIM-Nachprüfung und die Antwortzeiten jeder Ansicht. Die Entscheidung dazu ist D51 in [DECISIONS.md](DECISIONS.md).

## Ablauf

Auf der Zielmaschine mit dem echten Archiv, im Projektverzeichnis:

```sh
docker compose up -d --build
```

1. http://127.0.0.1:8000/import öffnen und „Import starten“ drücken. Das Dashboard zeigt Durchsatz (Mails/s, MB/s), Restzeit, Worker und Fehler live; `docker compose logs -f backend` zeigt dieselben Zahlen alle paar Sekunden als Text.
2. Den Speicher beobachten: `docker stats` (Spalte MEM USAGE für `mailrobbe-backend-1` und `mailrobbe-db-1`).
3. Einmal „Pausieren“ drücken, warten, bis „Import pausiert“ erscheint, und mit „Import fortsetzen“ weitermachen.
4. Nach „Import fertig“ die Antwortzeiten messen:

   ```sh
   docker compose exec backend mailrobbe bench --rounds 5
   docker compose exec backend mailrobbe bench --rounds 1 --with-export --only CSV
   ```

   `bench` sucht sich seine Stichproben (neueste Mails, Wörter aus Betreffs, die aktivste Person und eine aus der Mitte, ihr stärkster Kontakt, die größten Absender-Domains, Kartenschwellen unter 2.000 Knoten) über die API selbst und gibt je Ansicht Median, 95. Perzentil und Maximum aus. Mit Basic Auth liest es Benutzer und Passwort aus der Umgebung des Containers.
5. Festhalten: Gesamtdauer und MB/s des Imports, Dauer des Nachlaufs (Phase „Nachlauf“ im Dashboard, im Log „updated duplicates, threads, display names and aggregates in … s“), den höchsten Speicherbedarf, DB-Größe und Volltextindex aus den Kacheln und die Tabelle von `bench`.

Ein Archiv, das vor Meilenstein 6 eingelesen wurde, braucht keinen neuen Import: der nächste Start liest zuerst die Kopfzeilen der gespeicherten Mails nach (Phase „Header älterer Mails werden neu gelesen“, D52) und importiert dann, was neu ist.

Ohne echtes Archiv lässt sich derselbe Test mit Testdaten fahren:

```sh
uv run mailrobbe generate --out data/mbox --mails 400000 --persons 10000 --domains 600 \
  --attachment-share 0.03 --large-attachments 2
```

## Ergebnisse in der Entwicklungsumgebung (21.10.2026)

Umgebung: Linux-VM mit 4 Kernen und 15 GB RAM, PostgreSQL 16 ohne Docker, aber mit den Einstellungen aus `docker-compose.yml` (`shared_buffers` 2 GB, `effective_cache_size` 4 GB, `work_mem` 32 MB, `maintenance_work_mem` 1 GB, `max_wal_size` 4 GB), Seiten-Cache vor dem Import geleert, 4 Worker (Standard min(8, Kerne)). DKIM-Schlüssel aus der DNS-Override-Tabelle des Generators, also ohne Netz.

Archiv: 400.000 generierte Mails in 68 Dateien, 8,9 GB (im Mittel 22 KB je Mail), 10.000 Personen auf 600 Domains, 3 % mit Anhängen, zwei Anhänge zu 55 MB, 2 % Störfälle, 1 % Duplikate. Erzeugt mit dem Befehl oben (`--jobs 2`) in 6 min 12 s.

### Import

| Schritt | Ergebnis |
| --- | --- |
| Start aus dem Dashboard bis zur Job-Zeile | 1,1 s |
| Einlesen, 400.000 Mails | rund 257 s, im Mittel etwa 1.550 Mails/s und 34 MB/s (laufend 1.550 bis 1.680 Mails/s, 33 bis 36 MB/s) |
| Pause aus dem Dashboard bei 184.786 Mails | nach rund 3 s angehalten; 28 Dateien fertig, 4 bei 41 bis 89 % pausiert, 36 wartend |
| Fortsetzen | dort weiter, wo gespeichert wurde: am Ende genau 400.000 Mails, keine doppelt |
| Nachlauf beim ersten Import | 83 s (Duplikate, 59.181 Threads, Anzeigenamen, 328.699 Personenpaare, Kennzahlen je Person, 5.031 Alias-Vorschläge, Gesamtzahlen) |
| Erneuter Start ohne neue Dateien | 33 s, davon 31 s Nachlauf |
| Abgleich mit dem Manifest | DKIM je Status exakt (130.228 gültig, 5.447 ungültig, 151.036 Schlüssel fehlt, 110.398 unsigniert, 2.891 DNS-Fehler), 4.005 Duplikate exakt; 7.025 Importfehler (Zeichensatz 3.101, Message-ID 2.280, Datum 1.644) |
| Header-Nachlesen aller 400.000 Mails (Stand vor Meilenstein 6 nachgestellt) | 107 s, davon rund 76 s Nachlesen (etwa 5.200 Mails/s) und 28 s Nachlauf; danach keine Zeile anders als nach dem frischen Import, Verteiler (30) und Automaten (242) wieder erkannt |
| DKIM-Nachprüfung aus dem Dashboard („Schlüssel fehlt“, DNS-Fehler, ungeprüft) | 153.927 Mails in 75 s samt Kennzahlen, beim Prüfen rund 2.200 Mails/s mit 4 Prozessen |
| Statusabfrage des Dashboards während der Läufe | Median 26 ms, 95 % unter 66 ms, höchstens 171 ms (81 Abfragen) |

Speicher: die Importprozesse zusammen 0,65 bis 0,82 GB (ein Worker 150 bis 245 MB), Spitze 1,4 GB, als ein Worker die Mails mit 55-MB-Anhängen las (dieser Worker 0,86 GB). Die PostgreSQL-Prozesse kamen zusammengezählt auf bis zu 3,6 GB; darin ist der gemeinsame Puffer (2 GB) mehrfach enthalten, der echte Bedarf liegt darunter.

Datenbank nach dem Import: 1,7 GB, rund 20 % der Rohdaten (Tabelle `mail` 1,24 GB, `participation` 174 MB, `dkim_result` 95 MB, `edge_year` 57 MB, `edge` 47 MB), Volltextindex 104 MB.

### Antwortzeiten bei 400.000 Mails

`mailrobbe bench --rounds 5` gegen den Server nach dem Import, eine Anfrage nach der anderen, Zeit bis zum letzten Byte:

| Ansicht | Median | 95 % |
| --- | --- | --- |
| Gesamtzahlen (Kopfzeile) | 11 ms | 15 ms |
| Mailliste, erste und folgende Seite, älteste zuerst | 16 bis 18 ms | 18 bis 24 ms |
| Filter (DKIM, Anhang, Domain, Jahr, Kombination) | 16 bis 19 ms | 17 bis 23 ms |
| Volltextsuche nach einem Wort, `subject:` | 19 bis 24 ms | 25 bis 35 ms |
| `from:<adresse>` | 59 ms | 66 ms |
| Kennzahlen zur Liste ohne Filter, mit Volltextwort | 5 ms, 181 ms | 9 ms, 236 ms |
| Kennzahlen zur Liste mit `dkim=pass` (130.228 Treffer) | 1.013 ms | 1.108 ms |
| Vor/Zurück im Mail-Detail | 15 ms | 28 ms |
| Mail-Detail, Text, Header, Rohmail | 5 bis 28 ms | 6 bis 47 ms |
| Personenliste (nach Mails, Name, letzter Mail), Personensuche | 16 bis 56 ms | 16 bis 66 ms |
| Profil der aktivsten Person, einer mittleren | 36 ms, 19 ms | 44 ms, 19 ms |
| Kontakte der aktivsten Person, ihre Mails, Mails zwischen ihr und ihrem Kontakt | 24 bis 49 ms | 27 bis 58 ms |
| Mailzahlen der aktivsten Person in einem Jahr | 229 ms | 289 ms |
| Alias-Vorschläge | 44 ms | 47 ms |
| Karte (Top 50, Top 200, Ego-Tiefe 1 und 2, zwei Domains), Größenvorschau | 237 bis 397 ms | 244 bis 505 ms |
| GraphML-Download Top 50 | 291 ms | 337 ms |
| Import-Dashboard: Status, Kacheln, Fehlerprotokoll | 10 bis 13 ms | 10 bis 15 ms |
| CSV-Export aller 400.000 Mails (102 MB) | 16,6 s | |

Die Kennzahlen neben einer Liste mit über 100.000 Treffern brauchen rund eine Sekunde; sie laden neben der Liste, die sofort steht, und sind auf zwei Sekunden begrenzt (`MAILROBBE_API_COUNT_TIMEOUT`), danach zeigt die Oberfläche „mehr als 10.000“.

## Was erst die Zielmaschine zeigt

- **Dauer des echten Imports.** Die Testmails sind im Mittel 22 KB groß, die echten rund 700 KB (280 GB in 400.000 Mails). Hier begrenzte das Parsen (rund 400 Mails/s je Worker), beim echten Archiv wird es das Lesen der 280 GB über den Bind-Mount sein. Bei 50 bis 150 MB/s wären das grob 30 Minuten bis 1,5 Stunden, unter Docker Desktop auf macOS eher am langsamen Ende; das ist eine Schätzung, das Dashboard zeigt MB/s und Restzeit live.
- **DNS.** Hier kamen alle Schlüssel aus der Override-Tabelle. Echte Archive haben deutlich mehr Selectors, jeder wird einmal gefragt (Zeitlimit 5 s) und dann aus dem Cache gelesen; nicht mehr erreichbare Domains enden als „Schlüssel fehlt“ oder DNS-Fehler und lassen sich mit „DKIM für „Schlüssel fehlt“ neu prüfen“ nachholen.
- **Datenbankgröße.** Echte Mails haben längere Texte (gespeichert werden höchstens 50.000 Zeichen je Mail für die Suche), die Datenbank wird also größer als die 1,7 GB hier, vermutlich einige GB.
- **Speicher bei großen Mails.** Ein Worker brauchte hier bis 0,86 GB für eine Mail mit 55-MB-Anhängen; echte Archive haben mehr solcher Mails. Mit 8 Workern und 2 GB `shared_buffers` sollte das in 10 GB passen, wenn nicht viele Riesenmails gleichzeitig gelesen werden; `MAILROBBE_IMPORT_WORKERS` senkt den Bedarf.
- **Header-Nachlesen über den Bind-Mount.** Es liest nur die Kopfbereiche der Mails und überspringt große Anhänge, bei vielen kleinen Mails aber fast die ganze Datei.
- **Anhalten beim Stoppen des Containers.** `docker compose stop` gibt dem Backend 60 Sekunden, laufende Stapel zu speichern; ob das bei sehr großen Mails reicht, zeigt erst das echte Archiv (sonst setzt der nächste Import beim letzten gespeicherten Stapel fort, es geht nichts verloren).
