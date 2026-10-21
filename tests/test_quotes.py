"""Quoted text (D151): the segments of mail texts as the generator's clients write them, and the
lines the fingerprint of near duplicates reads (D152)."""

import itertools
import re

from mailrobbe.api.body import mail_text
from mailrobbe.mbox import read_message
from mailrobbe.quotes import split_text, unquoted_lines
from tests.conftest import GeneratedArchive


def lines(*rows: str) -> str:
    return "\n".join(rows)


def split(text: str) -> list[tuple[str, str, int, bool]]:
    """(kind, text, lines, folded) of every segment; they cover the text in order."""
    segments = split_text(text)
    assert "".join(text[segment.start : segment.end] for segment in segments) == text
    assert all(a.end == b.start for a, b in itertools.pairwise(segments))
    return [
        (segment.kind, text[segment.start : segment.end], segment.lines, segment.folded)
        for segment in segments
    ]


def kinds(text: str) -> list[tuple[str, bool]]:
    return [(kind, folded) for kind, _, _, folded in split(text)]


QUOTED_SIGNATURE = (
    "> Freundliche Grüße",
    ">",
    "> -- ",
    "> Dörte Lehmann",
    "> Elbtal GmbH",
)


def test_a_text_without_quotes_is_one_open_segment() -> None:
    text = lines("Hallo Max,", "", "bis morgen.", "")
    assert split(text) == [("text", text, 2, False)]
    assert split("") == [("text", "", 0, False)]


def test_thunderbird_top_posting_with_signature_and_quoted_history() -> None:
    own = lines("Hallo zusammen,", "", "einverstanden.", "", "Freundliche Grüße", "", "")
    signature = lines("-- ", "Daniel Ludwig", "Kundenservice", "", "")
    quote = lines(
        "Am 13.06.24 um 03:01 schrieb Dörte Lehmann:",
        "> Hallo zusammen,",
        ">",
        "> anbei der Vertragsentwurf.",
        *QUOTED_SIGNATURE,
    )
    assert split(own + signature + quote) == [
        ("text", own, 3, False),
        ("signature", signature, 3, True),
        ("quote", quote, 7, True),  # the history: nothing of the sender's own follows
    ]


def test_thunderbird_bottom_posting_opens_a_short_quote_and_folds_a_long_one() -> None:
    quote = lines(
        "On 3/10/20 9:33 AM, Connor Wiśniewski wrote:",
        "> Hi all,",
        ">",
        "> invoice 2020-0931 is still outstanding.",
        "",
        "",
    )
    own = lines("Hi all,", "", "Payment went out yesterday.", "", "Kind regards", "", "")
    signature = lines("-- ", "Marie Stein", "")
    assert split(quote + own + signature) == [
        ("quote", quote, 3, False),  # between own words and at most five lines
        ("text", own, 3, False),
        ("signature", signature, 2, True),
    ]
    long_quote = lines(
        "Am 13.06.24 um 03:01 schrieb Dörte Lehmann:", *(f"> Zeile {n}" for n in range(6))
    )
    assert kinds(long_quote + "\n\n" + own) == [("quote", True), ("text", False)]


def test_webmail_and_apple_attributions() -> None:
    for attribution in (
        "Am 14.06.2018 08:35, schrieb Prof. Dr. Theresa Busch:",
        "Am 02.02.2018 um 14:49 schrieb Office Bergmann <office@bergmann-architekten.test>:",
        "On Tue, May 21, 2024 at 13:20, Franziska Klein <franziska.klein@elbtal.example> wrote:",
    ):
        own = lines("Hallo zusammen,", "", "passt.", "", "Günter Voigt", "", "")
        quote = lines(attribution, "> Hallo zusammen,", ">", "> passt Ihnen der Mittwoch?", "")
        assert split(own + quote) == [("text", own, 3, False), ("quote", quote, 3, True)]


def test_an_attribution_wrapped_onto_two_lines() -> None:
    quote = lines(
        "On Fri, Oct 17, 2026 at 9:05 AM Jonas Brandt",
        "<j.brandt@stadtwerke-beispiel.example> wrote:",
        "",
        "> Hi",
    )
    assert split("Danke!\n\n" + quote) == [
        ("text", "Danke!\n\n", 1, False),
        ("quote", quote, 3, True),
    ]


def test_outlook_original_below_a_rule_of_underscores() -> None:
    own = lines("Hallo Klaus,", "", "Die Ware geht morgen raus.", "", "Jonas Weiß", "Marketing", "")
    original = lines(
        "_" * 32,
        "Von: Klaus Lange <klaus.lange@elbtal-technik.example>",
        "Gesendet: Mittwoch, 14. Juni 2017 17:30",
        "An: Jonas Weiß <jonas.weiss@elbtal-technik.example>",
        "Betreff: Bestellung Schutzhandschuhe",
        "",
        "Hallo Jonas,",
        "",
        "> nicht als Zitat zu lesen",
        "-- ",
        "Klaus Lange",
    )
    assert split(own + original) == [("text", own, 4, False), ("original", original, 9, True)]


def test_outlook_separators_and_its_text_export() -> None:
    for head in (
        ("-----Original Message-----", "From: Anouk Kowalski", "Sent: Monday, February 20, 2012"),
        ("-----Ursprüngliche Nachricht-----", "Von: Anouk", "Gesendet: Montag, 20. Februar 2012"),
        ("*Von:* Anouk Kowalski", "*Gesendet:* Montag, 20. Februar 2012 17:41", "*An:* Andrea"),
        ("From: Anouk", "To: Andrea", "Sent: Monday"),  # Sent within three lines of From
    ):
        original = lines(*head, "Subject: Order", "", "We would like to order 8 laptops.")
        assert split("Thanks.\n\n" + original) == [
            ("text", "Thanks.\n\n", 1, False),
            ("original", original, len(head) + 2, True),
        ]
    assert kinds(lines("Von: Anna", "bis morgen", "", "Gruß")) == [("text", False)]


def test_forwards_run_to_the_end() -> None:
    heads = (
        ("-------- Weitergeleitete Nachricht --------", "Betreff: Kurze Rückfrage"),
        ("---------- Weitergeleitete Nachricht ----------", "Betreff: Kurze Rückfrage"),
        ("---------- Forwarded message ---------", "From: Doris <doris@elbtal.example>"),
        ("-------- Forwarded Message --------", "Subject: Invoice 2025-3157"),
        ("Anfang der weitergeleiteten Nachricht:", "", "Von: Nicole Winkler"),
        ("Begin forwarded message:", "", "From: Nicole Winkler"),
    )
    for head in heads:
        forward = lines(*head, "", "Hallo zusammen,", "> zitiert", "", "-- ", "Doris")
        own = lines("Hallo Renate,", "", "siehe unten.", "", "")
        assert split(own + forward) == [
            ("text", own, 2, False),
            ("forward", forward, len(head) - head.count("") + 4, True),
        ]


def test_a_text_without_words_of_its_own_shows_its_first_segment() -> None:
    forward = lines("-------- Weitergeleitete Nachricht --------", "Betreff: Termin", "", "Text")
    assert kinds(forward) == [("forward", False)]
    assert kinds("\n\n" + forward) == [("forward", False)]  # blank lines join the first one
    quote = lines("Am 1.1.2026 schrieb X:", "> alt", "", "-- ", "Anna")
    assert kinds(quote) == [("quote", False), ("signature", True)]
    original = lines("Danke.", "-----Original Message-----", "From: x")
    assert kinds(original) == [("text", False), ("original", True)]


def test_inline_answers_stay_open() -> None:
    text = lines(
        "> Frage eins?",
        "Antwort eins.",
        "",
        "> Frage zwei?",
        ">",
        "> Noch eine Zeile?",
        "Antwort zwei.",
        "",
        "> Gruß",
        "> Jonas",
    )
    assert split(text) == [
        ("quote", "> Frage eins?\n", 1, False),
        ("text", "Antwort eins.\n\n", 1, False),
        ("quote", "> Frage zwei?\n>\n> Noch eine Zeile?\n", 2, False),
        ("text", "Antwort zwei.\n\n", 1, False),
        ("quote", "> Gruß\n> Jonas", 2, True),
    ]
    assert kinds(lines("Hallo,", "> Frage?", "Antwort darunter.")) == [
        ("text", False),
        ("quote", False),
        ("text", False),
    ]


def test_a_signature_without_the_space_and_crlf_line_ends() -> None:
    assert kinds(lines("Gruß", "--", "Anna Keller")) == [("text", False), ("signature", True)]
    assert kinds("Ja.\r\n-- \r\nAnna\r\n> Frage?\r\n") == [
        ("text", False),
        ("signature", True),
        ("quote", True),
    ]
    # A signature ends where a quote begins, and runs on over own words otherwise.
    assert kinds(lines("Gruß", "-- ", "Anna", "", "noch ein Satz")) == [
        ("text", False),
        ("signature", True),
    ]


def test_unquoted_lines_drop_markers_attributions_and_every_header_block() -> None:
    text = lines(
        "-------- Weitergeleitete Nachricht --------",
        "Betreff: Kurze Rückfrage",
        "Von: Doris",
        "",
        "Hallo zusammen,",
        "",
        "Am 1.1.2026 um 10:00 schrieb Jonas:",
        "> > alte Frage",
        "",
        "_" * 32,
        "Von: Klaus",
        "Gesendet: Mittwoch",
        "Betreff: Bestellung",
        "",
        "Hallo Jonas,",
    )
    assert unquoted_lines(text) == [
        "",
        "Hallo zusammen,",
        "",
        "alte Frage",
        "",
        "",
        "Hallo Jonas,",
    ]
    assert unquoted_lines("Anfang der weitergeleiteten Nachricht:\n\nVon: X\nAn: Y\n\nText") == [
        "",
        "Text",
    ]


_HISTORY = re.compile(
    r"^(>|-{2,} ?(Weitergeleitete Nachricht|Forwarded Message|Ursprüngliche Nachricht|Original "
    r"Message)|_{32}$|Anfang der weitergeleiteten Nachricht:|Begin forwarded message:)",
    re.M | re.I,
)


def test_no_history_of_the_generated_mails_stays_in_their_own_text(
    generated_archive: GeneratedArchive,
) -> None:
    replies = 0
    for record in generated_archive.manifest:
        raw = read_message(
            generated_archive.mbox_dir / record["file"], record["offset"], record["length"]
        )
        text = mail_text(raw).text
        segments = split(text)
        own = "".join(part for kind, part, _, _ in segments if kind in ("text", "signature"))
        assert not _HISTORY.search(own), record["index"]
        if record["in_reply_to"] and _HISTORY.search(text):
            replies += 1
            assert any(folded for _, _, _, folded in segments) or len(segments) > 1
    assert replies > 50
