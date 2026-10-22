<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./docs/logo/logo-wordmark-dark.svg">
  <img src="./frontend/public/logo-wordmark.svg" alt="Mailrobbe" width="480">
</picture>

<h1>Mailrobbe</h1>

[![CI](https://img.shields.io/github/actions/workflow/status/admonstrator/mailrobbe/ci.yml?event=pull_request&style=for-the-badge&logo=githubactions&logoColor=white&label=CI)](https://github.com/admonstrator/mailrobbe/actions/workflows/ci.yml?query=event%3Apull_request) [![Python](https://img.shields.io/badge/Python-3.12-1D5BD6?style=for-the-badge&logo=python&logoColor=white)](pyproject.toml) [![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?style=for-the-badge&logo=postgresql&logoColor=white)](docker-compose.yml) [![React](https://img.shields.io/badge/React-TypeScript-0EA5E9?style=for-the-badge&logo=react&logoColor=white)](frontend/) [![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)](#schnellstart)

[Auf einen Blick](#auf-einen-blick) | [Was Mailrobbe kann](#was-mailrobbe-kann) | [Schnellstart](#schnellstart) | [Web-Oberfläche](#web-oberfläche) | [Häufige Fragen](#häufige-fragen)

</div>

---

Mailrobbe liest große MBOX-Exporte ein (Zielgröße rund 400.000 Mails in etwa 70 Dateien), prüft jede Mail auf ihre DKIM-Signatur, ordnet sie den beteiligten Personen zu und macht alles in einer lokalen Web-Oberfläche durchsuchbar. Kernstück ist eine Beziehungskarte, die zeigt, wer mit wem wie oft kommuniziert.

Die Rohmails bleiben unverändert in den MBOX-Dateien, die read-only eingebunden werden. Die Datenbank (PostgreSQL) hält nur Metadaten, Byte-Offsets, den Volltextindex und Aggregationen.

## Auf einen Blick

| Frage                                                  | Wo in Mailrobbe                                                                                     |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------- |
| Wer hat mit wem wie oft geschrieben?                   | Beziehungskarte (`/karte`), Top-Kontakte im Personenprofil                                           |
| Ist diese Mail echt?                                   | DKIM-Ergebnis je Signatur im Mail-Detail, Filter `dkim:pass` und `dkim:fail`                         |
| Wer steckt hinter mehreren Adressen?                   | Alias-Vorschläge unter Personen, sichere getrennt von unsicheren; jede Zusammenführung lässt sich rückgängig machen |
| Wer wusste was wann?                                   | Zeitachse (`/zeitachse`): Verlauf, Ausreißer, Verstummen, erste Erwähnung je Person                 |
| Wer hat dieses Dokument wann an wen geschickt?         | Anhänge (`/anhaenge`) und die Seite des Dokuments                                                    |
| Welche Beträge, Konten und Namen tauchen auf?          | Entitäten (`/entitaeten`) und die Facetten neben der Mailliste, Filter nach Betrag und Bargeld/Spende/Quittung |
| Welche Mails sollte ich zuerst lesen?                  | Signale (`/auffaelligkeiten`): private Adressen, Bcc, Weiterleitungen nach außen, Nacht, Wortfelder, Verstummen |
| Wo steht ein Begriff, auch in PDFs und Tabellen?       | Volltextsuche über Mails und Anhänge, dazu `from:`, `to:`, `subject:`, `has:attachment`, `after:`    |
| Womit fange ich an?                                    | Themen unter Akten: Wortfelder und 18 Suchvorlagen zu den Schwerpunkten der Recherche                |
| Wie halte ich Funde im Team fest?                      | Rechercheakte (`/akten`): Status, Notizen, Schlagworte, Akten, gespeicherte Suchen, Permalinks       |
| Wie gebe ich Belege an Anwälte weiter?                 | Export als ZIP mit Originalmail, PDF je Mail, Manifest und `SHA256SUMS`                              |

---

## Was Mailrobbe kann

### Die Mails bleiben, wie sie sind

Mailrobbe ändert kein Byte an den MBOX-Dateien. Es merkt sich je Mail Datei, Byte-Offset, Länge und SHA-256 und liest Text, HTML, Header, Anhänge und Downloads erst beim Öffnen aus der Datei, geprüft gegen den Hash vom Import. Der Export gibt dieselben Bytes als EML weiter.

### Echtheit prüfen statt vermuten

Jede DKIM-Signatur wird einzeln geprüft und mit Grund gespeichert: gültig, ungültig (etwa weil der Body geändert wurde), Schlüssel fehlt, unsigniert oder DNS-Fehler. Eine gültige Signatur zeigt, dass die Mail mit dem Schlüssel der signierenden Domain unterschrieben wurde und die unterschriebenen Teile seither unverändert sind.

### Personen statt Adressen

Aus Absendern und Empfängern werden Personen mit Kennzahlen, Top-Kontakten und Aktivität je Jahr. Mailrobbe schlägt Adressen vor, die vermutlich zu derselben Person gehören, und trennt dabei sichere von unsicheren Vorschlägen. Zusammengeführt wird nie von selbst, sondern per Klick, und jede Zusammenführung lässt sich wieder rückgängig machen. Wer weiß, wer hinter einer Adresse steckt, gibt ihr einen Klarnamen, eine Rolle und eine Notiz; der Name steht dann überall, wo die Person auftaucht, auch auf der Karte, und die Suche findet sie darüber.

### Weniger doppelt lesen

Im Mail-Detail ist der zitierte Verlauf eingeklappt, ebenso Weiterleitungen, Outlook-Originale und Signaturen; steht ein Suchwort darin, klappt der Abschnitt von selbst auf. Mails mit fast gleichem Text, etwa ein Rundschreiben, das einzeln an viele ging, oder eine Weiterleitung ohne eigenes Wort, bilden eine Gruppe, und die Mailliste kann jede Gruppe auf eine Zeile zusammenfassen. Kalendereinladungen erscheinen als Termin mit Zeit, Ort, Organisator und den Antworten der Eingeladenen.

### Die Karte zeigt, wer mit wem

Die Beziehungskarte zeichnet Ausschnitte um eine oder mehrere Personen, die aktivsten Personen oder den Verkehr zwischen zwei Domains, Jahr für Jahr. Verteiler und Automaten lassen sich ausblenden, ein Klick auf eine Verbindung öffnet die Mails dazwischen. Kreise und Linien wachsen mit dem Logarithmus der Mails, so bleibt die Karte auch neben sehr aktiven Personen lesbar. Für Gephi gibt es GraphML.

### Die Zeitachse zeigt, wer was wann wusste

Für jede Suche zeigt die Zeitachse das Mailaufkommen je Tag, Woche oder Monat, auf Wunsch getrennt nach Personen, Threads oder Suchbegriffen. Ungewöhnlich viele oder wenige Mails und Personen, die plötzlich verstummen, sind markiert, nach einfachen, nachlesbaren Regeln. Für einen Begriff listet sie, wer ihn wann zuerst geschrieben oder bekommen hat. Ein Klick auf einen Balken öffnet genau diese Mails.

### Anhänge sind Teil der Suche

Text aus PDF, Word, Excel, PowerPoint, OpenDocument und vielen weiteren Formaten landet im selben Volltextindex wie die Mails. Jedes Dokument steht einmal in der Liste, auch wenn es durch viele Mails gewandert ist, mit der Antwort auf die Frage, wer es wann an wen geschickt hat. Wer eine Mail aus einer Suche öffnet, sieht, wo die Suchwörter stehen: im Betreff, im Text, im zitierten Verlauf oder in welchem Anhang. Die Fundstellen sind markiert, auch gebeugte Formen wie „Spenden“ bei der Suche nach „Spende“.

### Anhänge ansehen, ohne sie herunterzuladen

PDFs, Word-Dokumente (DOCX, ODT), Bilder, Audio und Video zeigt Mailrobbe auf der Dokumentseite und, aus der Anhangsliste im Mail-Detail, in einem Fenster über der Seite. Bilder öffnen sich groß, mit Zoom und Verschieben. Weil Anhänge aus einem fremden Archiv alles Mögliche enthalten können, läuft jede Vorschau abgeschottet: PDFs zeichnet ein eigener Betrachter ohne Netzzugang und ohne Zugriff auf die Anwendung, Word-Dateien werden in einem eigenen Prozess mit Zeit- und Speichergrenze in bereinigtes HTML umgewandelt und ohne Skripte angezeigt, Audio und Video spielt der Browser selbst ab. Was sich so nicht sicher zeigen lässt (DOC, RTF, Tabellen, Präsentationen), gibt es nur als Download. Umgewandelte Dokumente und Mediendateien landen beim ersten Öffnen in `data/previews` (`MAILROBBE_PREVIEW_DIR`); der Ordner enthält Kopien der Anhänge und darf jederzeit gelöscht werden. Anhänge über 50 MB (`MAILROBBE_PREVIEW_MAX_SIZE`) bekommen keine Vorschau. Ein neuer Import ist dafür nicht nötig.

### Was Dateien über sich verraten

Bilder, PDFs und Office-Dateien tragen oft Angaben über ihre Herkunft: Kamera, Aufnahmezeit und Ort aus den EXIF-Daten eines Fotos, Autor, Programm und Bearbeitungsgeschichte eines PDFs, Autor, zuletzt bearbeitet von, Firma, Vorlage, Kommentare und Änderungen eines Word-Dokuments. Mailrobbe liest sie beim Import aus, zeigt sie auf der Dokumentseite und als kurze Zeile am Anhang im Mail-Detail und macht Autor und Programm zu Filtern der Anhangsliste. Die Werte stehen so da, wie die Datei sie angibt; sie können falsch oder gefälscht sein. Eine Ortsangabe erscheint als Koordinaten mit einem Link zu OpenStreetMap, die Anwendung selbst lädt keine Karte.

### Entitäten zeigen, wonach man suchen kann

Mailrobbe liest aus Mails und Anhängen heraus, was darin erwähnt wird: Beträge, IBANs und Kontonummern, Organisationen, Personen, Orte, Telefonnummern, Adressen, Links, Daten und die Begriffe der Recherchethemen. Neben der Mailliste stehen die häufigsten davon für die aktuelle Suche; ein Klick grenzt die Treffer ein. Beträge, die neben Wörtern wie „bar“, „Spende“ oder „Quittung“ stehen, lassen sich gezielt filtern. Bewertet wird dabei nichts, die Liste zeigt nur, was vorkommt und wie oft.

### Signale zeigen, wo das Lesen anfangen kann

Einfache, nachlesbare Regeln zeigen auf Mails, die sich zu lesen lohnen können: eine private Adresse, Post von intern an privat, eine Blindkopie, viele Empfänger, eine Weiterleitung nach außen, eine Mail mitten in der Nacht oder am Wochenende, ein Begriff aus einem Recherchethema, eine Person, von der plötzlich nichts mehr kommt. Jede Mail sagt, warum sie ein Signal trägt. Signale bewerten nichts und beweisen nichts; viele haben harmlose Gründe, ob eine Mail zählt, zeigt erst das Lesen.

### Die Rechercheakte hält fest, was das Team findet

Prüfstatus, Notizen, Schlagworte, Akten und gespeicherte Suchen hängen am Inhalt der Mail und überstehen deshalb auch einen Neuimport. Mailrobbe markiert und bewertet nichts von selbst: Suchen zeigen auf Mails, Menschen lesen und entscheiden.

### Gebaut für 400.000 Mails

Der Importer liest jede Datei sequenziell in großen Blöcken, lässt sich pausieren und setzt ohne Dubletten fort. Im Lasttest liefen 400.000 Testmails in gut vier Minuten durch, Listen und Filter antworteten danach meist in 10 bis 60 ms.

---

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

Die Dateien landen in `data/mbox/` (Standard: Teildateien zu je höchstens 128 MB), dazu unter `data/mbox/_generator/` ein Manifest mit dem erwarteten Ergebnis jeder Mail, die DNS-Override-Tabelle für die DKIM-Prüfung und die Testschlüssel. 10.000 Mails ergeben rund 1,1 GB und brauchen auf vier Kernen etwa 20 Sekunden; 400.000 Mails ergeben mit den Voreinstellungen rund 35 GB, mit den Parametern des Lasttests ([docs/LOADTEST.md](docs/LOADTEST.md)) 8,9 GB in gut 6 Minuten. Die Anhänge sind echte Dokumente: PDFs mit und ohne Textebene, verschlüsselte und beschädigte PDFs, DOCX, XLSX, PPTX, ODT, CSV und ZIP, dazu Bilder (PNG, JPEG) und kurze Audio- und Videodateien (MP3, M4A, WAV, Ogg, FLAC, MP4, MOV, WebM sowie WMA und AVI, die kein Browser abspielt). Sie wandern weitergeleitet und erneut angehängt zwischen den Mails, und das Manifest nennt je Anhang Hash, Art, erwarteten Textstatus und ein Markierwort aus seinem Text. Gleiche Parameter und gleicher `--seed` ergeben bytegleiche MBOX-Dateien und Manifeste. `--help` zeigt alle Parameter (Personen, Domains, Zeitraum, Anhänge, Dateigröße, DKIM-Anteil, Fehler- und Duplikatquote, Seed, Prozesse).

## Import

Der Import läuft am bequemsten über das Dashboard unter http://127.0.0.1:8000/import: „Import starten“, „Pausieren“, „Import fortsetzen“, „Verzeichnis neu scannen“ und die DKIM-Nachprüfung, dazu Fortschritt je Datei, Durchsatz, Restzeit, Fehlerprotokoll, DKIM-Ergebnis und Datenbankgröße live. Die Einstellungen im Dashboard (Worker, Anhang-Limit, DNS-Resolver) gelten für den nächsten Start von dort. Auf der Kommandozeile geht dasselbe:

```sh
docker compose run --rm backend mailrobbe import   # liest /data/mbox im Container
uv run mailrobbe import --dir data/mbox            # mit lokalem Python und uv
```

Das Dashboard zeigt auch einen Import, der auf der Kommandozeile läuft, und kann ihn pausieren. Es läuft immer nur ein Import oder eine DKIM-Prüfung gleichzeitig. Ein Import, den das Dashboard gestartet hat, schreibt seine Ausgabe in `docker compose logs backend`; stoppt der Container, pausiert er sauber und setzt beim nächsten Start fort.

Der Importer liest jede MBOX-Datei unterhalb des Verzeichnisses (erkannt am Inhalt, nicht an der Endung) in einem eigenen Worker-Prozess, sequenziell und in großen Blöcken. Je Mail speichert er Kopfdaten, Byte-Offset und Länge in der MBOX-Datei, SHA-256, Personen, Anhänge (Name, Typ, Größe, Hash) und den Text für die Volltextsuche; die Rohmail selbst bleibt in der Datei. Die DKIM-Prüfung läuft dabei mit. Am Ende markiert er Duplikate, bildet Threads aus Message-ID, In-Reply-To und References, setzt die Anzeigenamen der Personen und berechnet die Kanten der Beziehungskarte, die Kennzahlen je Person und die Alias-Vorschläge.

Zum Schluss liest der Import die Anhänge aus. Jeder Inhalt (gleicher SHA-256) wird nur einmal gelesen, auch wenn er in vielen Mails steckt. Text kommt aus PDF, Word (DOCX), Excel (XLSX), PowerPoint (PPTX), OpenDocument (ODT, ODS, ODP), XPS, RTF, CSV, Text, HTML, XML, JSON, Kalendereinträgen, Visitenkarten und angehängten Mails; von ZIP-Archiven die Dateinamen darin. SVG-Grafiken, Schlüssel, Signaturen, Zertifikate, Stylesheets und Skripte bleiben ohne Text, auch wenn sie sich als Text ausgeben, ebenso ZIP-Container anderer Formate wie EPUB. Tabellen gibt er Zelle für Zelle so wieder, wie sie in der Datei stehen, Beträge und IBANs also unverändert. Gescannte PDFs ohne Textebene, verschlüsselte und beschädigte Dateien werden erkannt und gezählt. Bilder, Audio, Video und alte Office-Formate (DOC, XLS, PPT) bleiben ohne Text. Jedes Dokument wird in einem eigenen Prozess gelesen, der nach `MAILROBBE_ATTACHMENT_TEXT_TIMEOUT` (60 s) abgebrochen wird; bis dahin gelesener Text bleibt erhalten. Unter Linux und in Docker darf er höchstens `MAILROBBE_ATTACHMENT_TEXT_MEMORY` (1 GB) zusätzlich belegen. Dokumente über `MAILROBBE_ATTACHMENT_TEXT_MAX_SIZE` (50 MB) liest er gar nicht. Pausieren und Fortsetzen gelten auch hier. Bei einem Archiv, das vor Meilenstein 9 eingelesen wurde, wertet der nächste Import die Anhänge aus, ohne die Mails neu einzulesen.

Davor packt er Container aus (Schritt „Archive und angehängte Mails auspacken“): ZIP- und 7z-Archive und angehängte Mails. Was darin steckt, wird ein eigenes Dokument mit Text, Metadaten und Entitäten und steht im Mail-Detail unter seinem Container. Geöffnet wird nur eine Ebene tief: ein Archiv in einem Archiv wird aufgelistet, nicht ausgepackt. Je Container höchstens `MAILROBBE_ARCHIVE_MAX_MEMBERS` (1.000) Einträge und `MAILROBBE_ARCHIVE_MAX_SIZE` (500 MB) ausgepackt, damit eine präparierte Datei den Rechner nicht füllt; ZIP und 7z braucht das Programm 7-Zip, das im Docker-Image steckt. RAR, tar und gzip bleiben zu.

Nach dem Text sucht er Kennwörter (Schritt „Kennwörter suchen und probieren“). Was in einer Mail oder einem Anhang hinter „Kennwort“, „Passwort“, „PW“, „PIN“, „Zugangscode“, „password“ und ähnlichen Wörtern steht, probiert er an jeder verschlüsselten PDF-, Word-, Excel-, PowerPoint-, ZIP- und 7z-Datei, das Nächstliegende zuerst: dieselbe Mail, derselbe Thread, Mails zwischen denselben Personen 30 Tage davor und danach, deren Anhänge, dann der Rest des Archivs. Höchstens `MAILROBBE_PASSWORD_SECONDS` (10 s) je Datei und Lauf; Wortlisten und Raten gibt es nicht. Ein Treffer öffnet die Datei, ihr Text kommt in die Suche, und die Dokumentseite zeigt das Kennwort mit der Mail, in der es stand. Entschlüsselte Bytes speichert Mailrobbe nie; Vorschau und Download entschlüsseln bei jedem Abruf. Ein geöffnetes Archiv packt der nächste Lauf aus. Jeder Lauf probiert nur die Kennwörter, die seit dem letzten dazugekommen sind. Verschlüsselte OpenDocument-Dateien werden erkannt, aber noch nicht geöffnet, verschlüsselte Mails (PGP, S/MIME) nur gezählt.

Aus denselben Bytes liest er die Metadaten der Dateien: EXIF und GPS von JPEG, PNG, WebP und TIFF, Informationen, XMP, Revisionen und eingebettete Dateien von PDFs, die Eigenschaften von DOCX, XLSX, PPTX und OpenDocument, bei DOCX auch Kommentare und Änderungen mit ihren Autoren. Das läuft im selben abgeschotteten Prozess mit denselben Grenzen; eine kaputte Datei wird vermerkt und hält den Lauf nicht auf. Dokumente, die schon vorher eingelesen waren, holt der Schritt „Metadaten aus Anhängen lesen“ beim nächsten Lauf nach, ohne die Mails neu einzulesen. HEIC, alte Office-Formate (DOC, XLS) und die Herstellerdaten der Kameras (MakerNotes) liest er nicht.

Dann sucht er Kalendereinladungen (Schritt „Kalendereinladungen lesen“): Mails mit einem Kalenderteil (`text/calendar`, `.ics`) oder mit den Kennzeichen einer Einladung im Betreff oder Text liest er noch einmal aus der MBOX-Datei und speichert je Termin Titel, Zeit, Ort, Organisator und Eingeladene mit ihren Antworten. Für nahezu gleiche Mails bildet er je Mail einen Fingerabdruck aus Betreff und Text ohne Zitatzeichen, Anrede und Weiterleitungskopf (Schritt „Fingerabdrücke der Mailtexte“) und gruppiert danach alle Mails mit gleichem Abdruck (Schritt „Nahezu gleiche Mails gruppieren“); Serienbriefe mit anderem Betrag oder Datum bleiben getrennt. Beide Schritte sehen sich jede Mail nur einmal an, ein Archiv, das vor Meilenstein 14 eingelesen wurde, bekommt Termine und Gruppen beim nächsten „Import starten“, ohne Neuimport. Einladungen ohne Kalenderteil und ohne diese Kennzeichen findet er nicht.

Danach erkennt der Import die Entitäten (Schritt „Entitäten erkennen“) in Betreff und Text jeder Mail und im Text jedes Dokuments, mit so vielen Prozessen, wie er Worker hat. Er liest dafür nur, was schon in der Datenbank steht, nie die MBOX-Dateien. Jeder Text wird einmal ausgewertet; ändern sich die Wortlisten in `themes.toml` oder die Ortslisten in `src/mailrobbe/entities/data/`, wertet der nächste Import alles neu aus. Bei einem Archiv, das vor Meilenstein 10 eingelesen wurde, genügt „Import starten“ im Dashboard: die Mails werden nicht neu eingelesen, nur ihre Entitäten ergänzt. Pausieren und Fortsetzen gelten auch hier.

Anschließend berechnet der Import die Signale (Schritt „Signale berechnen“) aus dem, was in der Datenbank steht, bei jedem Lauf vollständig neu, so dass geänderte Einstellungen, Wortfelder und Zusammenführungen beim nächsten „Import starten“ wirken. Bei 6.000 Testmails dauert das unter einer Sekunde. Ein Archiv, das vor Meilenstein 12 eingelesen wurde, bekommt seine Signale so ohne Neuimport.

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

- **Mailliste**: Suche, Filterspalte (Zeitraum, DKIM-Status, Absender-Domain, Anhang, Thread, Duplikate, markierte Mails, MBOX-Datei), Kennzahlen zum aktuellen Filter, Sortierung nach Datum, Seiten zu je 50 Mails mit Zurück/Weiter, CSV-Export aller Treffer (Semikolon, öffnet direkt in Excel). Die Gruppe „Termine“ filtert Einladungen, Antworten und Absagen; „Dubletten zusammenfassen“ zeigt von nahezu gleichen Mails nur die früheste, die übrigen Filter bleiben wirksam, und „+N“ an einer Zeile nennt die anderen der Gruppe. Filter und Suche stehen in der Adresszeile, Links lassen sich also aufheben und teilen.
- **Mail-Detail**: Vor/Zurück innerhalb der Treffer (auch mit den Pfeiltasten), Kopfdaten mit Quelle (Datei, Offset, Größe) und SHA-256, DKIM-Prüfung je Signatur mit Grund, DNS-Record und „Neu prüfen“, Text, HTML, alle Header und Rohmail werden erst beim Öffnen aus der MBOX-Datei gelesen, Anhänge, Beteiligte, Thread, EML-Download, Markierung und Notiz. HTML-Mails laufen in einem abgeschotteten Rahmen ohne Skripte und ohne Nachladen von außen. Beim Scrollen bleibt oben eine schmale Leiste mit Betreff, Absender, Datum, DKIM und Vor/Zurück, damit Text und HTML die Höhe des Fensters bekommen. Die Anhänge stehen rechts unter der Recherche-Karte, mit der Metadatenzeile, Download, Vorschau im Fenster über der Seite und dem Weg zum Dokument; bei vielen Anhängen erst acht und „alle anzeigen“. Die Recherche-Karte lässt sich auf eine Zeile einklappen, ihre Tasten bleiben aktiv. Zitate, Weiterleitungen, Outlook-Originale und Signaturen beginnen eingeklappt, Fundstellen der Suche klappen sie auf; nur die Anzeige ändert sich, Suche, HTML-Ansicht und Export behalten den ganzen Text. Die Karte „nahezu gleiche Mails“ in der Seitenleiste listet die Gruppe der Mail, die Karte „Termin“ über dem Text zeigt eine Einladung mit Zeit (auch in Berliner Zeit), Ort, Organisator, Antworten und den anderen Mails desselben Termins.
- **Suche**: `from:anna@`, `to:@beispiel.de`, `cc:keller`, `subject:Vertrag`, `domain:beispiel.de`, `has:attachment`, `dkim:fail` (auch `pass`, `no_key`, `unsigned`, `temp_error`, `unchecked`), `after:2024-01-01`, `before:2025-01-01`, Anführungszeichen für Phrasen, eine `<message-id@host>` findet genau diese Mail; der Rest ist Volltext (deutsche Wortstämme). Adressen und Betreff finden auch Teilwörter. Der Volltext durchsucht auch die Texte der Anhänge. Eine Mail, die nur über einen Anhang gefunden wurde, trägt das Zeichen „im Anhang“. Das Suchmenü am Suchfeld oben (Knopf mit den Schiebereglern) grenzt den Volltext ein: nur in Betreff, Mailtext, Anhangstext oder Dateiname; „Ganzes Wort“ findet das Wort nur so, wie es geschrieben ist (ohne Wortstamm und Teilwörter, Groß- und Kleinschreibung egal, Umlaute und Akzente zählen: „Rat“ findet dann weder „Raten“ noch „Räte“ noch das englische „rate“, Beugungen nennt man selbst: `Rat or Räte`); „Mindestens n Treffer“ verlangt, dass die Suchwörter so oft in Mail und Anhängen stehen. `betreff:`, `text:`, `anhang:` und `datei:` suchen ein Wort nur an dieser Stelle, ein Minus vor jedem Operator schließt aus (`-datei:Entwurf`, `-from:anna`); das Feld „Wörter ausschließen“ im Suchmenü setzt die Minus-Wörter selbst. Dort stehen auch die gespeicherten Suchen und die Suchsyntax. Jede Zeile der Mailliste sagt, wo und wie oft die Suchwörter stehen.
- **Personen**: alle Personen mit Mails, Gesendet, Empfangen, Kontakten, letzter Mail und DKIM-Anteil, sortiert nach Mails, Name oder letzter Mail. Die Suche findet Teile von Adressen und Anzeigenamen, auch die der Aliase, und die Klarnamen und Rollen, die das Team vergeben hat; „Nur benannte“ zeigt nur benannte Personen.
- **Personenprofil**: Kennzahlen, Top-Kontakte, Aktivität pro Jahr, Anzeigenamen und Adressen der Person, darunter alle ihre Mails nach Rolle (Gesendet, Empfangen, Nur Cc), Jahr und Kontakt. Ein Klick auf ein Jahr oder einen Kontakt filtert die Liste; Vor/Zurück im Mail-Detail bleibt in diesen Mails. „Benennen“ gibt der Adresse Klarname, Rolle und Notiz; die Benennung hängt an der Adresse und übersteht Zusammenführen, Rückgängig und Neuimport, `from:`, `to:` und `cc:` finden sie mit. Die Karte „Termine“ zeigt die Einladungen, die die Person verschickt oder bekommen hat.
- **Aliase**: Mailrobbe führt Adressen nie von selbst zusammen. Es schlägt Paare vor und teilt sie in zwei Stufen. **Sicher** ist ein Paar, wenn die Namen übereinstimmen (derselbe Hauptname und derselbe Teil vor dem @, oder ein Name, den nur diese beiden tragen und aus dem beide Adressen gebildet sind, bei derselben Organisation) und beide Personen außerdem mehrere Kontakte gemeinsam haben; Namensvettern ohne gemeinsamen Umgang bleiben so draußen. Alles andere, was nur einen Namen oder nur den Teil vor dem @ teilt, ist **unsicher** und erscheint erst mit dem Schalter „Unsichere Vorschläge zeigen“. Funktionspostfächer (Zentralpostfach, Poststelle, Geschäftsstelle, kv.musterstadt und viele mehr), Verteiler, Automaten und Postfächer, die mehrere Leute unter ihrem Namen benutzen, erzeugen gar keinen Vorschlag; als Name einer Adresse zählt nur der, unter dem sie in mindestens der Hälfte ihrer Mails auftritt. Jeder Vorschlag sagt, warum er da ist. „Zusammenführen“ macht eine Adresse zum Alias einer Person, ihre Mails zählen dann dort; „Alle sicheren zusammenführen“ erledigt alle sicheren Vorschläge in einem Lauf, nach einer Rückfrage mit den Zahlen. Jede Zusammenführung steht unter „Zuletzt zusammengeführt“ und lässt sich dort einzeln oder als ganzer Lauf rückgängig machen, im Profil auch je Adresse; „Verwerfen“ blendet einen Vorschlag dauerhaft aus. Die Stufen berechnet jeder Import-Lauf neu, auch „Import fortsetzen“ ohne neue Mails.
- **Anhänge** (`/anhaenge`): jedes Dokument einmal, auch wenn es in vielen Mails steckt, mit Volltextsuche über Text und Dateinamen (Fundstelle im Text hervorgehoben). Filter: Dateiname, Art, Textstatus (darunter „Gescannt (ohne Text)“ für eine spätere Texterkennung), Zeitraum, Person als Absender oder Empfänger, „in mehreren Mails“, intern/extern sowie Autor und Programm aus den Metadaten der Dateien, mit Suche in den Werten. Sortiert wird nach erstem Auftauchen, Zahl der Mails oder Größe. Die Dokumentseite zeigt, wer das Dokument wann an wen geschickt hat, als Mailliste mit der ältesten Mail zuerst. Dazu kommen die Dateinamen, unter denen es lief, die häufigsten Absender und Empfänger, die Metadaten der Datei, der ausgelesene Text, der Download und eine Vorschau für Bilder, PDFs, DOCX, ODT, Audio und Video, Bilder auch in der Großansicht. Beim Scrollen schrumpft der Kopf zu einer schmalen Leiste, die Vorschau bekommt die Höhe des Fensters. Im Mail-Detail führt jeder Anhang zu seinem Dokument, zum Download und, wo es eine gibt, zur selben Vorschau. Downloads liest Mailrobbe bei jedem Abruf aus der MBOX-Datei, prüft sie gegen den Hash und liefert sie immer als Datei aus, nie zum Anzeigen im Browser.
- **Entitäten** (`/entitaeten`): alles, was in Mails und Anhängen erkannt wurde, mit Reitern je Art (Beträge, Konten, Organisationen, Personen, Orte, Telefon, E-Mail, Web, Daten, Themenbegriffe), Suche, Sortierung nach Mails, erster oder letzter Erwähnung, Betrag und Name, für Beträge mit einem Wertebereich. Die Seite einer Entität zeigt Mails pro Jahr, Absender und Empfänger, was in denselben Mails noch erwähnt wird, die frühesten Fundstellen mit Textausschnitt und bei Beträgen, wie oft sie neben Bargeld, Spende oder Quittung stehen. Neben der Mailliste stehen die häufigsten Entitäten der aktuellen Treffer (bis 10.000 Treffer genau, darüber aus einer Stichprobe); ein Klick nimmt eine Entität in den Filter, mehrere müssen alle vorkommen. Die Filterspalte hat dazu „Betrag ab“ und Bargeld/Spende/Quittung. Im Mail-Detail steht, was in der Mail und ihren Anhängen erkannt wurde. Personen erkennt Mailrobbe an bekannten Vornamen oder an „Herr“ und „Frau“, Orte an einer Liste und an Postleitzahlen; was dort fehlt, findet die Volltextsuche.
- **Signale** (`/auffaelligkeiten`): je Mail private Adresse, von intern an privat und zurück, private Zweitadresse einer Person, Blindkopie, viele Empfänger (ab 25), Weiterleitung und Weiterleitung nach außen, Nacht (22 bis 6 Uhr) und Wochenende in der Ortszeit sowie das Wortfeld jedes Recherchethemas, auch in Anhängen; je Person das Verstummen nach der Regel der Zeitachse. Die Übersicht erklärt, wie man mit Signalen sucht, nennt Regeln und Einstellungen und zeigt je Signal Mails, Anteil und die häufigsten Absender. Neben der Mailliste stehen die Signale der Treffer als Facetten (Filter `signal`, auch in Zeitachse, CSV, Akten und Export), im Mail-Detail die Karte „Warum fällt diese Mail auf“ mit dem Grund, im Personenprofil die Signale ihrer gesendeten Mails. Einstellungen in der `.env`: `MAILROBBE_INTERNAL_DOMAINS` (nötig für die internen Signale), `MAILROBBE_TIMEZONE` (Standard Europe/Berlin) und `MAILROBBE_PRIVATE_DOMAINS` als Ergänzung der Anbieterliste; Liste, Nachtstunden, Schwelle und Weiterleitungspräfixe stehen in `themes.toml` unter `[signals]`. Änderungen gelten ab dem nächsten „Import starten“. Ins Export-ZIP kommen Signale nur zusammen mit den Recherchedaten, weil die Wortfelder die Themen der Recherche verraten.
- **Akten** (`/akten`): die Rechercheakte des Teams. Jede Mail bekommt einen Prüfstatus (ungesichtet, gesichtet, relevant, nicht relevant), eine Markierung, beliebig viele Notizen und Schlagworte und lässt sich Akten zuordnen, einzeln im Mail-Detail oder in der Mailliste für ausgewählte Mails und alle Treffer eines Filters. Reiter für Akten, Themen, gespeicherte Suchen, Schlagworte, Notizen und Exporte. Die Themen zeigen Wortfelder zu Verfassungsfeindlichkeit, Rassismus, Extremismus, Gewalt, Spendenaffären und Verschleierung mit 18 Suchvorlagen (`src/mailrobbe/themes.toml`). Der Name, unter dem Notizen und Änderungen gespeichert werden, steht oben rechts. Permalinks (`/m/<Anfang des SHA-256>`) öffnen eine Mail über ihren Inhalt und gelten auch nach einem Neuimport.
- **Export**: bis zu 2.000 Mails (Auswahl, Filter oder Akte) als ZIP, je Mail die Originalmail als EML und ein PDF, dazu ein Manifest (JSON und CSV), `SHA256SUMS` zum Nachprüfen mit `sha256sum -c` und eine `LIESMICH.txt`. Notizen, Schlagworte, Status und Benennungen gehen nur auf Wunsch mit.
- **Zugriffsschutz**: ohne Login, solange nichts eingestellt ist. `MAILROBBE_BASIC_AUTH_USER` und `MAILROBBE_BASIC_AUTH_PASSWORD` in der `.env` schalten HTTP Basic Auth ein (offen bleiben nur `/api/health` für den Container-Healthcheck und die Programmdateien des PDF-Betrachters unter `/viewer/`, die keine Daten enthalten).
- **Intern/extern**: Mit `MAILROBBE_INTERNAL_DOMAINS=firma.de,firma.ch` erscheint der Filter „Nur extern ↔ intern“ (Mails, bei denen eine Seite intern und die andere extern ist; Subdomains zählen als intern).
- **Beziehungskarte** (`/karte`): wer mit wem wie oft geschrieben hat, als Ausschnitt um eine oder mehrere Personen (bis Tiefe 3), als die aktivsten Personen des Archivs oder zwischen zwei Domains. Mindestanzahl Mails je Verbindung, Zeitraum in ganzen Jahren, nur DKIM-gültige Mails, Cc mitzählen, Verteiler und Automaten ausblenden; Knoten lassen sich aufklappen und ausblenden, ein Klick auf eine Verbindung öffnet die Mails zwischen beiden. Vier Layouts, Einfärben nach Domain, Pfeile in Senderichtung, Zeitverlauf Jahr für Jahr, Export als PNG, SVG und GraphML. Mehr als 2.000 Personen zeichnet die Karte nicht; die Vorschau neben der Schwelle sagt vorher, wie groß der Ausschnitt wird. Auch dieser Zustand steht in der Adresszeile.
- **Zeitachse** (`/zeitachse`): das Mailaufkommen der aktuellen Suche und Filter der Mailliste über die Zeit, je Tag, Woche oder Monat (automatisch nach Zeitraum gewählt), insgesamt und auf Wunsch je Person (die sechs häufigsten oder selbst gewählte), je Thread oder je Suchbegriff (bis zu sechs, in der Suchsyntax der Mailliste). Markiert sind Abschnitte mit mindestens dreimal so vielen Mails wie im gleitenden Mittel davor (▲) oder höchstens einem Drittel davon (▽) und Reihen, die bis zum Ende des Archivs verstummen; die Regeln stehen unter dem Diagramm. „Wer taucht wann zuerst auf“ listet je Person die früheste Mail unter den Treffern, mit ihrer Rolle. Ein Klick auf einen Balken öffnet die Mailliste mit genau diesem Zeitraum und Filter. Über der Mailliste und im Personenprofil steht dieselbe Zeitachse als kleines Histogramm; ein Klick grenzt den Zeitraum ein. Die Zeitachse zählt bei jedem Aufruf direkt in der Datenbank und braucht keinen Neuimport. Der Filter `thread=<id>` zeigt alle Mails eines Threads (Link in der Thread-Karte des Mail-Details).
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
- [docs/logo/](docs/logo/): Logo als Wortmarke für dunkle Flächen, einfarbig und als PNG (Bildmarke, Wortmarke und Favicon liegen in `frontend/public/`)
- [CLAUDE.md](CLAUDE.md): Entwicklungshinweise (Befehle, Konventionen, Tests)

## Stand

Meilenstein 1 (Gerüst, Datenbankschema, Testdaten-Generator), Meilenstein 2 (Importer mit Fortsetzen, Duplikaten und Threads), Meilenstein 3 (DKIM-Prüfung mit DNS-Cache und Nachprüf-Befehl), Meilenstein 4 (API, Mailliste und Mail-Detail), Meilenstein 5 (Personen, Personenprofil, Alias-Vorschläge und Zusammenführen), Meilenstein 6 (Beziehungskarte mit GraphML-Export), Meilenstein 7 (Import-Dashboard und Lasttest mit 400.000 Mails), Meilenstein 8 (Rechercheakte), Meilenstein 9 (Anhänge mit Volltext, Dokumentliste und Dokumentseite), Meilenstein 10 (Entitäten als Facetten und eigene Seiten), Meilenstein 11 (Zeitachse mit Ausreißern, Verstummen und erster Erwähnung je Person) Meilenstein 12 (Signale mit Übersicht, Facetten und Grund je Mail), Meilenstein 13 (Themen je Zeitraum, je Auswahl und als Wortgruppen) und Meilenstein 14 (eingeklappte Zitate, nahezu gleiche Mails, Kalendereinladungen, benannte Adressen) sind fertig. Nach dem ersten kompletten Lauf mit dem echten Archiv kamen dazu: Alias-Vorschläge in Stufen mit Sammel-Zusammenführung und Rückgängig, lesbare Größen auf der Karte, die Großansicht für Bilder, die schmale Leiste und die Anhänge in der Seitenleiste des Mail-Details, die einklappbare Recherche-Karte und die Metadaten aus Anhängen. Den Lasttest aus [docs/LOADTEST.md](docs/LOADTEST.md) gibt es für die Auswertung der Anhänge und die Entitäten noch nicht.

---

## Häufige Fragen

### Verändert Mailrobbe meine Mails?

Nein. Die MBOX-Dateien sind schreibgeschützt eingebunden, die Datenbank hält nur Metadaten, Byte-Offsets, den Volltextindex und Aggregationen. Was die Oberfläche zeigt oder herunterlädt, liest Mailrobbe bei jedem Abruf aus der Datei und prüft es gegen den SHA-256 vom Import.

### Geht dabei etwas ins Internet?

Die Oberfläche lädt nichts von außen, HTML-Mails laufen in einem abgeschotteten Rahmen ohne Skripte und ohne Nachladen. Im Betrieb fragt Mailrobbe nur die DKIM-Schlüssel im DNS ab; mit `MAILROBBE_DKIM_OFFLINE=1` nutzt es ausschließlich den Cache und fragt niemanden. Der Link „auf OpenStreetMap ansehen“ bei einer Ortsangabe in den Metadaten eines Fotos führt nur nach außen, wenn man ihn anklickt.

### Was heißt „DKIM gültig“, und was heißt „Schlüssel fehlt“?

Gültig heißt: Die Signatur passt kryptografisch zum Schlüssel der Domain, die Mail wurde also mit diesem Schlüssel unterschrieben, und die unterschriebenen Teile sind seither unverändert. Wer sie geschrieben hat, beweist das nicht. „Schlüssel fehlt“ heißt nur, dass der Schlüssel heute nicht mehr im DNS steht, was bei älteren Mails häufig vorkommt; über eine Fälschung sagt das nichts.

### Können mehrere Leute gleichzeitig arbeiten?

Ja, alle auf demselben Server sehen dieselbe Rechercheakte. Konten gibt es nicht: Jeder Browser trägt einmal einen Namen ein, mit dem Notizen und Änderungen gespeichert werden. Das ist eine Zuordnung, kein Zugriffsschutz; den liefert bei Bedarf Basic Auth (`MAILROBBE_BASIC_AUTH_USER`, `MAILROBBE_BASIC_AUTH_PASSWORD`).

### Wo liegen Notizen, Schlagworte und Akten?

In der PostgreSQL-Datenbank im Docker-Volume `mailrobbe_pgdata`, nicht in den MBOX-Dateien. Wer die Rechercheakte behalten will, sichert dieses Volume oder die Datenbank mit `pg_dump`.

---

<div align="center">

**Mailrobbe ist von admon, für Recherchen in großen Mailarchiven.**

</div>
