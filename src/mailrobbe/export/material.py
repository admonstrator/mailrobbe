"""What the RSA equation of one exported DKIM signature needs (D104, D105): s^e = m (mod n), with
s the signature (b=) as a number and m the header hash encoded per EMSA-PKCS1-v1_5 for the key's
size, both as the reconstruction computes them (dkim.verify.signature_material,
dkim.keys.reconstruct.encoded_message).
"""

from dataclasses import dataclass

from mailrobbe.dkim.keys import reconstruct
from mailrobbe.dkim.verify import signature_material as signatures_of


@dataclass(frozen=True, slots=True)
class SignatureMaterial:
    signature: int  # s: b= as an unsigned big-endian number
    digest: bytes  # the header hash the signature covers
    hash_name: str  # sha256 or sha1

    def message(self, bits: int) -> int:
        """m: the digest encoded per EMSA-PKCS1-v1_5 for a modulus of this many bits."""
        return encoded_message(self.digest, self.hash_name, bits)


def encoded_message(digest: bytes, hash_name: str, bits: int) -> int:
    message = reconstruct.encoded_message(hash_name, digest, (bits + 7) // 8)
    if message is None:
        raise ValueError(f"no PKCS#1 v1.5 encoding of a {hash_name} digest for {bits} bits")
    return message


def signature_material(raw: bytes, index: int) -> SignatureMaterial | None:
    """The material of the index-th DKIM-Signature field of raw (topmost 0), as verify_mail
    checks it; None when that is no valid RSA signature or the header cannot be parsed."""
    for material in signatures_of(raw):
        if material.index == index and material.key_type == "rsa":
            return SignatureMaterial(
                int.from_bytes(material.signature), material.header_hash, material.hash_name
            )
    return None
