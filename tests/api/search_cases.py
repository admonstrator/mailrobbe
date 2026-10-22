"""A small archive of the cases of a search for "Neger" (D170): stems, file names, French words,
attachments, many occurrences, accents. Each mail has the Message-ID <case-N@verein.example>,
N its index in CASES, and the list's order is N (one day apart).

What the full text search finds for "Neger", by place (whole words / German stems):

    N  subject      body         attachment text  file names     note
    0  1 / 1        3 / 3        -                -             Neger-Witze, hyphenated
    1  -            1 / 1        -                -
    2  -            0 / 1        -                -             Negern: stem only
    3  -            0 / 1        -                -             French "negere": stem only
    4  -            0 / 1        -                -             French "negere": stem only
    5  -            -            -                0 / 2         Scan_NEG_..., NEG-Liste_...
    6  -            -            1 / 1            -             the word in an attachment only
    7  1 / 1        6 / 6        -                -             "NEGER RAUS"
    8  -            -            -                -             négère: no stem, no word
    9  -            -            -                -             nothing
"""

from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime
from pathlib import Path

# (sender, recipient, subject, body, [(file name, text)])
Case = tuple[str, str, str, str, list[tuple[str, str]]]
CASES: list[Case] = [
    (
        "karl.huber@verein.example",
        "vorstand@verein.example",
        "Neger-Witze im Verteiler",
        "Im Verteiler kursieren wieder Neger-Witze. Wer hat den Neger-Witz von gestern "
        "weitergeleitet? Das Wort Neger hat bei uns nichts verloren.",
        [],
    ),
    (
        "maria.berger@verein.example",
        "karl.huber@verein.example",
        "Re: Stammtisch",
        "Am Stammtisch fiel wieder das Wort Neger. Ich habe widersprochen.",
        [],
    ),
    (
        "maria.berger@verein.example",
        "presse@verein.example",
        "Stellungnahme",
        "Er hat von den Negern gesprochen, die angeblich das Viertel übernehmen.",
        [],
    ),
    (
        "jean.dupont@partenaire.example",
        "info@verein.example",
        "Réunion du comité",
        "Il ne faut pas negere les remarques du comité. La réunion aura lieu mardi.",
        [],
    ),
    (
        "jean.dupont@partenaire.example",
        "info@verein.example",
        "Compte rendu",
        "Le président a dit qu'on ne peut pas negere ce problème.",
        [],
    ),
    (
        "buchhaltung@verein.example",
        "vorstand@verein.example",
        "Belege März",
        "Anbei die gescannten Belege.",
        [
            ("Scan_NEG_2019-03.txt", "Quittung 120 Euro Saalmiete"),
            ("NEG-Liste_final.txt", "Positionen ohne Beleg: 4"),
        ],
    ),
    (
        "karl.huber@verein.example",
        "vorstand@verein.example",
        "Protokoll Klausur",
        "Das Protokoll liegt im Anhang.",
        [
            (
                "Protokoll_Klausur.txt",
                "TOP 3: Beschwerde über die Äußerung, man solle die Neger zurückschicken. "
                "Der Vorstand distanziert sich.",
            )
        ],
    ),
    (
        "anonym@extern.example",
        "info@verein.example",
        "NEGER RAUS",
        "Neger raus. Neger raus. Neger raus! Die Neger sollen gehen. Neger, Neger.",
        [],
    ),
    (
        "lea.wagner@verein.example",
        "info@verein.example",
        "Lesung",
        "Die Lesung heißt « négère » und ist ein Kunstwort der Autorin.",
        [],
    ),
    (
        "lea.wagner@verein.example",
        "info@verein.example",
        "Termine",
        "Die nächste Sitzung ist am Dienstag.",
        [],
    ),
]


def message_id(index: int, name: str = "case") -> str:
    return f"<{name}-{index}@verein.example>"


def write_search_cases(path: Path) -> None:
    """CASES as one MBOX file at path."""
    write_cases(path, CASES)


def write_cases(path: Path, cases: list[Case], name: str = "case") -> None:
    """cases as one MBOX file at path, the Message-ID of each message_id(N, name) for its index
    N, one day apart from 1 March 2021 on."""
    lines: list[bytes] = []
    for index, (sender, recipient, subject, body, attachments) in enumerate(cases):
        message = EmailMessage()
        message["From"] = sender
        message["To"] = recipient
        message["Subject"] = subject
        message["Date"] = format_datetime(datetime(2021, 3, 1, 10, tzinfo=UTC) + timedelta(index))
        message["Message-ID"] = message_id(index, name)
        message.set_content(body + "\n")
        for filename, text in attachments:
            data = (text + "\n").encode()
            message.add_attachment(data, maintype="text", subtype="plain", filename=filename)
        lines.append(f"From {sender} Mon Mar  1 10:00:00 2021\n".encode())
        for line in message.as_bytes().splitlines(keepends=True):
            lines.append(b">" + line if line.lstrip(b">").startswith(b"From ") else line)
        lines.append(b"\n")
    path.write_bytes(b"".join(lines))
