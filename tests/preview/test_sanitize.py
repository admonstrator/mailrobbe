"""The sanitizer of converted documents (D122): the classic vectors, what it keeps, the page,
and raster images as data: URLs."""

from html.parser import HTMLParser

import pytest

from mailrobbe.preview import sanitize as sanitizer
from mailrobbe.preview.sanitize import (
    IMAGE_PLACEHOLDER,
    POLICY,
    Images,
    page,
    raster_type,
    sanitize,
)
from tests.preview.samples import EMF, JPEG, SVG, png

PLACEHOLDER = IMAGE_PLACEHOLDER
PNG_URL = "data:image/png;base64,iVBORw0KGgo="


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<p>Hallo<script>alert(1)</script> Welt</p>", "<p>Hallo Welt</p>"),
        ("<SCRIPT>alert(1)</SCRIPT><p>Text</p>", "<p>Text</p>"),
        ("<script/>alert(1)", "alert(1)"),  # not markup: only text stays
        ("<img src=x onerror=alert(1)>", PLACEHOLDER),
        (
            f'<img src="{PNG_URL}" onerror="alert(1)" alt="Logo">',
            f'<img src="{PNG_URL}" alt="Logo">',
        ),
        ('<a href="javascript:alert(1)">Klick</a>', "<a>Klick</a>"),
        ('<a href=" javascript:alert(1)">Klick</a>', "<a>Klick</a>"),
        ('<a href="&#106;avascript&#58;alert(1)">Klick</a>', "<a>Klick</a>"),
        ('<a href="data:text/html,&lt;script&gt;alert(1)&lt;/script&gt;">x</a>', "<a>x</a>"),
        ('<a href="https://tracker.example/?id=7">Bericht</a>', "<a>Bericht</a>"),
        ('<meta http-equiv="refresh" content="0;url=https://evil.example/">Text', "Text"),
        ('<base href="https://evil.example/"><p>Text</p>', "<p>Text</p>"),
        ('<link rel="stylesheet" href="https://evil.example/x.css"><p>T</p>', "<p>T</p>"),
        ('<p style="background:url(https://tracker.example/x.png)">T</p>', "<p>T</p>"),
        ("<style>body{background:url(https://evil.example/)}</style><p>T</p>", "<p>T</p>"),
        ("<svg onload=alert(1)><text>SVG-Text</text><svg></svg></svg>Danach", "Danach"),
        ("<svg/>Danach", "Danach"),
        ('<math><mi xlink:href="javascript:alert(1)">x</mi></math>Danach', "Danach"),
        ('<iframe srcdoc="<script>alert(1)</script>">Innen</iframe>Danach', "Danach"),
        (
            '<form action="https://evil.example/"><input name="q" value="geheim">'
            "<button>Senden</button></form>Danach",
            "Danach",
        ),
        ('<img src="http://tracker.example/pixel.gif">', PLACEHOLDER),
        ('<img src="//tracker.example/pixel.gif">', PLACEHOLDER),
        ('<img src="data:image/svg+xml;base64,PHN2Zz4=">', PLACEHOLDER),
        ('<img src="data:image/png;base64,AAAA&quot; onerror=&quot;x">', PLACEHOLDER),
        (
            '<img srcset="https://tracker.example/a.png 2x" src="' + PNG_URL + '">',
            f'<img src="{PNG_URL}">',
        ),
        ("<template><img src=x onerror=alert(1)></template>Danach", "Danach"),
        (
            '<object data="https://evil.example/x"><embed src="https://evil.example/y"></object>T',
            "T",
        ),
        ('<noscript><p title="</noscript><img src=x onerror=alert(1)>"></p></noscript>T', "T"),
        ("<title>Titel</title><head><meta charset=utf-8></head><p>T</p>", "<p>T</p>"),
        ("&lt;script&gt;alert(1)&lt;/script&gt;", "&lt;script&gt;alert(1)&lt;/script&gt;"),
        ('<p onclick="alert(1)" id="a1" class="x">x</p>', '<p id="a1">x</p>'),
        ("<p id='x\" onclick=\"alert(1)'>x</p>", '<p id="x&quot; onclick=&quot;alert(1)">x</p>'),
        ('<p id="erste" id="zweite">x</p>', '<p id="erste">x</p>'),
        ('<td colspan="2" rowspan="x">z</td>', '<td colspan="2">z</td>'),
        ('<td colspan="99999" rowspan="3">z</td>', '<td rowspan="3">z</td>'),
        ('<p colspan="2">z</p>', "<p>z</p>"),
        (
            '<a href="#footnote-1" id="ref-1">[1]</a>',
            '<a href="about:srcdoc#footnote-1" id="ref-1">[1]</a>',
        ),
        ("<p><b>fett", "<p><b>fett</b></p>"),
        ("</div></p>Text<br></br>", "Text<br>"),
        ("<ul><li>eins<li>zwei</ul>", "<ul><li>eins<li>zwei</li></li></ul>"),
        ("<marquee>Laufschrift</marquee><blink>B</blink>", "LaufschriftB"),
        ("<!-- <script>alert(1)</script> --><![CDATA[x]]><?php echo 1 ?>T", "T"),
        ("<p>a &amp; b &lt; c</p>", "<p>a &amp; b &lt; c</p>"),
    ],
)
def test_the_allow_list(html: str, expected: str) -> None:
    result = sanitize(html)
    assert result == expected
    assert sanitize(result) == result  # stable: its own output passes unchanged
    for tag, attrs in _elements(result):
        assert tag in KEPT
        for name, value in attrs:
            assert name in ("id", "colspan", "rowspan", "href", "src", "alt")
            assert name != "href" or (tag == "a" and str(value).startswith("about:srcdoc#"))
            assert name != "src" or (tag == "img" and str(value).startswith("data:image/"))


KEPT = {
    *("p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "b", "em", "i", "u", "s", "sub"),
    *("sup", "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption"),
    *("blockquote", "pre", "code", "span", "div", "hr", "a", "img"),
}


def _elements(html: str) -> list[tuple[str, list[tuple[str, str | None]]]]:
    """Every start tag of the HTML with its attributes, as html.parser reads them."""
    found: list[tuple[str, list[tuple[str, str | None]]]] = []

    class Collector(HTMLParser):
        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            found.append((tag, attrs))

    collector = Collector()
    collector.feed(html)
    collector.close()
    return found


def test_what_a_document_keeps() -> None:
    html = (
        "<h1>Titel</h1><h6>Klein</h6><p>Ein <strong>fetter</strong>, <em>kursiver</em>, "
        "<u>unterstrichener</u>, <s>gestrichener</s> Text mit H<sub>2</sub>O und m<sup>2</sup>.</p>"
        "<blockquote><pre><code>code</code></pre></blockquote><hr>"
        "<table><caption>Tabelle</caption><thead><tr><th>A</th></tr></thead>"
        '<tbody><tr><td rowspan="2">1</td></tr></tbody><tfoot><tr><td>F</td></tr></tfoot></table>'
        '<ol><li><span>eins</span></li></ol><ul><li><div id="d">zwei</div></li></ul>'
    )
    assert sanitize(html) == html


def test_the_page() -> None:
    document = page("<p>Inhalt</p>")
    assert document.startswith('<!doctype html>\n<html><head><meta charset="utf-8">')
    assert f'<meta http-equiv="Content-Security-Policy" content="{POLICY}">' in document
    assert POLICY == "default-src 'none'; img-src data:; style-src 'unsafe-inline'"
    assert "<body><p>Inhalt</p></body></html>" in document
    assert document.count("<style>") == 1
    assert "url(" not in document and "@import" not in document


def test_raster_types_by_their_first_bytes() -> None:
    assert raster_type(png()) == "image/png"
    assert raster_type(JPEG) == "image/jpeg"
    assert raster_type(b"GIF87a..") == raster_type(b"GIF89a..") == "image/gif"
    assert raster_type(b"RIFF\x10\x00\x00\x00WEBPVP8 ") == "image/webp"
    for data in (
        EMF,
        SVG,
        b"\xd7\xcd\xc6\x9a",
        b"II*\x00",
        b"BM",
        b"RIFF\x10\x00\x00\x00WAVE",
        b"",
    ):
        assert raster_type(data) is None


def test_images_within_the_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sanitizer, "IMAGE_BUDGET", 300)
    images = Images()
    picture = png()
    url = images.data_url([picture[:10], picture[10:]])
    assert url is not None and url.startswith("data:image/png;base64,iVBORw0KGgo")
    assert sanitize(f'<img src="{url}">') == f'<img src="{url}">'
    assert images.data_url([EMF]) is None
    assert images.data_url([SVG]) is None
    assert images.data_url([JPEG + bytes(400)]) is None  # more than is left
    assert images.data_url([JPEG]) is not None
    assert images.data_url([picture, picture, picture]) is None  # the budget is spent
