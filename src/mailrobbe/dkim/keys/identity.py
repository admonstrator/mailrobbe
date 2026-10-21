"""The identity of a DKIM key across sources (D100), and records for reconstructed keys.

Two sources name the same key when its key_sha256 is the same: the SHA-256 of the DER
SubjectPublicKeyInfo for RSA (whatever form p= had: SubjectPublicKeyInfo or a bare
RSAPublicKey), of the raw 32 bytes for Ed25519. Records are parsed exactly as the verifier
parses them (verify.parse_key_record), so a key with an identity is a key the verifier can use.
"""

import base64
import hashlib
from dataclasses import dataclass

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from mailrobbe.dkim.override import normalise_name
from mailrobbe.dkim.verify import parse_key_record
from mailrobbe.enums import DkimReason

KEY_NAME_INFIX = "._domainkey."


@dataclass(frozen=True, slots=True)
class KeyIdentity:
    key_type: str  # rsa or ed25519
    bits: int
    key_sha256: str
    modulus: int | None  # RSA only
    exponent: int | None


def key_identity(record: str) -> KeyIdentity | None:
    """The key in a DKIM key record; None when it holds none (malformed, revoked, other k=)."""
    key = parse_key_record(record)
    if isinstance(key, DkimReason):
        return None
    if isinstance(key.public, rsa.RSAPublicKey):
        numbers = key.public.public_numbers()
        der = key.public.public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return KeyIdentity("rsa", key.bits, _sha256(der), numbers.n, numbers.e)
    raw = key.public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return KeyIdentity("ed25519", key.bits, _sha256(raw), None, None)


def rsa_record(modulus: int, exponent: int) -> str:
    """The key record of a reconstructed RSA key: v=DKIM1; k=rsa; p=<SubjectPublicKeyInfo>."""
    public = rsa.RSAPublicNumbers(exponent, modulus).public_key()
    der = public.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return "v=DKIM1; k=rsa; p=" + base64.b64encode(der).decode("ascii")


def split_key_name(name: str) -> tuple[str, str] | None:
    """(selector, domain) of '<selector>._domainkey.<domain>', normalised; None for any other
    name."""
    selector, infix, domain = normalise_name(name).partition(KEY_NAME_INFIX)
    if not infix or not selector or not domain or KEY_NAME_INFIX in domain:
        return None
    return selector, domain


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
