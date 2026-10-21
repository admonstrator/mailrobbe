# ruff: noqa: RUF001  (German typography: dashes and quotation marks are meant)
"""LIESMICH.txt of an export (D62): for the lawyer or archivist who receives it, what the files
are, how to check them and what a DKIM result says. German, CRLF line ends for Windows editors.
"""

from datetime import UTC

from mailrobbe.export.manifest import ManifestExport


def readme(export: ManifestExport, folder: str) -> bytes:
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
            "Notizen mit Verfasser und Zeit, dazu in manifest.json die Auswahl (Suche und "
            "Filter), mit der die Mails zusammengestellt wurden. Sie gehören nicht zu den Mails "
            "und können Rückschlüsse auf Quellen und Vorgehen erlauben. Bitte vertraulich "
            "behandeln."
        )
    else:
        research = (
            "nicht enthalten. Bewertungen, Markierungen, Schlagworte, Akten, Notizen und die "
            "Suchkriterien des Rechercheteams sind in keiner Datei dieses Exports."
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
                       DKIM-Ergebnis je Signatur mit Schlüssel und Prüfzeitpunkt, Anhänge.
                       Zeiten in UTC (ISO 8601).
  manifest.csv         Dieselben Angaben als Tabelle für Excel und LibreOffice (Semikolon,
                       UTF-8). Zellen, die mit = + - @ beginnen, haben dort ein vorangestelltes
                       Apostroph, damit kein Tabellenprogramm sie als Formel ausführt; in
                       manifest.json stehen die Werte unverändert.
  LIESMICH.txt         Diese Datei.
  SHA256SUMS           Die SHA-256-Prüfsumme jeder anderen Datei dieses Ordners.

Im Namen eines Mail-Ordners zählt NNNN die Mails in Exportreihenfolge ab 0001, ID ist die
Mail-ID in Mailrobbe (etwa 0001-4711). Byte-identische Kopien einer Mail im Archiv
erscheinen nur einmal. Anhänge sind in mail.eml enthalten und im Manifest mit Name, Typ, Größe
und Prüfsumme aufgeführt; als eigene Dateien liegen sie diesem Export nicht bei.


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
Schlüssel, der zum angegebenen Zeitpunkt im DNS stand oder im Cache von Mailrobbe lag.

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


MAILS OHNE DATEIEN

Stimmt eine Mail nicht mehr mit dem Archiv überein, schreibt Mailrobbe keine Dateien für sie
und vermerkt den Grund im Manifest: die MBOX-Datei ist nicht lesbar („source_missing“), an der
gespeicherten Stelle steht nicht mehr dieselbe Mail („source_changed“), oder keine Mail im
Archiv hat diesen Inhalt mehr („not_in_archive“). So enthält der Export nie andere Bytes als
die beim Import geprüften.
"""
    return text.replace("\n", "\r\n").encode()
