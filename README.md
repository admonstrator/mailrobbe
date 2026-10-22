<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./docs/logo/logo-wordmark-dark.svg">
  <img src="./frontend/public/logo-wordmark.svg" alt="Mailrobbe" width="480">
</picture>

<h1>Mailrobbe</h1>

**Mail-Leaks und große Mailarchive recherchieren: durchsuchen, prüfen, belegen.**

[![GitHub Sponsors](https://img.shields.io/badge/GitHub-Sponsors-EA4AAA?style=for-the-badge&logo=github)](https://github.com/sponsors/admonstrator) [![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/admon) [![PayPal](https://img.shields.io/badge/PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/aaronviehl) [![Ko-fi](https://img.shields.io/badge/Ko--fi-FF5E5B?style=for-the-badge&logo=ko-fi&logoColor=white)](https://ko-fi.com/admon)

Hinter Mailrobbe steht kein Konzern, sondern admon, viel Hartnäckigkeit und eine bedenkliche Menge Energydrinks.<br>
Wenn es dir eine Recherche leichter gemacht hat, freut sich die Weiterentwicklung über deine Unterstützung.

Wünsche, Lob und Kritik gern per Mail an [hey@admon.me](mailto:hey@admon.me), auf Wunsch verschlüsselt mit [diesem PGP-Schlüssel](https://github.com/admonstrator/Admonstrator/blob/main/pgp/hey@admon.me.asc).<br>
<sub>Fingerabdruck `C2D7 EB96 8E27 4D5F 1B24  1B04 95E1 6BDE A94F 50A4`</sub>

[Website](https://mailrobbe.admon.me/) | [Für wen](#für-wen) | [Auf einen Blick](#auf-einen-blick) | [Was Mailrobbe kann](#was-mailrobbe-kann) | [Schnellstart](#schnellstart) | [Häufige Fragen](#häufige-fragen)

</div>

---

Mailrobbe ist ein Recherchewerkzeug für Journalistinnen und Journalisten, Redaktionen und Rechercheteams. Es ist für Mailbestände gebaut, die niemand von vorn bis hinten lesen kann: ein Leak, der Postfach-Export einer Quelle, Hunderttausende Mails in MBOX-Dateien. Mailrobbe macht sie durchsuchbar, auch in den Anhängen, prüft per DKIM, welche Mails nachweislich unverändert sind, zeigt, wer mit wem wann worüber geschrieben hat, und öffnet verschlüsselte Anhänge, wenn das Kennwort irgendwo im Archiv steht.

Das Material bleibt im Haus: Mailrobbe läuft auf dem eigenen Rechner im Browser, ohne Cloud und ohne Konto, und die Mails bleiben unverändert in ihren Dateien. Jede Fundstelle führt zurück zur Originalmail. Und bewertet wird nichts: Mailrobbe zeigt, wo sich das Lesen lohnen kann. Lesen, prüfen und entscheiden muss die Redaktion.

![Die Mailliste mit Suche, Filtern, Kennzahlen, Signalen und Entitäten](site/img/mailliste.webp)

<sub>Alle Bilder hier und auf der [Website](https://mailrobbe.admon.me/) zeigen ein erfundenes Testarchiv, keine echten Mails.</sub>

---

## Für wen

Für Recherchen, bei denen ein großer Mailbestand im Kern der Geschichte steht:

- **Leaks und Postfach-Exporte**, zu groß zum Durchlesen, oft mit Anhängen, gepackten Archiven und Kennwörtern.
- **Veröffentlichen mit Beleg.** Bevor eine Mail zitiert wird, zeigt DKIM, ob sie unverändert ist. Der Export liefert Originalmails, PDFs und Prüfsummen für Justiziariat und Anwälte.
- **Personen und Netzwerke:** wer mit wem, wer wusste was wann, wer hinter welcher Adresse steckt.
- **Teams**, die gemeinsam sichten, markieren und Funde sammeln, ohne Material in eine Cloud zu laden.

Fürs eigene Postfach ist das zu viel Werkzeug. Dafür reicht das Mailprogramm.

---

## Auf einen Blick

| Frage | Wo in Mailrobbe |
| --- | --- |
| Wo steht ein Begriff, auch in PDFs, Tabellen und ZIP-Dateien? | Suchfeld oben, das Suchmenü daneben grenzt ein |
| Ist diese Mail echt und unverändert? | DKIM-Siegel und DKIM-Prüfung im Mail-Detail, Filter nach DKIM-Status |
| Wer hat mit wem wie oft geschrieben? | Karte, Top-Kontakte im Personenprofil |
| Wer steckt hinter mehreren Adressen? | Alias-Vorschläge unter Personen |
| Wer wusste was wann? | Zeitachse: Verlauf, Ausreißer, Verstummen, erste Erwähnung |
| Worüber wurde wann auffällig viel geschrieben? | Themen |
| Welche Mails lese ich zuerst? | Signale, Recherchethemen unter Akten |
| Wie werde ich Newsletter und Systemmails los? | Ausgeblendet |
| Was steht in einem verschlüsselten Anhang? | Anhänge, Filter „Verschlüsselt“ |
| Welche Beträge, Konten und Namen tauchen auf? | Entitäten, Facetten neben der Mailliste |
| Wo wurden Fotos gemacht, welche Orte fallen? | Orte |
| Wie halte ich Funde im Team fest? | Prüfstatus, Notizen, Schlagworte und Akten an jeder Mail |
| Wie gehen Belege ans Justiziariat oder an Anwälte? | Export als ZIP mit Originalmails, PDFs und Prüfsummen |
| Wie zeige ich eine Mail im Artikel oder in sozialen Medien? | Mail-Detail, Aktionen: „Als Bild für Soziale Medien“, mit Schwärzungen |

---

## Was Mailrobbe kann

### Suchen, auch in Anhängen

Ein Suchfeld für Betreff, Mailtext, den Text der Anhänge und Dateinamen, auch in ZIP-Archiven. Gebeugte Formen findet die Suche mit, „Spende“ also auch bei „Spenden“. Jede Zeile der Mailliste sagt, wo und wie oft die Suchwörter stehen. Das Suchmenü grenzt ein: nur im Betreff, nur das ganze Wort, mindestens fünf Treffer, ohne Signaturen und Zitate, nur was der Absender selbst geschrieben hat. Wie genau, steht unter [Suchen](#suchen).

![Das Suchmenü](site/img/suchmenue.webp)

### Lesen ohne Ballast

Eine Mail sieht aus wie im Mailprogramm: Kopf, Text, Anhänge darunter. DKIM-Prüfung und technische Angaben bleiben eingeklappt, bis man sie braucht, und jeder Block merkt sich, ob er offen war. Zitierter Verlauf, Weiterleitungen und Signaturen sind eingeklappt, die Fundstellen markiert, auch im eingeklappten Teil. Die Pfeiltasten blättern durch die Treffer. Text, HTML, Kopfzeilen und Rohmail liest Mailrobbe bei jedem Öffnen frisch aus der Originaldatei; HTML-Mails laufen abgeschottet, ohne Skripte und ohne Nachladen von außen. Kalendereinladungen erscheinen als Termin mit den Antworten der Eingeladenen.

### Newsletter und Signaturen loswerden

Ausblendregeln nehmen Newsletter, Verteiler und Systemmails aus Liste und Suche, nach Absender, Domain, Verteiler oder Betreff. Mailrobbe schlägt die größten Verteiler vor und zeigt jede Regel vorher an. Eine Mail mit Notiz oder Status „relevant“ bleibt immer sichtbar. Rechtshinweise und Signaturen, die unter vielen Mails stehen, erkennt Mailrobbe als Standardblöcke und lässt sie bei der Suche weg. Fast gleiche Rundschreiben fasst die Mailliste auf Wunsch zu einer Zeile zusammen.

### Echtheit prüfen statt vermuten

Bevor eine Mail zitiert wird, will man wissen, ob sie so verschickt wurde. Jede DKIM-Signatur wird einzeln geprüft und mit Grund gespeichert; das Siegel oben in der Mail zeigt das Ergebnis, ein Klick darauf die Prüfung mit Domain, Selektor und Schlüssel. Gültig heißt: Die Mail wurde mit dem Schlüssel der Domain unterschrieben und ist seither unverändert. Bei älteren Mails steht der Schlüssel oft nicht mehr im DNS. Dann sucht Mailrobbe unter Import, „Gelöschte Selektoren“, auf Knopfdruck weiter: im Archiv selbst, in einem öffentlichen Schlüsselarchiv und rechnerisch aus zwei Signaturen. Jede Signatur sagt, woher ihr Schlüssel stammt.

![Mail-Detail mit aufgeklappter DKIM-Prüfung, Anhängen, Prüfstatus, Schlagwort und Notiz](site/img/mail.webp)

### Personen statt Adressen

Aus Absendern und Empfängern werden Personen mit Kontakten, Aktivität je Jahr und den Begriffen, die sie auffällig oft schreiben. Mailrobbe schlägt Adressen vor, die vermutlich derselben Person gehören, führt aber nie von selbst zusammen, und jede Zusammenführung lässt sich rückgängig machen. Wer weiß, wer hinter einer Adresse steckt, gibt ihr einen Klarnamen; der steht dann überall, auch auf der Karte.

### Wer mit wem, wann und worüber

Die Karte zeigt, wer mit wem wie oft geschrieben hat: um eine Person herum, für die aktivsten des Archivs oder zwischen zwei Domains, auf Wunsch Jahr für Jahr. Ein Klick auf eine Verbindung öffnet die Mails dazwischen, für Gephi gibt es GraphML.

Die Zeitachse zeigt jede Suche über die Zeit, auf Wunsch je Person, markiert Ausreißer und Personen, die plötzlich verstummen, und listet, wer einen Begriff wann zuerst geschrieben hat. „Themen“ nennt die Wörter, die in einem Monat, bei einer Person oder in einer Suche deutlich häufiger vorkommen als sonst, mit den Zahlen dazu.

![Beziehungskarte der aktivsten Personen](site/img/karte.webp)

### Wo das Lesen anfangen kann

„Signale“ zeigen nach einfachen, nachlesbaren Regeln auf Mails, die sich zu lesen lohnen können: private Adressen, Blindkopien, Weiterleitungen nach außen, Mails mitten in der Nacht, Begriffe aus den Recherchethemen, verschlüsselte Anhänge. Jede Mail sagt, warum. Signale beweisen nichts, viele haben harmlose Gründe.

„Entitäten“ listet Beträge, IBANs, Organisationen, Personen, Orte, Telefonnummern und Links aus Mails und Anhängen; ein Klick grenzt die Suche ein. Unter „Akten“ stehen sechs Recherchethemen mit Wortfeldern und 18 fertigen Suchen als Einstieg.

### Anhänge

Jedes Dokument steht einmal in der Liste, auch wenn es durch viele Mails gewandert ist, mit der Antwort, wer es wann an wen geschickt hat. PDFs, Word-Dateien, Bilder, Audio und Video zeigt Mailrobbe direkt im Browser. Die Dokumentseite verrät, was die Datei über sich selbst sagt: Kamera, Aufnahmezeit und GPS eines Fotos, Autor und Programm eines PDFs, Kommentare und Änderungen in Word.

### Verschlüsselte Anhänge öffnen

Wer eine Datei mit Kennwort verschickt, schreibt das Kennwort oft dazu, in dieselbe Mail oder ein paar Tage später. Mailrobbe sucht solche Kennwörter im Archiv und probiert sie an verschlüsselten PDFs, Office-Dateien, ZIP- und 7z-Archiven, das Naheliegende zuerst. Geraten wird nicht. Die geöffnete Datei wird durchsuchbar, ihre Seite zeigt das Kennwort mit der Mail, in der es stand. Ein bekanntes Kennwort lässt sich auch von Hand eingeben.

![Ein verschlüsseltes PDF, geöffnet mit einem Kennwort aus einem anderen Anhang](site/img/kennwort.webp)

### Orte

Fotos nach ihren GPS-Daten, Orte, die Mails und Anhänge nennen, und die Orte von Terminen liegen auf einer eingebauten Karte, die kein Internet braucht. Eine Detailkarte mit Straßen lädt Mailrobbe auf Knopfdruck einmal herunter.

### Im Team festhalten und weitergeben

Prüfstatus, Markierung, Notizen, Schlagworte, Akten und gespeicherte Suchen hängen an der Mail und sind für alle sichtbar, die mit demselben Mailrobbe arbeiten. Der Export packt bis zu 2.000 Mails in ein ZIP für Justiziariat und Anwälte: Originalmails, PDFs, Manifest und Prüfsummen. Und „Als Bild für Soziale Medien“ unter den Aktionen einer Mail macht aus ihr ein PNG für Artikel und soziale Medien im Look eines Mailprogramms, mit geschwärzten Beteiligten, Adressen, Telefonnummern und Namen. Geschwärzt wird im Text, bevor gezeichnet wird: Unter einem Balken steht nichts mehr.

Mehr Bilder gibt es auf der [Website](https://mailrobbe.admon.me/).

---

## Bevor es losgeht

**Die Mails sind heilig. Die Rechercheakte auch.**

Mailrobbe bindet den Ordner mit den MBOX-Dateien nur lesend ein und ändert keine einzige Mail. Was das Team erarbeitet, also Notizen, Schlagworte, Akten und Zusammenführungen, liegt dagegen in der Datenbank im Docker-Volume `mailrobbe_pgdata`.

> Sichere dieses Volume, bevor du größere Dinge tust, und benutze nie `docker compose down -v`. Das löscht die Datenbank samt Rechercheakte, ohne Rückfrage und ohne Mitleid.

---

## Schnellstart

Nötig sind Docker und git: Docker Desktop unter macOS oder Windows, Docker Engine unter Linux. Ausgelegt ist Mailrobbe für einen Rechner mit etwa 10 GB Arbeitsspeicher für Datenbank und Import zusammen. So viel muss Docker auch bekommen: unter macOS in Docker Desktop unter Settings, Resources; unter Windows regelt das WSL, das sich standardmäßig die Hälfte des Arbeitsspeichers nimmt.

```sh
git clone https://github.com/admonstrator/mailrobbe.git
cd mailrobbe
echo "MAILROBBE_MBOX_HOST_DIR=/Volumes/Archiv/mbox" > .env   # Ordner mit den MBOX-Dateien
docker compose up -d --build
```

**Windows:** Die Befehle laufen in einem WSL-Terminal, etwa im Ubuntu, das `wsl --install` einrichtet. In Docker Desktop unter Settings, Resources, WSL Integration muss diese Distribution eingeschaltet sein. Ein Archiv auf Laufwerk D: heißt dort `/mnt/d/Archiv/mbox`. Schneller liest der Import, wenn die MBOX-Dateien im Dateisystem von WSL selbst liegen, etwa unter `~/mbox`.

Dann geht es so weiter:

1. **Einlesen.** http://127.0.0.1:8000/import öffnen und „Import starten“ klicken. Das Dashboard zeigt Fortschritt und Restzeit. „Pausieren“ hält an, der nächste Start macht dort weiter. MBOX-Dateien erkennt Mailrobbe am Inhalt, auch in Unterordnern.
2. **Aufräumen.** Unter „Ausgeblendet“ Newsletter und Systemmails per Regel aus Liste und Suche nehmen, unter „Personen“ die sicheren Alias-Vorschläge zusammenführen.
3. **Einsteigen.** Unter „Akten“, Reiter „Themen“, stehen Wortfelder und fertige Suchen. „Signale“, „Themen“ und „Entitäten“ bieten weitere Einstiege.
4. **Festhalten.** Oben rechts den eigenen Namen eintragen, dann Prüfstatus, Notizen, Schlagworte und Akten vergeben, einzeln oder für alle Treffer einer Suche.

### Aktualisieren

```sh
git pull
docker compose down
docker compose up -d --build
```

Danach unter http://127.0.0.1:8000/import „Import starten“ klicken. Neue Funktionen holen dabei nach, was sie brauchen. Die Mails werden nicht neu eingelesen, Notizen, Akten und Zusammenführungen bleiben.

### Einstellungen

Einstellungen stehen in der Datei `.env` neben `docker-compose.yml`, eine Zeile je Wert. Sie wirken nach `docker compose up -d`, was die Auswertung betrifft nach dem nächsten „Import starten“.

| Wert | Wofür |
| --- | --- |
| `MAILROBBE_MBOX_HOST_DIR` | Ordner mit den MBOX-Dateien (Voreinstellung `./data/mbox`) |
| `MAILROBBE_INTERNAL_DOMAINS` | die Domains der Organisation, kommagetrennt (`firma.de,firma.ch`); nötig für den Filter „Nur extern ↔ intern“ und die Signale zwischen intern und privat |
| `MAILROBBE_BASIC_AUTH_USER`, `MAILROBBE_BASIC_AUTH_PASSWORD` | Benutzername und Kennwort für die Oberfläche; ohne beide ist sie offen |
| `MAILROBBE_TIMEZONE` | Zeitzone für Nacht und Wochenende (Voreinstellung `Europe/Berlin`) |
| `MAILROBBE_PRIVATE_DOMAINS` | weitere Domains privater Mailanbieter, zusätzlich zur eingebauten Liste |
| `MAILROBBE_BLOCK_MIN_MAILS` | ab wie vielen Mails ein Absatz am Ende als Standardblock gilt (Voreinstellung 25) |
| `MAILROBBE_IMPORT_WORKERS` | Prozesse für den Import (Voreinstellung: Zahl der Kerne, höchstens 8) |
| `MAILROBBE_DKIM_NAMESERVERS` | eigene DNS-Server für die DKIM-Schlüssel, kommagetrennt |
| `MAILROBBE_MAP_HOST_DIR` | Ordner für die Detailkarte (bis 10 GB) außerhalb von Docker, etwa `./data/maps` |
| `MAILROBBE_MAP_SOURCE` | `off` nimmt das Angebot der Detailkarte ganz weg |
| `MAILROBBE_PORT` | Port der Oberfläche (Voreinstellung 8000) |

Die Recherchethemen mit ihren Wortfeldern und Suchen und die Regeln der Signale stehen in [`src/mailrobbe/themes.toml`](src/mailrobbe/themes.toml); nach einer Änderung `docker compose up -d --build` und „Import starten“. Alle übrigen Einstellungen stehen in [`src/mailrobbe/config.py`](src/mailrobbe/config.py).

---

## Suchen

| Eingabe | findet |
| --- | --- |
| `Spende` | das Wort und seine Formen („Spenden“, „spenden“) in Betreff, Text und Anhängen |
| `Spende Quittung` | Mails mit beiden Wörtern |
| `Rat or Räte` | Mails mit einem der beiden |
| `"genaue Phrase"` | die Wörter in dieser Folge |
| `"Spende bar"~5` | beide Wörter, höchstens fünf Wörter dazwischen |
| `-Entwurf` | nur Mails ohne dieses Wort; das Minus geht auch vor jedem Operator (`-from:anna`) |
| `betreff:` `text:` `anhang:` `datei:` | ein Wort nur im Betreff, im Mailtext, im Text der Anhänge oder in Dateinamen |
| `from:anna@` `to:@beispiel.de` `cc:keller` | Absender, Empfänger, Kopie; auch Teile der Adresse und vergebene Klarnamen |
| `domain:beispiel.de` | Mails, an denen diese Domain beteiligt ist |
| `subject:Vertrag` | Teil des Betreffs, auch mitten im Wort |
| `has:attachment` | nur Mails mit Anhang |
| `after:2024-01-01` `before:2025-01-01` | Zeitraum, auch als `01.01.2024` |
| `dkim:pass` `dkim:fail` | nach DKIM-Ergebnis, außerdem `consistent`, `no_key`, `unsigned`, `temp_error`, `unchecked` |
| `<message-id@host>` | genau diese Mail |

Das Suchmenü (Knopf mit den Schiebereglern am Suchfeld) stellt ein, wie gesucht wird:

- **Suchen in**: Betreff, Mailtext, Anhangstext, Dateiname.
- **Ganzes Wort**: nur genau so geschrieben, ohne Wortstamm und Teilwörter. „Rat“ findet dann weder „Raten“ noch „Räte“; Beugungen nennt man selbst: `Rat or Räte`.
- **Mindestens n Treffer**: die Suchwörter müssen so oft in Mail und Anhängen stehen.
- **Mailtext durchsuchen**: „Ohne Standardblöcke“ (Voreinstellung), „Nur selbst Geschriebenes“ (auch ohne Zitate und Weiterleitungen) oder „Alles“.
- **Ausschließen** setzt Minus-Wörter, **Ausgeblendete einbeziehen** zeigt auch die Mails der Ausblendregeln.
- Dazu die **gespeicherten Suchen** und eine Kurzfassung der Syntax.

Suche und Filter stehen in der Adresszeile. Ein Link lässt sich also aufheben und im Team teilen.

---

## Für Technik und Entwicklung

Alles aus dem Dashboard geht auch auf der Kommandozeile, jeweils mit `--help`:

```sh
docker compose run --rm backend mailrobbe import        # Import; Ctrl-C pausiert, der nächste Aufruf setzt fort
docker compose run --rm backend mailrobbe dkim          # DKIM nachprüfen, etwa wenn ein Schlüssel wieder erreichbar ist
docker compose run --rm backend mailrobbe dkim-keys     # Schlüssel gelöschter Selektoren suchen, rekonstruieren, prüfen
docker compose run --rm -T backend mailrobbe graph export - > mailrobbe.graphml   # ganzes Netz für Gephi
docker compose exec backend mailrobbe map download --region de --detail streets   # Detailkarte laden
```

Testdaten ohne echte Mails schreibt der Generator: `docker compose run --rm generator --mails 10000` legt synthetische MBOX-Dateien mit DKIM-Signaturen, Anhängen, Kennwörtern und absichtlichen Störfällen in `data/mbox/`. Daraus stammen auch alle Bilder dieser Seite.

- [docs/SPEC.md](docs/SPEC.md): Spezifikation mit Architektur, Datenmodell, API und Meilensteinen
- [docs/DECISIONS.md](docs/DECISIONS.md): alle Entscheidungen seit der Spezifikation, mit Grenzen und Begründungen
- [docs/DKIM-RECOVERY.md](docs/DKIM-RECOVERY.md): wie Mailrobbe Schlüssel gelöschter Selektoren wiederfindet
- [docs/LOADTEST.md](docs/LOADTEST.md): Lasttest mit 400.000 Mails und Messwerte
- [CLAUDE.md](CLAUDE.md): Entwicklungshinweise mit Aufbau, Befehlen, Konventionen und Tests
- [site/](site/): die [Website](https://mailrobbe.admon.me/), bei jeder Änderung auf `main` neu veröffentlicht

---

## Häufige Fragen

### „Verändert Mailrobbe meine Mails?“

Nein. Die MBOX-Dateien sind schreibgeschützt eingebunden, die Datenbank hält nur Metadaten, Fundstellen, den Suchindex und Auswertungen. Was die Oberfläche zeigt oder herunterlädt, liest Mailrobbe bei jedem Abruf aus der Datei und prüft es gegen die Prüfsumme vom Import.

### „Geht dabei etwas ins Internet?“

Von selbst fragt Mailrobbe nur die DKIM-Schlüssel im DNS ab. Nur auf Knopfdruck fragt es das Schlüsselarchiv ZK Email und lädt die Detailkarte herunter. Inhalte aus dem Archiv verlassen den Rechner nicht. DNS-Server und Schlüsselarchiv erfahren aber, welche Domains und Selektoren gefragt werden, und bei einem Leak kann schon das verraten, wessen Mails da gerade geprüft werden. Wer das vermeiden will, importiert ohne DNS-Abfragen mit `docker compose run --rm -e MAILROBBE_DKIM_OFFLINE=1 backend mailrobbe import` und prüft später mit `docker compose run --rm backend mailrobbe dkim` nach, wann und über welche DNS-Server (`MAILROBBE_DKIM_NAMESERVERS`) es passt.

### „Beweist ‚DKIM gültig‘, wer die Mail geschrieben hat?“

Nein. Gültig heißt, dass die Mail mit dem Schlüssel der Domain unterschrieben wurde und die unterschriebenen Teile seither unverändert sind. „Signatur stimmig“ heißt, ein aus Signaturen errechneter Schlüssel bestätigt sie; die Mails stammen also aus derselben Quelle, ob die Domain diesen Schlüssel veröffentlicht hat, ist damit nicht gesagt. „Schlüssel nicht abrufbar“ heißt nur, dass der Schlüssel heute nicht mehr im DNS steht. Über eine Fälschung sagt das nichts.

### „Warum fehlt eine Mail in der Liste?“

Vermutlich trifft sie eine Ausblendregel. Über der Mailliste steht dann „ausgeblendet · zeigen“, im Suchmenü holt „Ausgeblendete einbeziehen“ sie zurück, und das Mail-Detail nennt die Regel.

### „Was passiert mit gefundenen Kennwörtern?“

Sie stehen im Klartext auf der Dokumentseite, mit der Mail, in der sie standen, denn sie sind selbst ein Beleg. Entschlüsselte Dateien speichert Mailrobbe nie; Vorschau und Download entschlüsseln bei jedem Abruf neu. In einen Export kommen Kennwörter nur, wenn man es dort ankreuzt.

### „Läuft das auch unter Windows?“

Ja, mit Docker Desktop und WSL 2, wie unter macOS und Linux. Wie es geht, steht unter [Schnellstart](#schnellstart).

### „Können mehrere Leute gleichzeitig damit arbeiten?“

Ja. Alle, die denselben Mailrobbe im Browser öffnen, sehen dieselbe Rechercheakte. Konten gibt es nicht, jeder Browser trägt einmal einen Namen ein. Das ist eine Zuordnung, kein Zugriffsschutz; den liefern bei Bedarf Benutzername und Kennwort aus den [Einstellungen](#einstellungen).

### „Ist das mit KI gebaut?“

**Kurz:** Ja.

**Lang:** Mailrobbe ist mit viel KI-Unterstützung entstanden, gelenkt von einem Menschen, der es selbst benutzt und wenig Lust hat, sich mitten in einer Recherche über kaputte Software zu ärgern. Jede Funktion wird geprüft, über 4.000 automatische Tests laufen bei jeder Änderung, und jede der über 200 Entscheidungen steht mit Begründung in [docs/DECISIONS.md](docs/DECISIONS.md). Kein Haufen Code in einer einzigen Datei, sondern ein Projekt, das man nachlesen kann.

### „Ich habe einen Fehler gefunden. Und jetzt?“

Ein [Issue](https://github.com/admonstrator/mailrobbe/issues) aufmachen, mit möglichst genauer Beschreibung und ohne echte Mails im Anhang. Wer den Fehler nur mit echtem Material zeigen kann, schreibt lieber verschlüsselt an [hey@admon.me](mailto:hey@admon.me) ([PGP-Schlüssel](https://github.com/admonstrator/Admonstrator/blob/main/pgp/hey@admon.me.asc)). Wer den Fehler gleich selbst behebt, schickt einen Pull Request. Willkommen ist jeder, vom Gelegenheitsbastler bis zu den Leuten, die beim Wort „Speicherverwaltung“ leuchtende Augen bekommen.

---

## Haftungsausschluss

Mailrobbe wird so bereitgestellt, wie es ist, ohne jede Gewähr. Benutzung auf eigene Verantwortung.

Es kann unter anderem:

- deinen Rechner eine Nacht lang beschäftigen und den Lüfter zum Abheben bringen,
- dir Mails zeigen, die du lieber nicht gelesen hättest (dafür ist es allerdings gebaut),
- dich in eine Recherche ziehen, aus der du erst Tage später wieder auftauchst.

Was es nicht kann: entscheiden, ob etwas wahr, wichtig oder strafbar ist. Das bleibt bei Menschen, am besten bei solchen mit Recherche-Erfahrung und einer guten Rechtsabteilung.

---

<div align="center">

**Mailrobbe ist von admon, für Recherchen in Mail-Leaks und großen Mailarchiven.**

Wenn es dir nützt, freut sich das Repository über einen Stern.

</div>
