"""Milestone 19: protected documents, planted passwords, packed attachments, encrypted mails.

The checks render the shared plan and read the ground truth off RenderedMail, then confirm it
against the code the importer uses: passwords.candidates finds every planted password, the 7-Zip
command opens every protected ZIP with its password and lists exactly the members the manifest
states, the extractor opens every encrypted PDF with its password, and an attached .eml reads
back as the importer reads it (attachments.packed, importer.parse). D230 to D239.
"""

import hashlib
from collections import Counter
from email.message import Message
from email.parser import BytesParser
from email.policy import compat32

import pytest

from mailrobbe.attachments.extract import ExtractionLimits, extract_document
from mailrobbe.attachments.packed import SEVEN_ZIP, list_members
from mailrobbe.generator.model import PlannedMail, RenderedMail
from mailrobbe.generator.protection import TIERS
from mailrobbe.generator.render import render
from mailrobbe.importer.parse import attachment_payload, parse_record
from mailrobbe.importer.split import MboxRecord
from mailrobbe.passwords.candidates import candidates

# compat32, as the importer parses; a named .eml's bytes are serialised again from it (D231)
_COMPAT = BytesParser(policy=compat32)
_MAX_MEMBERS = 10_000
_MAX_SIZE = 256 * 1024**2


@pytest.fixture(scope="module")
def rendered(gen_plan: list[PlannedMail]) -> list[RenderedMail]:
    return [render(mail) for mail in gen_plan]


def _named_files(mail: RenderedMail) -> dict[str, Message]:
    """The attachment parts of a mail by file name, as the importer reads them (compat32)."""
    message = _COMPAT.parsebytes(mail.raw)
    return {name: part for part in message.walk() if (name := part.get_filename()) is not None}


def _candidate_values(mail: RenderedMail) -> set[str]:
    """Every password candidate the passwords step would find on a mail: in the body text the
    importer indexes (parse_record, plain or from HTML) and in its text attachments."""
    record = MboxRecord(
        byte_offset=0, byte_length=len(mail.raw), separator=b"", message=mail.raw, raw_sha256=""
    )
    parsed = parse_record(record, attachment_hash_limit=0)
    found: set[str] = set()
    if parsed.body_text:
        found |= {candidate.value for candidate in candidates(parsed.body_text)}
    for part in _COMPAT.parsebytes(mail.raw).walk():
        if part.get_content_type() == "text/plain" and part.get_filename():
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                text = payload.decode("utf-8", "replace")
                found |= {candidate.value for candidate in candidates(text)}
    return found


def test_every_planted_password_is_a_candidate(rendered: list[RenderedMail]) -> None:
    """A password written into a mail or its text file is found by the candidate rule (D234)."""
    checked = 0
    for mail in rendered:
        if not mail.passwords:
            continue
        found = _candidate_values(mail)
        for password in mail.passwords:
            assert password in found, (mail.planned.index, password)
            checked += 1
    assert checked > 0


def test_passwords_planted_nowhere_are_not_in_their_mail(rendered: list[RenderedMail]) -> None:
    """A document whose password went nowhere (tier None) stays locked: its password is written
    neither in its carrier's text nor in a text attachment of it."""
    checked = 0
    for mail in rendered:
        locked = [d for d in mail.documents if d.password is not None and d.tier is None]
        if not locked:
            continue
        found = _candidate_values(mail)
        for document in locked:
            assert document.password not in found, (mail.planned.index, document.filename)
            checked += 1
    assert checked > 0


@pytest.mark.skipif(not SEVEN_ZIP, reason="the 7-Zip command is not installed")
def test_seven_zip_opens_every_protected_zip(rendered: list[RenderedMail]) -> None:
    """Each protected ZIP opens with its password and lists exactly the members the truth names."""
    opened = 0
    for mail in rendered:
        files = _named_files(mail)
        for document in mail.documents:
            members = document.members or ()
            if not any(member["encrypted"] for member in members):
                continue
            assert document.password is not None and document.filename is not None
            payload = files[document.filename].get_payload(decode=True)
            assert isinstance(payload, bytes)
            assert hashlib.sha256(payload).hexdigest() == document.sha256
            result = list_members(
                payload, document.filename, "application/zip",
                max_members=_MAX_MEMBERS, max_size=_MAX_SIZE, password=document.password,
            )  # fmt: skip
            assert result.status.value == "done", result.error
            assert all(member.status.value == "document" for member in result.members)
            assert [(m.path, m.sha256) for m in result.members] == [
                (m["path"], m["sha256"]) for m in members
            ]
            opened += 1
    assert opened > 0


def test_encrypted_pdfs_open_with_their_password(rendered: list[RenderedMail]) -> None:
    """An encrypted PDF (D235) yields its text only once its password opens it (D236)."""
    opened = 0
    for mail in rendered:
        files = _named_files(mail)
        for document in mail.documents:
            if document.status != "encrypted" or document.members:
                continue
            assert document.password is not None and document.filename is not None
            payload = files[document.filename].get_payload(decode=True)
            assert isinstance(payload, bytes)
            locked = extract_document(
                payload, document.filename, "application/pdf", ExtractionLimits()
            )
            assert locked.status.value == "encrypted"
            opened_text = extract_document(
                payload, document.filename, "application/pdf", ExtractionLimits(),
                password=document.password,
            )  # fmt: skip
            assert opened_text.status.value == "text", (mail.planned.index, document.filename)
            opened += 1
    assert opened > 0


def test_named_eml_reads_back_as_the_importer_reads_it(rendered: list[RenderedMail]) -> None:
    """An attached .eml hashes and lists its members as attachments.packed and importer.parse
    produce them, so the manifest truth matches the database the importer writes (D231)."""
    checked = 0
    for mail in rendered:
        files = _named_files(mail)
        for document in mail.documents:
            if document.kind != "email":
                continue
            assert document.status == "text" and document.members is not None
            assert document.filename is not None
            data = attachment_payload(files[document.filename], "eml", [])
            assert hashlib.sha256(data).hexdigest() == document.sha256
            assert len(data) == document.size
            result = list_members(
                data, document.filename, "message/rfc822",
                max_members=_MAX_MEMBERS, max_size=_MAX_SIZE,
            )  # fmt: skip
            assert result.status.value == "done"
            assert [(m.path, m.sha256, m.size_bytes) for m in result.members] == [
                (m["path"], m["sha256"], m["size"]) for m in document.members
            ]
            checked += 1
    assert checked > 0


def test_password_tiers_are_the_documented_ones(rendered: list[RenderedMail]) -> None:
    """Every protected document names a tier the plants map to (or None), and the common tiers
    all occur in the plan (D235)."""
    tiers: Counter[str | None] = Counter()
    for mail in rendered:
        for document in mail.documents:
            if document.password is not None:
                tiers[document.tier] += 1
    assert set(tiers) <= set(TIERS.values())
    for tier in ("mail", "thread", "contacts"):
        assert TIERS[tier] in tiers, (tier, tiers)
    assert None in tiers  # some documents stay locked


def test_encrypted_mails_carry_their_signal(rendered: list[RenderedMail]) -> None:
    """A mail encrypted as a whole (D238) is S/MIME or PGP/MIME, carries encrypted_mail and no
    planted password."""
    kinds: Counter[str | None] = Counter()
    for mail in rendered:
        if mail.encrypted is None:
            continue
        kinds[mail.encrypted] += 1
        assert mail.signals == ["encrypted_mail"]
        assert not mail.passwords
    assert kinds  # the plan makes some; the kind split varies with the sample
    assert set(kinds) <= {"smime", "pgp"}


def test_separate_password_mails_carry_their_signal(rendered: list[RenderedMail]) -> None:
    """A mail that is only there to pass a password on to a thread or contact carries
    password_separate (D238); such mails exist."""
    separate = 0
    for mail in rendered:
        if "password_separate" in mail.signals:
            assert mail.passwords  # it writes the password it was made for
            separate += 1
    assert separate > 0


def test_protected_documents_appear_once(rendered: list[RenderedMail]) -> None:
    """A protected document never circulates (generator.documents): each occurs on one mail
    only, so its password's tier and the manifest truth are exact."""
    seen: Counter[tuple[str | None, str | None]] = Counter()
    for mail in rendered:
        for document in mail.documents:
            if document.password is not None:
                seen[document.filename, document.sha256] += 1
    assert seen
    assert all(count == 1 for count in seen.values()), seen
