"""Checks the signatures of signaturen.json against the key in record.txt (Mailrobbe export,
D105), with Python's standard library alone.

For RSA with PKCS#1 v1.5 a signature s holds for the message m under the key (n, e) exactly
when s^e mod n = m, and m is the hash the signature covers, padded as EMSA-PKCS1-v1_5 for the
key's size. This script checks both for every signature listed and prints a verdict in German.
Run it with Python 3.9 or later:

    python3 pruefe_rekonstruktion.py

Exit code 0 when every signature listed holds, 1 otherwise.
"""

import base64
import json
import sys
from pathlib import Path

# DER of DigestInfo up to the digest (RFC 8017 9.2, note 1)
DIGEST_INFO = {
    "sha256": bytes.fromhex("3031300d060960864801650304020105000420"),
    "sha1": bytes.fromhex("3021300906052b0e03021a05000414"),
}


def der_element(data: bytes, offset: int) -> tuple[int, bytes, int]:
    """Tag, contents and the end of the DER element at offset."""
    tag, length = data[offset], data[offset + 1]
    offset += 2
    if length & 0x80:
        count = length & 0x7F
        length = int.from_bytes(data[offset : offset + count], "big")
        offset += count
    return tag, data[offset : offset + length], offset + length


def public_key(record: str) -> tuple[int, int]:
    """n and e of the key in a DKIM key record (p=: SubjectPublicKeyInfo or RSAPublicKey)."""
    tags = {}
    for part in record.split(";"):
        name, _, value = part.partition("=")
        tags[name.strip()] = value
    der = base64.b64decode("".join(tags["p"].split()))
    _, sequence, _ = der_element(der, 0)
    tag, first, end = der_element(sequence, 0)
    if tag == 0x30:  # SubjectPublicKeyInfo: the algorithm, then the key in a BIT STRING
        _, bits, _ = der_element(sequence, end)
        _, sequence, _ = der_element(bits[1:], 0)
        tag, first, end = der_element(sequence, 0)
    _, exponent, _ = der_element(sequence, end)
    return int.from_bytes(first, "big"), int.from_bytes(exponent, "big")


def encoded(digest: bytes, hash_name: str, size: int) -> int:
    """EMSA-PKCS1-v1_5 of the digest for a modulus of size bytes."""
    info = DIGEST_INFO[hash_name] + digest
    return int.from_bytes(b"\x00\x01" + b"\xff" * (size - len(info) - 3) + b"\x00" + info, "big")


def main() -> int:
    folder = Path(__file__).resolve().parent
    n, e = public_key((folder / "record.txt").read_text(encoding="ascii"))
    listed = json.loads((folder / "signaturen.json").read_text(encoding="utf-8"))
    size = (n.bit_length() + 7) // 8
    print(f"Schlüssel {listed['key_name']}")
    print(f"  aus record.txt: {n.bit_length()} Bit, Exponent e = {e}")
    signatures = listed["signatures"]
    failed = 0
    for number, entry in enumerate(signatures, 1):
        s, m = int(entry["s"], 16), int(entry["m"], 16)
        digest = bytes.fromhex(entry["digest"])
        what = f"Mail {entry['mail_sha256'][:16]}…, DKIM-Signatur {entry['signature_index'] + 1}"
        if entry["e"] != e:
            verdict = f"STIMMT NICHT: e = {entry['e']} ist nicht der Exponent des Schlüssels"
        elif m != encoded(digest, entry["hash"], size):
            verdict = f"STIMMT NICHT: m ist keine PKCS#1-Kodierung des {entry['hash']}-Hashwerts"
        elif pow(s, e, n) != m:
            verdict = "STIMMT NICHT: s^e mod n ist nicht m"
        else:
            verdict = "stimmt: s^e mod n = m"
        failed += not verdict.startswith("stimmt")
        print(f"{number}. {what}: {verdict}")
    for entry in listed.get("missing", []):
        print(
            f"-  Mail {entry['mail_sha256'][:16]}…, DKIM-Signatur {entry['signature_index'] + 1}: "
            f"nicht prüfbar ({entry['reason']})"
        )
    if not signatures:
        print("Ergebnis: keine Signatur zum Prüfen.")
        return 1
    if failed:
        print(f"Ergebnis: {failed} von {len(signatures)} Signaturen passen NICHT zum Schlüssel.")
        return 1
    print(f"Ergebnis: alle {len(signatures)} Signaturen passen zum Schlüssel in record.txt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
