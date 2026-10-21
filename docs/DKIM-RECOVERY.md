# DKIM-Schlüssel für gelöschte Selektoren

Stufen 1 und 2 sind gebaut (Aaron hat sie am 21.10.2026 freigegeben); die Entscheidungen dazu stehen als D100 bis D105 in [DECISIONS.md](DECISIONS.md) und ergänzen D10 bis D13. Dieses Dokument hält fest, warum es so gebaut ist, welche Quellen geprüft wurden und was gebaut ist. Passive DNS (Stufe 3) und das ARC-Zeugnis (Stufe 4) sind nicht gebaut; die Quellen-Schnittstelle (`dkim_key_lookup` mit eigener `source`, Belege in `dkim_key_evidence`) nimmt sie später ohne Schemaänderung auf.

## Ausgangslage

`no_key` heißt heute: der Schlüssel unter `<selector>._domainkey.<domain>` ist nicht mehr im DNS (NXDOMAIN, kein TXT oder leeres `p=`). Bei einem Archiv über viele Jahre ist das der Normalfall für alte Mails. Im Testkorpus mit 20.000 Mails (Generator, Zeitraum 2012 bis 2026) sind 8.622 Mails `no_key` und nur 5.336 `pass`.

Ein zweites, bisher übersehenes Muster: Domains, die unter demselben Selektornamen einen neuen Schlüssel veröffentlichen (etwa `google` bei Google Workspace nach einem Neuerzeugen), machen alte Mails heute zu `fail` mit `signature_mismatch`, obwohl `body_hash_ok` stimmt. Auch diese Mails gehören in den Plan.

## Grundsatz

1. Kryptografie und Bindung werden getrennt ausgewiesen. Der Status sagt, ob eine Signatur zu einem Schlüssel passt. Die Herkunft sagt, wer belegt, dass die Domain diesen Schlüssel veröffentlicht hat.
2. Ein Schlüssel aus einer anderen Quelle als dem heutigen DNS gilt für eine Signatur nur, wenn er ihre Header-Signatur tatsächlich verifiziert. Passt keiner, bleibt die Signatur `no_key`.
3. Jede Antwort einer Quelle wird roh gespeichert, mit Abfrage, Zeitpunkt und SHA-256, auch Negativantworten.
4. Externe Quellen werden nur auf ausdrücklichen Befehl abgefragt, nie beim Import, und Mailrobbe lädt nie etwas hoch (kein „Contribute“ an Schlüsselarchive).

## Quellen

Geprüft am 21.10.2026 aus der Sandbox (eingeschränktes Netz, ohne Zugangsdaten).

| Quelle | Erreichbar | Zugang | DKIM-TXT historisch | Bewertung |
|---|---|---|---|---|
| ZK Email DKIM Archive (`archive.zk.email`, früher `archive.prove.email`), `GET /api/key?domain=` | ja, 0,5 bis 1 s | frei, ohne Schlüssel; Code MIT, Datenlizenz nicht angegeben | ja, alle Selektoren einer Domain samt Subdomains, mit `firstSeenAt`, `lastSeenAt` und Quelle je Beobachtung (`live_dns` oder `gcd_recovered`) | erste Wahl. Gute Abdeckung bei großen Absendern (gmail.com: 4 alte Selektoren, die heute widerrufen sind, nur dort; github.com 16 Selektoren, linkedin.com, amazon.de, paypal.com, wikimedia.org), keine bei kleineren Organisationen (t-online.de, heise.de, ccc.de, bund.de, sparkasse.de: leer). DNS-Beobachtungen meist erst ab 2024. |
| DomainTools/Farsight DNSDB | ja, antwortet „X-API-Key header not present“ | kostenpflichtig; früher Journalisten-Stipendium und Community Edition, heutiger Stand unklar | ja, TXT und `*._domainkey`-Abfragen dokumentiert, auch Suche nach Inhalt | stärkste Passive-DNS-Quelle, nur mit Konto |
| SecurityTrails (Recorded Future) | ja, 401 ohne Schlüssel | Konto; kleines Freikontingent (Angaben Dritter: rund 50 Abfragen) | Endpunkt `/v1/history/{host}/dns/txt` existiert; ob `_domainkey`-Namen erfasst sind, ist unklar | Versuch wert, wenn ein Konto da ist |
| CIRCL Passive DNS | ja, 401 | nur für vertrauenswürdige Partner auf Antrag | unklar | nachrangig |
| Validin, Silent Push, Spamhaus, WhoisXML, ViewDNS | ja, alle 401/403/422 ohne Schlüssel | Konten, teils kostenpflichtig | teils TXT (Spamhaus laut Produktseite), sonst unklar | nur bei vorhandenem Zugang |
| Mnemonic Passive DNS | ja, frei ohne Schlüssel | frei, mit Tageslimit | nein: nur A, AAAA, CNAME, PTR gefunden | hilft nur bei CNAME-Delegation (z. B. `selector1._domainkey.microsoft.com` → `…onmicrosoft.com`, 2017 bis 2019 gesehen) |
| AlienVault OTX | ja, frei | frei | keine Treffer für `_domainkey`-Namen | ungeeignet |
| Robtex | ja | frei | kein TXT | ungeeignet |
| Wayback Machine | nein, Zeitüberschreitung aus der Sandbox | frei | nur zufällig, wenn eine DNS-Prüfseite archiviert wurde | nachrangig, nicht bauen |
| DMARC- und BIMI-Berichte | – | nur für den Domaininhaber | keine Schlüssel | ungeeignet |

Passive-DNS-Anbieter, die selbst aktiv abfragen, kennen DKIM-Namen meist nicht, weil Selektoren nicht aufzählbar sind; nur Sensoren an großen Resolvern sehen sie, wenn Empfangsserver dort nachfragen. Deshalb ist DNSDB die einzige Passive-DNS-Quelle mit realistischer Aussicht (Einschätzung, nicht gemessen).

Weitere Quellen, die nichts kosten:

- **Das Archiv selbst.** Mails des IT-Dienstleisters oder Hosters („Ihr DKIM-Eintrag“), Zonendateien oder Konfigurationen im Anhang enthalten oft `v=DKIM1; … p=MII…`. Der Volltextindex und (mit Meilenstein 9) der Anhangstext lassen sich danach durchsuchen; jeder Fund wird gegen die Signaturen getestet.
- **Andere Selektoren derselben Domain.** Betreiber veröffentlichen denselben Schlüssel manchmal unter mehreren Namen. Ein rekonstruierter Schlüssel wird gegen die heute veröffentlichten Schlüssel üblicher Selektoren der Domain verglichen.
- **CNAME-Ziele von Versanddienstleistern.** Bei delegierten Selektoren (Microsoft 365, Mailchimp, SendGrid, Amazon SES) kann der Kunde den CNAME gelöscht haben, während das Ziel beim Anbieter noch antwortet.
- **ARC und Authentication-Results.** Kein Schlüssel, aber ein Zeugnis: der Empfangsserver hat beim Eingang `dkim=pass` notiert. Ist dieser Kopf durch ein ARC-Siegel eines heute noch veröffentlichten Schlüssels gedeckt (Googles `arc-20160816._domainkey.google.com` und Microsofts `arcselector9901` antworten am 21.10.2026), ist das Zeugnis selbst kryptografisch prüfbar. Eigener Baustein, siehe Reihenfolge.
- **Öffentliche Mailinglisten-Archive** mit Rohmails derselben Absender liefern weitere Signaturen für die Rekonstruktion und unabhängige Kopien.

## Rekonstruktion aus Signaturen

Für RSA mit PKCS#1 v1.5 gilt für jede Signatur `s` über die kodierte Nachricht `m`: `s^e ≡ m (mod n)`, also teilt `n` die Zahl `s^e − m`. Zwei Signaturen desselben Schlüssels ergeben `n` als größten gemeinsamen Teiler, bis auf kleine Faktoren, die per Probedivision entfallen. `m` berechnet Mailrobbe bereits heute (der Header-Hash aus `verify.py`, verpackt nach EMSA-PKCS1-v1_5); `e = 65537`, ersatzweise `3`. Das Archiv von ZK Email nutzt dasselbe Verfahren (Quelle `gcd_recovered`).

Messung am Testkorpus (21.10.2026, Sandbox, Intel Xeon 2,1 GHz, ein Kern je Selektor, GMP 6.3 über gmpy2):

| Schlüssellänge | `s^e` für zwei Signaturen | ggT | Operand |
|---|---|---|---|
| 1024 Bit | 0,7 s | 19 s | 8 MiB |
| 2048 Bit | 1,8 s | 47 s | 16 MiB |
| 4096 Bit | 3,6 s | 107 s | 32 MiB |

- Stichprobe von 12 gelöschten Selektoren (11 mit 2048 Bit, einer mit 1024 Bit): alle 12 rekonstruiert, jeder Schlüssel identisch mit dem Generator-Schlüssel, zusammen 174 s mit 4 Prozessen. Elfmal reichte das erste Paar; einmal enthielt es eine nach dem Signieren veränderte Mail, das zweite Paar traf.
- Mit den rekonstruierten Schlüsseln liefert `verify_mail` für die 232 Signaturen dieser Selektoren, die heute `no_key` sind: 218 `pass`, 7 `fail` mit `body_hash_mismatch`, 7 `fail` mit `signature_mismatch`. Das passt zu den Veränderungen, die der Generator nach dem Signieren einbaut (Listenfußzeilen, Betreff-Markierungen); einzeln abgeglichen wurde es nicht.
- Abdeckung im Testkorpus: 178 Selektoren sind gelöscht, mit 9.859 Signaturen; nur 14 davon haben eine einzige Signatur.
- Ohne GMP rechnet Python den ggT quadratisch: gemessen 5,7 s für 2 Mio. Bit, hochgerechnet rund 6 Stunden je 2048-Bit-Paar. gmpy2 (LGPL-3.0, Wheels für macOS und Linux) wäre die einzige neue Abhängigkeit.
- Nicht möglich: Ed25519 (der Hash enthält den öffentlichen Schlüssel), Selektoren mit nur einer Signatur (im Testkorpus 40 von 358 RSA-Selektoren), und Paare, bei denen eine Mail nach dem Signieren in signierten Kopfzeilen verändert wurde. Deshalb werden Paare der Reihe nach probiert, Dubletten (gleiches `b=`) vorher entfernt.
- Wechselt der Schlüssel unter demselben Namen, wird nach Zeit (`t=`) sortiert gepaart: rekonstruieren, alle passenden Signaturen abziehen, mit dem Rest wiederholen.
- Aussagekraft: ein rekonstruierter Schlüssel belegt nur, dass alle passenden Signaturen mit demselben privaten Schlüssel erzeugt wurden. Er belegt nicht, dass dieser Schlüssel je im DNS der Domain stand. Wer Mails fälscht und mit einem eigenen Schlüssel signiert, bekäme ebenfalls einen „passenden“ Schlüssel. Erst eine unabhängige Beobachtung desselben Schlüssels bindet ihn an die Domain.
- Nebenprüfung: alle gesammelten RSA-Moduli werden paarweise per Produktbaum auf gemeinsame Primfaktoren geprüft (Batch-GCD). Ein Treffer hieße, dass der private Schlüssel berechenbar war, und die Signatur taugt dann nicht als Beleg.

## Herkunft und Vertrauensstufen

Jede Signatur, die ein Schlüssel verifiziert, bekommt die Herkunft dieses Schlüssels. Gibt es für einen Schlüssel mehrere Belege, zählt der stärkste; die übrigen werden mit angezeigt.

| Stufe | Herkunft (`key_origin`) | Belegt | Status | In der Oberfläche |
|---|---|---|---|---|
| 1 | `dns` | die Domain veröffentlicht den Schlüssel heute | `pass` | „DNS heute“ |
| 2 | `observed` | ein Dritter hat den Schlüssel im DNS der Domain gesehen: Schlüsselarchiv mit `live_dns`, Passive DNS | `pass` | „im DNS beobachtet“, mit Quelle und Beobachtungszeitraum am Beleg |
| 3 | `documented` | ein Dokument enthält den Schlüssel: Fund im Archiv, Zonendatei, manuell hinterlegter Beleg | `pass` | „dokumentiert“, mit Verweis und Notiz am Beleg |
| 4 | `reconstructed` | nur: dieselben Signaturen stammen vom selben privaten Schlüssel; auch `gcd_recovered` aus dem ZK-Email-Archiv | neu: `consistent` | „Signatur stimmig“ und „rekonstruiert“, mit dem festen Hinweis, dass das die Domain nicht bindet |

- „Rekonstruiert, bestätigt durch …“ ist kein eigener Wert: stimmt der rekonstruierte Schlüssel mit einem Beleg der Stufe 1 bis 3 überein, hat er dessen Stufe, und die Rekonstruktion steht als zusätzlicher Beleg dabei („zusätzlich aus 37 Signaturen rekonstruiert“).
- `consistent` ist ein neuer Wert von `DkimStatus` mit Rang zwischen `pass` und `temp_error`. Ein rekonstruierter Schlüssel macht also nie `pass`; der Filter „gültig“ zeigt ihn nicht.
- Verifiziert ein Schlüssel die Header-Signatur, aber `bh=` passt nicht zum Body, ist das `fail` mit `body_hash_mismatch` auf jeder Stufe: dass der Body nach dem Signieren verändert wurde, hängt nicht an der Bindung des Schlüssels.
- Passt kein Kandidat, bleibt `no_key`, neuer Grund `key_mismatch` („vorhandene Schlüssel passen nicht“).
- Für `fail` mit `signature_mismatch` und `body_hash_ok` werden ebenfalls Kandidaten probiert (Schlüsselwechsel unter gleichem Namen); passt einer, wird die Signatur mit dessen Herkunft neu bewertet.

## Was gebaut ist

Alles läuft als Nachlauf über den vorhandenen Bestand; ein Neuimport ist nicht nötig. Die Migration 0011 legt die Tabellen an und setzt bei älteren Ergebnissen, die auf einem Schlüssel aus dem DNS beruhen, `key_origin = dns`.

### Datenmodell (Migration 0011)

- `dkim_key`: ein Schlüssel je Name und Inhalt (`name`, `domain`, `selector`, `key_type`, `bits`, `key_sha256`, `record`, `origin` als stärkste Herkunft seiner Belege, `factorable`); `key_sha256` ist bei RSA der SHA-256 des DER-SubjectPublicKeyInfo, gleich, ob `p=` als SPKI oder als nacktes RSAPublicKey kam.
- `dkim_key_lookup`: jede Frage an eine Quelle, auch ohne Treffer und bei Fehlern: `source` (`reconstruction`, `archive_text`, `manual`, `zkemail`, `dns`), `query` (nie mit Zugangsdaten), `asked_at`, `outcome`, `http_status`, `raw` unverändert mit `raw_sha256`, Medientyp und Dateiname, `message`, `tool_version`, `editor`.
- `dkim_key_evidence`: ein Beleg je Schlüssel und Abfrage: `origin`, `observed_from`/`observed_to` (die Zeitangaben der Quelle), `reference`, `note`, `details` (bei Rekonstruktion `exponent`, `hash` und die verwendeten Signaturen mit `mail_id`, `signature_index`, `mail_sha256`), `editor`.
- `dkim_result` bekommt `key_id` und `key_origin`; `DkimStatus` bekommt `consistent`, `DkimReason` bekommt `key_mismatch`.
- Anders als geplant bekommt `mail` keine Spalte `dkim_origin` (D100): der Status `consistent` trennt Stufe 4 schon in Liste und Filter, und eine neue Spalte zu füllen hätte jede Mailzeile samt Volltextindex neu geschrieben.

### Prüfung

`verify_mail(raw, keys, candidates)` bleibt rein. Gibt das DNS keinen, einen widerrufenen oder unbrauchbaren Schlüssel, eine Zeitüberschreitung oder einen Schlüssel, unter dem die Signatur bei intaktem Body nicht hält, probiert es die Kandidaten des Namens, stärkste Herkunft zuerst; ein Kandidat zählt nur, wenn er den Header-Hash verifiziert. Die Kandidaten werden je Lauf einmal geladen (wie `dns_cache`) und gelten beim Import, bei `mailrobbe dkim`, bei „Neu prüfen“ im Mail-Detail und in den Schlüssel-Läufen. Faktorisierbare Schlüssel sind nie Kandidaten.

### Kommandozeile

```sh
mailrobbe dkim-keys reconstruct [--name N]... [--jobs N]   # Schlüssel aus Signaturpaaren, dann Abgleich und Batch-GCD
mailrobbe dkim-keys search [--name N]...                   # Schlüsseleinträge in Mail- und Anhangstexten
mailrobbe dkim-keys fetch [--domain D]... [--name N]...    # ZK-Email-Archiv, eine Anfrage je Domain
mailrobbe dkim-keys check [--name N]...                    # Mails dieser Namen mit allen Kandidaten neu prüfen
mailrobbe dkim-keys add --name N (--record R | --record-file F) --reference REF \
    [--note T] [--evidence-file F] [--editor NAME] [--observed-from D] [--observed-to D]
mailrobbe dkim-keys status                                 # Kennzahlen als JSON
```

- Jede Aufgabe außer `status` ist ein Lauf der Art `dkim_keys` in der Tabelle `job` (D101) mit Schritten (D110): auswählen, die Aufgabe selbst, abgleichen, prüfen und die vier Aggregat-Schritte. Ctrl-C, SIGTERM und „Anhalten“ im Dashboard beenden nach dem laufenden Namen oder Block; was gefunden ist, wird trotzdem geprüft. Der Lauf teilt sich die Sperre mit `mailrobbe dkim`, beide laufen also nie gleichzeitig.
- `reconstruct` liest je Name bis zu acht Signaturen von Mails, die keine Dubletten sind (verschiedene `b=`, älteste `t=` zuerst), probiert Paare mit e = 65537, dann 3, legt verifizierte Signaturen beiseite und versucht es mit dem Rest erneut. Eine Signatur, die am heutigen Schlüssel scheitert (`signature_mismatch` bei intaktem Body), liest sie nur, wenn sie vor der ersten Signatur liegt, die der heutige Schlüssel bestätigt: nur dann spricht sie für einen ausgetauschten Schlüssel. Spätere sind unterwegs veränderte Mails (Betreff-Markierung einer Liste); jedes Paar davon kostet eine GCD von bis zu einer Minute und ergibt nie einen Schlüssel. Ein Name, dessen letzter Versuch dieselben Signaturen las, wird übersprungen; mit `--name` wird immer neu gerechnet. Danach `compare`: ein rekonstruierter Schlüssel, der heute unter einem anderen Selektor derselben Domain im DNS steht oder aus einer anderen Quelle bekannt ist, bekommt einen Beleg dieser Herkunft. Zum Schluss Batch-GCD über alle bekannten RSA-Moduli.
- `search` findet Texte über den Volltextindex (Tokens `dkim1`, `mii…`, `migf…`, `migj…`), liest die Schlüssel daraus, auch über mehrere Strings in Anführungszeichen verteilt, und testet jeden an den drei ältesten Signaturen jedes betroffenen Namens; ein passender wird `documented` mit dem Permalink `/m/<hash>` oder `/anhaenge/<id>` als Verweis.
- `fetch` fragt `MAILROBBE_DKIM_KEY_ARCHIVE_URL` (Vorgabe `https://archive.zk.email`, `off` schaltet ab) mit der Python-Standardbibliothek und den Proxy-Einstellungen der Umgebung. Domains unter reservierten TLDs (`.example`, `.test`, …) gehen nur an ein Archiv auf dieser Maschine.
- `add` speichert einen Schlüssel mit Verweis und optionaler Belegdatei als `documented` und prüft danach die Mails des Namens.

### Import-Dashboard

Karte „Gelöschte Selektoren“ unter `/import`: Selektoren und Mails ohne Schlüssel, davon rekonstruierbar, geklärte Selektoren, Mails „Signatur stimmig“, gefundene Schlüssel je Herkunft, faktorisierbare. Knöpfe „Schlüssel rekonstruieren“, „Im Archiv suchen“ und „Schlüsselarchiv abfragen …“; der letzte zeigt vorher je Domain, wie viele Selektoren und Mails betroffen sind und wann sie zuletzt gefragt wurde, mit Häkchen zum Abwählen. Ein laufender Schlüssel-Lauf zeigt seine Schritte wie Import und DKIM-Prüfung („41 von 164 Selektoren · 3,6 Selektoren/min“).

### Selektorseiten und Mail-Detail

- `/import/selektoren`: alle Schlüsselnamen mit Signaturen (offen, geklärt, alle), mit Statusmischung, RSA-Signaturen, Zeitraum, Schlüsseln und heutigem DNS-Stand.
- `/import/selektoren/<name>`: heutige DNS-Antwort, die Schlüssel mit Herkunft, Bits, SHA-256 und allen Belegen (Quelle, Abrufzeit, Zeitangaben der Quelle, Verweis, Notiz, Bearbeiter, Download der Rohantwort, bei Rekonstruktion die verwendeten Signaturen als Links), die Abfragen, die neuesten Mails, „Schlüssel rekonstruieren“ für diesen Namen und „Schlüssel von Hand hinzufügen“ (Eintrag oder `p=`-Wert, Herkunft, Notiz, Zeitraum, Belegdatei bis 10 MiB, Bearbeitername nach D54).
- Im Mail-Detail trägt jede Signatur ein Herkunftsabzeichen; hängt sie an einem Schlüssel aus `dkim_key`, stehen dessen SHA-256, Bits, Belege und der Weg zur Selektorseite dabei, bei `consistent` der Hinweis: „Die Signatur passt zu einem aus Signaturen berechneten Schlüssel. Das zeigt, dass diese Mails mit demselben privaten Schlüssel signiert wurden, nicht, dass die Domain ihn veröffentlicht hat.“

### Export (D62, D63, D105)

- `manifest.json` und `manifest.csv` je Signatur: `key_origin`, `key_sha256` und die Beleg-Nummern.
- Je Schlüssel, auf dem eine exportierte Signatur beruht, `schluessel/<name>/<key_sha256>/` mit `record.txt`, je Beleg `beleg-<id>.json` und der Rohantwort unverändert; bei Rekonstruktion `signaturen.json` (`s`, `m`, `e`, Hash, Mail und Signatur je Eintrag) und `pruefe_rekonstruktion.py`, das nur mit der Python-Standardbibliothek `pow(s, e, n) == m` nachrechnet. Alles in `SHA256SUMS`.
- PDF: je Signatur die Herkunft des Schlüssels, bei `consistent` der Hinweis; `LIESMICH.txt` erklärt die vier Herkünfte und das Prüfskript.

## Was ein Gutachter nachvollziehen können muss

- Jede Rohantwort jeder Quelle unverändert, mit Abfrage (ohne Zugangsdaten), Zeitpunkt der Abfrage in UTC, SHA-256 und Mailrobbe-Version, auch die Antworten ohne Treffer.
- Die Zeitangaben der Quelle (erste und letzte Beobachtung) getrennt vom eigenen Abrufzeitpunkt.
- Bei Rekonstruktion: welche Signaturen verwendet wurden, der Exponent, der Modulus und ein Skript, das ohne Mailrobbe nachrechnet; die Verifikation selbst ist billig, nur das Finden ist teuer.
- Bei manuellen Belegen: wer ihn wann hinterlegt hat und worauf er sich stützt (Permalink, Datei mit SHA-256, URL).
- Dass externe Archive selbst vertrauenswürdige Dritte sind: ZK Email schreibt selbst, dass ihr Server derzeit die einzige vertrauenswürdige Partei ist; Zeitstempel über witness.co belegen nur, dass ein Eintrag zu einem Zeitpunkt existierte.
- Optional: den SHA-256 des Beleg-Ordners mit einem RFC-3161-Zeitstempel versehen. Nicht Teil des Plans, wenn nicht gewünscht.

## Quellenschutz

Jede Abfrage verrät etwas. Schon heute fragt die DKIM-Prüfung das DNS der Organisation nach Selektoren, die seit Jahren gelöscht sind; das sieht deren Nameserver (mit `MAILROBBE_DKIM_NAMESERVERS` auf einem öffentlichen Resolver nur dessen Adresse). Passive-DNS-Dienste ordnen jede Abfrage einem Konto zu. Deshalb: externe Abfragen nur auf Befehl, je Domain statt je Selektor, mit Vorschau, und nie Uploads.

## Reihenfolge

1. **Fundament und Offline-Quellen**: gebaut (Tabellen, Herkunft in Prüfung, Liste, Detail und Export, Status `consistent`, Rekonstruktion als Lauf, Suche im eigenen Archiv, manuelle Belege, Batch-GCD).
2. **ZK-Email-Archiv und Abgleich**: gebaut (Abfrage je Domain mit Vorschau, `live_dns` als Stufe 2, `gcd_recovered` als Stufe 4, Abgleich rekonstruierter Schlüssel mit Archiv, anderen Quellen und heutigen Selektoren derselben Domain).
3. **Passive DNS**: offen, zuerst DNSDB, dann SecurityTrails, sobald ein Konto da ist; nur gegen aufgezeichnete Antworten testbar. Eine Quelle ist ein neuer `source`-Wert in `dkim_key_lookup` und eine Aufgabe von `mailrobbe dkim-keys`.
4. **ARC-Zeugnis**: offen. ARC-Siegel von Google und Microsoft prüfen und `dkim=pass` des Empfangsservers als eigenes Zeugnis anzeigen, nicht als Status.

Nicht bauen: Wayback, DMARC- und BIMI-Berichte, OTX, Robtex.

## Vorab auf dem echten Archiv messen

Wie viel die Rekonstruktion bringt und wie lange sie dauert, zeigt diese Abfrage (Dubletten zählen nicht):

```sql
WITH s AS (
  SELECT r.domain, r.selector, count(DISTINCT r.mail_id) AS mails
  FROM dkim_result r JOIN mail m ON m.id = r.mail_id
  WHERE r.status = 'no_key' AND r.algorithm LIKE 'rsa-%' AND m.is_duplicate_of IS NULL
  GROUP BY 1, 2)
SELECT count(*) AS selectors,
       count(*) FILTER (WHERE mails >= 2) AS reconstructable,
       sum(mails) AS no_key_mails,
       sum(mails) FILTER (WHERE mails >= 2) AS covered_mails
FROM s;
```

Aufruf: `docker compose exec db psql -U mailrobbe mailrobbe`. Rechenzeit grob: rekonstruierbare Selektoren mal 50 s (2048 Bit) geteilt durch die Zahl der Worker; 1.000 Selektoren mit 8 Workern rund 1,5 bis 2 Stunden.

## Offene Entscheidungen

- Zugang zu DNSDB anfragen; Farsight bot 2019 investigativen Journalisten freien Zugang an, ob das noch gilt, ist unklar.

Entschieden (D100 bis D105): eigener Status `consistent` statt `pass` mit Vermerk, Abfragen beim ZK-Email-Archiv nur auf Knopfdruck mit Vorschau, gmpy2 als einzige neue Abhängigkeit.
