"""Standard blocks in the entities phase (D205, D228): a mail's text is scanned with its blocks
blanked (phase.without_blocks), every position where it was; the subject and the documents'
texts are scanned whole."""

from typing import NamedTuple

import pytest

from mailrobbe.entities.extract import extract_entities
from mailrobbe.entities.model import scanned_text
from mailrobbe.entities.phase import without_blocks
from tests.entities.conftest import execute, rows, scan


class Span(NamedTuple):
    """A range of mail.blocks as the driver reads it (asyncpg's Range), half open."""

    lower: int | None
    upper: int | None


NOTICE = "Spendenkonto: Spende 50 EUR\nan DE89 3704 0044 0532 0130 00"
BODY = f"Danke für die Spende von 30 EUR in bar.\n\n{NOTICE}\n\nGruß Lea"
START, END = BODY.index(NOTICE), BODY.index(NOTICE) + len(NOTICE)


def test_a_block_becomes_spaces_of_its_length() -> None:
    blanked = without_blocks(BODY, [Span(START, END)])
    spaces = "\n".join(" " * len(line) for line in NOTICE.split("\n"))
    assert blanked == BODY[:START] + spaces + BODY[END:]
    assert blanked is not None and len(blanked) == len(BODY)


@pytest.mark.parametrize(
    ("text", "blocks", "expected"),
    [
        ("abc\ndef", [Span(1, 6)], "a  \n  f"),  # line breaks stay
        ("abcdef", [Span(0, 2), Span(4, 6)], "  cd  "),
        ("abcdef", [Span(4, 99)], "abcd  "),  # clipped to the text
        ("abcdef", [Span(4, None)], "abcd  "),
        ("abcdef", [Span(None, 2)], "  cdef"),
        ("abcdef", [Span(7, 9)], "abcdef"),  # beyond the text
        ("abcdef", [], "abcdef"),
        ("", [Span(0, 2)], ""),
        (None, [Span(0, 2)], None),
    ],
)
def test_without_blocks(text: str | None, blocks: list[Span], expected: str | None) -> None:
    assert without_blocks(text, blocks) == expected


@pytest.mark.db
@pytest.mark.slow
async def test_an_entity_inside_a_block_is_not_found(scanned_url: str) -> None:
    url = scanned_url
    subject = "Spende am Wochenende"  # scanned whole, as before
    [(blocked,), (plain,)] = await rows(
        url, "SELECT id FROM mail WHERE NOT has_attachments ORDER BY id LIMIT 2"
    )
    for mail in (blocked, plain):
        await execute(
            url,
            "UPDATE mail SET subject = :subject, body_text = :body WHERE id = :id",
            subject=subject,
            body=BODY,
            id=mail,
        )
        await execute(url, "DELETE FROM mail_entity_scan WHERE mail_id = :id", id=mail)
    await execute(
        url,
        "UPDATE mail SET blocks = CAST(CAST(:blocks AS text) AS int4multirange) WHERE id = :id",
        blocks=f"{{[{START},{END})}}",
        id=blocked,
    )
    result = await scan(url, workers=1)
    assert (result.mails, result.failed) == (2, 0)

    mentioned = """SELECT e.kind::text, e.key, m.occurrences, m.position FROM mail_entity m
                   JOIN entity e ON e.id = m.entity_id
                   WHERE m.mail_id = :id ORDER BY m.position, e.kind, e.key"""

    def mentions(text: str) -> list[tuple[str, str, int, int]]:
        found = extract_entities(scanned_text(subject, text))
        return sorted((f.kind.value, f.key, f.occurrences, f.position) for f in found)

    blanked = without_blocks(BODY, [Span(START, END)])
    assert blanked is not None
    assert sorted(await rows(url, mentioned, id=blocked)) == mentions(blanked)
    assert sorted(await rows(url, mentioned, id=plain)) == mentions(BODY)
    # inside the block nothing is found; outside it the same as in the whole text, at the same
    # position and with the occurrences outside the block
    inside = {("amount", "EUR 50.00"), ("iban", "DE89370400440532013000")}
    assert inside <= {row[:2] for row in mentions(BODY)}
    assert not inside & {row[:2] for row in mentions(blanked)}
    at = {row[:2]: row[3] for row in mentions(BODY)}
    assert all(at[row[:2]] == row[3] for row in mentions(blanked))
    assert ("amount", "EUR 30.00") in at
    assert {row[:2] for row in mentions(blanked)} == {row[:2] for row in mentions(BODY[:START])}
