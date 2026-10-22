"""The paragraphs of a mail's text and their hashes (D224).

A paragraph's hash is a signed 64-bit integer in the database (mail_paragraph.hash) and 16
lower-case hex digits of its unsigned value in the API (schemas.BLOCK_HASH_PATTERN).
"""

_MASK = (1 << 64) - 1


def hash_hex(value: int) -> str:
    """The API's form of a stored hash."""
    return format(value & _MASK, "016x")


def parse_hash(text: str) -> int:
    """The stored form of an API hash (16 hex digits, as BLOCK_HASH_PATTERN checks)."""
    value = int(text, 16)
    return value - (1 << 64) if value >= 1 << 63 else value
