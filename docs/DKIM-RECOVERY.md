# DKIM-Schlüssel für gelöschte Selektoren

Entwurf, nicht freigegeben. Dieser Plan beschreibt, wie Mailrobbe DKIM-Signaturen alter Mails noch prüfen kann, wenn der Selektor im DNS inzwischen gelöscht oder widerrufen ist. Er ergänzt D10 bis D13 in [DECISIONS.md](DECISIONS.md); gebaut wird erst nach Freigabe, die Entscheidungen bekommen dann die nächsten freien D-Nummern.

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

| Stufe | Herkunft (`key_origin`) | Belegt | Status | UI-Text (Vorschlag) |
|---|---|---|---|---|
| 1 | `dns` | die Domain veröffentlicht den Schlüssel heute | `pass` | „gültig (DNS heute)“ |
| 2 | `observed` | ein Dritter hat den Schlüssel im DNS der Domain gesehen: Schlüsselarchiv mit `live_dns`, Passive DNS | `pass` | „gültig (Schlüssel 2019 im DNS beobachtet, Quelle …)“, mit Hinweis, ob der Beobachtungszeitraum den Signaturzeitpunkt deckt |
| 3 | `documented` | ein Dokument enthält den Schlüssel: Fund im Archiv, Zonendatei, manuell hinterlegter Beleg | `pass` | „gültig (Schlüssel aus Beleg: …)“ |
| 4 | `reconstructed` | nur: dieselben Signaturen stammen vom selben privaten Schlüssel; auch `gcd_recovered` aus dem ZK-Email-Archiv | neu: `consistent` | „Signatur stimmig, Schlüssel rekonstruiert, nicht an die Domain gebunden“ |

- „Rekonstruiert, bestätigt durch …“ ist kein eigener Wert: stimmt der rekonstruierte Schlüssel mit einem Beleg der Stufe 1 bis 3 überein, hat er dessen Stufe, und die Rekonstruktion steht als zusätzlicher Beleg dabei („zusätzlich aus 37 Signaturen rekonstruiert“).
- `consistent` ist ein neuer Wert von `DkimStatus` mit Rang zwischen `pass` und `temp_error`. Ein rekonstruierter Schlüssel macht also nie `pass`; der Filter „gültig“ zeigt ihn nicht.
- Verifiziert ein Schlüssel die Header-Signatur, aber `bh=` passt nicht zum Body, ist das `fail` mit `body_hash_mismatch` auf jeder Stufe: dass der Body nach dem Signieren verändert wurde, hängt nicht an der Bindung des Schlüssels.
- Passt kein Kandidat, bleibt `no_key`, neuer Grund `key_mismatch` („vorhandene Schlüssel passen nicht“).
- Für `fail` mit `signature_mismatch` und `body_hash_ok` werden ebenfalls Kandidaten probiert (Schlüsselwechsel unter gleichem Namen); passt einer, wird die Signatur mit dessen Herkunft neu bewertet.

## Änderungen

### Datenmodell (eine neue Alembic-Revision)

- `dkim_key`: ein Schlüssel je Name und Inhalt. `id`, `name` (`<selector>._domainkey.<domain>`), `key_type`, `bits`, `key_sha256` (SHA-256 des DER-SubjectPublicKeyInfo, Identität über alle Quellen), `record` (TXT wie veröffentlicht, bei Rekonstruktion `v=DKIM1; k=rsa; p=…` erzeugt), `created_at`; eindeutig über `(name, key_sha256)`.
- `dkim_key_lookup`: jede Frage an eine Quelle, auch ohne Treffer. `source` (`zkemail`, `dnsdb`, `securitytrails`, `circl`, `archive_text`, `manual`, `reconstruction`), `query` (URL oder Name, nie mit API-Schlüssel), `asked_at`, `outcome` (`found`, `not_found`, `error`), `http_status`, `raw` (Antwort unverändert, bytea), `raw_sha256`, `tool_version`.
- `dkim_key_evidence`: ein Beleg für einen Schlüssel. `key_id`, `lookup_id`, `origin` (`dns`, `observed`, `documented`, `reconstructed`), `observed_from` und `observed_to` (die Zeitangaben der Quelle), `reference` (URL, Permalink `/m/<hash>`, Datei mit SHA-256), `note`, `editor` (D54), `created_at`; bei Rekonstruktion zusätzlich `exponent` und `signatures` (jsonb: `mail_id`, `signature_index`, `raw_sha256` je verwendeter Signatur).
- `dkim_result`: neu `key_id` und `key_origin`. `mail`: neu `dkim_origin` (Herkunft der Signatur, die `dkim_status` bestimmt), damit Liste und Filter ohne Join schnell bleiben. `DkimStatus` bekommt `consistent`, `DkimReason` bekommt `key_mismatch`.
- `dns_cache` bleibt, wie es ist: nur heutiges DNS.

### Prüfung

- `verify_mail` bleibt rein. Neben der `KeySource` bekommt es eine zweite Quelle für Kandidaten je Name (aus `dkim_key`, beim Start eines Laufs einmal geladen wie `dns_cache`). Liefert das DNS `not_found`, einen widerrufenen Schlüssel oder einen, der nicht verifiziert, werden die Kandidaten nach Stufe probiert.
- `SignatureResult` bekommt `key_id` und `key_origin`; `MailVerdict.status` wählt bei gleichem Status die stärkere Herkunft.

### Kommandozeile

```sh
mailrobbe dkim-keys status                       # no_key-Selektoren nach betroffenen Mails, Kandidaten, Herkunft
mailrobbe dkim-keys reconstruct [--name N] [--jobs N] [--limit N]
mailrobbe dkim-keys find-in-archive               # Volltext und Anhangstext nach "v=DKIM1" und "p=MII"
mailrobbe dkim-keys fetch --source zkemail [--domain D] [--dry-run]
mailrobbe dkim-keys fetch --source dnsdb|securitytrails|circl [--dry-run]
mailrobbe dkim-keys add --name N --record R --reference REF [--note TEXT]
mailrobbe dkim-keys import keys.csv               # name, record, reference, note
mailrobbe dkim-keys show N                        # Belege, Rohantworten, Signaturen
mailrobbe dkim --sources dns,observed,documented,reconstructed   # welche Herkünfte eine Nachprüfung nutzt
```

- `reconstruct` arbeitet die Selektoren nach Zahl der betroffenen Mails ab, ist wie Import und DKIM-Lauf ein Job (D46, D47) mit Pause, Fortsetzen und Live-Zahlen, und prüft am Ende die betroffenen Mails neu.
- `fetch` fragt je Domain, nicht je Selektor (das ZK-Email-Archiv liefert alle Selektoren einer Domain, so verrät die Abfrage nicht, welche Selektoren im Archiv vorkommen). `--dry-run` zeigt, was an wen ginge.
- Zugangsdaten nur über Umgebungsvariablen: `MAILROBBE_DKIM_KEY_ARCHIVE_URL` (Vorgabe `https://archive.zk.email`, leer schaltet ab), `MAILROBBE_DKIM_DNSDB_KEY`, `MAILROBBE_DKIM_SECURITYTRAILS_KEY`, `MAILROBBE_DKIM_CIRCL_USER` und `MAILROBBE_DKIM_CIRCL_PASSWORD`. Ohne Schlüssel ist die Quelle aus.

### Import-Dashboard

Neue Kachel „Gelöschte Selektoren“: Selektoren und Mails mit `no_key`, davon rekonstruierbar (mindestens zwei RSA-Signaturen), Fortschritt und Restzeit der Rekonstruktion, Treffer je Quelle, Verteilung nach Herkunft. Knöpfe „Rekonstruieren“, „Im Archiv suchen“ und „Schlüsselarchive abfragen“; der letzte zeigt vorher, welche Domains an welchen Dienst gehen.

### Mail-Detail

Je Signatur ein Herkunftsabzeichen neben dem Status, aufklappbar: Quelle, Beobachtungszeitraum gegen `t=`, Abrufzeit, SHA-256 der Rohantwort mit Download, bei Rekonstruktion die Zahl der Signaturen und Links auf die Mails. `consistent` bekommt einen festen Hinweistext, der sagt, was nicht belegt ist. Eine Seite je Selektor (aus dem Dashboard erreichbar) zeigt alle Belege und Signaturen und erlaubt einen manuellen Beleg mit Herkunftsvermerk.

### Export (D62, D63)

- `manifest.json` und `manifest.csv` je Signatur: `key_origin`, `key_sha256`, alle Belege.
- Ordner `schluessel/<name>/<key_sha256>/` mit `record.txt`, je Beleg die Rohantwort unverändert plus `beleg.json` (Quelle, Abfrage, Zeitpunkte, SHA-256), bei Rekonstruktion `signaturen.json` (`s`, `m`, `e`, Mail und Signatur je Eintrag) und `pruefe_rekonstruktion.py`, das nur mit der Python-Standardbibliothek `pow(s, e, n) == m` für jede Signatur nachrechnet. Alles in `SHA256SUMS`.
- PDF: Zeile „Herkunft des Schlüssels“; bei Stufe 4 der Hinweistext. `LIESMICH.txt` erklärt die vier Stufen.

## Was ein Gutachter nachvollziehen können muss

- Jede Rohantwort jeder Quelle unverändert, mit Abfrage (ohne Zugangsdaten), Zeitpunkt der Abfrage in UTC, SHA-256 und Mailrobbe-Version, auch die Antworten ohne Treffer.
- Die Zeitangaben der Quelle (erste und letzte Beobachtung) getrennt vom eigenen Abrufzeitpunkt.
- Bei Rekonstruktion: welche Signaturen verwendet wurden, der Exponent, der Modulus und ein Skript, das ohne Mailrobbe nachrechnet; die Verifikation selbst ist billig, nur das Finden ist teuer.
- Bei manuellen Belegen: wer ihn wann hinterlegt hat und worauf er sich stützt (Permalink, Datei mit SHA-256, URL).
- Dass externe Archive selbst vertrauenswürdige Dritte sind: ZK Email schreibt selbst, dass ihr Server derzeit die einzige vertrauenswürdige Partei ist; Zeitstempel über witness.co belegen nur, dass ein Eintrag zu einem Zeitpunkt existierte.
- Optional: den SHA-256 des Beleg-Ordners mit einem RFC-3161-Zeitstempel versehen. Nicht Teil des Plans, wenn nicht gewünscht.

## Quellenschutz

Jede Abfrage verrät etwas. Schon heute fragt die DKIM-Prüfung das DNS der Organisation nach Selektoren, die seit Jahren gelöscht sind; das sieht deren Nameserver (mit `MAILROBBE_DKIM_NAMESERVERS` auf einem öffentlichen Resolver nur dessen Adresse). Passive-DNS-Dienste ordnen jede Abfrage einem Konto zu. Deshalb: externe Abfragen nur auf Befehl, je Domain statt je Selektor, mit Vorschau, und nie Uploads.

## Reihenfolge und Aufwand

1. **Fundament und Offline-Quellen** (ein Meilenstein, etwa so groß wie M8): Tabellen, Herkunft in Prüfung, Liste, Detail und Export, Status `consistent`, Rekonstruktion als Job, Suche im eigenen Archiv, manuelle Belege, Batch-GCD. Kein Netz nötig, kein Quellenschutzproblem, deckt jeden RSA-Selektor mit zwei Signaturen ab.
2. **ZK-Email-Archiv und Abgleich** (klein): Abfrage je Domain mit Vorschau, Einordnung `live_dns` als Stufe 2 und `gcd_recovered` als Stufe 4, Vergleich rekonstruierter Schlüssel mit Archiv und heutigen Selektoren derselben Domain.
3. **Passive DNS** (klein je Anbieter, aber nur gegen aufgezeichnete Antworten testbar): zuerst DNSDB, dann SecurityTrails, sobald Aaron ein Konto hat.
4. **ARC-Zeugnis** (klein, getrennt): ARC-Siegel von Google und Microsoft prüfen und `dkim=pass` des Empfangsservers als eigenes Zeugnis anzeigen, nicht als Status.

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

- Eigener Status `consistent` für rekonstruierte Schlüssel statt `pass` mit Vermerk (Empfehlung: ja).
- Abfragen beim ZK-Email-Archiv erlauben, nur auf Knopfdruck mit Vorschau (Empfehlung: ja).
- Zugang zu DNSDB anfragen; Farsight bot 2019 investigativen Journalisten freien Zugang an, ob das noch gilt, ist unklar.
- gmpy2 als neue Abhängigkeit (Empfehlung: ja).
