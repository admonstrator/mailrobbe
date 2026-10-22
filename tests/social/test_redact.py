"""What a social media image blacks out (D215, D216): the one rule, without a database.

The property every test rests on: after a redaction, no form of a redacted name is left in the
text the renderer is given, and the renderer draws nothing else.
"""

from mailrobbe.social.model import CardOptions, RedactionKind
from mailrobbe.social.redact import BLOCK, MAX_BLOCKS, MIN_BLOCKS, participant_terms, redactor
from tests.social.conftest import (
    IBAN,
    LABEL_NAME,
    RECIPIENT,
    RECIPIENT_NAME,
    SENDER,
    SENDER_NAME,
    export_mail,
    message,
)


def test_the_participants_are_gone_in_every_form() -> None:
    mail = export_mail(message())
    hide = redactor(mail, CardOptions())
    text = (
        f"Hallo Jürgen, {SENDER_NAME} schreibt an {RECIPIENT}. "
        f"WEISS und juergen.weiss sind dieselbe Person, {LABEL_NAME} auch."
    )
    done = hide.apply(text)
    for gone in ("Jürgen", "Anna", "Petrova", RECIPIENT, SENDER, "WEISS", "juergen.weiss", "Weiß"):
        assert gone.lower() not in done.text.lower()
    assert BLOCK in done.text
    assert done.redaction.counts[RedactionKind.PARTICIPANT] > 0


def test_the_terms_of_a_mail_are_its_addresses_names_and_their_words() -> None:
    terms = participant_terms(export_mail(message()))
    assert SENDER in terms and RECIPIENT in terms
    assert SENDER_NAME in terms and RECIPIENT_NAME in terms
    assert "Petrova" in terms and "petrova" in terms  # the name and the local part's word
    assert "Schatzmeister" in terms  # the role the team gave the address (D156)
    assert all(len(term) >= 4 for term in terms if " " not in term)
    assert terms == sorted(terms, key=lambda term: (-len(term), term))


def test_contact_data_in_the_text_goes_by_the_entity_rules() -> None:
    mail = export_mail(message())
    text = f"Konto {IBAN}, Tel. 030 1234567, post@dritte.example, Berlin bleibt."
    on = redactor(mail, CardOptions(participants=False)).apply(text)
    assert IBAN not in on.text
    assert "post@dritte.example" not in on.text
    assert "1234567" not in on.text
    assert "Berlin" in on.text  # organisations and places only on request
    assert on.redaction.counts[RedactionKind.CONTACT] == 3

    off = redactor(mail, CardOptions(participants=False, contacts=False, names=False)).apply(text)
    assert off.text == text
    assert off.redaction.places == 0


def test_organisations_and_places_only_on_request() -> None:
    mail = export_mail(message())
    text = "Der Kreisverband Musterstadt in Berlin, siehe https://beispiel.example/spenden."
    done = redactor(
        mail, CardOptions(participants=False, contacts=False, names=False, organizations=True)
    ).apply(text)
    assert "Musterstadt" not in done.text  # part of the organisation's name
    assert "Berlin" not in done.text
    assert "beispiel.example" not in done.text
    assert done.redaction.counts[RedactionKind.ORGANIZATION] >= 2


def test_the_teams_own_terms_hold_in_any_case() -> None:
    mail = export_mail(message())
    options = CardOptions(participants=False, contacts=False, names=False, terms=["Projekt Nord"])
    done = redactor(mail, options).apply("Zum projekt nord und zu Projekt Nord.")
    assert "rojekt" not in done.text
    assert done.redaction.counts[RedactionKind.TERM] == 2


def test_a_term_shorter_than_three_characters_blacks_out_nothing() -> None:
    mail = export_mail(message())
    options = CardOptions(participants=False, contacts=False, names=False, terms=["an", " ", ""])
    done = redactor(mail, options).apply("Wir danken Ihnen an dieser Stelle.")
    assert done.text == "Wir danken Ihnen an dieser Stelle."


def test_a_place_counts_in_the_first_category_that_covers_it() -> None:
    """A sender's address is a participant and an e-mail address of the text; it counts once,
    as the participant it is (the dialog lists the categories in that order)."""
    mail = export_mail(message())
    done = redactor(mail, CardOptions()).apply(f"Schreib an {SENDER}.")
    assert done.redaction.counts == {RedactionKind.PARTICIPANT: 1}


def test_overlapping_places_are_one_bar() -> None:
    mail = export_mail(message())
    options = CardOptions(participants=False, contacts=False, names=False, terms=["Spende", "nde"])
    done = redactor(mail, options).apply("Spende")
    assert set(done.text) == {BLOCK}
    assert done.redaction.places == 1


def test_a_bar_says_nothing_about_what_it_covers() -> None:
    mail = export_mail(message())
    options = CardOptions(participants=False, contacts=False, names=False, terms=["ab" * 60, "xyz"])
    long = redactor(mail, options).apply("ab" * 60)
    short = redactor(mail, options).apply("xyz")
    assert len(long.text) == MAX_BLOCKS
    assert len(short.text) == MIN_BLOCKS


def test_a_text_without_a_place_stays_as_it_is() -> None:
    mail = export_mail(message())
    done = redactor(mail, CardOptions()).apply("Die Sitzung beginnt um zehn.")
    assert done.text == "Die Sitzung beginnt um zehn."
    assert done.redaction.places == 0
