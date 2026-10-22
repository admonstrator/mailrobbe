<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./docs/logo/logo-wordmark-dark.svg">
  <img src="./frontend/public/logo-wordmark.svg" alt="Mailrobbe" width="480">
</picture>

<h1>Mailrobbe</h1>

[![CI](https://img.shields.io/github/actions/workflow/status/admonstrator/mailrobbe/ci.yml?event=pull_request&style=for-the-badge&logo=githubactions&logoColor=white&label=CI)](https://github.com/admonstrator/mailrobbe/actions/workflows/ci.yml?query=event%3Apull_request) [![Python](https://img.shields.io/badge/Python-3.12-1D5BD6?style=for-the-badge&logo=python&logoColor=white)](pyproject.toml) [![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?style=for-the-badge&logo=postgresql&logoColor=white)](docker-compose.yml) [![React](https://img.shields.io/badge/React-TypeScript-0EA5E9?style=for-the-badge&logo=react&logoColor=white)](frontend/) [![Docker Compose](https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white)](#installieren)

[Auf einen Blick](#auf-einen-blick) | [Erste Schritte](#erste-schritte) | [Was Mailrobbe kann](#was-mailrobbe-kann) | [Suchen](#suchen) | [Installieren](#installieren) | [Häufige Fragen](#häufige-fragen)

</div>

---

Mailrobbe erschließt große Mailarchive für Recherchen. Es liest MBOX-Exporte ein (gebaut für rund 400.000 Mails), prüft bei jeder Mail die DKIM-Signatur, ordnet die Mails Personen zu und macht Mails und Anhänge durchsuchbar. Es zeigt, wer mit wem wann worüber geschrieben hat, öffnet verschlüsselte Anhänge, wenn das Kennwort irgendwo im Archiv steht, und legt Fotos und erwähnte Orte auf eine Karte.

Mailrobbe läuft auf dem eigenen Rechner im Browser, ohne Cloud und ohne Konto. Die Mails bleiben unverändert in ihren Dateien. Bewertet wird nichts: Mailrobbe zeigt, wo sich das Lesen lohnen kann, lesen und entscheiden muss das Team.

## Auf einen Blick

| Frage | Wo in Mailrobbe |
| --- | --- |
| Wer hat mit wem wie oft geschrieben? | Karte (`/karte`), Top-Kontakte im Personenprofil |
| Ist diese Mail echt? | DKIM-Siegel im Mail-Detail, Filter nach DKIM-Status; fehlende Schlüssel sucht Mailrobbe unter Import, „Gelöschte Selektoren“ |
| Wer steckt hinter mehreren Adressen? | Alias-Vorschläge unter Personen, jede Zusammenführung lässt sich rückgängig machen |
| Wer wusste was wann? | Zeitachse (`/zeitachse`): Verlauf, Ausreißer, Verstummen, erste Erwähnung je Person |
| Worüber wurde wann auffällig viel geschrieben? | Themen (`/themen`): Wörter, die in einem Monat, Quartal oder Jahr herausstechen |
| Welche Mails sollte ich zuerst lesen? | Signale (`/auffaelligkeiten`): private Adressen, Blindkopien, Weiterleitungen nach außen, Nacht, verschlüsselte Anhänge |
| Wo steht ein Begriff, auch in PDFs, Tabellen und ZIP-Dateien? | Suchfeld oben, das Suchmenü daneben grenzt ein |
| Wie werde ich Newsletter und Systemmails los? | Ausgeblendet (`/ausgeblendet`): Ausblendregeln mit Vorschau |
| Wie suche ich ohne Signaturen, Rechtshinweise und Zitate? | Suchmenü: „Ohne Standardblöcke“ (Voreinstellung) oder „Nur selbst Geschriebenes“ |
| Was steht in einem verschlüsselten Anhang? | Mailrobbe sucht das Kennwort im Archiv; die Dokumentseite zeigt es mit Fundstelle |
| Wer hat dieses Dokument wann an wen geschickt? | Anhänge (`/anhaenge`) und die Seite des Dokuments |
| Welche Beträge, Konten und Namen tauchen auf? | Entitäten (`/entitaeten`) und die Facetten neben der Mailliste |
| Wo wurden Fotos gemacht, welche Orte fallen? | Orte (`/orte`): Fotos nach GPS, Orte aus den Texten und Termine auf einer Karte |
| Womit fange ich an? | Recherchethemen unter Akten: Wortfelder und 18 fertige Suchen |
| Wie halte ich Funde im Team fest? | Akten (`/akten`): Prüfstatus, Notizen, Schlagworte, Akten, gespeicherte Suchen |
| Wie gebe ich Belege an Anwälte weiter? | Export als ZIP mit Originalmail, PDF je Mail und Prüfsummen |
| Wie zeige ich eine Mail öffentlich? | „Als Bild für Soziale Medien“ im Mail-Detail: ein PNG, Beteiligte und Kontaktdaten geschwärzt |

---

## Erste Schritte

1. **Einlesen.** Mailrobbe [installieren](#installieren), dann unter http://127.0.0.1:8000/import auf „Import starten“ klicken. Das Dashboard zeigt Fortschritt und Restzeit. „Pausieren“ hält an, der nächste Start macht dort weiter.
2. **Aufräumen.** Unter „Ausgeblendet“ Newsletter, Verteiler und Systemmails per Regel aus Liste und Suche nehmen; Mailrobbe schlägt die größten Verteiler und automatischen Absender vor. Unter „Personen“ die sicheren Alias-Vorschläge prüfen und zusammenführen.
3. **Einsteigen.** Unter „Akten“, Reiter „Themen“, stehen Wortfelder und fertige Suchen zu Verfassungsfeindlichkeit, Rassismus, Extremismus, Gewalt, Spendenaffären und Verschleierung. „Signale“, „Themen“ und „Entitäten“ bieten weitere Einstiege.
4. **Suchen.** Das Suchfeld oben durchsucht Mails und Anhänge, das Suchmenü daneben grenzt ein (siehe [Suchen](#suchen)). Filter und Facetten neben der Mailliste schränken nach Zeitraum, DKIM-Status, Domain, Anhang, Beträgen, Entitäten, Signalen und mehr ein.
5. **Lesen.** Im Mail-Detail sind Zitate und Signaturen eingeklappt und die Suchwörter markiert; die Pfeiltasten blättern durch die Treffer.
6. **Festhalten.** Jede Mail bekommt einen Prüfstatus, Notizen und Schlagworte und lässt sich Akten zuordnen, einzeln oder für alle Treffer einer Suche. Oben rechts steht der Name, unter dem das gespeichert wird.
7. **Weitergeben.** Ein Export-ZIP für Anwälte, ein geschwärztes Bild für soziale Medien oder ein Permalink fürs Team.

---

## Was Mailrobbe kann

### Suchen, auch in Anhängen

Die Suche findet Wörter in Betreff, Mailtext, im Text der Anhänge und in Dateinamen, auch gebeugte Formen („Spenden“ bei der Suche nach „Spende“). Jede Zeile der Mailliste sagt, wo und wie oft die Suchwörter stehen, im Mail-Detail sind die Fundstellen markiert, auch im eingeklappten Verlauf. Suche und Filter stehen in der Adresszeile, ein Link lässt sich also aufheben und teilen. Wie man genauer sucht, steht unter [Suchen](#suchen).

### Weniger Ballast

Ausblendregeln nehmen Newsletter, Rundmails und Systemmails aus Liste und Suche, nach Absender, Person, Domain, Verteiler, „automatisch versendet“ oder Betreff. Jede Regel zeigt vorher, welche Mails sie trifft, und gilt für das ganze Team. Eine Mail mit Notiz, Markierung, Akte oder Status „relevant“ bleibt immer sichtbar, und „Ausgeblendete einbeziehen“ im Suchmenü holt alles zurück.

Rechtshinweise, Disclaimer und Signaturen, die am Ende vieler Mails stehen, erkennt Mailrobbe als Standardblöcke und lässt sie bei der Suche weg. Im Mail-Detail sind sie grau und eingeklappt; jeder Absatz lässt sich dort als Standardblock markieren oder zurücknehmen. Nahezu gleiche Mails, etwa ein Rundschreiben, das einzeln an viele ging, fasst die Mailliste mit „Dubletten zusammenfassen“ zu einer Zeile zusammen.

### Mails lesen

Das Mail-Detail zeigt Text, HTML-Ansicht, alle Kopfzeilen und die Rohmail, jeweils frisch aus der Originaldatei gelesen. Zitate, Weiterleitungen und Signaturen beginnen eingeklappt, ein Suchwort darin klappt sie auf. Kalendereinladungen erscheinen als Termin mit Zeit, Ort, Organisator und den Antworten der Eingeladenen. HTML-Mails laufen abgeschottet, ohne Skripte und ohne Nachladen von außen.

### Echtheit prüfen

Jede DKIM-Signatur wird einzeln geprüft und mit Grund gespeichert. Gültig heißt: Die Mail wurde mit dem Schlüssel der Domain unterschrieben, und die unterschriebenen Teile sind seither unverändert. Bei älteren Mails steht der Schlüssel oft nicht mehr im DNS. Dann sucht Mailrobbe unter Import, „Gelöschte Selektoren“, auf Knopfdruck weiter: in den Mails und Anhängen des Archivs, in einem öffentlichen Schlüsselarchiv (ZK Email) und rechnerisch aus zwei Signaturen desselben Schlüssels. Jede Signatur sagt, woher ihr Schlüssel stammt. Ein nur errechneter Schlüssel ergibt „Signatur stimmig“, nicht „gültig“. Einen Schlüssel aus eigener Quelle kann man mit Beleg von Hand eintragen.

### Personen statt Adressen

Aus Absendern und Empfängern werden Personen mit Kennzahlen, Top-Kontakten und Aktivität je Jahr. Mailrobbe schlägt Adressen vor, die vermutlich zu derselben Person gehören, trennt sichere von unsicheren Vorschlägen und führt nie von selbst zusammen; jede Zusammenführung lässt sich rückgängig machen. Wer weiß, wer hinter einer Adresse steckt, gibt ihr mit „Benennen“ Klarname, Rolle und Notiz. Der Name steht dann überall, wo die Person auftaucht, auch auf der Karte, und die Suche findet sie darüber.

### Beziehungen und Zeit

Die Karte zeigt, wer mit wem wie oft geschrieben hat: um eine oder mehrere Personen, die aktivsten des Archivs oder zwischen zwei Domains, Jahr für Jahr. Ein Klick auf eine Verbindung öffnet die Mails dazwischen, für Gephi gibt es einen GraphML-Export.

Die Zeitachse zeigt das Mailaufkommen jeder Suche über die Zeit, markiert Ausreißer und Personen, die plötzlich verstummen, und listet, wer einen Begriff wann zuerst geschrieben oder bekommen hat. „Themen“ nennt die Wörter, die in einem Monat, Quartal oder Jahr deutlich häufiger vorkommen als im übrigen Archiv, dasselbe für jede Auswahl (eine Person, ein Zeitraum, eine Suche), und Gruppen von Wörtern, die oft gemeinsam vorkommen. Jede Zahl steht dabei, damit sich nachvollziehen lässt, warum ein Wort auftaucht.

### Anhänge

Jedes Dokument steht einmal in der Liste, auch wenn es durch viele Mails gewandert ist, mit der Antwort, wer es wann an wen geschickt hat. Text aus PDF, Word, Excel, PowerPoint, OpenDocument und vielen weiteren Formaten ist durchsuchbar. PDFs, Word-Dateien, Bilder, Audio und Video zeigt Mailrobbe direkt im Browser, abgeschottet und ohne Herunterladen.

Die Metadaten der Dateien stehen auf der Dokumentseite: Kamera, Aufnahmezeit und GPS eines Fotos, Autor, Programm und Bearbeitungsgeschichte eines PDFs, bei Word-Dateien auch Kommentare und Änderungen mit ihren Autoren. Autor und Programm sind Filter der Anhangsliste. Die Werte stehen da, wie die Datei sie angibt; sie können falsch oder gefälscht sein.

### Verschlüsselte und verpackte Anhänge

Wer eine Datei mit Kennwort verschickt, schreibt das Kennwort oft dazu: in dieselbe Mail, eine Antwort oder eine Mail ein paar Tage später. Mailrobbe sucht solche Kennwörter im Archiv und probiert sie an verschlüsselten PDFs, Office-Dateien, ZIP- und 7z-Archiven, das Naheliegende zuerst; Wortlisten und Raten gibt es nicht. Eine geöffnete Datei wird durchsuchbar, ihre Seite zeigt das Kennwort mit der Mail, in der es stand. Ein bekanntes Kennwort lässt sich auf der Dokumentseite eingeben, auf Wunsch für alle verschlüsselten Dateien. ZIP- und 7z-Archive und angehängte Mails packt Mailrobbe aus, ihr Inhalt wird durchsuchbar wie jeder andere Anhang. In der Anhangsliste filtert „Verschlüsselt“ nach Dateien, deren Kennwort noch fehlt.

### Orte

Die Seite „Orte“ legt auf eine Karte: Fotos nach ihren GPS-Daten, Orte, die Mails und Anhänge nennen, und die Orte von Kalendereinladungen. Ein Klick auf ein Foto zeigt Bild, Aufnahmezeit, Gerät, den nächsten Ort und die Mails dazu; von dort geht es zu Fotos in der Nähe und vom selben Gerät. Die Karte ist eingebaut und braucht kein Internet. Auf Knopfdruck lädt Mailrobbe einmal eine Detailkarte mit Straßen aus OpenStreetMap-Daten herunter (Deutschland, Österreich, Schweiz oder der aktuelle Ausschnitt), danach ist auch sie offline.

### Hinweise, wo das Lesen anfangen kann

„Entitäten“ listet, was in Mails und Anhängen vorkommt: Beträge, IBANs und Kontonummern, Organisationen, Personen, Orte, Telefonnummern, Adressen, Links, Daten und die Begriffe der Recherchethemen. Neben der Mailliste stehen die häufigsten für die aktuelle Suche, ein Klick grenzt die Treffer ein. Beträge, die neben „bar“, „Spende“ oder „Quittung“ stehen, lassen sich gezielt filtern.

„Signale“ zeigen nach einfachen, nachlesbaren Regeln auf Mails, die sich zu lesen lohnen können: eine private Adresse, Post von intern an privat, eine Blindkopie, viele Empfänger, eine Weiterleitung nach außen, Nacht und Wochenende, ein Begriff aus einem Recherchethema, ein verschlüsselter Anhang, ein Kennwort, das in einer anderen Mail kam. Jede Mail sagt, warum sie ein Signal trägt. Signale beweisen nichts, viele haben harmlose Gründe.

### Im Team festhalten

Die Rechercheakte hält Prüfstatus (ungesichtet, gesichtet, relevant, nicht relevant), Markierung, Notizen, Schlagworte, Akten und gespeicherte Suchen fest, für alle, die mit demselben Mailrobbe arbeiten. Sie hängt am Inhalt der Mail und übersteht deshalb auch ein erneutes Einlesen. Permalinks (`/m/…`) öffnen eine Mail über ihren Inhalt.

### Weitergeben

Der Export packt bis zu 2.000 Mails (Auswahl, Suche oder Akte) in ein ZIP: je Mail die Originalmail als EML und ein PDF, dazu ein Manifest und `SHA256SUMS` zum Nachprüfen. Notizen, Schlagworte und gefundene Kennwörter gehen nur auf Wunsch mit.

„Als Bild für Soziale Medien“ im Mail-Detail macht aus einer Mail ein PNG im Look eines Mailprogramms, als Hochformat, Quadrat oder Breitbild. Geschwärzt werden standardmäßig die Beteiligten und im Text Adressen, Telefonnummern, IBANs, Kontonummern und Personennamen, auf Wunsch auch Organisationen, Orte und eigene Begriffe. Geschwärzt wird im Text, bevor gezeichnet wird: Unter einem Balken steht nichts mehr. Vor dem Veröffentlichen das Bild trotzdem ansehen.

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

Das Suchmenü (Knopf mit den Schiebereglern am Suchfeld) stellt ein, wie die Wörter gesucht werden:

- **Suchen in**: Betreff, Mailtext, Anhangstext, Dateiname.
- **Ganzes Wort**: nur genau so geschrieben, ohne Wortstamm und Teilwörter. „Rat“ findet dann weder „Raten“ noch „Räte“; Beugungen nennt man selbst: `Rat or Räte`.
- **Mindestens n Treffer**: die Suchwörter müssen so oft in Mail und Anhängen stehen.
- **Mailtext durchsuchen**: „Ohne Standardblöcke“ (Voreinstellung), „Nur selbst Geschriebenes“ (auch ohne Zitate, Weiterleitungen und Vorgängermails) oder „Alles“.
- **Ausschließen** setzt Minus-Wörter, **Ausgeblendete einbeziehen** zeigt auch die Mails der Ausblendregeln.
- Dazu die **gespeicherten Suchen** und eine Kurzfassung der Syntax.

---

## Installieren

Nötig sind Docker (Docker Desktop unter macOS, Docker Engine unter Linux) und git. Ausgelegt ist Mailrobbe für einen Rechner mit etwa 10 GB Arbeitsspeicher für Datenbank und Import zusammen.

```sh
git clone https://github.com/admonstrator/mailrobbe.git
cd mailrobbe
echo "MAILROBBE_MBOX_HOST_DIR=/Volumes/Archiv/mbox" > .env   # Ordner mit den MBOX-Dateien
docker compose up -d --build
```

Danach http://127.0.0.1:8000/import öffnen und „Import starten“ klicken. Der Ordner wird nur lesend eingebunden; MBOX-Dateien erkennt Mailrobbe am Inhalt, auch in Unterordnern. Ohne `.env` liest es den Ordner `data/mbox` im Projekt.

## Aktualisieren

```sh
git pull
docker compose down
docker compose up -d --build
```

Danach unter http://127.0.0.1:8000/import „Import starten“ klicken (oder „Import fortsetzen“, falls ein Import pausiert ist). Neue Funktionen holen dabei nach, was sie brauchen; die Mails werden nicht neu eingelesen, Notizen, Akten und Zusammenführungen bleiben. Nie `docker compose down -v` benutzen: Das löscht die Datenbank samt Rechercheakte.

## Einstellungen

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

Die Recherchethemen mit ihren Wortfeldern und Suchen und die Regeln der Signale stehen in [`src/mailrobbe/themes.toml`](src/mailrobbe/themes.toml); nach einer Änderung `docker compose up -d --build` und „Import starten“. Alle übrigen Einstellungen mit ihren Voreinstellungen stehen in [`src/mailrobbe/config.py`](src/mailrobbe/config.py), die Speicherwerte der Datenbank in [`docker-compose.yml`](docker-compose.yml).

## Für Technik und Entwicklung

Alles aus dem Dashboard geht auch auf der Kommandozeile, jeweils mit `--help`:

```sh
docker compose run --rm backend mailrobbe import        # Import; Ctrl-C pausiert, der nächste Aufruf setzt fort
docker compose run --rm backend mailrobbe dkim          # DKIM nachprüfen, etwa wenn ein Schlüssel wieder erreichbar ist
docker compose run --rm backend mailrobbe dkim-keys     # Schlüssel gelöschter Selektoren suchen, rekonstruieren, prüfen
docker compose run --rm -T backend mailrobbe graph export - > mailrobbe.graphml   # ganzes Netz für Gephi
docker compose exec backend mailrobbe map download --region de --detail streets   # Detailkarte laden
```

Testdaten ohne echte Mails schreibt der Generator: `docker compose run --rm generator --mails 10000` (oder `uv run mailrobbe generate --mails 10000`) legt synthetische MBOX-Dateien mit DKIM-Signaturen, Anhängen, Kennwörtern und absichtlichen Störfällen in `data/mbox/`.

- [docs/SPEC.md](docs/SPEC.md): Spezifikation mit Architektur, Datenmodell, API und Meilensteinen
- [docs/DECISIONS.md](docs/DECISIONS.md): alle Entscheidungen seit der Spezifikation, mit Grenzen und Begründungen
- [docs/DKIM-RECOVERY.md](docs/DKIM-RECOVERY.md): wie Mailrobbe Schlüssel gelöschter Selektoren wiederfindet
- [docs/LOADTEST.md](docs/LOADTEST.md): Lasttest mit 400.000 Mails und Messwerte
- [docs/mockup/](docs/mockup/): erster klickbarer UI-Prototyp
- [docs/logo/](docs/logo/): Logo in weiteren Fassungen (Bildmarke, Wortmarke und Favicon liegen in `frontend/public/`)
- [CLAUDE.md](CLAUDE.md): Entwicklungshinweise mit Aufbau, Befehlen, Konventionen und Tests

---

## Häufige Fragen

### Verändert Mailrobbe meine Mails?

Nein. Die MBOX-Dateien sind schreibgeschützt eingebunden, die Datenbank hält nur Metadaten, Fundstellen in den Dateien, den Suchindex und Auswertungen. Was die Oberfläche zeigt oder herunterlädt, liest Mailrobbe bei jedem Abruf aus der Datei und prüft es gegen die Prüfsumme (SHA-256) vom Import.

### Geht dabei etwas ins Internet?

Die Oberfläche lädt nichts von außen. Von selbst fragt Mailrobbe nur die DKIM-Schlüssel im DNS ab. Nur auf Knopfdruck fragt es das Schlüsselarchiv ZK Email (es zeigt vorher, welche Domains es fragen würde) und lädt die Detailkarte von build.protomaps.com. Inhalte aus dem Archiv verlassen den Rechner nicht; DNS und Schlüsselarchiv erfahren nur die Namen von Domains und Selektoren. Wer auch keine DNS-Abfragen will, importiert auf der Kommandozeile mit `docker compose run --rm -e MAILROBBE_DKIM_OFFLINE=1 backend mailrobbe import`; fehlende Schlüssel gelten dann als DNS-Fehler und lassen sich später nachprüfen.

### Was heißen „DKIM gültig“, „Signatur stimmig“ und „Schlüssel nicht abrufbar“?

Gültig: Die Signatur passt zum Schlüssel der Domain, die Mail wurde also mit diesem Schlüssel unterschrieben, und die unterschriebenen Teile sind seither unverändert. Wer sie geschrieben hat, beweist das nicht. Signatur stimmig: Ein aus Signaturen errechneter Schlüssel bestätigt sie; das zeigt, dass die Mails aus derselben Quelle signiert wurden, aber nicht, dass die Domain diesen Schlüssel veröffentlicht hat. Schlüssel nicht abrufbar: Der Schlüssel steht heute nicht mehr im DNS, was bei älteren Mails häufig ist; über eine Fälschung sagt das nichts.

### Warum findet „Rat“ auch „Räte“?

Die Suche arbeitet mit deutschen Wortstämmen, damit „Spende“ auch „Spenden“ findet. Wer nur genau ein Wort will, schaltet im Suchmenü „Ganzes Wort“ ein und nennt die Formen selbst: `Rat or Räte`.

### Warum fehlt eine Mail in der Liste?

Vermutlich trifft sie eine Ausblendregel. Über der Mailliste steht dann „ausgeblendet · zeigen“, im Suchmenü holt „Ausgeblendete einbeziehen“ sie zurück, und das Mail-Detail nennt die Regel. Mails mit Notiz, Markierung, Akte oder Status „relevant“ blendet keine Regel aus.

### Was passiert mit gefundenen Kennwörtern?

Sie stehen im Klartext auf der Dokumentseite, mit der Mail, in der sie standen, denn sie sind selbst ein Beleg. Entschlüsselte Dateien speichert Mailrobbe nie; Vorschau und Download entschlüsseln bei jedem Abruf neu. In einen Export kommen Kennwörter nur, wenn man es dort ankreuzt. Ein Archiv, das erst ein gefundenes Kennwort öffnet, packt der nächste „Import starten“ aus.

### Muss ich nach einem Update neu importieren?

Nein. Nach `git pull` und `docker compose up -d --build` genügt „Import starten“ unter `/import`, siehe [Aktualisieren](#aktualisieren).

### Können mehrere Leute gleichzeitig arbeiten?

Ja, alle, die denselben Mailrobbe-Server im Browser öffnen, sehen dieselbe Rechercheakte. Konten gibt es nicht: Jeder Browser trägt einmal einen Namen ein, unter dem Notizen und Änderungen gespeichert werden. Das ist eine Zuordnung, kein Zugriffsschutz; den liefern bei Bedarf Benutzername und Kennwort aus den [Einstellungen](#einstellungen).

### Wo liegen Notizen, Schlagworte und Akten?

In der Datenbank im Docker-Volume `mailrobbe_pgdata`, nicht in den MBOX-Dateien. Wer die Rechercheakte sichern will, sichert dieses Volume oder die Datenbank mit `pg_dump`.

---

<div align="center">

**Mailrobbe ist von admon, für Recherchen in großen Mailarchiven.**

</div>
