"""RSA keys from signatures (D104), and the moduli that share a prime factor (Batch-GCD).

A PKCS#1 v1.5 signature s of a key (n, e) over the encoded header hash m satisfies s^e = m
(mod n), so n divides s^e - m, and the GCD of that number for two signatures of one key is n up
to small factors. A modulus counts only when it has the signatures' length and verifies both;
the signatures it verifies are set aside and the rest are paired again, which finds a new key
under an old name too. A pair fails when one of its mails was changed in a signed header after
signing, or when the two come from different keys.

Everything here takes and returns plain ints and bytes, so worker processes can run it. gmpy2
(GMP) computes the GCD of the 16 MiB numbers of a 2048-bit pair in about 50 s and of a 1024-bit
pair in about 20 s; Python's own GCD would take hours. Every other step is cheap.
"""

import math
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Any

import gmpy2

# EMSA-PKCS1-v1_5 (RFC 8017 9.2): 00 01 FF..FF 00 DigestInfo hash; the DigestInfo prefixes
DIGEST_INFO = {
    "sha256": bytes.fromhex("3031300d060960864801650304020105000420"),
    "sha1": bytes.fromhex("3021300906052b0e03021a05000414"),
}
EXPONENTS = (65537, 3)  # the exponent of nearly every key, then the only other one in use
SMALL_FACTORS_BELOW = 2**16  # the GCD's extra factors are divided out up to here
# Pairs tried per key with e = 65537, the expensive part: every pair among the first four
# signatures, so up to two changed mails among them still leave a pair that holds.
PAIR_LIMIT = 6

_SMALL_PRIMES = gmpy2.primorial(SMALL_FACTORS_BELOW)  # their product


@dataclass(frozen=True, slots=True)
class RsaSignature:
    """One RSA signature as the arithmetic needs it (from verify.SignatureMaterial)."""

    value: bytes  # b=
    hash_name: str  # sha256 or sha1
    header_hash: bytes  # the digest b= signs


@dataclass(frozen=True, slots=True)
class RebuiltKey:
    modulus: int
    exponent: int
    signatures: tuple[int, ...]  # positions of the signatures it verifies, in input order


def encoded_message(hash_name: str, digest: bytes, size: int) -> int | None:
    """m: the digest encoded for a key of `size` bytes, as a number; None when it cannot be."""
    prefix = DIGEST_INFO.get(hash_name)
    if prefix is None:
        return None
    info = prefix + digest
    padding = size - len(info) - 3
    if padding < 8:
        return None
    return int.from_bytes(b"\x00\x01" + b"\xff" * padding + b"\x00" + info)


def verifies(modulus: int, exponent: int, signature: RsaSignature) -> bool:
    """s^e = m (mod n), with m encoded for the modulus' length, as every verifier computes it."""
    if modulus < 2:
        return False
    size = (modulus.bit_length() + 7) // 8
    message = encoded_message(signature.hash_name, signature.header_hash, size)
    value = int.from_bytes(signature.value)
    return message is not None and gmpy2.powmod(value, exponent, modulus) == message


def modulus_from_pair(first: RsaSignature, second: RsaSignature, exponent: int) -> int | None:
    """The modulus of the key that made both signatures with this exponent; None if there is
    none (different keys, a changed header, another exponent)."""
    return _Pairs([first, second]).modulus(0, 1, exponent)


def rebuild_keys(
    signatures: Sequence[RsaSignature], pair_limit: int = PAIR_LIMIT
) -> list[RebuiltKey]:
    """The keys of these signatures, in the order found; best ordered oldest first.

    Pairs are tried in order, (0, 1), (0, 2), (1, 2), (0, 3), ..., with each exponent, at most
    pair_limit per key; a key found takes every remaining signature it verifies, and the rest
    are paired again.
    """
    pairs = _Pairs(signatures)
    remaining = list(range(len(signatures)))
    found: list[RebuiltKey] = []
    while len(remaining) >= 2:
        key = pairs.first_key(remaining, pair_limit)
        if key is None:
            break
        modulus, exponent = key
        taken = tuple(i for i in remaining if verifies(modulus, exponent, signatures[i]))
        found.append(RebuiltKey(modulus, exponent, taken))
        remaining = [i for i in remaining if i not in taken]
        pairs.forget(taken)
    return found


def shared_factors(moduli: Collection[int]) -> set[int]:
    """The moduli that share a prime factor with another one (Batch-GCD).

    The product of all moduli comes from a product tree; the remainder tree gives each P mod
    n^2, and gcd(P mod n^2 / n, n) > 1 exactly when another modulus shares a factor with n.
    The same modulus given twice counts once.
    """
    distinct = sorted({modulus for modulus in moduli if modulus > 1})
    if len(distinct) < 2:
        return set()
    tree = [[gmpy2.mpz(modulus) for modulus in distinct]]
    while len(tree[-1]) > 1:
        level = tree[-1]
        tree.append([math.prod(level[i : i + 2]) for i in range(0, len(level), 2)])
    remainders = tree.pop()
    while tree:
        level = tree.pop()
        remainders = [remainders[i // 2] % (value * value) for i, value in enumerate(level)]
    return {
        modulus
        for modulus, remainder in zip(distinct, remainders, strict=True)
        if gmpy2.gcd(remainder // modulus, modulus) > 1
    }


class _Pairs:
    """s^e - m per signature and exponent, computed once: the power is 16 MiB for a 2048-bit
    key with e = 65537."""

    def __init__(self, signatures: Sequence[RsaSignature]) -> None:
        self._signatures = signatures
        self._powers: dict[tuple[int, int], Any] = {}

    def first_key(self, remaining: list[int], pair_limit: int) -> tuple[int, int] | None:
        tried = 0
        for second in range(1, len(remaining)):
            for first in range(second):
                a, b = remaining[first], remaining[second]
                if len(self._signatures[a].value) != len(self._signatures[b].value):
                    continue  # keys of different lengths
                if tried == pair_limit:
                    return None
                tried += 1
                for exponent in EXPONENTS:
                    modulus = self.modulus(a, b, exponent)
                    if modulus is not None:
                        return modulus, exponent
        return None

    def modulus(self, a: int, b: int, exponent: int) -> int | None:
        first, second = self._signatures[a], self._signatures[b]
        size = len(first.value)
        x, y = self._power(a, exponent), self._power(b, exponent)
        if len(second.value) != size or x is None or y is None:
            return None
        modulus = _without_small_factors(gmpy2.gcd(x, y))
        if (modulus.bit_length() + 7) // 8 != size:
            return None
        modulus = int(modulus)
        if verifies(modulus, exponent, first) and verifies(modulus, exponent, second):
            return modulus
        return None

    def forget(self, taken: Collection[int]) -> None:
        for key in [key for key in self._powers if key[0] in taken]:
            del self._powers[key]

    def _power(self, index: int, exponent: int) -> Any:
        key = (index, exponent)
        if key not in self._powers:
            signature = self._signatures[index]
            size = len(signature.value)
            message = encoded_message(signature.hash_name, signature.header_hash, size)
            self._powers[key] = (
                None
                if message is None
                else gmpy2.mpz(int.from_bytes(signature.value)) ** exponent - message
            )
        return self._powers[key]


def _without_small_factors(value: Any) -> Any:
    """value without its prime factors below SMALL_FACTORS_BELOW."""
    factor = gmpy2.gcd(value, _SMALL_PRIMES)
    while factor > 1:
        value //= factor
        factor = gmpy2.gcd(value, factor)
    return value
