from pathlib import Path
from urllib.parse import parse_qs

import pytest

from mailrobbe.api.query import parse_query
from mailrobbe.themes import ThemesError, load_themes


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
