"""What the RSA equation of one DKIM signature needs (D104, D105): s^e = m (mod n), with s the
signature (b=) as a number and m the header hash encoded per EMSA-PKCS1-v1_5 for the key's size.

A stand-in with the verifier's own parsing and header hash (dkim.verify), until dkim/keys offers
the signature material the reconstruction works with; the export reads it from here.
"""

from dataclasses import dataclass

import dkim
from dkim.util import InvalidTagValueList, parse_tag_value

from mailrobbe.dkim import verify
from mailrobbe.enums import DkimReason

# DER of DigestInfo up to the digest (RFC 8017 9.2, note 1)
DIGEST_INFO = {
    "sha256": bytes.fromhex("3031300d060960864801650304020105000420"),
    "sha1": bytes.fromhex("3021300906052b0e03021a05000414"),
}


@dataclass(frozen=True, slots=True)
class SignatureMaterial:
    signature: int  # s: b= as an unsigned big-endian number
    digest: bytes  # the header hash the signature covers
    hash_name: str  # sha256 or sha1

    def message(self, bits: int) -> int:
        """m: the digest encoded per EMSA-PKCS1-v1_5 for a modulus of this many bits."""
        return encoded_message(self.digest, self.hash_name, bits)


def encoded_message(digest: bytes, hash_name: str, bits: int) -> int:
    size = (bits + 7) // 8
    info = DIGEST_INFO[hash_name] + digest
    return int.from_bytes(b"\x00\x01" + b"\xff" * (size - len(info) - 3) + b"\x00" + info)


def signature_material(raw: bytes, index: int) -> SignatureMaterial | None:
    """The material of the index-th DKIM-Signature field of raw (topmost 0), as verify_mail
    checks it; None when that is no valid RSA signature or the header cannot be parsed."""
    header_end, body_start = verify._split(raw)
    try:
        headers, _ = dkim.rfc822_parse(raw[:header_end])
    except Exception:  # as in verify_mail
        return None
    fields = [(name, value) for name, value in headers if name.lower() == b"dkim-signature"]
    if index >= len(fields):
        return None
    name, value = fields[index]
    try:
        signature = verify._parse_signature(parse_tag_value(value))
    except InvalidTagValueList:
        return None
    if isinstance(signature, DkimReason) or signature.key_type != b"rsa":
        return None
    digest = verify._Mail(raw, body_start, headers)._header_hash(name, value, signature)
    return SignatureMaterial(int.from_bytes(signature.signature), digest, signature.hash_name)
