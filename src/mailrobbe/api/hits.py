"""How often q's full text words occur in a mail, by place (D174, D176): the count min_hits
compares and the figures the mail list and the mail detail show, from the same words
(FullText.counted) and by the same rules.

The places are the mail's subject and its own text (mail.tsv, weight A, and the weights of the
parts of the text body_part looks at, D226) and the file names and texts of its attachments'
documents (document.tsv, A and B; fulltext.mail_weights and DOCUMENT_WEIGHTS). Each counted
words counts in each of its places, and the counts add up.

Stemmed, a words counts the positions of its lexemes in the tsvector that carry a weight of the
place. Its lexemes are its own tsvector's (to_tsvector of the words, which PostgreSQL computes
once while planning); a words with several lexemes, a phrase, a hyphenated word or a proximity
term (D229), counts as its least frequent lexeme, and 0 when one is missing or it has none (a
stop word). One unnest of a tsvector serves every words and place: its lexemes are joined to the
words' (_occurrences). PostgreSQL keeps at most 256 positions per lexeme and puts every word
beyond the 16,383rd at that one position, so very long texts count low (D174). Whole words, and
quoted words and phrases (D341, FullText.exact), count the matches of fulltext.word_regex, in any
case, in the stored texts: mail.subject and body_text cut to body_part's parts, document.names
and extracted_text (D173, fulltext.stored_texts).

Only a mail or a document whose tsvector can hold a counted word in its places is looked at
(_holding), so that a text unrelated to the words is never unnested or read, and of the
documents only those of the mail's attachments: every attachment row counts, so a document
attached twice counts twice. hit_count is one expression correlated to mail, which
mail_conditions adds after the conditions the full text indexes serve, so it runs on their
candidates only; page_hits and mail_places run the same SQL (_own, _attached) for the mails of
a page or the attachments of one mail, and machine_hits for the mails of a page whose words stand
in a text an AI run recognised or transcribed (D189, D296).

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
    and_,
    any_,
    cast,
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
    TEXT_SEARCH,
    FullText,
    mail_weights,
    stored_texts,
    weighted,
    weights,
    word_regex,
    words_query,
)
from mailrobbe.api.schemas import MailHitCounts, SearchField
from mailrobbe.db.models import Attachment, Document, Mail
from mailrobbe.enums import TextOrigin

_Select = Select[*tuple[Any, ...]]
_Rows = _Select | CompoundSelect[*tuple[Any, ...]]


def hit_count(search: FullText) -> ColumnElement[int]:
    """The occurrences of search's counted words in the mail (correlated to mail) and the
    texts and file names of its attachments' documents, each in its places (D174)."""
    counts: list[ColumnElement[int]] = []
    places = mail_weights(search.body_part)
    if (holding := _holding(search, places)) is not None:
        own = _occurrences(search, places, Mail.tsv).subquery("occurrences")
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


async def machine_hits(
    session: AsyncSession, mail_ids: Sequence[int], search: FullText
) -> dict[int, set[TextOrigin]]:
    """The mails among mail_ids where a counted word stands in the text of an attachment whose
    document an AI run recognised or transcribed (D189, D296), not in one read from its file;
    each with the origins of those texts (ocr, transcript)."""
    machine = Document.text_origin != TextOrigin.EXTRACTED
    ids = literal(list(mail_ids), ARRAY(BigInteger))
    attached = _attached(search, and_(Attachment.mail_id == any_(ids), machine))
    if not mail_ids or attached is None:
        return {}
    rows, documents = attached
    statement = (
        documents.add_columns(Attachment.mail_id, Document.text_origin, _total(rows))
        .where(rows.c.place == "attachment")
        .group_by(Attachment.mail_id, Document.text_origin)
    )
    found: dict[int, set[TextOrigin]] = {}
    for mail_id, origin, count in await session.execute(statement):
        if count > 0:
            found.setdefault(mail_id, set()).add(TextOrigin(origin))
    return found


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
    places = mail_weights(search.body_part)
    holding = _holding(search, places)
    if holding is None:
        return None
    rows = _occurrences(search, places, Mail.tsv).lateral("occurrences")
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
    """A tsquery that mail.tsv (places fulltext.mail_weights) or document.tsv (DOCUMENT_WEIGHTS)
    matches when it holds one of the counted words in one of the words' places there, as it
    must to hold the words as written too; None when no counted word is looked for in these
    places."""
    queries = [
        weighted(words_query(words, search.whole_word), labels)
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
    texts = stored_texts(search.body_part)
    as_written = [
        select(
            literal(place, Text).label("place"),
            func.coalesce(func.regexp_count(texts[place], word_regex(words), 1, "i"), 0).label(
                "count"
            ),
        ).correlate(Mail, Document)
        for _, words, place in counted
        if search.exact(words)
    ]
    stemmed = [(index, words, place) for index, words, place in counted if not search.exact(words)]
    if not stemmed:
        return _union(as_written)
    arrays = {
        index: func.tsvector_to_array(func.to_tsvector(TEXT_SEARCH, words.text))
        for index, words, _ in stemmed
    }
    # one row per words, place, weight of the place and lexeme
    lexemes = _union(
        [
            select(
                literal(index, Integer).label("words"),
                literal(place, Text).label("place"),
                literal(weight, Text).label("weight"),
                func.unnest(arrays[index]).label("lexeme"),
            )
            for index, _, place in stemmed
            for weight in places[place]
        ]
    ).subquery("lexemes")
    # vector with these lexemes only (ts_delete removes all others, those left when they are
    # removed): unnesting it is cheaper than unnesting every lexeme of a long text
    others = func.tsvector_to_array(func.ts_delete(vector, reduce(func.array_cat, arrays.values())))
    only = func.ts_delete(vector, others)
    found = func.unnest(only).table_valued("lexeme", "weights", name="found")
    positions = func.cardinality(func.array_positions(found.c.weights, lexemes.c.weight))
    # the positions of each lexeme in the place's weights, then the least frequent lexeme
    per_lexeme = (
        select(
            lexemes.c.words,
            lexemes.c.place,
            cast(func.sum(func.coalesce(positions, 0)), Integer).label("count"),
        )
        .select_from(lexemes.outerjoin(found, found.c.lexeme == lexemes.c.lexeme))
        .group_by(lexemes.c.words, lexemes.c.place, lexemes.c.lexeme)
        .subquery("per_lexeme")
    )
    least = select(per_lexeme.c.place, func.min(per_lexeme.c.count).label("count")).group_by(
        per_lexeme.c.words, per_lexeme.c.place
    )
    return _union([*as_written, least])


def _union(parts: Sequence[_Select]) -> _Rows:
    return parts[0] if len(parts) == 1 else union_all(*parts)


def _total(rows: Any) -> ColumnElement[int]:
    return func.coalesce(func.sum(rows.c.count), 0)
