"""The fast body canonicalisation must give exactly dkimpy's canonical body."""

import base64
import random

import dkim
import pytest
from dkim.canonicalization import CanonicalizationPolicy

from mailrobbe.dkim import canonical
from mailrobbe.dkim.canonical import canonical_blocks, canonical_body

_PIECES = (
    b"Text",
    b"x",
    b" ",
    b"  ",
    b"\t",
    b" \t ",
    b"\r",
    b"\n",
    b"\r\n",
    b"\n\n",
    b"\r\r\n",
    b" \n",
    b"\t\r\n",
    b"\x0b",
    b"\xe4",
    b"QUJD",
)


def dkimpy(body: bytes, relaxed: bool) -> bytes:
    """dkimpy's canonical form of a body as it stands in a message."""
    _, parsed = dkim.rfc822_parse(b"Subject: x\n\n" + body)
    c = b"relaxed/relaxed" if relaxed else b"simple/simple"
    canonical: bytes = CanonicalizationPolicy.from_c_value(c).canonicalize_body(parsed)
    return canonical


@pytest.mark.parametrize("relaxed", [True, False], ids=["relaxed", "simple"])
@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"\n",
        b"\r\n",
        b"\n\n\n",
        b" \n\t\n  \n",
        b"no final line break",
        b"text\n\n\n",
        b"tab\tinside\n",
        b"two  spaces and a long run" + b" " * 1000 + b"end\n",
        b"trailing \nwhitespace\t\nend",
        b"-- \nsignature separator\n",
        b"stray\r\ncarriage\rreturns\r\n",
        b"a \r \n",
        b"mixed\r\nline\nends\r\n\r\n",
        b"whitespace only at the end   ",
        b"blank\n   \nline in the middle\n",
        b"QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo=\nYWJj\n\n",
    ],
)
def test_bodies(body: bytes, relaxed: bool) -> None:
    expected = dkimpy(body, relaxed)
    assert canonical_body(body, relaxed) == expected
    assert canonical_body(body.replace(b"\n", b"\r\n"), relaxed) == dkimpy(
        body.replace(b"\n", b"\r\n"), relaxed
    )


@pytest.mark.parametrize("block_size", [1, 3, 16, canonical.BLOCK_SIZE])
def test_random_bodies(monkeypatch: pytest.MonkeyPatch, block_size: int) -> None:
    """Small blocks put block borders everywhere: into runs of whitespace, between CR and LF."""
    monkeypatch.setattr(canonical, "BLOCK_SIZE", block_size)
    rng = random.Random(block_size)
    for _ in range(3000):
        body = b"".join(rng.choice(_PIECES) for _ in range(rng.randint(0, 40)))
        for relaxed in (True, False):
            assert canonical_body(body, relaxed) == dkimpy(body, relaxed), body


def test_large_body_with_text_and_attachment() -> None:
    rng = random.Random(4)
    text = b"Hallo zusammen,  \n\tanbei die Unterlagen.\n-- \nAnna\n" * 2000
    attachment = base64.encodebytes(rng.randbytes(3 * canonical.BLOCK_SIZE + 17))
    body = text + b"\n" + attachment + b" \n\n" + text + b"\n \n\t\n\n"
    for relaxed in (True, False):
        assert canonical_body(body, relaxed) == dkimpy(body, relaxed)
        assert len(list(canonical_blocks(body, relaxed))) > 3


def test_blocks_of_a_body_inside_a_message() -> None:
    message = b"Subject: x\n\nbody  text\n\n"
    start = message.index(b"\n\n") + 2
    for relaxed in (True, False):
        blocks = canonical_blocks(message, relaxed, start)
        assert b"".join(blocks) == canonical_body(message[start:], relaxed)
