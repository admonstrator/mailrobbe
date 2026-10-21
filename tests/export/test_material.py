"""The numbers behind an export's signaturen.json (D105) without a database: s and m of the
generated mails' signatures against the generator's keys, and the check script's own reading of
a key record and of m."""

import base64
from collections import Counter

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from mailrobbe.export import pruefe_rekonstruktion
from mailrobbe.export.material import encoded_message, signature_material
from mailrobbe.generator.config import DKIM_KEY_DIR
from mailrobbe.mbox import read_message
from tests.conftest import GeneratedArchive


def _keys(archive: GeneratedArchive) -> dict[int, rsa.RSAPublicKey]:
    keys = {}
    for pem in (archive.config.meta_dir / DKIM_KEY_DIR).glob("rsa-*.pem"):
        key = serialization.load_pem_private_key(pem.read_bytes(), password=None)
        assert isinstance(key, rsa.RSAPrivateKey)
        keys[key.key_size] = key.public_key()
    return keys


def test_signatures_hold_under_the_generator_keys(generated_archive: GeneratedArchive) -> None:
    """Every signature expected to pass holds, and so do retired selectors' signatures, except
    those whose signed header changed after signing (no key showed that at import)."""
    numbers = [key.public_numbers() for key in _keys(generated_archive).values()]
    held: Counter[str] = Counter()
    for record in generated_archive.manifest:
        raw = None
        for index, outcome in enumerate(record["dkim"]["signatures"]):
            if (outcome["expected"], outcome["reason"]) not in {
                ("pass", None),
                ("no_key", "selector_retired"),
            }:
                continue
            raw = raw or read_message(
                generated_archive.mbox_dir / record["file"], record["offset"], record["length"]
            )
            material = signature_material(raw, index)
            assert material is not None, (record["index"], index)
            assert material.hash_name == "sha256"
            holds = any(
                pow(material.signature, n.e, n.n) == material.message(n.n.bit_length())
                for n in numbers
            )
            assert holds or outcome["expected"] == "no_key", (record["index"], index)
            held[outcome["expected"] if holds else "changed"] += 1
    assert held["pass"] > 100 and held["no_key"] > 5, held


def test_no_material_without_a_valid_rsa_signature() -> None:
    assert signature_material(b"Subject: x\n\nbody\n", 0) is None
    broken = b"DKIM-Signature: v=1; a=rsa-sha256; d=firma.example\nFrom: a@firma.example\n\nx\n"
    assert signature_material(broken, 0) is None
    assert signature_material(broken, 1) is None


def test_the_check_script_reads_both_key_formats(generated_archive: GeneratedArchive) -> None:
    for bits, key in _keys(generated_archive).items():
        numbers = key.public_numbers()
        for public_format in (
            serialization.PublicFormat.SubjectPublicKeyInfo,
            serialization.PublicFormat.PKCS1,
        ):
            der = key.public_bytes(serialization.Encoding.DER, public_format)
            p = base64.b64encode(der).decode()
            record = f"v=DKIM1; k=rsa; p={p[:30]} {p[30:]}"
            assert pruefe_rekonstruktion.public_key(record) == (numbers.n, numbers.e)
        digest = bytes(range(32))
        size = (bits + 7) // 8
        assert pruefe_rekonstruktion.encoded(digest, "sha256", size) == encoded_message(
            digest, "sha256", bits
        )
        assert encoded_message(digest[:20], "sha1", bits).bit_length() == bits - 15
