# ruff: noqa: RUF001  (typographic quotes, apostrophes and dashes in texts are meant)
"""Names: organisations, persons and places (D81), by patterns and the gazetteers of data/.

    organization  one to five capitalised words before a legal form (GmbH, AG, KG, e.V., Ltd. and
                  the others of _LEGAL_FORM), with &, und, digits and hyphens between them, and
                  der, des, für after a word such as Verein or Verband (Verband der
                  Automobilindustrie e.V.); a word of common_words.txt, a line break or
                  punctuation ends the name to the left (Die Muster GmbH gives Muster GmbH); an
                  association word (Förderverein, Bund) is its first word, after at most one
                  adjective (Deutscher Fußball-Bund e.V.). Further a word of
                  organization_prefixes.txt before one to three capitalised words (Stiftung X,
                  Kreisverband X, Staatsanwaltschaft X), and the names of organizations.txt as
                  written. Key case-folded, e. V. as e.V.; label as written.
    person        Herr, Frau (Hr., Fr., Herrn, Mr, Mrs, Ms) with academic titles and a surname,
                  with or without first names (key "herr müller" without one), or first names of
                  first_names.txt and a surname; a surname is capitalised and no common word,
                  place, legal form or noun by its ending. Key the case-folded names without
                  titles ("thomas müller"), label as written without titles.
    place         towns and countries of cities.txt and countries.txt (detail city or country),
                  the longest name first (Frankfurt am Main); the names of ambiguous_places.txt,
                  and those that are first names or common words too, only after a five-digit
                  postcode or after in, aus, nach, bei; and any capitalised town after a postcode
                  at the start of a line or after a comma, when the line or a comma ends it
                  (12345 Kleinkleckersdorf). Key case-folded, label the gazetteer's spelling (or
                  as written).

Organisations run first, then persons, then places, each claiming its span: "Stiftung Berlin"
is an organisation and not the place, "Thomas Bremen" no person but the place. Names written in
capitals and "Surname, Firstname" are left out.
"""

import re
from dataclasses import dataclass
from functools import cache

from mailrobbe.entities.gazetteer import entries
from mailrobbe.entities.occurrences import Occurrences
from mailrobbe.enums import EntityKind

_UPPER = "".join(char for char in map(chr, range(0x41, 0x250)) if char.isupper())
# The lookaheads let the scans pass the positions that start no match at once (dates._DATE).
_CAPITALISED = re.compile(rf"(?=[{_UPPER}])(?<![\w'’-])[{_UPPER}][\w'’]*(?:-[\w'’]+)*")
_LEGAL_FORM = re.compile(
    r"(?=[&ABCGIKLNOPSUegmp])(?<![\w-])"
    r"(?:GmbH[ \t]?&[ \t]?Co\.?[ \t]?KG(?:aA)?|&[ \t]?Co\.?[ \t]?(?:KG(?:aA)?|OHG)"
    r"|UG[ \t]?\(haftungsbeschränkt\)|gGmbH|GmbH|mbH|KGaA|AG|KG|OHG|GbR|UG|e\.[ \t]?V\.?|eV|eG"
    r"|SE|Ltd\.?|Inc\.?|LLC|Corp\.?|plc|PLC|S\.A\.|B\.V\.|N\.V\.|AB)(?![\w])"
)
LEGAL_FORMS = frozenset(
    ["GmbH", "gGmbH", "mbH", "AG", "KG", "KGaA", "OHG", "GbR", "UG", "eV", "eG", "SE", "Ltd",
     "Inc", "LLC", "Corp", "plc", "PLC", "AB", "Co"]
)  # fmt: skip
# Association words start an association's name (Förderverein Nordwind e.V.), after at most one
# adjective; der, des, für after them and after institution words belong to the name (Verband
# der Automobilindustrie e.V., Gesellschaft für Informatik e.V.).
_ASSOCIATIONS = "verein|verband|stiftung|bund|kreis|initiative|bündnis|liga|partei|vereinigung|club"
_ASSOCIATION = re.compile(rf"(?:{_ASSOCIATIONS})\Z", re.IGNORECASE)
_INSTITUTION = re.compile(
    rf"(?:{_ASSOCIATIONS}|gesellschaft|institut|akademie|forum|netzwerk|union|gemeinschaft"
    r"|zentrum|haus|amt|rat|büro)\Z",
    re.IGNORECASE,
)
# Deutscher, Freie, Evangelische, but no noun such as Mitgliederliste.
_ADJECTIVE = re.compile(r"(?:er|es|en|[iu]sche|liche|ige|eie|eue|üne)\Z")
_JOINING = frozenset({"&", "+", "und", "and"})  # between two words of a name
_AFTER_ASSOCIATION = frozenset({"für", "der", "des", "zur", "zum", "of", "for"})
_OPENING = "(\"'„“‚‘«["
_CLOSING = ',;:)]!?"“”»'
_NOUN_ENDING = re.compile(r"(?:heit|keit|schaft|tion|ität|ismus|ierung|ungen)\Z|.{5}ung\Z")
_HONORIFICS = {
    "Herr": "Herr", "Herrn": "Herr", "Hr": "Herr", "Frau": "Frau", "Fr": "Frau",
    "Mr": "Mr", "Mrs": "Mrs", "Ms": "Ms",
}  # fmt: skip
_DOTTED = frozenset({"Hr", "Fr"})  # only with their dot
_TITLES = re.compile(
    r"(?:[ \t]{1,3}(?:Prof\.|Dr\.(?:-Ing\.)?|Dipl\.-\w+\.|med\.|jur\.|phil\.|rer\.[ ]?nat\."
    r"|rer\.[ ]?pol\.|h\.[ ]?c\.|habil\.|MdB|MdL|MdEP)(?![\w]))*"
)
_PARTICLE = "von der|von dem|van der|van den|van de|de la|von|vom|van|zu|de|di|da|ten|ter|dos|del"
_NAME_PART = re.compile(
    rf"[ \t]{{1,3}}(?:(?P<particle>{_PARTICLE})[ \t]+)?"
    rf"(?P<word>[{_UPPER}]\.|[{_UPPER}][\w'’]*(?:-[{_UPPER}][\w'’]*)*)(?![\w'’-])"
)
_PLACE_CUE = re.compile(r"(?:(?<![\w])(?:in|aus|nach|bei|In|Aus|Nach|Bei)|(?<!\d)\d{5})[ \t]+\Z")
_POSTCODE = re.compile(rf"(?<![\w.,/-])(?:D-|DE-)?\d{{5}}[ \t]+(?=[{_UPPER}])")
_POSTCODE_AFTER = re.compile(r"(?:\A|\n[ \t]*|[,;·|–-][ \t]*)\Z")
_TOWN = re.compile(
    rf"(?:(?:Bad|St\.|Sankt)[ \t]+)?[{_UPPER}][\w'’]+(?:-[{_UPPER}]?[\w'’]+)*"
    rf"(?:[ \t]+(?:am|an der|im|in der|ob der|vor der|bei)[ \t]+[{_UPPER}][\w'’]+)?"
    rf"(?:[ \t]?\([{_UPPER}][\w'’. ]{{1,20}}\))?(?![\w'’-])"
)
# An unlisted town ends its line or its part of it (12345 Kleinkleckersdorf, Germany), unlike
# an article number and its name in a price list (12345 Schutzhandschuhe Plus 21,73).
_TOWN_END = re.compile(r"[ \t]*(?:[,;·|/\n]|\Z)")
_SPACES = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class _Name:
    """A gazetteer entry, found by its first word."""

    pattern: re.Pattern[str]  # matched where its first word stands
    label: str
    key: str
    detail: str | None = None
    ambiguous: bool = False


@dataclass(frozen=True, slots=True)
class _Gazetteers:
    first_names: frozenset[str]
    common: frozenset[str]
    prefixes: frozenset[str]
    places: dict[str, tuple[_Name, ...]]
    place_words: frozenset[str]
    organizations: dict[str, tuple[_Name, ...]]
    lowercase_organizations: re.Pattern[str] | None
    lowercase_names: dict[str, _Name]
    # The words a capitalised word must be (or start with, before a hyphen) to be looked at.
    starts: frozenset[str]


@cache
def gazetteers() -> _Gazetteers:
    """The lists of data/ as the finders use them; built once per process."""
    first_names = frozenset(entries("first_names.txt"))
    common = frozenset(entries("common_words.txt"))
    ambiguous = frozenset(entries("ambiguous_places.txt"))
    places: dict[str, list[_Name]] = {}
    for detail, lines in (("city", entries("cities.txt")), ("country", entries("countries.txt"))):
        for line in lines:
            written, entity = _entity(line)
            unclear = written in ambiguous or written in first_names or written in common
            _index(places, written, _Name(_pattern(written), entity, _key(entity), detail, unclear))
    organizations: dict[str, list[_Name]] = {}
    lowercase: dict[str, _Name] = {}
    for line in entries("organizations.txt"):
        written, entity = _entity(line)
        name = _Name(_pattern(written), entity, _organization_key(entity))
        if _CAPITALISED.match(written):
            _index(organizations, written, name)
        else:
            lowercase[written] = name
    lowercase_pattern = None
    if lowercase:
        written = "|".join(re.escape(name) for name in sorted(lowercase, key=len, reverse=True))
        lowercase_pattern = re.compile(rf"(?<![\w'’-])(?:{written})(?![\w'’-])")
    prefixes = frozenset(entries("organization_prefixes.txt"))
    return _Gazetteers(
        first_names=first_names,
        common=common,
        prefixes=prefixes,
        places=_sorted(places),
        place_words=frozenset(
            name.label for names in places.values() for name in names if not name.ambiguous
        ),
        organizations=_sorted(organizations),
        lowercase_organizations=lowercase_pattern,
        lowercase_names=lowercase,
        starts=first_names | prefixes | _HONORIFICS.keys() | places.keys() | organizations.keys(),
    )


def _entity(line: str) -> tuple[str, str]:
    """A gazetteer line: the name as written, and the entity it stands for ("Name = Entity")."""
    written, _, entity = line.partition(" = ")
    return written, entity or written


def _pattern(name: str) -> re.Pattern[str]:
    words = [re.escape(word) for word in name.split()]
    # A hyphen may follow: AfD-Fraktion, Berlin-Mitte (the whole word is looked up first).
    return re.compile(r"(?:[ \t]+|[ \t]*\n[ \t]*)".join(words) + r"(?![\w'’])")


def _key(name: str) -> str:
    return " ".join(name.casefold().split())


def _index(index: dict[str, list[_Name]], written: str, name: _Name) -> None:
    first = _CAPITALISED.match(written)
    if first is not None:
        index.setdefault(first.group(), []).append(name)


def _sorted(index: dict[str, list[_Name]]) -> dict[str, tuple[_Name, ...]]:
    """Longest written name first."""
    return {
        word: tuple(sorted(names, key=lambda name: -len(name.pattern.pattern)))
        for word, names in index.items()
    }


def find_names(found: Occurrences) -> None:
    """Organisations, persons and places, in this order of precedence."""
    names = gazetteers()
    _legal_forms(found, names)
    _lowercase_organizations(found, names)
    _postcode_towns(found, names)
    text = found.text
    starts = names.starts
    for start in _starting(text, starts):
        match = _CAPITALISED.match(text, start)
        if match is None:  # inside a word
            continue
        word = match.group()
        head = word.partition("-")[0]
        end = match.end()
        if (word not in starts and head not in starts) or not found.free(start, end):
            continue  # a longer word (Annabell where Anna was looked for)
        if (
            _prefixed_organization(found, names, word, start, end)
            or _gazetted(found, names.organizations.get(word), EntityKind.ORGANIZATION, start)
            or _gazetted(found, names.organizations.get(head), EntityKind.ORGANIZATION, start)
            or _person(found, names, word, start, end)
        ):
            continue
        for candidates in (names.places.get(word), names.places.get(head)):
            if candidates and _gazetted(
                found, candidates, EntityKind.PLACE, start, cue=_cued(text, start)
            ):
                break


def _starting(text: str, starts: frozenset[str]) -> list[int]:
    """Where the capitalised words stand that are, or start with, a word of `starts`, in text
    order. The words are compared as sets and only those found are looked for again, since a
    Python loop over every capitalised word would cost a third of the extraction."""
    written = set(_CAPITALISED.findall(text))
    # A compound such as AfD-Fraktion or Berlin-Mitte names its first part.
    wanted = (written & starts) | {
        word for word in written if "-" in word and word.partition("-")[0] in starts
    }
    positions: set[int] = set()
    for word in wanted:
        position = text.find(word)
        while position >= 0:
            positions.add(position)
            position = text.find(word, position + 1)
    return sorted(positions)


# Organisations -----------------------------------------------------------------------------------


def _legal_forms(found: Occurrences, names: _Gazetteers) -> None:
    text = found.text
    for match in _LEGAL_FORM.finditer(text):
        start = _name_before(found, match.start(), names)
        if start is None or not found.free(start, match.end()):
            continue
        label = _SPACES.sub(" ", text[start : match.end()])
        found.add(EntityKind.ORGANIZATION, _organization_key(label), label, start, match.end())


def _organization_key(label: str) -> str:
    key = _key(label)
    key = re.sub(r"\be\. ?v\.?\Z", "e.v.", key)
    return re.sub(r" ?& ?co\.? ?kg", " & co. kg", key)


def _name_before(found: Occurrences, end: int, names: _Gazetteers) -> int | None:
    """Where the name before a legal form at `end` starts (the module docstring's rules); a
    span claimed before (the organisation before it in a list) ends it too."""
    text = found.text
    line_start = text.rfind("\n", 0, end) + 1
    window = max(line_start, end - 160)
    tokens = [(match.start(), match.group()) for match in _TOKENS.finditer(text, window, end)]
    if window > line_start and tokens:
        tokens.pop(0)  # perhaps cut
    start: int | None = None
    words = 0
    index = len(tokens) - 1
    while index >= 0 and words < 5:
        position, token = tokens[index]
        if token[-1] in _CLOSING or not found.free(position, position + len(token)):
            break
        word = token.lstrip(_OPENING)
        position += len(token) - len(word)
        if _name_word(word, names):
            start, words = position, words + 1
            if word != token:  # an opening bracket or quote: the name starts here
                break
            if _ASSOCIATION.search(word):
                previous = _token(tokens, index - 1)
                if previous and _name_word(previous[1], names) and _ADJECTIVE.search(previous[1]):
                    start = previous[0]
                break
            index -= 1
            continue
        previous = _token(tokens, index - 1)
        if previous is None or not _name_word(previous[1], names):
            break
        joining = (word in _JOINING and start is not None) or word.isdigit()
        if not (joining or (word in _AFTER_ASSOCIATION and _INSTITUTION.search(previous[1]))):
            break
        index -= 1  # the word before the joining one is taken in the next round
    return start


# Words, and a comma or semicolon ends one even without a space (2020;Kornfeld Bau KG in a CSV).
_TOKENS = re.compile(r"[^\s,;]*[,;]|[^\s,;]+")


def _token(tokens: list[tuple[int, str]], index: int) -> tuple[int, str] | None:
    return tokens[index] if index >= 0 else None


def _name_word(word: str, names: _Gazetteers) -> bool:
    """A capitalised word that can be part of a name (no common word, no legal form)."""
    return (
        bool(word)
        and word[0].isupper()
        and word not in names.common
        and word.rstrip(".") not in LEGAL_FORMS
    )


def _prefixed_organization(
    found: Occurrences, names: _Gazetteers, word: str, start: int, end: int
) -> bool:
    """A prefix word and one to three capitalised words after it (Stiftung X)."""
    if word not in names.prefixes:
        return False
    text = found.text
    position = end
    for _ in range(3):
        part = _NAME_PART.match(text, position)
        if part is None or part.group("particle") or not _name_word(part.group("word"), names):
            break
        word = part.group("word")
        if word.endswith(".") or word in names.prefixes:
            break
        place = _longest(names.places.get(word), text, part.start("word"))
        position = place or part.end()
        if place:  # Amtsgericht Frankfurt am Main, Kreisverband Meißen: the place ends it
            break
    if position == end or not found.free(start, position):
        return False
    label = _SPACES.sub(" ", found.text[start:position])
    found.add(EntityKind.ORGANIZATION, _key(label), label, start, position)
    return True


def _lowercase_organizations(found: Occurrences, names: _Gazetteers) -> None:
    if names.lowercase_organizations is None:
        return
    for match in names.lowercase_organizations.finditer(found.text):
        if found.free(*match.span()):
            name = names.lowercase_names[match.group()]
            found.add(EntityKind.ORGANIZATION, name.key, name.label, *match.span())


def _longest(candidates: tuple[_Name, ...] | None, text: str, start: int) -> int | None:
    """The end of the longest candidate written at `start`."""
    for name in candidates or ():
        match = name.pattern.match(text, start)
        if match:
            return match.end()
    return None


def _gazetted(
    found: Occurrences,
    candidates: tuple[_Name, ...] | None,
    kind: EntityKind,
    start: int,
    *,
    cue: bool = False,
) -> bool:
    """The longest candidate written at `start`; an ambiguous one only after a cue."""
    for name in candidates or ():
        match = name.pattern.match(found.text, start)
        if match is None or (name.ambiguous and not cue) or not found.free(start, match.end()):
            continue
        found.add(kind, name.key, name.label, start, match.end(), detail=name.detail)
        return True
    return False


# Persons -----------------------------------------------------------------------------------------


def _person(found: Occurrences, names: _Gazetteers, word: str, start: int, end: int) -> bool:
    text = found.text
    honorific = _HONORIFICS.get(word)
    if honorific is not None:
        dotted = text.startswith(".", end)
        if word in _DOTTED and not dotted:
            return False
        titles = _TITLES.match(text, end + dotted)  # always matches, perhaps nothing
        position = titles.end() if titles else end + dotted
        parts = _name_parts(text, position)
        if not parts:
            return False
        given, surname = _split_name(parts, names, titled=True)
        if surname is None:
            return False
        if given:
            return _add_person(found, [*given, surname], start)
        label_end = surname[2]
        label = f"{honorific} {_SPACES.sub(' ', text[surname[1] : label_end])}"
        found.add(EntityKind.PERSON, _key(label), label, start, label_end)
        return True
    if not _first_name(word, names):
        return False
    given, surname = _split_name([(word, start, end, False), *_name_parts(text, end)], names)
    if not given or surname is None:
        return False
    return _add_person(found, [*given, surname], start)


_Part = tuple[str, int, int, bool]  # word, start, end, after a particle


def _name_parts(text: str, position: int) -> list[_Part]:
    parts: list[_Part] = []
    while len(parts) < 4:
        match = _NAME_PART.match(text, position)
        if match is None:
            break
        particle = match.group("particle")
        word_start = match.start("particle" if particle else "word")
        parts.append((match.group("word"), word_start, match.end(), bool(particle)))
        position = match.end()
    return parts


def _split_name(
    parts: list[_Part], names: _Gazetteers, *, titled: bool = False
) -> tuple[list[_Part], _Part | None]:
    """The given names (first names and initials) and the surname after them. When only first
    names follow, the last of two (or after Herr or Frau, of one) is the surname: Sven Wolf,
    Herr Thomas."""
    given: list[_Part] = []
    for part in parts:
        word, _, _, particle = part
        if not particle and (_first_name(word, names) or _initial(word)) and len(given) < 3:
            given.append(part)
            continue
        return given, part if _surname(word, names) else None
    if (
        len(given) >= (1 if titled else 2)
        and not _initial(given[-1][0])
        and _surname(given[-1][0], names)
    ):
        return given[:-1], given[-1]
    return given, None


def _add_person(found: Occurrences, parts: list[_Part], start: int) -> bool:
    first, end = parts[0][1], parts[-1][2]
    if not found.free(start, end):
        return False
    label = _SPACES.sub(" ", found.text[first:end])
    found.add(EntityKind.PERSON, _key(label), label, start, end)
    return True


def _first_name(word: str, names: _Gazetteers) -> bool:
    return word in names.first_names or (
        "-" in word and all(part in names.first_names for part in word.split("-"))
    )


def _initial(word: str) -> bool:
    return len(word) == 2 and word[1] == "."


def _surname(word: str, names: _Gazetteers) -> bool:
    return (
        len(word) >= 2
        and word[0].isupper()
        and any(char.islower() for char in word)
        and word not in names.common
        and word not in names.place_words
        and word not in names.prefixes
        and word not in LEGAL_FORMS
        and not _NOUN_ENDING.search(word)
    )


# Places ------------------------------------------------------------------------------------------


def _cued(text: str, start: int) -> bool:
    """After in, aus, nach, bei or a postcode."""
    return _PLACE_CUE.search(text, max(0, start - 9), start) is not None


def _postcode_towns(found: Occurrences, names: _Gazetteers) -> None:
    """A town after a five-digit postcode: from the gazetteer if listed (also an ambiguous one),
    else any capitalised word when the postcode starts a line or follows a comma."""
    text = found.text
    for postcode in _POSTCODE.finditer(text):
        start = postcode.end()
        word = _CAPITALISED.match(text, start)
        if word is None or not found.free(start, word.end()):
            continue
        if _gazetted(found, names.places.get(word.group()), EntityKind.PLACE, start, cue=True):
            continue
        town = _TOWN.match(text, start)
        before = _POSTCODE_AFTER.search(text, max(0, postcode.start() - 8), postcode.start())
        if (
            town is None
            or before is None
            or not _TOWN_END.match(text, town.end())
            or not _name_word(word.group(), names)
        ):
            continue
        label = _SPACES.sub(" ", town.group())
        found.add(EntityKind.PLACE, _key(label), label, start, town.end(), detail="city")
