"""The contract of milestone 10: the scanned text of a mail and the scan version."""

from mailrobbe.entities.mentions import mentions
from mailrobbe.entities.model import scan_version, scanned_text


def test_scanned_text_puts_the_subject_on_its_own_line() -> None:
    assert scanned_text("Spende", "Betrag: 5.000 EUR") == "Spende\nBetrag: 5.000 EUR"
    assert scanned_text(None, None) == "\n"


def test_scan_version_is_a_stable_positive_31_bit_number() -> None:
    version = scan_version()
    assert 0 < version < 2**31
    assert scan_version() == version


def test_mentions_has_the_columns_the_api_reads() -> None:
    columns = [column.name for column in mentions().c]
    assert columns == ["entity_id", "mail_id", "occurrences", "context", "position", "document_id"]
