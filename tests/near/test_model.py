"""The fingerprint of near duplicates (D152) on mail texts as the generator's clients write them."""

import pytest

from mailrobbe.near.model import MIN_WORDS, fingerprint, fingerprint_text


def lines(*rows: str) -> str:
    return "\n".join(rows)


BODY = (
    "",
    "kurze Rückfrage zu unserem Telefonat von gestern. Hast du die Zahlen",
    "schon an die Geschäftsführung weitergegeben? Ich bräuchte sie bis Montag.",
    "",
    "Viele Grüße",
    "Doris Schuster",
)
MAIL = lines("Hallo Martin,", *BODY)


def test_the_same_text_to_two_recipients_with_their_own_greetings() -> None:
    other = lines("Guten Tag Frau Dr. Sarah Vogt,", *BODY)
    assert fingerprint("Kurze Rückfrage", MAIL) == fingerprint("Kurze Rückfrage", other)
    assert fingerprint("Kurze Rückfrage", lines("Hallo zusammen,", *BODY)) == fingerprint(
        "Kurze Rückfrage", lines(*BODY[1:])
    )
    assert fingerprint_text("Kurze Rückfrage", MAIL) == (
        "kurze rückfrage\nkurze rückfrage zu unserem telefonat von gestern hast du die zahlen "
        "schon an die geschäftsführung weitergegeben ich bräuchte sie bis montag viele grüsse "
        "doris schuster"
    )


@pytest.mark.parametrize(
    "head",
    [
        (  # Thunderbird
            "-------- Weitergeleitete Nachricht --------",
            "Betreff: Kurze Rückfrage",
            "Datum: Donnerstag, 11. Mai 2023 15:19",
            "Von: Doris Schuster <doris.schuster@elbtal.example>",
            "An: Martin <martin@elbtal.example>",
            "",
        ),
        (  # webmail
            "---------- Forwarded message ---------",
            "From: Doris Schuster <doris.schuster@elbtal.example>",
            "Date: Thu, May 11, 2023 at 3:19 PM",
            "Subject: Kurze Rückfrage",
            "To: Martin <martin@elbtal.example>",
            "",
        ),
        (  # Apple Mail
            "Anfang der weitergeleiteten Nachricht:",
            "",
            "Von: Doris Schuster <doris.schuster@elbtal.example>",
            "Betreff: Kurze Rückfrage",
            "Datum: Donnerstag, 11. Mai 2023 15:19",
            "An: Martin <martin@elbtal.example>",
            "",
        ),
        (  # Outlook
            "_" * 32,
            "Von: Doris Schuster <doris.schuster@elbtal.example>",
            "Gesendet: Donnerstag, 11. Mai 2023 15:19",
            "An: Martin <martin@elbtal.example>",
            "Betreff: Kurze Rückfrage",
            "",
        ),
    ],
)
def test_a_forward_without_words_of_its_own_is_the_mail_it_forwards(head: tuple[str, ...]) -> None:
    original = fingerprint("Kurze Rückfrage", MAIL)
    assert original is not None
    assert fingerprint("WG: Kurze Rückfrage", lines(*head, MAIL)) == original
    assert fingerprint("Fwd: Kurze Rückfrage", lines("", *head, MAIL, "")) == original
    with_words = lines("Hallo Renate,", "", "siehe unten, was meinst du?", "", *head, MAIL)
    assert fingerprint("Fwd: Kurze Rückfrage", with_words) != original


def test_a_quote_without_an_answer_is_the_mail_it_quotes() -> None:
    quoted = lines(
        "Am 11.05.23 um 15:19 schrieb Doris Schuster:", *(f"> {row}" for row in MAIL.split("\n"))
    )
    assert fingerprint("Re: Kurze Rückfrage", quoted) == fingerprint("Kurze Rückfrage", MAIL)


def test_the_history_of_a_forwarded_reply_reads_like_the_reply() -> None:
    reply = lines(
        "Hallo Doris,",
        "",
        "die Zahlen sind schon unterwegs, du hast sie morgen früh auf dem Tisch.",
        "",
        "Am 11.05.23 um 15:19 schrieb Doris Schuster:",
        *(f"> {row}" for row in MAIL.split("\n")),
        "",
        "-----Ursprüngliche Nachricht-----",
        "Von: Jonas",
        "Gesendet: Mittwoch",
        "",
        "Erste Nachricht des Verlaufs.",
    )
    forward = lines(
        "_" * 32,
        "Von: Martin <martin@elbtal.example>",
        "Gesendet: Freitag, 12. Mai 2023 08:00",
        "Betreff: AW: Kurze Rückfrage",
        "",
        reply,
    )
    assert fingerprint("WG: AW: Kurze Rückfrage", forward) == fingerprint(
        "AW: Kurze Rückfrage", reply
    )


def test_replies_with_other_words_and_templates_with_other_amounts_stay_apart() -> None:
    reply = lines("Hallo Doris,", "", "die Zahlen kommen morgen, ich war krank.", "", "Martin")
    other = lines("Hallo Doris,", "", "die Zahlen kommen übermorgen, ich war krank.", "", "Martin")
    quote = lines("", "Am 11.05.23 um 15:19 schrieb Doris Schuster:", "> Hast du die Zahlen?")
    assert fingerprint("Re: Zahlen", reply + quote) != fingerprint("Re: Zahlen", other + quote)

    def reminder(invoice: str, amount: str) -> str:
        return lines(
            "Sehr geehrte Damen und Herren,",
            "",
            f"die Rechnung {invoice} über {amount} EUR ist noch offen. Bitte überweisen Sie",
            "den Betrag innerhalb der nächsten 10 Tage.",
        )

    first = fingerprint("Zahlungserinnerung", reminder("2025-3157", "22.548,44"))
    assert first is not None
    assert fingerprint("Zahlungserinnerung", reminder("2025-3157", "1.200,00")) != first
    assert fingerprint("Zahlungserinnerung", reminder("2025-3158", "22.548,44")) != first


def test_a_short_text_gets_no_fingerprint() -> None:
    assert fingerprint("Danke", "Danke, passt so!") is None
    assert (
        fingerprint("Re: Danke", lines("Hallo Max,", "", "danke, passt so.", "-- ", "Anna")) is None
    )
    assert fingerprint("Leer", None) is None
    words = " ".join(f"Wort{n}" for n in range(MIN_WORDS))
    assert fingerprint_text("x", words) is not None
    assert fingerprint_text("x", words.rpartition(" ")[0]) is None


@pytest.mark.parametrize(
    "subject",
    [
        "Projekt Lagerhalle Süd",
        "Re: AW: [ak-logistik] Projekt Lagerhalle Süd",
        "AW[2]: Projekt Lagerhalle Süd",
        "WG: Fwd: RE: Projekt Lagerhalle Süd",
        "[EXTERN] Antw: SV: VS: TR: Fw: Projekt Lagerhalle Süd",
        "  re : projekt lagerhalle süd ",
    ],
)
def test_reply_and_forward_prefixes_and_list_tags(subject: str) -> None:
    text = fingerprint_text(subject, MAIL)
    assert text is not None and text.startswith("projekt lagerhalle süd\n")


def test_a_subject_is_part_of_it() -> None:
    assert fingerprint("Kurze Rückfrage", MAIL) != fingerprint("Rückfrage Zahlen", MAIL)
    assert fingerprint(None, MAIL) == fingerprint("", MAIL) == fingerprint("Re:", MAIL)
