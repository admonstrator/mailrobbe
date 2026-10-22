"""Standard blocks in the topics (D205, D228): the vocabulary, the labels and the terms of a
selection leave the blocks (weight D of mail.tsv) out, quotes (C) stay in; the fingerprint
follows the standard blocks applied."""

from datetime import date

import pytest
from sqlalchemy import text

from mailrobbe.api.topics import _lexeme_counts
from tests.topics.conftest import M, compute, fingerprint_now, insert_mails, rows, sessions, value

pytestmark = pytest.mark.db

OWN = "Neue Termine im Verein."
QUOTE = "Am Montag schrieb Lea:\n> Der Wochenrückblick kommt."
NOTICE = "Rechtshinweis: KASSE KASSE KASSE Vertraulichkeit"
BODY = f"{OWN}\n\n{QUOTE}\n\n{NOTICE}"
BLOCKED = [M(BODY, date(2024, 2, 20 + day)) for day in range(4)]
_SET_RANGES = text("""
    UPDATE mail SET history = CAST(CAST(:history AS text) AS int4multirange),
                    blocks = CAST(CAST(:blocks AS text) AS int4multirange)
    WHERE id = ANY(CAST(:ids AS bigint[]))
""")


def _range(part: str) -> str:
    return f"{{[{BODY.index(part)},{BODY.index(part) + len(part)})}}"


async def with_blocks(url: str) -> list[int]:
    """BLOCKED into the sample, each mail's quote in history and its notice in blocks, as the
    blocks step would set them; their ids."""
    ids = await insert_mails(url, BLOCKED, path="blocks.mbox")
    async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
        ranges = {"history": _range(QUOTE), "blocks": _range(NOTICE), "ids": ids}
        await session.execute(_SET_RANGES, ranges)
    return ids


async def lexeme(url: str, word: str) -> str:
    return str(await value(url, "SELECT (ts_lexize('german_stem', lower(:w)))[1]", w=word))


async def test_a_word_only_in_standard_blocks_is_no_term(sample_url: str) -> None:
    url = sample_url
    ids = await with_blocks(url)
    assert await compute(url) is not None
    terms = {
        row[0]: row[1:] for row in await rows(url, "SELECT lexeme, label, mails FROM topic_term")
    }
    holding = "SELECT count(*) FROM mail WHERE tsv @@ CAST(quote_literal(:l) AS tsquery)"
    for word in ("Rechtshinweis", "Vertraulichkeit"):
        found = await lexeme(url, word)
        assert await value(url, holding, l=found) == len(BLOCKED), word  # in mail.tsv, as D
        assert found not in terms, word
    # the quote counts, with its spelling
    assert terms[await lexeme(url, "Wochenrückblick")] == ("Wochenrückblick", len(BLOCKED))
    # "Kasse" is a term of SAMPLE: the blocks add no mail and their spelling is not its label
    assert terms["kass"] == ("Kasse", 4)

    async with sessions(url) as sessionmaker, sessionmaker() as session:
        counted = {row.lexeme: row.a for row in await session.execute(_lexeme_counts(ids))}
    assert counted[await lexeme(url, "Wochenrückblick")] == len(BLOCKED)
    assert counted["verein"] == len(BLOCKED)
    assert "kass" not in counted


async def test_the_fingerprint_follows_the_standard_blocks(sample_url: str) -> None:
    url = sample_url
    assert await compute(url) is not None
    assert await fingerprint_now(url) is None
    insert = text("""
        INSERT INTO paragraph_block (hash, standard, detected, mails, senders, sample)
        VALUES (:hash, :standard, true, 30, 2, 'Rechtshinweis: vertraulich')
    """)
    async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
        await session.execute(insert, {"hash": 17, "standard": False})
    assert await fingerprint_now(url) is None  # a block taken back is applied to no mail
    async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
        await session.execute(insert, {"hash": 18, "standard": True})
    waiting = await fingerprint_now(url)
    assert waiting is not None
    assert await compute(url) is not None
    assert await fingerprint_now(url) is None
    async with sessions(url) as sessionmaker, sessionmaker() as session, session.begin():
        await session.execute(text("UPDATE paragraph_block SET standard = NOT standard"))
    assert await fingerprint_now(url) not in (None, waiting)
