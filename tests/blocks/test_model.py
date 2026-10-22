"""Paragraphs and their hashes (D224) on mail texts as clients write them: blank lines inside
quotes, the normal form, the length that counts, quoted paragraphs, the tail, the history."""

from mailrobbe.blocks.model import (
    MIN_CHARS,
    hash_hex,
    history,
    multirange,
    normalise,
    paragraph_hash,
    paragraphs,
    parse_hash,
)

NOTICE = "Diese Nachricht ist vertraulich und nur für den Empfänger bestimmt."


def lines(*rows: str) -> str:
    return "\n".join(rows)


def shown(text: str) -> list[tuple[str, bool, bool]]:
    """(text, quoted, tail) of every paragraph that counts."""
    found = paragraphs(text)
    for paragraph in found:
        assert paragraph.hash == paragraph_hash(text[paragraph.start : paragraph.end])
    return [(text[p.start : p.end], p.quoted, p.tail) for p in found]


def test_the_hash_of_one_text_is_pinned() -> None:
    # A change of the rule changes this hash: then PARAGRAPH_VERSION must rise, so that every
    # mail is split again.
    assert (
        normalise("> Rat für die  Spende\n>\tbitte  BEACHTEN")
        == "rat für die spende bitte beachten"
    )
    pinned = paragraph_hash("Rat für die Spende, bitte beachten Sie den Rechtshinweis.")
    assert pinned is not None and hash_hex(pinned) == "7198ac121813e610"
    value = paragraph_hash(NOTICE)
    assert value is not None and parse_hash(hash_hex(value)) == value
    assert -(2**63) <= value < 2**63


def test_quote_markers_case_and_white_space_do_not_make_another_paragraph() -> None:
    quoted = "> diese nachricht ist vertraulich\n>   und nur für den Empfänger bestimmt."
    assert paragraph_hash(quoted) == paragraph_hash(NOTICE)
    assert paragraph_hash(">> " + NOTICE.upper()) == paragraph_hash(NOTICE)
    assert paragraph_hash(NOTICE.replace("nur", "allein")) != paragraph_hash(NOTICE)


def test_a_paragraph_counts_from_min_chars_normalised() -> None:
    assert MIN_CHARS == 30
    short = "Wochenrückblick der Abteilung"  # 29 characters
    assert paragraph_hash(short) is None
    assert paragraph_hash(short + "A") is not None
    # quote markers and runs of white space do not make it longer
    assert paragraph_hash(">  Wochenrückblick  der\n>   Abteilung  ") is None
    assert paragraph_hash(">  Wochenrückblick  der\n>   Abteilung A") is not None
    text = lines("Hallo Max,", "", "Danke!", "", short, "", short + "A")
    assert [paragraph for paragraph, _, _ in shown(text)] == [short + "A"]


def test_paragraphs_end_at_blank_lines_also_inside_a_quote() -> None:
    quote = lines(
        "Am 17.10.2026 um 09:12 schrieb Jonas Brandt:",
        "> Hallo Anna, anbei der Entwurf mit der Haftungsklausel.",
        ">",
        "> > " + NOTICE,
        "> >",
        ">   ",
        "> Gruß Jonas",
    )
    text = lines("Passt so, ich schicke den Vertrag morgen an alle.", "", quote, "")
    assert shown(text) == [
        ("Passt so, ich schicke den Vertrag morgen an alle.", False, False),
        (
            "Am 17.10.2026 um 09:12 schrieb Jonas Brandt:\n"
            "> Hallo Anna, anbei der Entwurf mit der Haftungsklausel.",
            True,
            False,
        ),
        ("> > " + NOTICE, True, False),  # "Gruß Jonas" is too short
    ]
    assert paragraphs(text)[2].hash == paragraph_hash(NOTICE)


def test_the_tail_is_the_signature_and_the_end_of_the_own_text_but_not_its_start() -> None:
    first = "kurze Rückfrage zu unserem Telefonat von gestern, bitte um Rückruf."
    middle = "Ich bräuchte die Zahlen bis Montag, sonst verschiebt sich der Rat."
    text = lines(
        "Hallo Martin,",  # short, but it counts among the paragraphs of the own text
        "",
        first,
        "",
        middle,
        "",
        "Viele Grüße",
        "Doris",
        "",
        "-- ",
        "Doris Schuster, Abteilung Recht",
        "",
        "Sitz der Gesellschaft: Köln, Amtsgericht Köln HRB 19414",
    )
    # own paragraphs: greeting, first, middle, closing, two in the signature; the last three
    # are closing and the signature's, so only those of the signature are long enough
    assert shown(text) == [
        (first, False, False),
        (middle, False, False),
        ("Doris Schuster, Abteilung Recht", False, True),
        ("Sitz der Gesellschaft: Köln, Amtsgericht Köln HRB 19414", False, True),
    ]
    short = lines("Hallo,", "", middle, "", NOTICE)
    assert shown(short) == [(middle, False, True), (NOTICE, False, True)]
    # the first paragraph of the own text is never the tail, even when it is the only one
    assert shown(lines(NOTICE, "")) == [(NOTICE, False, False)]
    assert shown(lines(first, "", NOTICE)) == [(first, False, False), (NOTICE, False, True)]


def test_a_signature_with_and_without_its_separator_is_one_paragraph() -> None:
    signature = ("Anna Keller", "Nordlicht GmbH, Abteilung Recht")
    with_separator = lines("Passt so.", "", "-- ", *signature)
    without = lines("Passt so.", "", *signature)
    dropped = lines("Passt so.", "", "--", *signature)
    hashes = [[p.hash for p in paragraphs(text)] for text in (with_separator, without, dropped)]
    assert hashes[0] == hashes[1] == hashes[2] == [paragraph_hash("\n".join(signature))]
    assert shown(with_separator) == [("Anna Keller\nNordlicht GmbH, Abteilung Recht", False, True)]


def test_inline_answers_count_every_own_paragraph_across_the_quotes() -> None:
    answer = "Ja, Donnerstag um zehn Uhr passt mir gut, ich bringe alles mit."
    text = lines(
        "Hallo Peter,",
        "",
        "> Können wir den Termin für den Rat auf Donnerstag legen?",
        answer,
        "",
        "> Und bringst du die Unterlagen zur Spende mit, bitte?",
        "Mache ich, die Unterlagen liegen schon bereit im Büro.",
        "",
        "Gruß Anna",
    )
    # own paragraphs: greeting, answer, the second answer, closing; the last three of them
    # are the tail, and the quotes between them never are
    assert shown(text) == [
        ("> Können wir den Termin für den Rat auf Donnerstag legen?", True, False),
        (answer, False, True),
        ("> Und bringst du die Unterlagen zur Spende mit, bitte?", True, False),
        ("Mache ich, die Unterlagen liegen schon bereit im Büro.", False, True),
    ]


def test_originals_and_forwards_are_quoted_and_never_the_tail() -> None:
    text = lines(
        "Zur Info, siehe unten. Bitte bis Freitag ansehen und melden.",
        "",
        "-------- Weitergeleitete Nachricht --------",
        "Betreff: Spende",
        "Von: Jonas Brandt <j.brandt@stadtwerke.example>",
        "",
        NOTICE,
    )
    assert shown(text) == [
        ("Zur Info, siehe unten. Bitte bis Freitag ansehen und melden.", False, False),
        (
            "-------- Weitergeleitete Nachricht --------\nBetreff: Spende\n"
            "Von: Jonas Brandt <j.brandt@stadtwerke.example>",
            True,
            False,
        ),
        (NOTICE, True, False),
    ]


def test_history_is_the_quoted_segments_merged() -> None:
    reply = lines("Passt.", "", "Am 1.3.2019 um 10:12 schrieb Eva:", "> Treffen am Montag?", "")
    start = len("Passt.\n\n")
    assert history(reply) == [(start, len(reply))]
    assert multirange(history(reply)) == f"{{[{start},{len(reply)})}}"
    inline = lines("Hallo,", "> Frage eins?", "Antwort eins.", "> Frage zwei?", "Antwort.")
    assert history(inline) == [(7, 21), (35, 49)]
    assert history("Nur eigener Text.\n") == [] and multirange([]) is None
    # a quote right before a forward: one range
    both = lines("> zitiert", "-------- Weitergeleitete Nachricht --------", "Text")
    assert history(both) == [(0, len(both))]
    assert paragraphs("") == [] and history("") == []
