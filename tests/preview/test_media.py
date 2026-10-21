"""Audio and video by their first bytes (D123)."""

import pytest

from mailrobbe.preview.media import media_type
from tests.preview.samples import JPEG, png, wav

WEBM = b"\x1aE\xdf\xa3\x9fB\x86\x81\x01B\xf7\x81\x01B\xf2\x81\x04B\xf3\x81\x08B\x82\x84webm"
MATROSKA = b"\x1aE\xdf\xa3\xa3B\x86\x81\x01B\xf7\x81\x01B\xf2\x81\x04B\xf3\x81\x08B\x82\x88matroska"


def ftyp(brand: bytes) -> bytes:
    return b"\x00\x00\x00\x20ftyp" + brand + b"\x00\x00\x02\x00isomiso2mp41"


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (b"ID3\x04\x00\x00\x00\x00\x00\x00", "audio/mpeg"),
        (b"\xff\xfb\x90\x64\x00", "audio/mpeg"),  # MPEG-1 Layer III, 128 kbit/s, 44.1 kHz
        (b"\xff\xf3\x48\xc4\x00", "audio/mpeg"),  # MPEG-2 Layer III
        (b"\xff\xe3\x18\xc4\x00", "audio/mpeg"),  # MPEG-2.5 Layer III
        (b"\xff\xf1\x50\x80\x02\x1f\xfc", "audio/aac"),  # ADTS, AAC LC, 44.1 kHz
        (b"\xff\xf9\x4c\x80\x02\x1f\xfc", "audio/aac"),  # ADTS, MPEG-2
        (wav(), "audio/wav"),
        (b"OggS\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00", "audio/ogg"),
        (b"fLaC\x00\x00\x00\x22", "audio/flac"),
        (ftyp(b"M4A "), "audio/mp4"),
        (ftyp(b"M4B "), "audio/mp4"),
        (ftyp(b"isom"), "video/mp4"),
        (ftyp(b"mp42"), "video/mp4"),
        (ftyp(b"M4V "), "video/mp4"),
        (ftyp(b"qt  "), "video/mp4"),  # MOV: Chrome and Firefox play it under video/mp4
        (WEBM, "video/webm"),
        # no media a browser plays, or no media at all
        (MATROSKA, None),
        (ftyp(b"heic"), None),
        (ftyp(b"avif"), None),
        (b"RIFF\x24\x00\x00\x00AVI LIST", None),
        (b"0&\xb2u\x8ef\xcf\x11\xa6\xd9\x00\xaa\x00b\xce\x6c", None),  # WMA/WMV (ASF)
        (b"FORM\x00\x00\x00\x00AIFF", None),
        (b"\xff\xfb\xf0\x64", None),  # a bad bitrate
        (b"\xff\xfb\x9c\x64", None),  # a reserved sampling rate
        (b"\xff\xeb\x90\x64", None),  # a reserved MPEG version
        (b"\xff\xf9\x7c\x80", None),  # ADTS with an unknown sampling rate
        (b"\xff\xfb", None),
        (JPEG, None),
        (png(), None),
        (b"%PDF-1.7", None),
        (b"", None),
    ],
)
def test_media_types_by_their_first_bytes(head: bytes, expected: str | None) -> None:
    assert media_type(head) == expected
