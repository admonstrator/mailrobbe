import pytest

from mailrobbe.enums import ImportErrorKind
from mailrobbe.importer.model import Issue
from mailrobbe.importer.text import (
    ascii_bytes,
    clean,
    decode_base64,
    decode_bytes,
    decode_words,
    header_text,
    html_to_text,
)


def _messages(issues: list[Issue]) -> list[str]:
    assert all(issue.kind is ImportErrorKind.ENCODING for issue in issues)
    return [issue.message for issue in issues]


def test_clean_removes_what_postgresql_cannot_store() -> None:
    assert clean("a\x00b\udcfcc\ud800") == "abc"
    assert clean("Grüße \U0001f600") == "Grüße \U0001f600"


def test_ascii_bytes_gives_back_the_raw_bytes() -> None:
    assert ascii_bytes("Gr\udcfc\udcdfe") == b"Gr\xfc\xdfe"
    assert ascii_bytes("Grüße") == "Grüße".encode()


@pytest.mark.parametrize(
    ("data", "charset", "text", "issue"),
    [
        (b"plain", None, "plain", None),
        ("Grüße".encode(), "UTF-8", "Grüße", None),
        ("Grüße".encode(), '"utf-8"', "Grüße", None),
        ("Grüße".encode(), "utf-8*de", "Grüße", None),  # RFC 2231 language suffix
        ("Grüße".encode("latin-1"), "ISO-8859-1", "Grüße", None),
        (b"\x93quoted\x94 \x80", "iso-8859-1", "“quoted” €", None),
        ("Grüße".encode(), "iso-8859-1", "Grüße", "labelled iso-8859-1 but is UTF-8"),
        ("Grüße".encode(), "windows-1252", "Grüße", "labelled windows-1252 but is UTF-8"),
        ("Grüße".encode(), "iso-8859-15", "Grüße", "labelled iso-8859-15 but is UTF-8"),
        ("Grüße".encode("latin-1"), "utf-8", "Grüße", "invalid utf-8 bytes, read as cp1252"),
        ("Grüße".encode(), None, "Grüße", "invalid US-ASCII bytes, read as utf-8"),
        (b"\x81\x8d", "us-ascii", "\x81\x8d", "invalid us-ascii bytes, read as latin-1"),
        ("Grüße".encode(), "x-unknown", "Grüße", "unknown charset 'x-unknown', read as utf-8"),
        (b"Gr\xfc\xdfe", "utf-9", "Grüße", "unknown charset 'utf-9', read as cp1252"),
        (b"text", "base64", "text", "unknown charset 'base64', read as utf-8"),
        ("中文".encode("gbk"), "gb2312", "中文", None),
        ("Привет".encode("koi8-r"), "koi8-r", "Привет", None),
        ("日本".encode("iso-2022-jp"), "iso-2022-jp", "日本", None),
    ],
)
def test_decode_bytes(data: bytes, charset: str | None, text: str, issue: str | None) -> None:
    issues: list[Issue] = []
    assert decode_bytes(data, charset, "part", issues) == text
    assert _messages(issues) == ([f"part: {issue}"] if issue else [])


def test_utf8_in_other_charsets_is_not_guessed() -> None:
    # Valid UTF-8 is only assumed for Western labels; in koi8-r the same bytes are letters.
    issues: list[Issue] = []
    assert decode_bytes("ü".encode(), "koi8-r", "part", issues) == "ц╪"
    assert not issues


@pytest.mark.parametrize(
    ("value", "text", "issue"),
    [
        ("Re: Termin", "Re: Termin", None),
        ("Re: Termin\r\n am Montag", "Re: Termin am Montag", None),
        ("Gr\udcc3\udcbc\udcc3\udc9fe", "Grüße", None),  # UTF-8 bytes (RFC 6532)
        ("Gr\udcfc\udcdfe", "Grüße", "raw 8-bit bytes, read as cp1252"),
        ("\udc81\udc8d", "\x81\x8d", "raw 8-bit bytes, read as latin-1"),
    ],
)
def test_header_text(value: str, text: str, issue: str | None) -> None:
    issues: list[Issue] = []
    assert header_text(value, "Subject header", issues) == text
    assert _messages(issues) == ([f"Subject header: {issue}"] if issue else [])


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("no words", "no words"),
        ("=?utf-8?q?Gr=C3=BC=C3=9Fe_aus_K=C3=B6ln?=", "Grüße aus Köln"),
        ("=?UTF-8?B?R3LDvMOfZQ==?=", "Grüße"),
        ("=?iso-8859-1?q?M=FCller?=, Eva", "Müller, Eva"),
        ("Re: =?utf-8?Q?a?= =?utf-8?Q?b?= c", "Re: ab c"),
        ("=?utf-8?Q?a?=\t =?iso-8859-1?Q?=FC?=", "aü"),
        ("=?utf-8?Q?a?= x =?utf-8?Q?b?=", "a x b"),
        # A multibyte character split across two words, as some mailers do.
        ("=?utf-8?B?w6E=?= =?utf-8?B?w7w=?= =?utf-8?Q?=C3?= =?utf-8?Q?=BC?=", "áüü"),
        ("=?utf-8*de?Q?Gr=C3=BC=C3=9Fe?=", "Grüße"),
        ("=?windows-1252?Q?=84Zitat=93?=", "„Zitat“"),
    ],
)
def test_decode_words(value: str, text: str) -> None:
    issues: list[Issue] = []
    assert decode_words(value, "Subject header", issues) == text
    assert not issues


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("=?utf-8?Q?Gr=C3=BC=C3=9Fe aus Berlin", "Grüße aus Berlin"),  # `?=` lost
        ("=?utf-8?Q?Gr=C3=BC=C3=9Fe", "Grüße"),
        ("=?utf-8?B?R3LDvMOfZQ?=", "Grüße"),  # padding lost
        ("=?utf-8?B?R3LDvM!OfZQ==?=", "Grüße"),  # a character outside the alphabet
        ("=?utf-8?B?R3LDvMOfZQ?= =?utf-8?B?IGF1cw?=", "Grüße aus"),  # one issue per header
    ],
)
def test_malformed_words_are_decoded_as_far_as_possible(value: str, text: str) -> None:
    issues: list[Issue] = []
    assert decode_words(value, "Subject header", issues) == text
    assert _messages(issues) == ["Subject header: malformed encoded word"]


def test_words_in_unknown_charsets_are_guessed() -> None:
    issues: list[Issue] = []
    assert decode_words("=?x-unknown?Q?Gr=FC=DFe?=", "Subject header", issues) == "Grüße"
    assert _messages(issues) == ["Subject header: unknown charset 'x-unknown', read as cp1252"]


@pytest.mark.parametrize(
    ("data", "decoded", "valid"),
    [
        (b"SGFsbG8gV2VsdA==", b"Hallo Welt", True),
        (b"SGFsbG8g\r\nV2Vs dA==\r\n", b"Hallo Welt", True),
        (b"", b"", True),
        (b"SGFsbG8gV2VsdA", b"Hallo Welt", False),
        (b"SGFsbG8gV2VsdA=", b"Hallo Welt", False),
        (b"SGFsbG8g*V2VsdA==", b"Hallo Welt", False),
        (b"SGFsbG8gV2VsdA==Q", b"Hallo Welt", False),
        (b"SGFsbG8gV2VsdA==SGFsbG8=", b"Hallo WeltHallo", False),
    ],
)
def test_decode_base64(data: bytes, decoded: bytes, valid: bool) -> None:
    assert decode_base64(data) == (decoded, valid)


@pytest.mark.parametrize(
    ("html", "text"),
    [
        ("<p>one</p><p>two</p>", "one\n\ntwo"),
        ("one<br>two<br/>three", "one\ntwo\nthree"),
        ("<head><title>T</title><meta charset=utf-8></head><body>text</body>", "text"),
        ("<title>loose title</title>text", "text"),  # no head element
        ("a<script>var x = '<p>';</script><style>p {}</style>b", "ab"),
        ("<p>  many \n  spaces\t here </p>", "many spaces here"),
        ("<pre>  keep\n    lines</pre>", "keep\nlines"),  # indentation is no search text
        ("<table><tr><td>a</td><td>b</td></tr><tr><td>c</td></tr></table>", "a b\n\nc"),
        ("<ul><li>one</li><li>two</li></ul>", "one\n\ntwo"),
        ("&lt;tag&gt; &amp; &auml; &#8364; &nbsp;x", "<tag> & ä € x"),
        ("<p>a</p><![if !supportLists]>b<![endif]><p>c</p>", "a\nb\nc"),
        ("a<!-- hidden -->b", "ab"),
        ("<p>unclosed <b>tags", "unclosed tags"),
        ("", ""),
    ],
)
def test_html_to_text(html: str, text: str) -> None:
    assert html_to_text(html) == text
