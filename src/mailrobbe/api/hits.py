"""How often q's full text words occur in a mail, by place (D174, D176): the count min_hits
compares and the figures the mail list and the mail detail show, from the same words
(FullText.counted) and by the same rules.

The places are the mail's subject and its own text (mail.tsv, weights A and B) and the file names
and texts of its attachments' documents (document.tsv, A and B; fulltext.MAIL_WEIGHTS and
DOCUMENT_WEIGHTS). Each counted words counts in each of its places, and the counts add up.

Stemmed, a words counts the positions of its lexemes in the tsvector that carry the weight of
the place. Its lexemes are its own tsvector's (to_tsvector of the words, which PostgreSQL computes
once while planning); a words with several lexemes, a phrase or a hyphenated word, counts as its
least frequent lexeme, and 0 when one is missing or it has none (a stop word). One unnest of a
tsvector serves every words and place: its lexemes are joined to the words' (_occurrences).
PostgreSQL keeps at most 256 positions per lexeme and puts every word beyond the 16,383rd at that
one position, so very long texts count low (D174). Whole words count the matches of
fulltext.word_regex, in any case, in the stored texts: mail.subject and body_text,
document.names and extracted_text (D173).

Only a mail or a document whose tsvector can hold a counted word in its places is looked at
(_holding), so that a text unrelated to the words is never unnested or read, and of the
documents only those of the mail's attachments: every attachment row counts, so a document
attached twice counts twice. hit_count is one expression correlated to mail, which
mail_conditions adds after the conditions the full text indexes serve, so it runs on their
candidates only; page_hits and mail_places run the same SQL (_own, _attached) for the mails of
a page or the attachments of one mail.

This module must not import filters.py, which imports it.
"""

from collections.abc import Sequence
from functools import reduce
from typing import Any

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    CompoundSelect,
    Integer,
    Select,
    Text,
    any_,
    func,
    literal,
    select,
    true,
    union_all,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.fulltext import (
    DOCUMENT_WEIGHTS,
    FIELDS,
    MAIL_WEIGHTS,
    TEXT_SEARCH,
    FullText,
    ts_query,
    weighted,
    weights,
    word_regex,
)
from mailrobbe.api.schemas import MailHitCounts, SearchField
from mailrobbe.db.models import Attachment, Document, Mail

_Select = Select[*tuple[Any, ...]]
_Rows = _Select | CompoundSelect[*tuple[Any, ...]]
# The stored text of each place, for whole words.
_TEXTS: dict[SearchField, Any] = {
    "subject": Mail.subject,
    "body": Mail.body_text,
    "filename": Document.names,
    "attachment": Document.extracted_text,
}


def hit_count(search: FullText) -> ColumnElement[int]:
    """The occurrences of search's counted words in the mail (correlated to mail) and the
    texts and file names of its attachments' documents, each in its places (D174)."""
    counts: list[ColumnElement[int]] = []
    if (holding := _holding(search, MAIL_WEIGHTS)) is not None:
        own = _occurrences(search, MAIL_WEIGHTS, Mail.tsv).subquery("occurrences")
        counts.append(select(_total(own)).where(Mail.tsv.bool_op("@@")(holding)).scalar_subquery())
    if (attached := _attached(search, Attachment.mail_id == Mail.id)) is not None:
        rows, documents = attached
        counts.append(documents.add_columns(_total(rows)).scalar_subquery())
    return reduce(lambda total, count: total + count, counts) if counts else literal(0, Integer)


async def page_hits(
    session: AsyncSession, mail_ids: Sequence[int], search: FullText
) -> dict[int, MailHitCounts]:
    """The counts by place of the mails of a page, every one of mail_ids present (D176)."""
    found = {mail_id: dict.fromkeys(FIELDS, 0) for mail_id in mail_ids}
    ids = literal(list(mail_ids), ARRAY(BigInteger))
    sides = [
        _own(search, Mail.id == any_(ids)),
        _by(search, Attachment.mail_id, Attachment.mail_id == any_(ids)),
    ]
    statements = [statement for statement in sides if statement is not None]
    if mail_ids and statements:
        for mail_id, place, count in await session.execute(_union(statements)):
            found[mail_id][place] += count
    return {mail_id: MailHitCounts(**counts) for mail_id, counts in found.items()}


async def mail_places(
    session: AsyncSession, mail_id: int, search: FullText
) -> tuple[MailHitCounts, dict[int, MailHitCounts]]:
    """The counts by place of one mail, as page_hits counts them, and those of each of its
    attachments whose document can hold a counted word, by attachment id (D176)."""
    own: dict[SearchField, int] = dict.fromkeys(FIELDS, 0)
    attachments: dict[int, dict[SearchField, int]] = {}
    statement = _own(search, Mail.id == mail_id)
    if statement is not None:
        for _, place, count in await session.execute(statement):
            own[place] += count
    statement = _by(search, Attachment.id, Attachment.mail_id == mail_id)
    if statement is not None:
        for attachment_id, place, count in await session.execute(statement):
            attachments.setdefault(attachment_id, dict.fromkeys(FIELDS, 0))[place] += count
            own[place] += count
    return MailHitCounts(**own), {
        attachment_id: MailHitCounts(**counts) for attachment_id, counts in attachments.items()
    }


def _own(search: FullText, where: ColumnElement[bool]) -> _Select | None:
    """Rows (mail id, place, count) of the mails meeting where that can hold a counted word in
    their own places; None when no counted word is looked for there."""
    holding = _holding(search, MAIL_WEIGHTS)
    if holding is None:
        return None
    rows = _occurrences(search, MAIL_WEIGHTS, Mail.tsv).lateral("occurrences")
    return (
        select(Mail.id, rows.c.place, _total(rows))
        .select_from(Mail)
        .join(rows, true())
        .where(where, Mail.tsv.bool_op("@@")(holding))
        .group_by(Mail.id, rows.c.place)
    )


def _by(search: FullText, key: Any, where: ColumnElement[bool]) -> _Select | None:
    """Rows (key, place, count) of _attached, key a column of attachment."""
    attached = _attached(search, where)
    if attached is None:
        return None
    rows, documents = attached
    return documents.add_columns(key, rows.c.place, _total(rows)).group_by(key, rows.c.place)


def _attached(search: FullText, where: ColumnElement[bool]) -> tuple[Any, _Select] | None:
    """The occurrences (place, count) in the documents of the attachments meeting where that
    can hold a counted word, and a select without columns yet of the attachments joined to
    their documents and these occurrences; None when no counted word is looked for in
    documents."""
    holding = _holding(search, DOCUMENT_WEIGHTS)
    if holding is None:
        return None
    rows = _occurrences(search, DOCUMENT_WEIGHTS, Document.tsv).lateral("occurrences")
    documents = (
        select()
        .select_from(Attachment)
        .join(Document, Document.id == Attachment.document_id)
        .join(rows, true())
        .where(where, Document.tsv.bool_op("@@")(holding))
    )
    return rows, documents


def _holding(search: FullText, places: dict[SearchField, str]) -> ColumnElement[Any] | None:
    """A tsquery that mail.tsv (places MAIL_WEIGHTS) or document.tsv (DOCUMENT_WEIGHTS) matches
    when it holds one of the counted words in one of the words' places there, as it must to
    hold the words as written too; None when no counted word is looked for in these places."""
    queries = [
        weighted(ts_query(words.websearch()), labels)
        for words, fields in search.counted
        if (labels := weights(fields, places))
    ]
    if not queries:
        return None
    return reduce(lambda found, query: found.op("||")(query), queries)


def _occurrences(search: FullText, places: dict[SearchField, str], vector: Any) -> _Rows:
    """Rows (place, count): each counted words in each of its places among places, correlated
    to the mail or the document whose tsvector is vector."""
    counted = [
        (index, words, place)
        for index, (words, fields) in enumerate(search.counted)
        for place in sorted(fields & places.keys())
    ]
    if search.whole_word:
        return _union(
            [
                select(
                    literal(place, Text).label("place"),
                    func.coalesce(
                        func.regexp_count(_TEXTS[place], word_regex(words), 1, "i"), 0
                    ).label("count"),
                ).correlate(Mail, Document)
                for _, words, place in counted
            ]
        )
    arrays = {
        index: func.tsvector_to_array(func.to_tsvector(TEXT_SEARCH, words.text))
        for index, words, _ in counted
    }
    lexemes = _union(
        [
            select(
                literal(index, Integer).label("words"),
                literal(place, Text).label("place"),
                literal(places[place], Text).label("weight"),
                func.unnest(arrays[index]).label("lexeme"),
            )
            for index, _, place in counted
        ]
    ).subquery("lexemes")
    # vector with these lexemes only (ts_delete removes all others, those left when they are
    # removed): unnesting it is cheaper than unnesting every lexeme of a long text
    others = func.tsvector_to_array(func.ts_delete(vector, reduce(func.array_cat, arrays.values())))
    only = func.ts_delete(vector, others)
    found = func.unnest(only).table_valued("lexeme", "weights", name="found")
    positions = func.cardinality(func.array_positions(found.c.weights, lexemes.c.weight))
    return (
        select(lexemes.c.place, func.min(func.coalesce(positions, 0)).label("count"))
        .select_from(lexemes.outerjoin(found, found.c.lexeme == lexemes.c.lexeme))
        .group_by(lexemes.c.words, lexemes.c.place)
    )


def _union(parts: Sequence[_Select]) -> _Rows:
    return parts[0] if len(parts) == 1 else union_all(*parts)


def _total(rows: Any) -> ColumnElement[int]:
    return func.coalesce(func.sum(rows.c.count), 0)
