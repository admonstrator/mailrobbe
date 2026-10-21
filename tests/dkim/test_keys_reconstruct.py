"""keys.reconstruct: RSA moduli from pairs of signatures, and Batch-GCD.

Keys of 512 bits made from seeded primes, signed with plain arithmetic (s = m^d mod n), keep the
GCDs small: a pair with e = 3 takes microseconds, one with e = 65537 about 7 s. The structure
tests therefore try e = 3 alone; two slow tests run the real exponent order.
"""

import hashlib
import math
import random
from collections.abc import Iterator

import gmpy2
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.utils import Prehashed

from mailrobbe.dkim.keys import reconstruct
from mailrobbe.dkim.keys.reconstruct import (
    RebuiltKey,
    RsaSignature,
    encoded_message,
    modulus_from_pair,
    rebuild_keys,
    shared_factors,
    verifies,
)
from tests.dkim.test_verify import private_key


class Key:
    """An RSA key from seeded primes; signs header hashes like a DKIM signer."""

    def __init__(self, seed: int, exponent: int = 3, bits: int = 512) -> None:
        rng = random.Random(seed)
        self.p, self.q = _prime(rng, bits // 2, exponent), _prime(rng, bits // 2, exponent)
        self.n, self.e = self.p * self.q, exponent
        self.d = pow(exponent, -1, (self.p - 1) * (self.q - 1))
        self.size = (self.n.bit_length() + 7) // 8

    def sign(self, text: str, hash_name: str = "sha256") -> RsaSignature:
        digest = hashlib.new(hash_name, text.encode()).digest()
        message = encoded_message(hash_name, digest, self.size)
        assert message is not None
        value = pow(message, self.d, self.n).to_bytes(self.size)
        return RsaSignature(value, hash_name, digest)


def _prime(rng: random.Random, bits: int, exponent: int) -> int:
    while True:
        prime = int(gmpy2.next_prime(rng.getrandbits(bits) | (3 << (bits - 2))))
        if prime.bit_length() == bits and math.gcd(exponent, prime - 1) == 1:
            return prime


def changed(signature: RsaSignature) -> RsaSignature:
    """The signature of a mail whose signed header changed after signing."""
    digest = hashlib.new(signature.hash_name, signature.header_hash).digest()
    return RsaSignature(signature.value, signature.hash_name, digest)


@pytest.fixture
def only_e3(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(reconstruct, "EXPONENTS", (3,))
    yield


@pytest.mark.parametrize("hash_name", ["sha256", "sha1"])
def test_the_encoding_is_what_pkcs1_signs(hash_name: str) -> None:
    key = private_key("rsa1024")
    assert isinstance(key, rsa.RSAPrivateKey)
    numbers = key.public_key().public_numbers()
    digest = hashlib.new(hash_name, b"header").digest()
    algorithm = hashes.SHA256() if hash_name == "sha256" else hashes.SHA1()
    value = key.sign(digest, padding.PKCS1v15(), Prehashed(algorithm))
    assert pow(int.from_bytes(value), numbers.e, numbers.n) == encoded_message(
        hash_name, digest, 128
    )
    signature = RsaSignature(value, hash_name, digest)
    assert verifies(numbers.n, numbers.e, signature)
    assert not verifies(numbers.n, 3, signature)
    assert encoded_message("sha512", digest, 128) is None
    assert encoded_message(hash_name, digest, len(digest) + 20) is None  # no room for padding


@pytest.mark.parametrize("hash_name", ["sha256", "sha1"])
def test_two_signatures_give_the_modulus(only_e3: None, hash_name: str) -> None:
    key = Key(1)
    first, second = key.sign("one", hash_name), key.sign("two", "sha256")
    assert modulus_from_pair(first, second, 3) == key.n
    assert modulus_from_pair(first, first, 3) is None  # one signature: s^e - m itself
    assert rebuild_keys([first, second, key.sign("three")]) == [RebuiltKey(key.n, 3, (0, 1, 2))]


def test_signatures_of_another_key_or_a_changed_header_hold_no_pair(only_e3: None) -> None:
    key, other = Key(1), Key(2)
    assert modulus_from_pair(key.sign("one"), other.sign("two"), 3) is None
    assert modulus_from_pair(key.sign("one"), changed(key.sign("two")), 3) is None
    assert rebuild_keys([key.sign("one")]) == []
    assert rebuild_keys([]) == []
    # signatures of different lengths are not even paired
    assert rebuild_keys([key.sign("one"), Key(3, bits=1024).sign("two")]) == []


def test_a_changed_header_is_set_aside(only_e3: None) -> None:
    key = Key(1)
    signatures = [changed(key.sign("zero")), key.sign("one"), key.sign("two")]
    # (0, 1) and (0, 2) fail, (1, 2) holds; the changed one is verified by no key
    assert rebuild_keys(signatures) == [RebuiltKey(key.n, 3, (1, 2))]


def test_a_new_key_under_the_old_name(only_e3: None) -> None:
    old, new = Key(1), Key(2)
    signatures = [old.sign("a"), old.sign("b"), new.sign("c"), old.sign("d"), new.sign("e")]
    assert rebuild_keys(signatures) == [
        RebuiltKey(old.n, 3, (0, 1, 3)),
        RebuiltKey(new.n, 3, (2, 4)),
    ]


def test_pairs_are_tried_up_to_the_limit(only_e3: None) -> None:
    key = Key(1)
    bad = [changed(key.sign(text)) for text in ("a", "b", "c")]
    signatures = [*bad, key.sign("d"), key.sign("e")]
    # six pairs among the first four signatures fail; (3, 4) is the tenth
    assert rebuild_keys(signatures) == []
    assert rebuild_keys(signatures, pair_limit=10) == [RebuiltKey(key.n, 3, (3, 4))]


def test_a_leading_zero_byte_dropped_from_b() -> None:
    key = Key(1)
    signature = next(s for s in (key.sign(str(i)) for i in range(2000)) if s.value[0] == 0)
    shortened = RsaSignature(signature.value[1:], signature.hash_name, signature.header_hash)
    assert verifies(key.n, 3, shortened)


@pytest.mark.slow
def test_e_65537() -> None:
    key = Key(4, exponent=65537)
    signatures = [key.sign("one"), key.sign("two", "sha1")]
    assert rebuild_keys(signatures) == [RebuiltKey(key.n, 65537, (0, 1))]


@pytest.mark.slow
def test_e_3_after_65537() -> None:
    key = Key(5, exponent=3)
    assert rebuild_keys([key.sign("one"), key.sign("two")]) == [RebuiltKey(key.n, 3, (0, 1))]


def test_batch_gcd_finds_the_moduli_sharing_a_prime() -> None:
    a, b, c = Key(1), Key(2), Key(3)
    shared = a.p * b.q  # a modulus made with a's prime
    moduli = [a.n, b.n, c.n, shared, a.n]
    assert shared_factors(moduli) == {a.n, b.n, shared}
    assert shared_factors([a.n, b.n, c.n, a.n]) == set()
    assert shared_factors([a.n]) == set()
    assert shared_factors([]) == set()
    # both primes shared: the gcd is n itself
    assert shared_factors([a.n, a.p * c.p, a.q * c.q]) == {a.n, a.p * c.p, a.q * c.q}
