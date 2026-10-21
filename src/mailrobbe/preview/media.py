"""Audio and video the browsers play (D123), recognised by their first bytes: the type the media
endpoint serves them with.

MP3 (an ID3 tag or an MPEG audio frame), AAC (an ADTS frame), WAV, Ogg (Vorbis, Opus), FLAC, WebM
(EBML with the doc type webm; other Matroska files are not offered, browsers play only some of
them) and the MP4 family by the major brand of its ftyp box: M4A and M4B as audio/mp4, HEIF and
AVIF (images in the same box format) not at all, everything else as video/mp4. That includes
QuickTime (brand "qt  "): Chrome and Firefox refuse video/quicktime but play a MOV with H.264
under video/mp4, and Safari plays both, so MOV is served as video/mp4. Anything else has no
preview.
"""

VERSION = 1  # of the cached media files: the attachment's bytes as they are

_AUDIO_BRANDS = frozenset({b"M4A ", b"M4B ", b"M4P "})
_IMAGE_BRANDS = frozenset(
    {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"avif", b"avis"}
)
_EBML = b"\x1aE\xdf\xa3"
_DOC_TYPE = b"\x42\x82"  # EBML element id of the doc type


def media_type(head: bytes) -> str | None:
    """The type of audio or video a browser plays, from the first bytes; None for anything
    else."""
    if head.startswith(b"ID3"):
        return "audio/mpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head.startswith(b"OggS"):
        return "audio/ogg"
    if head.startswith(b"fLaC"):
        return "audio/flac"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in _AUDIO_BRANDS:
            return "audio/mp4"
        return None if brand in _IMAGE_BRANDS else "video/mp4"
    if head.startswith(_EBML):
        return "video/webm" if _doc_type(head) == b"webm" else None
    return _frame(head)


def _frame(head: bytes) -> str | None:
    """audio/mpeg or audio/aac when the content starts with an MPEG audio or an ADTS frame."""
    if len(head) < 4 or head[0] != 0xFF or head[1] & 0xE0 != 0xE0:
        return None
    if head[1] & 0xF6 == 0xF0:  # ADTS: a 12-bit sync, layer 0
        return "audio/aac" if (head[2] >> 2) & 0x0F <= 12 else None  # a known sampling rate
    version, layer = (head[1] >> 3) & 3, (head[1] >> 1) & 3
    bitrate, rate = head[2] >> 4, (head[2] >> 2) & 3
    if version == 1 or layer == 0 or bitrate == 15 or rate == 3:  # reserved values
        return None
    return "audio/mpeg"


def _doc_type(head: bytes) -> bytes:
    """The doc type of an EBML header (webm, matroska), when written with a one-byte size as
    every muxer does; b"" otherwise."""
    at = head.find(_DOC_TYPE, len(_EBML), 64)
    if at < 0 or at + 3 > len(head) or not head[at + 2] & 0x80:
        return b""
    start = at + 3
    return head[start : start + (head[at + 2] & 0x7F)]
