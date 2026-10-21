"""The pass over mail.tsv and the vocabulary of the topics phase (D141, D146: step topic_terms).

    pass        one statement over the tsv of every mail that is no duplicate counts the mails of
                each lexeme of MIN_LENGTH to MAX_LENGTH characters per UTC month (NULL for undated
                mails) into the temporary table topic_tmp_month; a second, light one counts the
                mails per month. N, the mails of every period and every term's mails come from
                these two counts, and no later step reads mail.tsv again.
    vocabulary  the lexemes in at least MIN_MAILS mails that model.usable_lexeme accepts, less
                English stop words (ts_lexize('english_stem') gives none for exactly those; the
                German ones are never indexed), less the stems of [topics] ignore, and less the
                stems of the words of the persons' display names (person.display_name and the
                names of person_email.display_names) unless they are stems of single-word theme
                terms. Those stems also give a term its themes, in themes.toml order. A stem of a
                word is every lexeme to_tsvector('german') gives for it, so one form leaves out
                every form, and the parts of a hyphenated word go with it. The vocabulary goes
                into the temporary table topic_tmp_term for the periods.

Names are left out because the names of the correspondents crowd every list (greetings,
signatures) and have screens of their own; names of people who are only mentioned stay. A word
of a theme's word field stays even when somebody is called so, since the research looks for it.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe import themes
from mailrobbe.topics.model import MAX_LENGTH, MIN_LENGTH, MIN_MAILS, usable_lexeme

# Every lexeme of every mail that is no duplicate, with its mails per UTC month. A lexeme is in a
# tsvector once, so count(*) counts mails. The length test only spares the aggregate the short
# tokens; usable_lexeme decides. Utility statements take no parameters, hence the f-string.
_MONTH_LEXEMES = text(f"""
    CREATE TEMP TABLE topic_tmp_month ON COMMIT DROP AS
    SELECT date_trunc('month', m.date_utc AT TIME ZONE 'UTC')::date AS month, l AS lexeme,
           count(*)::integer AS mails
    FROM mail m CROSS JOIN LATERAL unnest(tsvector_to_array(m.tsv)) AS l
    WHERE m.is_duplicate_of IS NULL AND length(l) BETWEEN {MIN_LENGTH} AND {MAX_LENGTH}
    GROUP BY 1, 2
""")
_MONTHS = text("""
    SELECT date_trunc('month', date_utc AT TIME ZONE 'UTC')::date AS month, count(*)
    FROM mail WHERE is_duplicate_of IS NULL GROUP BY 1
""")
_CANDIDATES = text("""
    SELECT lexeme, sum(mails)::integer FROM topic_tmp_month
    GROUP BY lexeme HAVING sum(mails) >= :min_mails
""")
_ENGLISH_STOP_WORDS = text("""
    SELECT l FROM unnest(CAST(:lexemes AS text[])) AS l WHERE ts_lexize('english_stem', l) = '{}'
""")
_STEMS = text("""
    SELECT DISTINCT l
    FROM unnest(CAST(:words AS text[])) AS w,
        unnest(tsvector_to_array(to_tsvector('german', w))) AS l
""")
_NAME_STEMS = text("""
    SELECT DISTINCT l
    FROM (
        SELECT display_name AS name FROM person WHERE display_name IS NOT NULL
        UNION
        SELECT jsonb_object_keys(display_names) FROM person_email
    ) AS names, unnest(tsvector_to_array(to_tsvector('german', names.name))) AS l
""")
_THEME_STEMS = text("""
    SELECT u.key, l
    FROM unnest(CAST(:keys AS text[]), CAST(:words AS text[])) WITH ORDINALITY
        AS u(key, word, ordinal),
        unnest(tsvector_to_array(to_tsvector('german', u.word))) AS l
    ORDER BY u.ordinal, l
""")
_TERM_TABLE = text("""
    CREATE TEMP TABLE topic_tmp_term (lexeme text PRIMARY KEY, mails integer NOT NULL)
    ON COMMIT DROP
""")
_TERM_ROWS = text("""
    INSERT INTO topic_tmp_term (lexeme, mails)
    SELECT * FROM unnest(CAST(:lexemes AS text[]), CAST(:mails AS integer[]))
""")
# Autovacuum never analyses temporary tables, and the periods join these two.
_ANALYZE = (text("ANALYZE topic_tmp_month"), text("ANALYZE topic_tmp_term"))


@dataclass(frozen=True, slots=True)
class Counted:
    """What the step topic_terms found; the vocabulary is in topic_tmp_term as well."""

    total: int  # N: the mails that are no duplicates, undated included
    months: dict[date, int]  # mails per UTC month (first day), months with mails only
    undated: int
    frequent: int  # lexemes in MIN_MAILS mails or more, before the rules
    mails: dict[str, int]  # the vocabulary: lexeme -> its mails (df)
    themes: dict[str, tuple[str, ...]]  # its terms from a theme's word field -> their keys
    left_out: dict[str, int]  # lexemes in MIN_MAILS mails or more left out, by rule


def theme_words() -> tuple[tuple[str, str], ...]:
    """The single-word terms of the themes' word fields as (theme key, word), in themes.toml
    order; terms of several words ("in bar", "Tag X") name a phrase, not a topic word."""
    return tuple(
        (theme.key, term)
        for theme in themes.load_themes()
        for term in theme.terms
        if len(term.split()) == 1
    )


async def count_terms(session: AsyncSession) -> Counted:
    """The pass over mail.tsv and the vocabulary (module docstring), in session's transaction."""
    await session.execute(_MONTH_LEXEMES)
    months: dict[date, int] = {}
    undated = 0
    for month, count in await session.execute(_MONTHS):
        if month is None:
            undated = count
        else:
            months[month] = count
    rows = await session.execute(_CANDIDATES, {"min_mails": MIN_MAILS})
    found: dict[str, int] = {lexeme: count for lexeme, count in rows}
    usable = sorted(lexeme for lexeme in found if usable_lexeme(lexeme))
    stop_words = set(
        (await session.execute(_ENGLISH_STOP_WORDS, {"lexemes": usable})).scalars().all()
    )
    ignored = await _stems(session, themes.load_topic_ignore())
    names = set((await session.execute(_NAME_STEMS)).scalars().all())
    theme_keys = await _theme_stems(session)
    left_out = dict.fromkeys(("not words", "English stop words", "ignored", "names"), 0)
    left_out["not words"] = len(found) - len(usable)
    mails: dict[str, int] = {}
    for lexeme in usable:
        if lexeme in stop_words:
            left_out["English stop words"] += 1
        elif lexeme in ignored:
            left_out["ignored"] += 1
        elif lexeme in names and lexeme not in theme_keys:
            left_out["names"] += 1
        else:
            mails[lexeme] = found[lexeme]
    await session.execute(_TERM_TABLE)
    await session.execute(_TERM_ROWS, {"lexemes": list(mails), "mails": list(mails.values())})
    for statement in _ANALYZE:
        await session.execute(statement)
    return Counted(
        total=sum(months.values()) + undated,
        months=months,
        undated=undated,
        frequent=len(found),
        mails=mails,
        themes={lexeme: keys for lexeme, keys in theme_keys.items() if lexeme in mails},
        left_out=left_out,
    )


async def _stems(session: AsyncSession, words: Iterable[str]) -> set[str]:
    rows = await session.execute(_STEMS, {"words": list(words)})
    return set(rows.scalars().all())


async def _theme_stems(session: AsyncSession) -> dict[str, tuple[str, ...]]:
    """Every stem of a single-word theme term -> the keys of its themes, in themes.toml order."""
    words = theme_words()
    rows = await session.execute(
        _THEME_STEMS,
        {"keys": [key for key, _ in words], "words": [word for _, word in words]},
    )
    keys: dict[str, list[str]] = {}
    for key, lexeme in rows:
        found = keys.setdefault(lexeme, [])
        if key not in found:
            found.append(key)
    return {lexeme: tuple(found) for lexeme, found in keys.items()}
