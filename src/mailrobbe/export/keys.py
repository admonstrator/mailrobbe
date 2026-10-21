"""The key folders of an export (D105), one per key from another source than today's DNS that a
signature of an exported mail rests on:

    schluessel/<name>/<key_sha256>/
        record.txt                 the key record as Mailrobbe stores it
        beleg-<id>.json            per piece of evidence: source, query, times, outcome, SHA-256
        beleg-<id>-<file>          the source's answer or the evidence file, byte for byte
        signaturen.json            a reconstructed key: s, m and e of the signatures it was
                                   computed from and of the exported mails' signatures it holds
        pruefe_rekonstruktion.py   checks signaturen.json against record.txt, standard library only

The models below are the format of beleg-<id>.json and signaturen.json; field names in English
as in manifest.json, times ISO 8601 in UTC, big numbers as hexadecimal strings.
"""

import mimetypes
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from mailrobbe.dkim.keys.identity import key_identity
from mailrobbe.enums import KeyOrigin
from mailrobbe.export.material import SignatureMaterial
from mailrobbe.export.records import ExportKey, KeyEvidence

KEYS_FOLDER = "schluessel"
CHECK_SCRIPT = "pruefe_rekonstruktion.py"
_SCRIPT = (Path(__file__).parent / CHECK_SCRIPT).read_bytes()
_UNSAFE = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')

# Why a signature listed in a reconstruction's evidence has no values in signaturen.json.
Missing = Literal[
    "not_in_archive",  # no mail of the archive has this content any more
    "source_missing",  # its MBOX file cannot be read
    "source_changed",  # the bytes at the stored offset are not the imported mail any more
    "no_rsa_signature",  # the mail has no valid RSA signature with this index
]


class EvidenceFile(BaseModel):
    """beleg-<id>.json: one piece of evidence and the question to the source it comes from."""

    evidence_id: int
    key_name: str
    key_sha256: str
    origin: KeyOrigin  # what the evidence says: observed, documented or reconstructed
    source: str  # reconstruction, archive_text, manual, zkemail, dns
    query: str  # what was asked: URL, key name or search, without credentials
    asked_at: datetime  # when Mailrobbe asked, or the key was entered
    outcome: str  # found, not_found, error
    http_status: int | None
    observed_from: datetime | None  # the source's own times: first seen, a document's date
    observed_to: datetime | None
    reference: str | None  # URL, permalink /m/<hash>, /anhaenge/<id>, file name
    note: str | None
    editor: str | None  # the name given in Mailrobbe (D54), not verified
    answer_file: str | None  # the answer in this folder, unchanged; None without one
    answer_sha256: str | None
    answer_size: int | None
    answer_type: str | None  # media type
    answer_name: str | None  # the file name an uploaded evidence file had
    tool_version: str  # Mailrobbe's version that asked
    details: dict[str, Any]  # per source; a reconstruction's signatures, an archive's entry


class CheckedSignature(BaseModel):
    mail_sha256: str  # the mail.eml whose DKIM-Signature field this is
    signature_index: int  # topmost DKIM-Signature field 0
    reconstruction: bool  # the key was computed from it
    exported: bool  # an exported signature that rests on this key
    hash: str  # sha256 or sha1
    digest: str  # the header hash the signature covers, hexadecimal
    e: int
    s: str  # b= as a number, hexadecimal
    m: str  # the digest encoded per EMSA-PKCS1-v1_5, hexadecimal


class MissingSignature(BaseModel):
    mail_sha256: str
    signature_index: int
    reason: Missing


class SignatureFile(BaseModel):
    """signaturen.json: what pruefe_rekonstruktion.py checks, s^e mod n = m per signature."""

    key_name: str
    key_sha256: str
    bits: int
    exponent: int
    signatures: list[CheckedSignature]
    missing: list[MissingSignature]  # signatures of the reconstruction it cannot list


@dataclass(frozen=True, slots=True)
class SignatureUse:
    """A signature for signaturen.json, with its material or why there is none."""

    mail_sha256: str
    signature_index: int
    reconstruction: bool
    exported: bool
    material: SignatureMaterial | Missing


def key_folder(key: ExportKey) -> str:
    return f"{KEYS_FOLDER}/{_safe(key.name)}/{key.key_sha256}"


def reconstructed(key: ExportKey) -> bool:
    """Whether the key has evidence that it was computed from signatures (here or by a key
    archive): its folder gets signaturen.json and the check script."""
    return key.key_type == "rsa" and any(
        item.origin is KeyOrigin.RECONSTRUCTED for item in key.evidence
    )


def key_files(key: ExportKey, uses: list[SignatureUse]) -> list[tuple[str, bytes]]:
    """The files of the key's folder, path relative to the export's folder, in a fixed order."""
    folder = key_folder(key)
    files = [(f"{folder}/record.txt", key.record.encode() + b"\n")]
    for item in key.evidence:
        answer = None
        if item.raw is not None:
            answer = f"beleg-{item.id}-{_answer_name(item)}"
            files.append((f"{folder}/{answer}", item.raw))
        evidence = _evidence(key, item, answer)
        files.append((f"{folder}/beleg-{item.id}.json", _json(evidence)))
    if reconstructed(key):
        files.append((f"{folder}/signaturen.json", _json(_signatures(key, uses))))
        files.append((f"{folder}/{CHECK_SCRIPT}", _SCRIPT))
    return files


def _evidence(key: ExportKey, item: KeyEvidence, answer: str | None) -> EvidenceFile:
    return EvidenceFile(
        evidence_id=item.id,
        key_name=key.name,
        key_sha256=key.key_sha256,
        origin=item.origin,
        source=item.source,
        query=item.query,
        asked_at=item.asked_at,
        outcome=item.outcome,
        http_status=item.http_status,
        observed_from=item.observed_from,
        observed_to=item.observed_to,
        reference=item.reference,
        note=item.note,
        editor=item.editor,
        answer_file=answer,
        answer_sha256=item.raw_sha256 if item.raw is not None else None,
        answer_size=None if item.raw is None else len(item.raw),
        answer_type=item.raw_type,
        answer_name=item.raw_name,
        tool_version=item.tool_version,
        details=item.details,
    )


def _signatures(key: ExportKey, uses: list[SignatureUse]) -> SignatureFile:
    identity = key_identity(key.record)
    assert identity is not None and identity.modulus and identity.exponent, "a stored RSA key"
    bits, exponent = identity.modulus.bit_length(), identity.exponent
    checked, missing = [], []
    for use in uses:
        if isinstance(use.material, SignatureMaterial):
            checked.append(
                CheckedSignature(
                    mail_sha256=use.mail_sha256,
                    signature_index=use.signature_index,
                    reconstruction=use.reconstruction,
                    exported=use.exported,
                    hash=use.material.hash_name,
                    digest=use.material.digest.hex(),
                    e=exponent,
                    s=f"{use.material.signature:x}",
                    m=f"{use.material.message(bits):x}",
                )
            )
        else:
            missing.append(
                MissingSignature(
                    mail_sha256=use.mail_sha256,
                    signature_index=use.signature_index,
                    reason=use.material,
                )
            )
    return SignatureFile(
        key_name=key.name,
        key_sha256=key.key_sha256,
        bits=bits,
        exponent=exponent,
        signatures=checked,
        missing=missing,
    )


def _answer_name(item: KeyEvidence) -> str:
    """The answer's file name: an uploaded file keeps its name, an answer is named after its
    media type."""
    if item.raw_name:
        return _safe(item.raw_name)[:100] or "datei"
    media_type = (item.raw_type or "").partition(";")[0].strip()
    return "antwort" + (mimetypes.guess_extension(media_type) or ".bin")


def _safe(name: str) -> str:
    """A name as one path segment on every system."""
    return _UNSAFE.sub("_", name).strip(" .") or "_"


def _json(model: BaseModel) -> bytes:
    return (model.model_dump_json(indent=2) + "\n").encode()
