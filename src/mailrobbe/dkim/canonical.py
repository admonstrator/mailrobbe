"""DKIM body canonicalisation (RFC 6376 3.4.3, 3.4.4), byte-identical to dkimpy's, but fast.

dkimpy's canonicalize_body works on the body as rfc822_parse returns it (split into lines and
joined with CRLF) and runs two whitespace regexes over all of it; with the parsing that costs
about 20 ms per MB, also where nothing changes, as in base64 attachments. Here the body is taken
as it stands in the message, LF or CRLF, and converted in blocks of whole lines with plain bytes
operations: CRLF line ends, then for relaxed tabs to spaces, runs of spaces to one and no space
before a line end. A block without spaces and tabs, such as base64, skips the relaxed steps after
two scans, and one with some (text, an indented HTML part) costs a few scans more, never a regex.
Trailing empty lines (for relaxed also lines of whitespace only) are cut off a short tail.
"""

from dkim.canonicalization import correct_empty_body, strip_trailing_lines

BLOCK_SIZE = 64 * 1024  # a block of lines stays in the CPU cache through all of its steps


def canonical_body(body: bytes, relaxed: bool) -> bytes:
    """dkimpy's canonicalize_body (relaxed or simple) of a body with LF or CRLF line endings."""
    return b"".join(canonical_chunks(body, relaxed))


def canonical_chunks(data: bytes, relaxed: bool, start: int = 0) -> list[bytes]:
    """canonical_body of data[start:] in pieces, without copying the body out of data first."""
    end = _content_end(data, start, b" \t\r\n" if relaxed else b"\r\n")
    chunks = []
    position = start
    while position < end:
        # Blocks end after a LF, so neither a CRLF nor a run of whitespace spans two of them.
        stop = data.find(b"\n", position + BLOCK_SIZE, end)
        stop = end if stop < 0 else stop + 1
        chunks.append(_convert(data[position:stop], relaxed))
        position = stop
    tail = strip_trailing_lines(_convert(data[end:], relaxed))
    if relaxed and not chunks:
        tail = correct_empty_body(tail)
    chunks.append(tail)
    return chunks


def _content_end(data: bytes, start: int, trailing: bytes) -> int:
    """Index after the last byte of data[start:] not in trailing; start if there is none.

    What follows it are line breaks and whitespace only, the part canonicalisation may cut.
    """
    end = len(data)
    window = 256
    while end > start:
        low = max(start, end - window)
        kept = len(data[low:end].rstrip(trailing))
        if kept:
            return low + kept
        end, window = low, window * 2
    return start


def _convert(block: bytes, relaxed: bool) -> bytes:
    # Line ends as rfc822_parse leaves them: every LF, with or without a CR before it, as CRLF.
    if b"\r" in block:
        block = block.replace(b"\r\n", b"\n")
    block = block.replace(b"\n", b"\r\n")
    if relaxed and (b" " in block or b"\t" in block):
        # dkimpy removes whitespace before CRLF, then turns every run of it into one space;
        # turning runs into one space first and then removing a space before CRLF is the same.
        block = block.replace(b"\t", b" ")
        while b"  " in block:
            block = block.replace(b"  ", b" ")
        block = block.replace(b" \r\n", b"\r\n")
    return block
