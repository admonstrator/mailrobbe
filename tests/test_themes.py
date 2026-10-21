from pathlib import Path
from urllib.parse import parse_qs

import pytest

from mailrobbe.api.query import parse_query
from mailrobbe.enums import EntityContext
from mailrobbe.themes import (
    ThemesError,
    load_entity_context,
    load_signal_lists,
    load_themes,
    load_topic_ignore,
)


def test_the_shipped_themes_load() -> None:
    themes = load_themes()
    assert [theme.key for theme in themes] == [
        "verfassungsfeindlichkeit",
        "rassismus",
        "extremismus",
        "gewalt",
        "spenden",
        "verschleierung",
    ]
    for theme in themes:
        assert theme.terms and theme.searches and theme.description
        for search in theme.searches:
            assert search.name.startswith(f"{theme.name}: ")
            assert parse_qs(search.query) == {"q": [search.q]}
            # Every search is full text joined by "or", no operator by accident.
            assert {term.key for term in parse_query(search.q)} == {"text"}


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "themes.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_wrong_colour_and_duplicates_are_refused(tmp_path: Path) -> None:
    theme = '[[theme]]\nkey = "a"\nname = "A"\ncolor = "{color}"\n'
    with pytest.raises(ThemesError, match="colour purple"):
        load_themes(_write(tmp_path, theme.format(color="purple")))
    twice = theme.format(color="red") + theme.format(color="blue").replace('"A"', '"a"')
    with pytest.raises(ThemesError, match="theme key used twice: a"):
        load_themes(_write(tmp_path, twice))


def test_a_search_with_an_unusable_operator_is_refused(tmp_path: Path) -> None:
    text = (
        '[[theme]]\nkey = "a"\nname = "A"\ncolor = "red"\n'
        '[[theme.search]]\nname = "A: x"\nq = "dkim:maybe"\n'
    )
    with pytest.raises(ThemesError, match="search A: x"):
        load_themes(_write(tmp_path, text))


_SEARCH = (
    '[[theme]]\nkey = "a"\nname = "A"\ncolor = "red"\n'
    '[[theme.search]]\nname = "A: x"\nq = "Neger"\n'
)


def test_a_search_carries_the_options_of_the_mail_list(tmp_path: Path) -> None:
    options = 'scope = ["filename", "subject", "subject"]\nwhole_word = true\nmin_hits = 3\n'
    (search,) = load_themes(_write(tmp_path, _SEARCH + options))[0].searches
    assert (search.scope, search.whole_word, search.min_hits) == (("subject", "filename"), True, 3)
    # as the mail list writes its URL: places repeated, defaults left out
    assert search.query == "q=Neger&scope=subject&scope=filename&whole_word=true&min_hits=3"
    everywhere = 'scope = ["attachment", "body", "filename", "subject"]\nwhole_word = false\n'
    (tmp_path / "all").mkdir()  # load_themes keeps what it read per path
    (search,) = load_themes(_write(tmp_path / "all", _SEARCH + everywhere))[0].searches
    assert (search.scope, search.query) == ((), "q=Neger")


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ('scope = ["subject", "anhang"]', "theme a, search A: x: unknown places anhang"),
        ('scope = "subject"', "theme a, search A: x: scope must be a list of places"),
        ("whole_word = 1", "theme a, search A: x: whole_word must be true or false"),
        ("min_hits = 0", "theme a, search A: x: min_hits must be a whole number from 1 to 999"),
        ("min_hits = 1000", "min_hits must be a whole number"),
        ("min_hits = true", "min_hits must be a whole number"),
        ('min_hits = "3"', "min_hits must be a whole number"),
    ],
)
def test_wrong_search_options_are_refused(tmp_path: Path, options: str, message: str) -> None:
    with pytest.raises(ThemesError, match=message):
        load_themes(_write(tmp_path, f"{_SEARCH}{options}\n"))


def test_the_shipped_entity_contexts_load() -> None:
    contexts = load_entity_context()
    assert list(contexts) == [EntityContext.CASH, EntityContext.DONATION, EntityContext.RECEIPT]
    assert {"Bargeld", "bar"} <= set(contexts[EntityContext.CASH])
    assert {"Spende", "Zuwendung"} <= set(contexts[EntityContext.DONATION])
    assert {"Quittung", "Spendenbescheinigung"} <= set(contexts[EntityContext.RECEIPT])
    # Membership fees are routine, not donations (themes.toml says why).
    assert all("beitrag" not in word.lower() for words in contexts.values() for word in words)


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ("", "the table \\[entity_context\\] is missing"),
        ('[entity_context]\ncash = ["bar"]\ndonation = ["Spende"]\n', "the list receipt"),
        (
            '[entity_context]\ncash = ["bar"]\ndonation = []\nreceipt = ["Beleg"]\n',
            "the list donation is missing or empty",
        ),
        (
            '[entity_context]\ncash = ["bar", " "]\ndonation = ["Spende"]\nreceipt = ["Beleg"]\n',
            "cash: every word must be a non-empty text",
        ),
        (
            '[entity_context]\ncash = ["Bar", "bar"]\ndonation = ["Spende"]\nreceipt = ["Beleg"]\n',
            "cash: used twice: bar",
        ),
        (
            '[entity_context]\ncash = ["bar"]\ndonation = ["Spende"]\nreceipt = ["Beleg"]\n'
            'fee = ["Beitrag"]\n',
            "unknown lists fee",
        ),
    ],
)
def test_wrong_entity_contexts_are_refused(tmp_path: Path, table: str, message: str) -> None:
    with pytest.raises(ThemesError, match=message):
        load_entity_context(_write(tmp_path, table))


def test_the_shipped_signal_lists_load() -> None:
    lists = load_signal_lists()
    assert (lists.night_from, lists.night_to, lists.many_recipients) == (22, 6, 25)
    assert {"gmail.com", "gmx.de", "web.de", "t-online.de", "icloud.com"} <= set(
        lists.private_domains
    )
    assert all(domain == domain.lower() for domain in lists.private_domains)
    assert len(set(lists.private_domains)) == len(lists.private_domains)
    assert {"Fwd", "WG"} <= set(lists.forward_prefixes)


_SIGNALS = """
[signals]
night_from = 22
night_to = 6
many_recipients = 25
forward_prefixes = ["Fwd", "WG"]
private_domains = ["Mail.Example", "mail.example", "box.test"]
"""


def test_signal_lists_are_normalised(tmp_path: Path) -> None:
    lists = load_signal_lists(_write(tmp_path, _SIGNALS))
    assert lists.private_domains == ("mail.example", "box.test")
    assert lists.forward_prefixes == ("Fwd", "WG")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("night_from = 22", "night_from = 24", "night_from: must be an hour"),
        ("night_to = 6", "night_to = 22", "must differ"),
        ("many_recipients = 25", "many_recipients = 1", "many_recipients"),
        ("many_recipients = 25", "many_recipients = true", "many_recipients"),
        ('["Fwd", "WG"]', "[]", "forward_prefixes: the list is missing or empty"),
        ('["Fwd", "WG"]', '["Fwd:"]', "letters A to Z only: Fwd:"),
        ('"box.test"]', '"box"]', "not a domain: box"),
        ("night_to = 6", "night_to = 6\nevening = 18", "unknown keys evening"),
        ("[signals]", "[signal]", "the table \\[signals\\] is missing"),
    ],
)
def test_wrong_signal_lists_are_refused(tmp_path: Path, old: str, new: str, message: str) -> None:
    with pytest.raises(ThemesError, match=message):
        load_signal_lists(_write(tmp_path, _SIGNALS.replace(old, new)))


def test_the_shipped_topic_ignore_list_loads() -> None:
    words = load_topic_ignore()
    assert {"Gruß", "Montag", "Januar", "anbei", "Betreff"} <= set(words)
    # No word of a research theme's word field is ignored (D141).
    ignored = {word.casefold() for word in words}
    assert not ignored & {term.casefold() for theme in load_themes() for term in theme.terms}


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ("", "the table \\[topics\\] is missing"),
        ('[topics]\nignore = ["Gruß", " "]\n', "every word must be a non-empty text"),
        ('[topics]\nignore = ["Gruß", "GRUSS"]\n', "used twice: gruss"),
        ('[topics]\nignore = []\nkeep = ["Spende"]\n', "unknown keys keep"),
    ],
)
def test_wrong_topic_ignore_lists_are_refused(tmp_path: Path, table: str, message: str) -> None:
    with pytest.raises(ThemesError, match=message):
        load_topic_ignore(_write(tmp_path, table))
