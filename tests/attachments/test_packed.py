"""attachments.packed (D231, D232, D239): the entries of ZIP and 7z archives and of attached mails,
locked without their password, within the limits against archive bombs, and never an exception
for a damaged container."""

import gzip
import io
import tarfile
from email import encoders
from email.mime.base import MIMEBase

import pytest

from mailrobbe.attachments import packed
from mailrobbe.attachments.packed import Member, Members, list_members, read_member
from mailrobbe.enums import DocumentMembersStatus, DocumentMemberStatus
from tests.attachments.doubles import digest
from tests.passwords.samples import ZIP_MIME, mail, needs_seven_zip, seven_zip
from tests.passwords.samples import packed as zipped

MS = DocumentMembersStatus
ES = DocumentMemberStatus
SEVEN_Z_MIME = "application/x-7z-compressed"
EML_MIME = "message/rfc822"
ALPHA = b"Alpha, der erste Eintrag\n"
BETA = b"Beta im Unterordner\n"
ENTRIES = {"a.txt": ALPHA, "sub/b.txt": BETA}
PASSWORD = "Hafen-2019"


def listed(
    data: bytes, filename: str | None, mime_type: str, password: str | None = None
) -> Members:
    """The entries within limits these tests do not reach."""
    return list_members(
        data, filename, mime_type, max_members=100, max_size=10**6, password=password
    )


def documents(*entries: tuple[str, bytes]) -> list[Member]:
    return [Member(path, len(data), ES.DOCUMENT, digest(data)) for path, data in entries]


def locked(*entries: tuple[str, bytes]) -> list[Member]:
    return [Member(path, len(data), ES.LOCKED) for path, data in entries]


def attached_mail() -> bytes:
    """A mail with a text, two attachments of the same name and one without a name."""
    message = mail(
        1,
        "anna@a.example",
        "bert@b.example",
        "Unterlagen",
        "Siehe die Anhänge.\n",
        [
            ("Bericht.pdf", "application/pdf", b"%PDF-1.4 erster"),
            ("Bericht.pdf", "application/pdf", b"%PDF-1.4 zweiter"),
        ],
    )
    unnamed = MIMEBase("text", "plain")
    unnamed.set_payload(b"ohne Namen")
    encoders.encode_base64(unnamed)
    unnamed.add_header("Content-Disposition", "attachment")
    message.attach(unnamed)
    return message.as_bytes()


# ZIP and 7z -------------------------------------------------------------------------------------


@needs_seven_zip
def test_a_zip_lists_its_entries_in_order_without_folders() -> None:
    data = zipped({"a.txt": ALPHA, "sub/": b"", "sub/b.txt": BETA, "leer.txt": b""})
    assert listed(data, "Akten.zip", ZIP_MIME) == Members(
        MS.DONE, documents(("a.txt", ALPHA), ("sub/b.txt", BETA), ("leer.txt", b""))
    )
    # by its first bytes, whatever its name and type say
    assert listed(data, None, "application/octet-stream").status is MS.DONE


@needs_seven_zip
@pytest.mark.parametrize("method", ["AES256", "ZipCrypto"])
def test_a_protected_zip_is_locked_without_its_password(method: str) -> None:
    data = seven_zip(ENTRIES, "x.zip", "-tzip", f"-p{PASSWORD}", f"-mem={method}")
    entries = (("a.txt", ALPHA), ("sub/b.txt", BETA))
    assert listed(data, "x.zip", ZIP_MIME) == Members(MS.LOCKED, locked(*entries))
    opened = listed(data, "x.zip", ZIP_MIME, password=PASSWORD)
    assert opened == Members(MS.DONE, documents(*entries))
    # a wrong password extracts nothing: the entries are listed, none is a document
    wrong = listed(data, "x.zip", ZIP_MIME, password="Falsch")
    assert [(m.path, m.status, m.error) for m in wrong.members] == [
        ("a.txt", ES.FAILED, "not extracted"),
        ("sub/b.txt", ES.FAILED, "not extracted"),
    ]
    assert packed.opens_archive(data, "x.zip", ZIP_MIME, PASSWORD)
    assert not packed.opens_archive(data, "x.zip", ZIP_MIME, "Falsch")


@needs_seven_zip
def test_a_7z_with_encrypted_headers_hides_even_its_entries() -> None:
    data = seven_zip(ENTRIES, "x.7z", "-t7z", f"-p{PASSWORD}", "-mhe=on")
    expected = Members(MS.LOCKED, [], "the archive's entries need a password")
    assert listed(data, "x.7z", SEVEN_Z_MIME) == expected
    assert listed(data, "x.7z", SEVEN_Z_MIME, password="Falsch") == expected
    opened = listed(data, "x.7z", SEVEN_Z_MIME, password=PASSWORD)
    assert opened == Members(MS.DONE, documents(("a.txt", ALPHA), ("sub/b.txt", BETA)))
    assert packed.opens_archive(data, "x.7z", SEVEN_Z_MIME, PASSWORD)
    assert not packed.opens_archive(data, "x.7z", SEVEN_Z_MIME, "Falsch")
    assert read_member(data, "x.7z", SEVEN_Z_MIME, "sub/b.txt", PASSWORD) == BETA
    assert read_member(data, "x.7z", SEVEN_Z_MIME, "sub/b.txt") is None
    assert read_member(data, "x.7z", SEVEN_Z_MIME, "sub/b.txt", "Falsch") is None


@needs_seven_zip
def test_a_7z_without_protection_needs_no_password() -> None:
    data = seven_zip(ENTRIES, "x.7z", "-t7z")
    expected = Members(MS.DONE, documents(("a.txt", ALPHA), ("sub/b.txt", BETA)))
    assert listed(data, "x.7z", SEVEN_Z_MIME) == expected
    assert not packed.opens_archive(data, "x.7z", SEVEN_Z_MIME, PASSWORD)  # nothing is locked


@needs_seven_zip
def test_read_member_by_path_with_its_password_and_limit() -> None:
    plain = zipped({**ENTRIES, "leer.txt": b""})
    assert read_member(plain, "x.zip", ZIP_MIME, "sub/b.txt") == BETA
    assert read_member(plain, "x.zip", ZIP_MIME, "b.txt") is None  # paths match whole
    assert read_member(plain, "x.zip", ZIP_MIME, "leer.txt") == b""
    assert read_member(plain, "x.zip", ZIP_MIME, "fehlt.txt") is None
    assert read_member(plain, "x.zip", ZIP_MIME, "a.txt", limit=len(ALPHA)) == ALPHA
    assert read_member(plain, "x.zip", ZIP_MIME, "a.txt", limit=len(ALPHA) - 1) is None
    protected = seven_zip(ENTRIES, "x.zip", "-tzip", f"-p{PASSWORD}", "-mem=AES256")
    assert read_member(protected, "x.zip", ZIP_MIME, "a.txt", PASSWORD) == ALPHA
    assert read_member(protected, "x.zip", ZIP_MIME, "a.txt") is None
    assert read_member(protected, "x.zip", ZIP_MIME, "a.txt", "Falsch") is None


@needs_seven_zip
def test_the_entry_limit_and_the_listed_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    data = zipped({f"{n}.txt": b"x" * n for n in range(1, 6)})
    found = list_members(data, "x.zip", ZIP_MIME, max_members=2, max_size=10**6)
    assert [(m.path, m.size_bytes, m.status) for m in found.members] == [
        ("1.txt", 1, ES.DOCUMENT),
        ("2.txt", 2, ES.DOCUMENT),
        ("3.txt", 3, ES.TOO_MANY),
        ("4.txt", 4, ES.TOO_MANY),
        ("5.txt", 5, ES.TOO_MANY),
    ]
    assert (found.status, found.error) == (MS.DONE, None)
    monkeypatch.setattr(packed, "LISTED", 3)
    found = list_members(data, "x.zip", ZIP_MIME, max_members=2, max_size=10**6)
    assert [m.status for m in found.members] == [ES.DOCUMENT, ES.DOCUMENT, ES.TOO_MANY]
    assert found.error == "2 entries beyond the first 3 not listed"


@needs_seven_zip
def test_the_size_limit_counts_what_is_unpacked() -> None:
    data = zipped({"a.txt": b"a" * 10, "b.txt": b"b" * 10, "c.txt": b"c" * 5})
    found = list_members(data, "x.zip", ZIP_MIME, max_members=10, max_size=16)
    assert [(m.path, m.status) for m in found.members] == [
        ("a.txt", ES.DOCUMENT),
        ("b.txt", ES.TOO_LARGE),  # 20 bytes would be unpacked
        ("c.txt", ES.DOCUMENT),  # 15 fit
    ]
    assert found.members[1].sha256 is None


@needs_seven_zip
def test_an_entry_larger_than_its_header_says_is_not_read_beyond_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The header of a crafted archive may understate an entry: 7-Zip's output is cut at the
    bytes left, whatever the header says."""
    real = packed._seven_zip_entries

    def understated(path: str, password: str | None = None) -> tuple[list[packed._Entry], bool]:
        entries, header_locked = real(path, password)
        return [packed._Entry(e.path, 1, e.encrypted) for e in entries], header_locked

    monkeypatch.setattr(packed, "_seven_zip_entries", understated)
    data = zipped({"a.txt": b"a" * 100, "b.txt": b"b" * 10})
    found = list_members(data, "x.zip", ZIP_MIME, max_members=10, max_size=50)
    assert [(m.path, m.size_bytes, m.status) for m in found.members] == [
        ("a.txt", 1, ES.TOO_LARGE),
        ("b.txt", 10, ES.DOCUMENT),
    ]


@needs_seven_zip
def test_a_container_inside_a_container_is_an_entry_not_unpacked() -> None:
    inner = zipped({"tief.txt": b"Ganz unten\n"})
    found = listed(zipped({"inner.zip": inner, "c.txt": b"C"}), "x.zip", ZIP_MIME)
    assert found == Members(MS.DONE, documents(("inner.zip", inner), ("c.txt", b"C")))


@needs_seven_zip
def test_a_damaged_archive_fails_without_an_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    for data, name in (
        (b"PK\x03\x04" + b"kein ZIP" * 20, "x.zip"),
        (b"7z\xbc\xaf\x27\x1c" + b"kein 7z" * 20, "x.7z"),
    ):
        found = listed(data, name, ZIP_MIME)
        assert (found.status, found.members) == (MS.FAILED, [])
        assert found.error is not None and found.error.startswith("7-Zip could not read")
        assert read_member(data, name, ZIP_MIME, "a.txt") is None
    good = zipped(ENTRIES)
    cut = listed(good[:40] + b"\x00" * 60, "x.zip", ZIP_MIME)
    assert all(m.status is not ES.DOCUMENT for m in cut.members)

    def broken(*args: object, **kwargs: object) -> object:
        raise RuntimeError("kaputt")

    monkeypatch.setattr(packed, "_seven_zip_entries", broken)
    assert listed(good, "x.zip", ZIP_MIME) == Members(
        MS.FAILED, [], "unpacking failed: RuntimeError: kaputt"
    )


def test_rar_tar_gzip_and_a_zip_name_on_other_bytes_are_not_unpacked() -> None:
    tar = io.BytesIO()
    with tarfile.open(fileobj=tar, mode="w") as archive:
        info = tarfile.TarInfo("a.txt")
        info.size = len(ALPHA)
        archive.addfile(info, io.BytesIO(ALPHA))
    for data, name, mime_type, fmt in (
        (b"Rar!\x1a\x07\x01\x00" + bytes(40), "x.rar", "application/vnd.rar", "archive"),
        (tar.getvalue(), "x.tar", "application/x-tar", "archive"),
        (gzip.compress(tar.getvalue()), "x.tar.gz", "application/gzip", "archive"),
        (b"kein Archiv", "x.zip", ZIP_MIME, "zip"),
    ):
        found = listed(data, name, mime_type)
        assert found == Members(MS.UNSUPPORTED, [], f"not unpacked ({fmt})")
        assert read_member(data, name, mime_type, "a.txt") is None
        assert not packed.opens_archive(data, name, mime_type, PASSWORD)


def test_without_the_7zip_command_only_attached_mails_are_unpacked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(packed, "_SEVENZIP", None)
    data = zipped(ENTRIES)
    assert listed(data, "x.zip", ZIP_MIME) == Members(
        MS.UNSUPPORTED, [], "the 7-Zip command is not installed"
    )
    assert read_member(data, "x.zip", ZIP_MIME, "a.txt") is None
    assert not packed.opens_archive(data, "x.zip", ZIP_MIME, PASSWORD)
    assert listed(attached_mail(), "x.eml", EML_MIME).status is MS.DONE


# Attached mails ---------------------------------------------------------------------------------


def test_an_attached_mail_lists_its_attachments_by_name() -> None:
    data = attached_mail()
    assert listed(data, "Weitergeleitet.eml", EML_MIME) == Members(
        MS.DONE,
        documents(
            ("Bericht.pdf", b"%PDF-1.4 erster"),
            ("Bericht.pdf (2)", b"%PDF-1.4 zweiter"),  # the same name made unique
            ("part-3", b"ohne Namen"),  # no name: its place
        ),
    )
    assert read_member(data, None, EML_MIME, "Bericht.pdf (2)") == b"%PDF-1.4 zweiter"
    assert read_member(data, None, EML_MIME, "part-3") == b"ohne Namen"
    assert read_member(data, None, EML_MIME, "Bericht (3).pdf") is None
    text_only = mail(3, "a@a.example", "b@b.example", "Nur Text", "Kein Anhang.\n").as_bytes()
    assert listed(text_only, None, EML_MIME) == Members(MS.DONE, [])


def test_an_attached_mail_within_the_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    data = attached_mail()
    found = list_members(data, None, EML_MIME, max_members=1, max_size=10**6)
    assert [(m.path, m.size_bytes, m.status) for m in found.members] == [
        ("Bericht.pdf", 15, ES.DOCUMENT),
        ("Bericht.pdf (2)", None, ES.TOO_MANY),
        ("part-3", None, ES.TOO_MANY),
    ]
    found = list_members(data, None, EML_MIME, max_members=10, max_size=25)
    assert [m.status for m in found.members] == [ES.DOCUMENT, ES.TOO_LARGE, ES.DOCUMENT]
    monkeypatch.setattr(packed, "LISTED", 2)
    found = listed(data, None, EML_MIME)
    assert [m.path for m in found.members] == ["Bericht.pdf", "Bericht.pdf (2)"]
    assert found.error == "1 entries beyond the first 2 not listed"


def test_a_mail_that_breaks_the_parser_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(data: bytes) -> object:
        raise ValueError("kaputt")

    monkeypatch.setattr(packed, "_mail_parts", broken)
    assert listed(attached_mail(), None, EML_MIME) == Members(
        MS.FAILED, [], "unpacking failed: ValueError: kaputt"
    )
