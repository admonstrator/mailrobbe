# ruff: noqa: RUF001  (German typography: dashes and quotation marks are meant)
"""LIESMICH.txt of an export (D62): for the lawyer or archivist who receives it, what the files
are, how to check them, what a DKIM result says and where its key comes from (D105), and with
the research data what its signals are (D139). German, CRLF line ends for Windows editors.
"""

from datetime import UTC

from mailrobbe.export.keys import CHECK_SCRIPT, KEYS_FOLDER
from mailrobbe.export.manifest import ManifestExport


def readme(export: ManifestExport, folder: str, keys: int) -> bytes:
    """keys: the number of key folders in KEYS_FOLDER; the folder is described only with one."""
    label = f" – „{export.label}“" if export.label else ""
    who = export.created_by or "ohne Namensangabe"
    when = f"{export.created_at.astimezone(UTC):%d.%m.%Y um %H:%M:%S} UTC"
    errors = (
        f"Bei {export.errors} von ihnen fehlen die Dateien (siehe „Mails ohne Dateien“)."
        if export.errors
        else "Zu jeder liegen beide Dateien bei."
    )
    if export.include_research:
        research = (
            "ENTHALTEN. manifest.json, manifest.csv und die PDF-Dateien enthalten interne "
            "Arbeitsangaben des Rechercheteams: Bewertung, Markierung, Schlagworte, Akten und "
            "Notizen mit Verfasser und Zeit, die Signale jeder Mail, dazu in manifest.json die "
            "Auswahl (Suche und Filter), mit der die Mails zusammengestellt wurden. Sie gehören "
            "nicht zu den Mails und können Rückschlüsse auf Quellen und Vorgehen erlauben. Bitte "
            "vertraulich behandeln. Signale sind Hinweise, die Mailrobbe nach einfachen Regeln "
            "berechnet (etwa private Adressen, Blindkopien, Uhrzeiten oder Wörter der "
            "Recherchethemen); sie bewerten nichts. Ihre Regeln stehen in Mailrobbe auf der "
            "Seite „Signale“ (/auffaelligkeiten) und in der Datei themes.toml (Abschnitt "
            "[signals] und die Wortfelder der Themen)."
        )
    else:
        research = (
            "nicht enthalten. Bewertungen, Markierungen, Schlagworte, Akten, Notizen, Signale "
            "und die Suchkriterien des Rechercheteams sind in keiner Datei dieses Exports."
        )
    key_row = (
        f"""\
  {KEYS_FOLDER}/          Die Schlüssel, auf denen DKIM-Ergebnisse dieses Exports beruhen,
                       soweit die Domain sie heute nicht mehr im DNS veröffentlicht, mit ihren
                       Belegen ({keys} Ordner; siehe „Schlüssel aus anderen Quellen“).
"""
        if keys
        else ""
    )
    key_section = (
        f"""


SCHLÜSSEL AUS ANDEREN QUELLEN

Für jeden Schlüssel, der nicht heute im DNS steht, liegt ein Ordner
{KEYS_FOLDER}/<Name>/<SHA-256 des Schlüssels>/ bei. <Name> ist der DNS-Name des Schlüssels
(<Selector>._domainkey.<Domain>), die SHA-256-Prüfsumme dieselbe wie in manifest.json
(„key_sha256“). Darin:

  record.txt           Der Schlüssel, wie Mailrobbe ihn zum Prüfen verwendet hat
                       (DKIM-Schlüsseleintrag mit p=).
  beleg-N.json         Ein Beleg: welche Quelle, was gefragt wurde, wann, mit welchem
                       Ergebnis, die Zeiten, die die Quelle selbst nennt (etwa „zuerst gesehen“
                       und „zuletzt gesehen“), Fundstelle, Notiz, wer ihn eingetragen hat (die in
                       Mailrobbe eingegebene Bezeichnung) und die Version von Mailrobbe. N ist
                       die Nummer, die manifest.json je Signatur unter „evidence“ nennt.
  beleg-N-<Datei>      Die Antwort der Quelle oder die eingereichte Belegdatei, Byte für Byte
                       unverändert; ihre SHA-256-Prüfsumme steht in beleg-N.json.
  signaturen.json      Nur bei rekonstruierten Schlüsseln: je Signatur die Mail (SHA-256 von
                       mail.eml), die Nummer der Signatur, die Signatur s, der Exponent e und der
                       signierte Hashwert m, so wie RSA ihn verschlüsselt (Zahlen hexadezimal).
                       Zuerst die Signaturen, aus denen der Schlüssel berechnet wurde, dann die
                       weiteren dieses Exports.
  {CHECK_SCRIPT}
                       Prüft mit Python allein, ohne Mailrobbe, für jede Signatur aus
                       signaturen.json, ob s hoch e modulo n gleich m ist (n und e aus
                       record.txt), und ob m der signierte Hashwert ist. Aufruf im Ordner des
                       Schlüssels, mit Python ab Version 3.9:

                         python3 {CHECK_SCRIPT}

                       (unter Windows „py {CHECK_SCRIPT}“). Es meldet je Signatur
                       „stimmt“ oder „STIMMT NICHT“ und endet mit dem Rückgabewert 0 nur, wenn
                       alle stimmen.

Für die Signaturen, aus denen der Schlüssel berechnet wurde, gilt die Gleichung schon durch die
Berechnung; dort zeigt die Prüfung, dass richtig gerechnet wurde. Dass sich aus ihnen
überhaupt ein Schlüssel der erwarteten Länge ergab, ist nur möglich, wenn sie vom selben
privaten Schlüssel stammen und ihre signierten Teile unverändert sind. Jede weitere Signatur,
für die die Gleichung gilt, bestätigt das unabhängig. Wem dieser Schlüssel gehörte und ob die
Domain ihn veröffentlicht hat, belegt die Prüfung nicht."""
        if keys
        else ""
    )
    text = f"""\
Mailrobbe-Export {export.id}{label}
{"=" * 72}

Erstellt am {when} von {who}
(der Name ist die in Mailrobbe eingegebene Bezeichnung, kein geprüftes Konto).
Enthält {export.mails} Mails in Exportreihenfolge, die älteste zuerst. {errors}
Rechercheangaben: {research}


WAS IST DAS?

Mailrobbe erschließt ein Archiv von Mails, die in MBOX-Dateien vorliegen. Dieser Export
stellt ausgewählte Mails daraus für die Weitergabe zusammen, etwa an eine Kanzlei, ein
Gericht oder ein Archiv.


INHALT DES ORDNERS {folder}/

  NNNN-ID/mail.eml     Eine Mail, Byte für Byte so, wie sie in der MBOX-Datei des Archivs
                       steht, ohne die Hülle des MBOX-Formats (die „From “-Trennzeile davor,
                       die Leerzeile danach und das „>“ vor Textzeilen, die mit „From “
                       beginnen). Vor dem Schreiben wurde geprüft, dass ihre SHA-256-Prüfsumme
                       der beim Import berechneten entspricht. Sie lässt sich mit jedem
                       Mailprogramm öffnen und enthält auch die Anhänge. Diese Datei ist
                       maßgeblich.
  NNNN-ID/mail.pdf     Eine Lesefassung derselben Mail: Kopfzeilen, Fundstelle im Archiv,
                       Prüfsumme, DKIM-Ergebnis, Liste der Anhänge und Text. Sie dient nur dem
                       Lesen und Ausdrucken; HTML-Darstellung und Anhänge enthält sie nicht.
                       Zeichen, die die eingebettete Schrift nicht darstellen kann (etwa Emoji),
                       erscheinen als �.
  manifest.json        Alle Angaben zum Export und zu jeder Mail, maschinenlesbar: Nummer,
                       Ordner, Mail-ID, Message-ID, Datum, Absender und Empfänger, Betreff,
                       MBOX-Datei mit Byte-Offset und Länge, SHA-256 von mail.eml und mail.pdf,
                       DKIM-Ergebnis je Signatur mit Schlüssel, Herkunft des Schlüssels,
                       seiner SHA-256-Prüfsumme, den Nummern seiner Belege und Prüfzeitpunkt,
                       Anhänge mit ihren Metadaten. Zeiten in UTC (ISO 8601).
  manifest.csv         Dieselben Angaben als Tabelle für Excel und LibreOffice (Semikolon,
                       UTF-8). Zellen, die mit = + - @ beginnen, haben dort ein vorangestelltes
                       Apostroph, damit kein Tabellenprogramm sie als Formel ausführt; in
                       manifest.json stehen die Werte unverändert.
{key_row}  LIESMICH.txt         Diese Datei.
  SHA256SUMS           Die SHA-256-Prüfsumme jeder anderen Datei dieses Ordners.

Im Namen eines Mail-Ordners zählt NNNN die Mails in Exportreihenfolge ab 0001, ID ist die
Mail-ID in Mailrobbe (etwa 0001-4711). Byte-identische Kopien einer Mail im Archiv
erscheinen nur einmal. Anhänge sind in mail.eml enthalten und im Manifest mit Name, Typ, Größe
und Prüfsumme aufgeführt; als eigene Dateien liegen sie diesem Export nicht bei.

Unter „metadata“ steht in manifest.json bei jedem Anhang, was seine Datei über sich selbst
angibt, etwa Autor, Programm, Kamera, Aufnahmezeit oder Ort (EXIF, PDF-Dokumentinformationen,
XMP, Office- und OpenDocument-Eigenschaften), alle Felder so, wie sie in der Datei stehen. Diese
Angaben sind ungeprüft: Programme schreiben sie oft unvollständig, und jeder kann sie ändern.


PRÜFEN, OB DIE DATEIEN UNVERÄNDERT SIND

SHA256SUMS listet die SHA-256-Prüfsumme jeder Datei. Im Ordner {folder}:

  Linux:    sha256sum -c SHA256SUMS
  macOS:    shasum -a 256 -c SHA256SUMS
  Windows:  in der PowerShell
            Get-Content SHA256SUMS | ForEach-Object {{ $h, $p = $_ -split '  ', 2;
              if ((Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash -eq $h) {{ "OK      $p" }}
              else {{ "FEHLER  $p" }} }}

Jede Zeile muss „OK“ melden. Die Prüfsumme von SHA256SUMS selbst hat Mailrobbe beim ersten
vollständigen Herunterladen dieses Exports gespeichert (Akten > Exporte); stimmt sie überein,
sind alle Dateien so, wie Mailrobbe sie ausgegeben hat. Die Prüfsumme von mail.eml ist
dieselbe, die Mailrobbe beim Import der Mail berechnet hat (manifest.json: „sha256“).


WAS DAS DKIM-ERGEBNIS AUSSAGT

DKIM ist eine digitale Signatur, die der versendende Mailserver über ausgewählte Kopfzeilen
und den Text einer Mail legt; den passenden öffentlichen Schlüssel veröffentlicht die
signierende Domain (d=) im DNS. Mailrobbe hat jede Signatur kryptografisch geprüft, mit dem
Schlüssel, der zum angegebenen Zeitpunkt im DNS stand oder im Cache von Mailrobbe lag, und,
wo die Domain ihn nicht mehr veröffentlicht, mit einem Schlüssel aus einer anderen Quelle
(siehe „Woher der Schlüssel stammt“).

„pass“ (gültig) heißt: Die signierten Teile der Mail sind seit dem Signieren unverändert, und
signiert hat ein Server, der über den Schlüssel der Domain d= verfügte. Das gilt nur für den
Text und die signierten Kopfzeilen; welche das sind, steht in der Mail selbst im Feld
DKIM-Signature (h=). Es sagt nicht, wer die Mail geschrieben hat, dass der angezeigte Absendername
stimmt, dass die Mail zugestellt oder gelesen wurde, oder dass ihr Inhalt wahr ist. Ablaufdaten
der Signatur (x=) wurden aufgezeichnet, entscheiden aber nicht.

„fail“ (ungültig) heißt: Signatur und Mail passen nicht zusammen. Das kann eine Veränderung
nach dem Versand bedeuten, entsteht aber oft harmlos, etwa wenn Verteiler oder Weiterleitungen
Betreff oder Text anpassen. „no_key“ (Schlüssel nicht abrufbar): Die Domain veröffentlicht den
Schlüssel nicht mehr, was nach einem Schlüsselwechsel üblich ist; die Signatur lässt sich dann
nicht mehr prüfen. Das ist kein Hinweis auf eine Fälschung. „unsigned“: Die Mail trägt keine
Signatur. „temp_error“: Der Schlüssel konnte nicht abgefragt werden. „unchecked“: Die Mail
wurde noch nicht geprüft.

„consistent“ (Signatur stimmig) heißt: Die Signatur passt zu einem Schlüssel, der aus
Signaturen berechnet wurde. Die signierten Teile der Mail sind seit dem Signieren unverändert,
und die Signatur stammt vom selben privaten Schlüssel wie die Signaturen, aus denen er
berechnet wurde. Das belegt nicht, dass die Domain diesen Schlüssel veröffentlicht hat; ein
„consistent“ ist deshalb nie ein „pass“.


WOHER DER SCHLÜSSEL STAMMT

Nach einem Schlüsselwechsel löschen Domains den alten Schlüssel meist aus dem DNS. Mailrobbe
nennt deshalb je Signatur, woher der Schlüssel stammt, mit dem sie geprüft wurde (manifest.json:
„key_origin“; manifest.csv und mail.pdf: „Herkunft des Schlüssels“), vom stärksten zum
schwächsten Beleg:

  heute im DNS veröffentlicht („dns“)
      Die Domain veröffentlicht den Schlüssel heute; Mailrobbe hat ihn selbst abgefragt.
  von Dritten im DNS gesehen („observed“)
      Ein Schlüsselarchiv hat den Schlüssel früher im DNS der Domain gesehen und nennt, wann.
      Ergebnis bei unveränderter Mail „pass“.
  dokumentiert („documented“)
      Ein Dokument enthält den Schlüssel: eine Mail oder ein Anhang dieses Archivs oder ein von
      Hand eingetragener Beleg. Ergebnis bei unveränderter Mail „pass“. Wie belastbar das ist,
      hängt vom Dokument ab; Fundstelle und Belegdatei liegen bei.
  rekonstruiert („reconstructed“)
      Mailrobbe oder ein Schlüsselarchiv hat den Schlüssel aus mindestens zwei Signaturen
      berechnet. Ergebnis „consistent“, nie „pass“.

Ohne Angabe beruht das Ergebnis auf keinem Schlüssel (etwa „no_key“). Gibt es für einen
Schlüssel Belege verschiedener Art, gilt der stärkste.{key_section}


MAILS OHNE DATEIEN

Stimmt eine Mail nicht mehr mit dem Archiv überein, schreibt Mailrobbe keine Dateien für sie
und vermerkt den Grund im Manifest: die MBOX-Datei ist nicht lesbar („source_missing“), an der
gespeicherten Stelle steht nicht mehr dieselbe Mail („source_changed“), oder keine Mail im
Archiv hat diesen Inhalt mehr („not_in_archive“). So enthält der Export nie andere Bytes als
die beim Import geprüften.
"""
    return text.replace("\n", "\r\n").encode()
