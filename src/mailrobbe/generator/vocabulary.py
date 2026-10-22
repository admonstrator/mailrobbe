"""Built-in names, organisation stems and text building blocks for the generator.

Everything here is invented or generic. Organisation stems become domains below reserved TLDs
(.example, .test), so no generated address, host or Message-ID can point at a real domain.
"""

from dataclasses import dataclass

FIRST_NAMES_DE = (
    "Thomas", "Michael", "Andreas", "Stefan", "Christian", "Markus", "Frank", "Jürgen", "Klaus",
    "Peter", "Wolfgang", "Uwe", "Jörg", "Matthias", "Martin", "Sebastian", "Tobias", "Florian",
    "Daniel", "Alexander", "Jan", "Lukas", "Jonas", "Felix", "Maximilian", "Max", "Leon", "Paul",
    "Moritz", "Niklas", "Tim", "Philipp", "Benedikt", "Björn", "Sören", "Hans-Peter",
    "Karl-Heinz", "Günter", "Dieter", "Horst", "Bernd", "Ralf", "Holger", "Dirk", "Sven", "Kai",
    "Torsten", "Rüdiger", "Volker", "Sabine", "Petra", "Claudia", "Andrea", "Susanne", "Birgit",
    "Monika", "Karin", "Ute", "Gabriele", "Martina", "Nicole", "Stefanie", "Katrin", "Julia",
    "Anna", "Lena", "Laura", "Sarah", "Lisa", "Katharina", "Johanna", "Hannah", "Sophie", "Marie",
    "Lea", "Miriam", "Jana", "Franziska", "Christina", "Melanie", "Simone", "Anja", "Silke",
    "Heike", "Doris", "Renate", "Ingrid", "Bärbel", "Jutta", "Dörte", "Maike", "Annika", "Svenja",
    "Carolin", "Theresa", "Charlotte", "Clara", "Greta", "Anne-Kathrin",
)  # fmt: skip

SURNAMES_DE = (
    "Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner", "Becker", "Schulz",
    "Hoffmann", "Schäfer", "Koch", "Bauer", "Richter", "Klein", "Wolf", "Schröder", "Neumann",
    "Schwarz", "Zimmermann", "Braun", "Krüger", "Hofmann", "Hartmann", "Lange", "Schmitt",
    "Werner", "Schmitz", "Krause", "Meier", "Lehmann", "Schmid", "Schulze", "Maier", "Köhler",
    "Herrmann", "König", "Walter", "Mayer", "Huber", "Kaiser", "Fuchs", "Peters", "Lang",
    "Scholz", "Möller", "Weiß", "Jung", "Hahn", "Schubert", "Vogel", "Friedrich", "Keller",
    "Günther", "Frank", "Berger", "Winkler", "Roth", "Beck", "Lorenz", "Baumann", "Franke",
    "Albrecht", "Schuster", "Simon", "Ludwig", "Böhm", "Winter", "Kraus", "Martin", "Schumacher",
    "Krämer", "Vogt", "Stein", "Jäger", "Otto", "Sommer", "Groß", "Seidel", "Heinrich", "Brandt",
    "Haas", "Schreiber", "Graf", "Schulte", "Dietrich", "Ziegler", "Kuhn", "Kühn", "Pohl",
    "Engel", "Horn", "Busch", "Bergmann", "Voigt", "Sauer", "Arnold", "Wolff", "Pfeiffer",
    "Löffler", "Dreßler", "Nüßlein", "Gärtner", "Wöhler", "Brückner", "Jürgens", "Strauß",
    "von Bredow", "Meyer-Lüdenscheidt",
)  # fmt: skip

FIRST_NAMES_INTL = (
    "James", "John", "Emma", "Olivia", "Liam", "Sophia", "David", "Rachel", "Mehmet", "Ayşe",
    "Emre", "Elif", "Zeynep", "Piotr", "Łukasz", "Agnieszka", "Katarzyna", "Marco", "Giulia",
    "Luca", "Francesca", "Pierre", "Camille", "Élodie", "François", "Javier", "Lucía", "Sofía",
    "Mateo", "Søren", "Lars", "Astrid", "Pieter", "Anouk", "Daan", "Priya", "Rahul", "Wei",
    "Mei", "Hiroshi", "Yuki", "Ana", "João", "Nikolai", "Olga", "Siobhan", "Connor",
)  # fmt: skip

SURNAMES_INTL = (
    "Smith", "Johnson", "Brown", "Taylor", "Wilson", "Davies", "Evans", "O'Connor", "Y\u0131lmaz",
    "Kaya", "Demir", "Şahin", "Çelik", "Kowalski", "Nowak", "Wiśniewski", "Wójcik", "Rossi",
    "Russo", "Bianchi", "Romano", "Dubois", "Lefèvre", "Moreau", "García", "Fernández", "López",
    "Martínez", "Jensen", "Nielsen", "Hansen", "Andersson", "Johansson", "de Vries", "van Dijk",
    "Jansen", "Bakker", "Sharma", "Patel", "Kumar", "Chen", "Wang", "Tanaka", "Suzuki", "Sato",
    "Silva", "Santos", "Ivanov", "Petrova", "Murphy",
)  # fmt: skip

ACADEMIC_TITLES = ("Dr.", "Prof. Dr.", "Dr.-Ing.")

# Organisation names are a prefix and a branch word; the domain label is their slug, for
# example "Bergmann" + "Möbel" -> bergmann-moebel.example, shown as "Bergmann Möbel".
INTERNAL_PREFIXES = ("Nordwind", "Hafenkante", "Lindenhof", "Elbtal", "Weserland")
SUBSIDIARY_WORDS = ("Logistik", "Service", "Technik", "Digital")
ORG_PREFIXES_DE = (
    "Bergmann", "Hansen", "Alpenblick", "Kranich", "Lindenau", "Sonnenberg", "Falkenstein",
    "Moorwiese", "Ostwind", "Hafenblick", "Eichenwald", "Silberstreif", "Tannenhof", "Bachmann",
    "Schwanensee", "Birkenau", "Rosenfeld", "Steinbruch", "Wolkenlos", "Fuchsbau", "Seeblick",
    "Kornfeld", "Eisvogel", "Drachenfels", "Auenland", "Brunnenhof", "Feldberg", "Heidekraut",
    "Klippenrand", "Rotbuche", "Sandkamp", "Talsperre", "Weidenring", "Zugvogel", "Lerchenfeld",
    "Nordstern", "Hochmoor", "Kiefernweg", "Mühlenbach", "Grünwald",
)  # fmt: skip
ORG_WORDS_DE = (
    "Logistik", "Bau", "Technik", "Druck", "Software", "Versicherung", "Immobilien",
    "Consulting", "Agrar", "Solar", "Spedition", "Möbel", "Medien", "Kliniken", "Elektro",
    "Catering", "Steuerberatung", "Gartenbau", "Ingenieure", "IT", "Werbeagentur", "Reisen",
    "Backwaren", "Labor", "Recht", "Holz", "Getränke", "Maschinenbau", "Pflege", "Verlag",
    "Architekten", "Kunststoff", "Textil", "Personal", "Metall", "Energie",
)  # fmt: skip
ORG_PREFIXES_EN = (
    "Harbourline", "Northgate", "Bluefield", "Riverside", "Oakmont", "Silverline",
    "Brightwater", "Westbrook", "Stonehill", "Clearpath", "Redwood", "Lighthouse", "Copperleaf",
    "Fairhaven", "Greywater",
)  # fmt: skip
ORG_WORDS_EN = (
    "Systems", "Partners", "Analytics", "Legal", "Freight", "Labs", "Media", "Engineering",
    "Consulting", "Supply", "Ventures", "Design", "Shipping", "Research",
)  # fmt: skip

LEGAL_FORMS_DE = ("GmbH", "GmbH", "GmbH", "AG", "KG", "GmbH & Co. KG", "mbH")
LEGAL_FORMS_EN = ("Ltd", "Ltd", "Inc.", "LLC", "plc", "B.V.")

FREEMAIL_STEMS = (
    "webpost", "netzpost", "briefkasten", "postfach", "mailo", "inbox", "postamt", "fernpost",
)  # fmt: skip

# Service domains: (name words, kind of mails it sends, subdomain of the sending host, theme of
# its notifications).
SERVICES = (
    (("Kaufhaus", "Elbe"), "newsletter", "news", ""),
    (("Fachverlag", "Nordlicht"), "newsletter", "newsletter", ""),
    (("Reisewelt", "Sonne"), "newsletter", "mail", ""),
    (("Technikmarkt", "Ost"), "newsletter", "news", ""),
    (("Bücherwurm", "Versand"), "newsletter", "", ""),
    (("Sportwelt", "Süd"), "newsletter", "info", ""),
    (("Paketblitz",), "notification", "", "parcel"),
    (("Ticketwerk",), "notification", "support", "ticket"),
    (("Cloudablage",), "notification", "", "share"),
    (("Terminfinder",), "notification", "", "appointment"),
    (("Onlinebank", "Nord"), "notification", "service", "account"),
    (("Jobportal", "Mitte"), "notification", "", "account"),
    (("Stadtwerke", "Hallenau"), "invoice", "", ""),
    (("Mobilfunk", "Plus"), "invoice", "rechnung", ""),
    (("Hosting", "Süd"), "invoice", "billing", ""),
    (("Telefon", "Kompakt"), "invoice", "", ""),
    (("Leasing", "Nordost"), "invoice", "", ""),
    (("Bürobedarf", "Direkt"), "invoice", "shop", ""),
)

SERVICE_LOCALS = {
    "newsletter": ("newsletter", "news", "info", "mailing"),
    "notification": ("noreply", "no-reply", "benachrichtigung", "notification", "service"),
    "invoice": ("rechnung", "billing", "kundenservice", "noreply"),
    "list": ("listmaster", "mailman"),
}

# Hosts of mailing lists: (name words, list local part, list name); lists live on lists.<host>.
LIST_HOSTS = (
    (("Ruderverein", "Elbe"), "mitglieder", "Mitglieder"),
    (("Fachforum", "IT"), "diskussion", "Diskussion"),
    (("Open", "Source", "Nord"), "users", "Users"),
    (("Arbeitskreis", "Logistik"), "ak-logistik", ""),
    (("Elternbeirat", "Lindenschule"), "eltern", "Eltern"),
    (("Developer", "Community"), "general", "General"),
)

DEPARTMENTS = (
    "Geschäftsführung", "Vertrieb", "Einkauf", "Buchhaltung", "Personal", "IT", "Marketing",
    "Produktion", "Logistik", "Recht", "Kundenservice", "Qualitätssicherung",
)  # fmt: skip

ROLE_MAILBOXES = (
    ("info", "Info"), ("kontakt", "Kontakt"), ("buchhaltung", "Buchhaltung"),
    ("vertrieb", "Vertrieb"), ("support", "Support"), ("office", "Office"),
    ("einkauf", "Einkauf"), ("personal", "Personalabteilung"), ("empfang", "Empfang"),
)  # fmt: skip

# Landline numbers reserved by the German regulator for fiction (film and TV).
PHONE_PREFIXES = ("+49 30 23125", "+49 69 90009", "+49 40 66969", "+49 221 4710", "+49 89 99998")

CITIES_DE = (
    "Hamburg", "Bremen", "Hannover", "Berlin", "Leipzig", "Dresden", "Köln", "Düsseldorf",
    "Frankfurt am Main", "Stuttgart", "München", "Nürnberg", "Kiel", "Lübeck", "Münster",
)  # fmt: skip
# Their centres (latitude, longitude), where the photos of an outing are taken (D241).
CITY_POINTS = {
    "Hamburg": (53.5507, 9.9930), "Bremen": (53.0758, 8.8072), "Hannover": (52.3744, 9.7386),
    "Berlin": (52.5200, 13.4050), "Leipzig": (51.3397, 12.3731), "Dresden": (51.0504, 13.7373),
    "Köln": (50.9375, 6.9603), "Düsseldorf": (51.2277, 6.7735),
    "Frankfurt am Main": (50.1109, 8.6821), "Stuttgart": (48.7758, 9.1829),
    "München": (48.1372, 11.5755), "Nürnberg": (49.4521, 11.0767), "Kiel": (54.3233, 10.1228),
    "Lübeck": (53.8655, 10.6866), "Münster": (51.9607, 7.6261),
}  # fmt: skip
# Cameras and phones of the photos: make and model as EXIF writes them.
CAMERAS = (
    ("Apple", "iPhone 13"), ("Apple", "iPhone 15 Pro"), ("samsung", "SM-S911B"),
    ("Google", "Pixel 8"), ("Canon", "Canon EOS R6"), ("NIKON CORPORATION", "NIKON Z 6_2"),
    ("FUJIFILM", "X-T4"), ("SONY", "ILCE-7M3"),
)  # fmt: skip

WEEKDAYS_DE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")
WEEKDAYS_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MONTHS_DE = (
    "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
    "Oktober", "November", "Dezember",
)  # fmt: skip
MONTHS_EN = (
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December",
)  # fmt: skip

PROJECTS = (
    "Elbbrücke", "Nordlicht", "Phoenix", "Hafenkante 2", "Sonnenhof", "Leuchtturm", "Kompass",
    "Westflügel", "Neubau Halle 3", "Relaunch Website", "ERP-Umstellung", "Atlas", "Merkur",
    "Brückenkopf", "Lagerhalle Süd", "Pilot Hamburg", "Regenbogen", "Zugspitze",
)  # fmt: skip
PRODUCTS = (
    "Druckerpapier A4", "Laptops", "Bürostühle", "Serverschrank", "Etikettendrucker",
    "Hubwagen", "Lizenzpaket", "Ersatzteile", "Schutzhandschuhe", "Displays", "Kaffeemaschine",
)  # fmt: skip
SYSTEMS = ("ERP", "VPN", "Telefonanlage", "Fileserver", "Zeiterfassung", "WLAN", "CRM", "Wiki")
EVENTS_DE = (
    "Sommerfest", "Kick-off", "Messe", "Weihnachtsfeier", "Jahresgespräch", "Workshop",
    "Betriebsversammlung", "Kundentag", "Strategietag", "Schulung",
)  # fmt: skip
EVENTS_EN = (
    "Summer party", "Kick-off", "Trade fair", "Annual review", "Workshop", "Customer day",
    "Strategy offsite", "Training", "Board meeting",
)  # fmt: skip
MEETINGS_DE = ("Teamrunde", "Jour fixe", "Lenkungskreis", "Projektrunde", "Abteilungsrunde")
MEETINGS_EN = ("team meeting", "steering committee", "project meeting", "weekly sync")
PRODUCTS_EN = ("laptops", "office chairs", "server racks", "spare parts", "displays", "licences")
QUESTIONS_DE = (
    "Reisekosten", "Urlaubsantrag", "Zugang zum Laufwerk", "Datenschutz", "Dienstwagen",
    "Homeoffice", "Arbeitszeitkonto", "Spesenabrechnung", "Lieferbedingungen", "Rahmenvertrag",
)  # fmt: skip
QUESTIONS_EN = (
    "travel expenses", "the shared drive", "data protection", "payment terms",
    "the framework agreement", "remote work", "the onboarding", "delivery terms",
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class Topic:
    """A subject pattern with one argument slot and the sentences a mail on it is made of."""

    subject: str  # contains "{}" once, or not at all
    arg: str  # kind of argument: project, product, weekday, meeting, ...
    body: tuple[str, ...]
    reply: tuple[str, ...]

    @property
    def affixes(self) -> tuple[str, str]:
        prefix, _, suffix = self.subject.partition("{}")
        return prefix, suffix


# Sentence placeholders: {arg}, {weekday}, {time}, {date} (some days later), {past} (some days
# before), {n}, {amount}, {pct}, {month}, {city}, and in automated mail {bill} (a private
# invoice) and {threshold} (a small amount).
TOPICS_DE = (
    Topic(
        "Angebot {}",
        "project",
        (
            "anbei erhalten Sie wie besprochen unser Angebot für {arg}.",
            "Die Preise gelten bis Ende {month}, die Lieferzeit beträgt etwa {n} Wochen.",
            "Den Rabatt von {pct} % aus unserem letzten Gespräch haben wir bereits eingerechnet.",
            "Bei Rückfragen zum Angebot melden Sie sich gerne jederzeit.",
            "Über eine kurze Rückmeldung bis {weekday} würden wir uns freuen.",
        ),
        (
            "vielen Dank für das Angebot zu {arg}.",
            "Wir prüfen die Positionen intern und melden uns bis {weekday}.",
            "Könnten Sie die Position 3 noch einmal getrennt ausweisen?",
            "Das Angebot passt so, die Bestellung geht heute noch raus.",
        ),
    ),
    Topic(
        "Termin am {}",
        "weekday",
        (
            "passt Ihnen der {arg} um {time} Uhr für eine kurze Abstimmung?",
            "Wir können uns gerne bei uns im Büro treffen oder kurz telefonieren.",
            "Falls der Termin nicht passt, schlagen Sie gerne eine Alternative vor.",
            "Eine Einladung mit Einwahldaten schicke ich nach Ihrer Bestätigung.",
        ),
        (
            "der {arg} um {time} Uhr passt mir gut.",
            "Leider bin ich am {arg} unterwegs, ginge auch {weekday} Vormittag?",
            "Ich habe den Termin eingetragen, bis dann.",
            "Können wir eine halbe Stunde später anfangen?",
        ),
    ),
    Topic(
        "Protokoll {}",
        "meeting",
        (
            "anbei das Protokoll vom {past} ({arg}).",
            "Die offenen Punkte habe ich markiert und den Verantwortlichen zugeordnet.",
            "Bitte gebt bis {weekday} Bescheid, falls etwas fehlt oder falsch ist.",
            "Der nächste Termin ist am {weekday} um {time} Uhr.",
        ),
        (
            "danke für das Protokoll.",
            "Unter Punkt {n} fehlt noch der Hinweis zum Budget.",
            "Von meiner Seite passt alles.",
            "Ich ergänze meine Punkte direkt im Dokument.",
        ),
    ),
    Topic(
        "Rechnung Nr. {}",
        "invoice",
        (
            "die Rechnung Nr. {arg} über {amount} EUR ist laut unserer Buchhaltung noch offen.",
            "Wir bitten um Ausgleich innerhalb der nächsten {n} Tage.",
            "Sollte die Zahlung bereits erfolgt sein, betrachten Sie diese Nachricht als "
            "gegenstandslos.",
            "Die Rechnung finden Sie zur Sicherheit noch einmal im Anhang.",
        ),
        (
            "die Zahlung zur Rechnung {arg} ist gestern rausgegangen.",
            "Wir haben die Rechnung an die Buchhaltung weitergegeben.",
            "Bitte schicken Sie uns eine korrigierte Rechnung mit unserer Bestellnummer.",
        ),
    ),
    Topic(
        "Lieferung KW {}",
        "week",
        (
            "die Lieferung für KW {arg} verschiebt sich leider um {n} Tage.",
            "Grund ist ein Engpass bei unserem Vorlieferanten.",
            "Eine Teillieferung wäre bereits am {weekday} möglich.",
            "Bitte teilen Sie uns mit, ob Ihnen das so hilft.",
        ),
        (
            "danke für die Info zur Lieferung.",
            "Eine Teillieferung am {weekday} wäre uns sehr recht.",
            "Bitte halten Sie uns auf dem Laufenden.",
            "Das ist ärgerlich, wir brauchen die Ware spätestens Ende KW {arg}.",
        ),
    ),
    Topic(
        "Frage zu {}",
        "question",
        (
            "ich hätte eine kurze Frage zum Thema {arg}.",
            "Gibt es dafür ein Formular oder reicht eine formlose Mail?",
            "Im Wiki habe ich dazu leider nichts Aktuelles gefunden.",
            "Danke schon mal für die Hilfe.",
        ),
        (
            "das Formular liegt im Intranet unter Personal / Vorlagen.",
            "eine formlose Mail an die Personalabteilung reicht.",
            "Ich kläre das und melde mich bis {weekday}.",
            "Gute Frage, das hat sich zum {date} geändert.",
        ),
    ),
    Topic(
        "Projekt {}: aktueller Stand",
        "project",
        (
            "hier ein kurzer Zwischenstand zum Projekt {arg}.",
            "Die Planung ist zu etwa {pct} % abgeschlossen, die Ausschreibung läuft.",
            "Kritisch ist weiterhin der Termin für die Abnahme am {date}.",
            "Die Kosten liegen aktuell bei {amount} EUR und damit im Rahmen.",
            "Details besprechen wir am {weekday} in der Projektrunde.",
        ),
        (
            "danke für den Überblick.",
            "Können wir den Abnahmetermin noch um eine Woche schieben?",
            "Für die Projektrunde bringe ich die aktuellen Zahlen mit.",
            "Sieht gut aus, weiter so.",
        ),
    ),
    Topic(
        "Vertragsentwurf {}",
        "project",
        (
            "anbei der Vertragsentwurf für {arg} mit unseren Anmerkungen.",
            "Offen sind noch die Haftungsregelung und die Kündigungsfrist.",
            "Unsere Rechtsabteilung hat Paragraph {n} grundlegend überarbeitet.",
            "Bitte prüfen Sie den Entwurf bis {weekday}.",
        ),
        (
            "danke für den Entwurf.",
            "Mit den Änderungen in Paragraph {n} sind wir einverstanden.",
            "Die Kündigungsfrist von drei Monaten ist für uns zu lang.",
            "Wir schicken Ihnen bis {weekday} eine kommentierte Fassung.",
        ),
    ),
    Topic(
        "Einladung: {}",
        "event",
        (
            "hiermit laden wir herzlich zum {arg} am {date} ein.",
            "Beginn ist um {time} Uhr, für Essen und Getränke ist gesorgt.",
            "Bitte gebt bis {weekday} Bescheid, ob ihr dabei seid.",
            "Wir freuen uns auf euch.",
        ),
        (
            "ich bin dabei.",
            "Leider kann ich an dem Tag nicht, viel Spaß euch.",
            "Ich komme gerne, eventuell etwas später.",
        ),
    ),
    Topic(
        "Wartung {} am Wochenende",
        "system",
        (
            "am Samstag ab {time} Uhr wird das {arg} gewartet.",
            "In dieser Zeit ist das System nicht erreichbar.",
            "Bitte speichert eure Arbeit vorher und meldet euch ab.",
            "Bei Problemen nach der Wartung wendet euch bitte an den IT-Support.",
        ),
        (
            "danke für die Vorwarnung.",
            "Seit der Wartung funktioniert bei mir die Anmeldung nicht mehr.",
            "Gilt das auch für den Zugriff von außen?",
        ),
    ),
    Topic(
        "Unterlagen für {}",
        "event",
        (
            "anbei die Unterlagen für den {arg}.",
            "Die Präsentation ist noch nicht final, die Zahlen kommen bis {weekday}.",
            "Bitte schaut einmal drüber und gebt Feedback.",
        ),
        (
            "danke, ich schaue es mir heute Abend an.",
            "Auf Folie {n} ist ein Zahlendreher.",
            "Von mir aus kann das so raus.",
        ),
    ),
    Topic(
        "Urlaubsvertretung {}",
        "month",
        (
            "ich bin im {arg} für drei Wochen im Urlaub.",
            "Die Vertretung übernimmt in dieser Zeit das Team aus dem {dept}.",
            "Die wichtigsten offenen Vorgänge habe ich in einer Übergabe zusammengefasst.",
        ),
        (
            "danke für die Übergabe, ich übernehme gerne.",
            "Kannst du mir vorher noch die Zugangsdaten für das Kundenportal geben?",
            "Schönen Urlaub!",
        ),
    ),
    Topic(
        "Bestellung {}",
        "product",
        (
            "wir möchten gerne {n} Stück {arg} bestellen.",
            "Lieferadresse ist unser Lager in {city}.",
            "Bitte bestätigen Sie den Liefertermin und den Preis von {amount} EUR netto.",
        ),
        (
            "vielen Dank für Ihre Bestellung.",
            "Die Ware ist ab Lager verfügbar und geht morgen raus.",
            "Leider ist der Artikel erst in KW {n} wieder lieferbar.",
        ),
    ),
    Topic(
        "Kurze Rückfrage",
        "",
        (
            "kurze Rückfrage zu unserem Telefonat von gestern.",
            "Hast du die Zahlen schon an die Geschäftsführung weitergegeben?",
            "Ich bräuchte sie bis {weekday} für die Präsentation.",
        ),
        (
            "ja, die Zahlen sind gestern raus.",
            "Noch nicht, ich schicke sie dir heute bis {time} Uhr.",
            "Ich kümmere mich drum.",
        ),
    ),
)

TOPICS_EN = (
    Topic(
        "Quote for {}",
        "project",
        (
            "please find attached our quote for {arg} as discussed.",
            "Prices are valid until the end of {month}, delivery takes about {n} weeks.",
            "The {pct} % discount we talked about is already included.",
            "Let me know if you have any questions.",
        ),
        (
            "thanks for the quote for {arg}.",
            "We will review it internally and get back to you by {weekday}.",
            "Could you break out item 3 separately?",
        ),
    ),
    Topic(
        "Meeting on {}",
        "weekday",
        (
            "would {arg} at {time} work for a quick call?",
            "We can meet at our office or do it over the phone.",
            "If that does not suit you, feel free to suggest another slot.",
        ),
        (
            "{arg} at {time} works for me.",
            "I am travelling on {arg}, would {weekday} morning work instead?",
            "Sent you an invite, talk soon.",
        ),
    ),
    Topic(
        "Minutes: {}",
        "meeting",
        (
            "attached are the minutes of the {arg} on {past}.",
            "Open items are highlighted and assigned to an owner.",
            "Please let me know by {weekday} if anything is missing.",
        ),
        (
            "thanks for the minutes.",
            "Item {n} is missing the note on the budget.",
            "Looks complete from my side.",
        ),
    ),
    Topic(
        "Invoice {}",
        "invoice",
        (
            "according to our records invoice {arg} for EUR {amount} is still outstanding.",
            "Please arrange payment within the next {n} days.",
            "If you have already paid, please disregard this message.",
        ),
        (
            "payment for invoice {arg} went out yesterday.",
            "I have forwarded the invoice to our accounts payable team.",
        ),
    ),
    Topic(
        "Question about {}",
        "question",
        (
            "quick question about {arg}.",
            "Is there a form for this or is an email enough?",
            "From what I can tell the wiki page is out of date.",
            "Thanks in advance.",
        ),
        (
            "an email to HR is enough.",
            "Let me check and get back to you by {weekday}.",
            "Good question, this changed on {past}.",
        ),
    ),
    Topic(
        "Project {}: status update",
        "project",
        (
            "here is a short status update on project {arg}.",
            "Planning is about {pct} % complete and the tender is running.",
            "The acceptance date on {date} is still the critical point.",
            "We will go through the details on {weekday}.",
        ),
        (
            "thanks for the overview.",
            "Can we move the acceptance date by a week?",
            "Looks good, keep it up.",
        ),
    ),
    Topic(
        "Invitation: {}",
        "event",
        (
            "you are warmly invited to the {arg} on {date}.",
            "We start at {time}, food and drinks will be provided.",
            "Please let us know by {weekday} whether you can make it.",
        ),
        (
            "count me in.",
            "Unfortunately I cannot make it that day, have fun.",
        ),
    ),
    Topic(
        "Order {}",
        "product",
        (
            "we would like to order {n} units of {arg}.",
            "Please confirm the delivery date and the price of EUR {amount} net.",
        ),
        (
            "thank you for your order.",
            "The goods are in stock and will ship tomorrow.",
        ),
    ),
    Topic(
        "Quick question",
        "",
        (
            "quick follow-up on our call yesterday.",
            "Did you already send the figures to the management team?",
            "I need them by {weekday} for the presentation.",
        ),
        (
            "yes, they went out yesterday.",
            "Not yet, you will have them today by {time}.",
        ),
    ),
)

OPENERS_DE = ("ich hoffe, es geht Ihnen gut.", "wie besprochen hier die Infos.", "")
CLOSINGS_DE_FORMAL = ("Mit freundlichen Grüßen", "Freundliche Grüße", "Beste Grüße")
CLOSINGS_DE_INFORMAL = ("Viele Grüße", "Gruß", "LG", "Beste Grüße", "Danke und Gruß")
CLOSINGS_EN = ("Best regards", "Kind regards", "Cheers", "Thanks", "Best")

# Later answers in a thread: short, and fitting any topic.
FOLLOW_UPS_DE = (
    "danke, das hilft mir weiter.",
    "alles klar, dann machen wir es so.",
    "prima, danke für die schnelle Rückmeldung.",
    "passt, ich kümmere mich darum.",
    "verstanden, ich gebe es so weiter.",
    "Gut, dann warte ich auf die finale Version.",
    "Ich melde mich, sobald ich mehr weiß.",
    "Können wir das kurz telefonisch klären?",
)
FOLLOW_UPS_EN = (
    "thanks, that helps.",
    "sounds good, let's do it that way.",
    "great, thanks for the quick reply.",
    "Noted, I will take care of it.",
    "I will get back to you once I know more.",
    "Can we have a quick call about this?",
)
FORWARD_INTROS_DE = (
    "zur Info.",
    "kannst du dir das bitte einmal anschauen?",
    "siehe unten, was meinst du dazu?",
    "zur Kenntnis und mit der Bitte um Rückmeldung.",
)
FORWARD_INTROS_DE_FORMAL = (
    "zur Information.",
    "könnten Sie sich das bitte einmal ansehen?",
    "anbei die Nachricht unten, was meinen Sie dazu?",
    "zur Kenntnis und mit der Bitte um Rückmeldung.",
)
FORWARD_INTROS_EN = ("FYI.", "could you take a look at this?", "see below, what do you think?")

NEWSLETTER_SUBJECTS_DE = (
    "Ihr Newsletter im {month} {year}",
    "Nur bis Sonntag: {pct} % auf ausgewählte Artikel",
    "Neu im Sortiment: Unsere Highlights für den {season}",
    "Ihre persönlichen Empfehlungen",
    "Wochenrückblick KW {week}",
)
NEWSLETTER_SUBJECTS_EN = (
    "Your {month} newsletter",
    "Only until Sunday: {pct} % off selected items",
    "Your weekly digest",
)
# Notification subjects per theme: (German, English).
NOTIFICATION_SUBJECTS = {
    "parcel": (
        ("Ihr Paket ist unterwegs", "Ihre Sendung {n} wird heute zugestellt",
         "Zustellversuch für Sendung {n}"),
        ("Your parcel is on its way", "Your shipment {n} arrives today"),
    ),
    "ticket": (
        ("Ticket #{n} wurde aktualisiert", "Ihr Ticket #{n} wurde geschlossen",
         "Neue Antwort zu Ticket #{n}"),
        ("Ticket #{n} has been updated", "Your ticket #{n} was closed"),
    ),
    "share": (
        ("Ein Dokument wurde mit Ihnen geteilt", "Ihr Speicherplatz ist zu {pct} % belegt"),
        ("A file was shared with you", "Your storage is {pct} % full"),
    ),
    "appointment": (
        ("Erinnerung: Termin am {date}", "Ihr Termin am {date} wurde bestätigt"),
        ("Reminder: appointment on {date}", "Your appointment on {date} is confirmed"),
    ),
    "account": (
        ("Neue Nachricht in Ihrem Postfach", "Neue Anmeldung bei Ihrem Konto",
         "Ihr Passwort läuft in {days} Tagen ab"),
        ("New message in your inbox", "New sign-in to your account"),
    ),
    "list": (
        ("Erinnerung an Ihre Mitgliedschaft in Mailinglisten",
         "Bestätigung Ihres Abonnements", "Ihre Nachricht wartet auf Freigabe"),
        ("Mailing list memberships reminder", "Your message is awaiting moderator approval"),
    ),
    "intranet": (
        ("Ihr Urlaubsantrag wurde genehmigt",
         "Erinnerung: Zeiterfassung für KW {week} abschließen",
         "Ihr Passwort läuft in {days} Tagen ab",
         "Neue Aufgabe im Workflow: Freigabe Bestellung {n}",
         "Raumbuchung bestätigt: Besprechungsraum {room}"),
        ("Your leave request was approved", "Your password expires in {days} days"),
    ),
}  # fmt: skip
INTERNAL_NOTIFICATION_LINES_DE = (
    "diese Nachricht wurde automatisch vom Intranet erzeugt.",
    "Details finden Sie im Mitarbeiterportal unter Meine Vorgänge.",
    "Vorgangsnummer: {n}",
    "Bei Fragen wenden Sie sich bitte an den IT-Support.",
)
INVOICE_SUBJECTS_DE = (
    "Ihre Rechnung {month} {year}",
    "Rechnung Nr. {n}",
    "Ihre Rechnung ist da",
    "Zahlungserinnerung zur Rechnung {n}",
)
INVOICE_SUBJECTS_EN = ("Your invoice for {month} {year}", "Invoice {n}")

NEWSLETTER_LINES_DE = (
    "Entdecken Sie jetzt unsere neuen Angebote für den {season}.",
    "Nur für kurze Zeit: {pct} % Rabatt auf das gesamte Sortiment.",
    "Unsere Kundinnen und Kunden empfehlen in diesem Monat besonders die Neuheiten.",
    "Kostenloser Versand ab {threshold} EUR Bestellwert.",
    "Lesen Sie im Magazin, wie Sie im Alltag Energie sparen.",
)
NEWSLETTER_LINES_EN = (
    "Discover our new offers for the {season}.",
    "For a limited time only: {pct} % off everything.",
    "Free shipping on orders over EUR {threshold}.",
)
NOTIFICATION_LINES_DE = (
    "dies ist eine automatisch erzeugte Nachricht.",
    "Den aktuellen Status können Sie jederzeit in Ihrem Kundenkonto einsehen.",
    "Vorgangsnummer: {n}",
    "Bitte antworten Sie nicht auf diese E-Mail.",
)
NOTIFICATION_LINES_EN = (
    "this is an automatically generated message.",
    "You can check the current status in your account at any time.",
    "Reference number: {n}",
    "Please do not reply to this email.",
)
INVOICE_LINES_DE = (
    "Ihre aktuelle Rechnung über {bill} EUR steht ab sofort bereit.",
    "Der Betrag wird am {date} von Ihrem Konto abgebucht.",
    "Sie finden die Rechnung als PDF im Anhang oder in Ihrem Kundenportal.",
    "Kundennummer: {n}",
)
INVOICE_LINES_EN = (
    "Your current invoice for EUR {bill} is now available.",
    "The amount will be debited from your account on {date}.",
    "Customer number: {n}",
)
SEASONS_DE = ("Frühling", "Sommer", "Herbst", "Winter")
SEASONS_EN = ("spring", "summer", "autumn", "winter")

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

# Attachment templates: (file name pattern, MIME type, median size, spread, weight). Sizes are
# log-normal around the median; office files and PDFs are common, videos and archives rare.
# Placeholders: {year}, {month2}, {day2}, {n}, {project}, {word}. Every template carries a real
# file (generator.documents.TEMPLATES, which also adds association papers and recordings of its
# own).
ATTACHMENT_TYPES = (
    ("Angebot_{project}.pdf", "application/pdf", 90_000, 0.9, 3.0),
    ("Rechnung_{year}-{month2}.pdf", "application/pdf", 50_000, 0.6, 2.0),
    ("Protokoll_Sitzung.docx", _DOCX, 35_000, 0.8, 2.0),
    ("Angebot.xlsx", _XLSX, 25_000, 0.9, 2.0),
    ("IMG_{n}.jpg", "image/jpeg", 700_000, 0.7, 1.5),
    ("Scan_{year}{month2}{day2}_{n}.pdf", "application/pdf", 250_000, 0.9, 2.0),
    ("Präsentation_{project}.pptx", _PPTX, 900_000, 0.9, 0.6),
    ("Lieferschein_{n}.pdf", "application/pdf", 40_000, 0.6, 1.5),
    ("Übersicht_{year}.xlsx", _XLSX, 40_000, 0.9, 1.0),
    ("Vertrag_{project}_v{n}.docx", _DOCX, 60_000, 0.7, 1.0),
    ("Foto.png", "image/png", 250_000, 1.0, 0.8),
    ("Export_{year}{month2}.csv", "text/csv", 15_000, 1.2, 0.8),
    ("Notizen.txt", "text/plain", 2_000, 1.0, 0.6),
    ("Unterlagen.zip", "application/zip", 800_000, 1.2, 0.4),
    ("Bewerbung_{word}.pdf", "application/pdf", 500_000, 0.6, 0.4),
    ("Grundriss_{project}.pdf", "application/pdf", 500_000, 0.9, 0.5),
    ("Einladung.ics", "text/calendar", 2_000, 0.5, 1.0),
    ("Visitenkarte.vcf", "text/vcard", 800, 0.4, 0.6),
    ("Messe_Video.mp4", "video/mp4", 3_000_000, 0.8, 0.1),
    ("Katalog_{year}.pdf", "application/pdf", 1_500_000, 0.8, 0.2),
)
LARGE_ATTACHMENT_NAMES = (
    ("Projektarchiv_{year}.zip", "application/zip"),
    ("Aufzeichnung_Workshop.mp4", "video/mp4"),
    ("Baupläne_komplett.pdf", "application/pdf"),
    ("Datensicherung_{year}{month2}.zip", "application/zip"),
    ("Bildmaterial_Messe.zip", "application/zip"),
)
INLINE_IMAGE_NAMES = (("image001.png", "image/png"), ("image002.jpg", "image/jpeg"))
