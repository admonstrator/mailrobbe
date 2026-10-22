"""Protected documents, their passwords in the archive, and encrypted mails (milestone 19).

Protected documents (pdf_encrypted, zip_protected; generator.documents) get a password of their
own (password(): random strings, words with a year and a sign, words joined by hyphens; no
password twice). Where it is written is the planner's choice per document (choose_plant, from
the stream "plan-protection"); each place has the tier of D235 the passwords step must open the
document with, which the manifest states as the document's tier:

    mail          in the mail that carries the document, below its text           mail
    thread        in a reply of its sender to that mail, minutes to hours later   thread
    contacts      in a new mail of its sender to the same recipients within four
                  days, not in that thread                                        contacts
    attachment    in a text file (zugangsdaten.txt) of the carrying mail or of
                  such a reply                                                    attachments
    archive       in a mail between two persons the carrying mail does not
                  involve                                                         archive
    nowhere       not written: the document stays locked                          None

Automated mail writes the password into the mail itself or nowhere. A reply, new mail or mail
between others takes a stream position of its own; without room for it before the end of the
stream the password goes into the carrying mail. The opened tier gets no plan: whether a
password that opened one document is offered to another before or after it is found nearer
depends on the order the passwords step tries them in.

The words around a password follow the candidate rule of D234 (passwords.candidates): the
password follows its keyword directly or after "ist", "lautet", ":" or "=", on the same line
or the next, so every planted password is a candidate. The texts also name a password
without giving it ("Das Kennwort kommt separat"), which only yields wrong candidates.

Mails encrypted as a whole (ENCRYPTED_MAIL_SHARE of the mails people write that start no thread
and are not quoted) are S/MIME or PGP/MIME; the renderer writes them with noise as their content
(encrypted_payload).

The truth holds because a protected document never circulates (generator.documents), the mails
that carry one or hold a planted password are guarded (no byte fault, no duplicate in their
place, faults.py), and the mails passing on a password are never forwarded nor duplicated, so
the first mail holding a password in its tier is the one the manifest names (D238:
password_separate).
"""

import base64
import random
from dataclasses import dataclass

from mailrobbe.enums import PasswordTier
from mailrobbe.generator.model import AttachmentSpec, PlannedMail

# Where a password goes, with its weight, for the mails people write.
PLANTS: tuple[tuple[str, float], ...] = (
    ("mail", 0.25),
    ("thread", 0.30),
    ("contacts", 0.20),
    ("attachment", 0.10),
    ("archive", 0.05),
    ("nowhere", 0.10),
)
AUTOMATED_MAIL_SHARE = 0.5  # automated mail: the rest writes the password nowhere
ATTACHMENT_IN_REPLY_SHARE = 0.5  # text files in a reply of the sender, else in the mail itself
ENCRYPTED_MAIL_SHARE = 0.004
SMIME_SHARE = 0.5  # of the encrypted mails; the rest PGP/MIME
TIERS = {
    "mail": PasswordTier.MAIL.value,
    "thread": PasswordTier.THREAD.value,
    "contacts": PasswordTier.CONTACTS.value,
    "attachment": PasswordTier.ATTACHMENTS.value,
    "archive": PasswordTier.ARCHIVE.value,
    "nowhere": None,
}
NEW_MAILS = frozenset({"thread", "contacts", "archive"})  # take a stream position of their own

_ALPHABET = "abcdefghkmnpqrstuvwxyz23456789"  # no i, l, o, 0, 1: nothing to mistake
_MIXED = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghkmnpqrstuvwxyz23456789"
_WORDS = (
    "Hafen", "Linde", "Sommer", "Verein", "Kasse", "Garten", "Nordstern", "Elbe", "Turm",
    "Anker", "Wiese", "Fuchs", "Ostwind", "Kranich", "Muschel", "Leuchtturm",
)  # fmt: skip
_SIGNS = "!#?$%+*"


def password(rng: random.Random, taken: set[str]) -> str:
    """A new password in one of the styles people use, none in `taken` (which it joins). ASCII
    only, never starting with "ist" or "lautet" (the candidate rule would eat them)."""
    while True:
        style = rng.random()
        if style < 0.35:
            value = "".join(rng.choice(_ALPHABET) for _ in range(10))
        elif style < 0.6:
            value = f"{rng.choice(_WORDS)}{rng.randint(2010, 2026)}{rng.choice(_SIGNS)}"
        elif style < 0.8:
            value = "".join(rng.choice(_MIXED) for _ in range(rng.randint(8, 12)))
        else:
            words = rng.sample(_WORDS, 2)
            value = f"{words[0]}-{words[1]}-{rng.randint(10, 99)}"
        if value not in taken:
            taken.add(value)
            return value


def choose_plant(rng: random.Random, automated: bool, room: bool) -> str:
    """Where the password of a new protected document goes (module docstring); `room` says
    whether a mail of its own still fits into the stream."""
    if automated:
        return "mail" if rng.random() < AUTOMATED_MAIL_SHARE else "nowhere"
    point = rng.random() * sum(weight for _, weight in PLANTS)
    plant = PLANTS[-1][0]
    for name, weight in PLANTS:
        point -= weight
        if point < 0:
            plant = name
            break
    if plant in NEW_MAILS and not room:
        return "mail"
    return plant


@dataclass(frozen=True, slots=True)
class Plant:
    """A mail the planner still owes a protected document: it passes the password on."""

    kind: str  # thread, contacts, archive, attachment (a text file in the sender's reply)
    carrier: PlannedMail  # the mail carrying the document, stripped
    document: AttachmentSpec
    password: str
    due: int  # stream position from which it may be written


# Texts ---------------------------------------------------------------------------------------

# Lines below the text of the carrying mail. {pw}: the password.
_IN_MAIL = {
    "de": (
        ("Die Datei ist mit einem Kennwort geschützt.", "Kennwort: {pw}"),
        ("Das Passwort lautet:", "{pw}"),
        ("PW: {pw}",),
        ("Zum Öffnen: Passwort = {pw}",),
        ("Die Datei ist verschlüsselt, das Kennwort ist {pw}",),
    ),
    "en": (
        ("The file is password protected.", "Password: {pw}"),
        ("PW: {pw}",),
    ),
}
_IN_AUTOMATED = {
    "de": (("Ihr Dokument ist geschützt. Zugangscode: {pw}",),),
    "en": (("Your document is protected. Access code: {pw}",),),
}
# The carrying mail when the password comes separately. {file}: the document's file name.
_ANNOUNCED = {
    "de": (
        ("Die Datei ist mit einem Kennwort geschützt, das kommt separat.",),
        ("Das Passwort schicke ich dir getrennt.",),
        ("{file} ist verschlüsselt, Kennwort folgt.",),
    ),
    "en": (("The file is encrypted, I will send the password separately.",),),
}
_IN_TEXT_FILE = {
    "de": ("Das Kennwort steht in der Datei {txt}.",),
    "en": ("The password is in {txt}.",),
}
# A reply of the sender to the carrying mail, a new mail to its recipients, a mail between
# others; each ends with the password line.
_FOLLOW_UP = {
    "de": (
        ("Nachtrag: {file} ist geschützt, hier das Kennwort.", "Kennwort: {pw}"),
        ("Hier noch das Kennwort zur Datei von eben.", "Kennwort: {pw}"),
        ("Wie angekündigt das Passwort separat:", "PW: {pw}"),
        ("Das Passwort lautet:", "{pw}"),
    ),
    "en": (("As promised, the password for {file}.", "Password: {pw}"),),
}
_FOLLOW_UP_FILE = {
    "de": ("Die Zugangsdaten für {file} stehen in der angehängten Datei.",),
    "en": ("The access data for {file} are in the attached file.",),
}
_NEW_MAIL = {
    "de": (
        ("Das Kennwort für {file} von neulich:", "Kennwort: {pw}"),
        ("Hier das Passwort, wie am Telefon besprochen.", "Passwort: {pw}"),
        ("Zugangsdaten für {file}:", "Zugangscode: {pw}"),
    ),
    "en": (("Here is the password for {file}, as discussed on the phone.", "Password: {pw}"),),
}
_NEW_SUBJECTS = {
    "de": ("Kennwort", "Zugang zur Datei", "Passwort für {file}", "Nachtrag zu {file}"),
    "en": ("Password", "Access to {file}"),
}
_PASSED_ON = {
    "de": (
        ("Falls du {file} von {name} öffnen musst:", "Kennwort: {pw}"),
        ("{name} hat mir das Kennwort für {file} gegeben.", "PW: {pw}"),
    ),
    "en": (("In case you need to open {file} from {name}:", "Password: {pw}"),),
}
_PASSED_ON_SUBJECTS = {
    "de": ("Kennwort für {file}", "Zugang {file}"),
    "en": ("Password for {file}",),
}
TEXT_FILES = ("zugangsdaten.txt", "Zugangsdaten.txt", "kennwort.txt", "Passwort.txt")


def _language(language: str) -> str:
    return "de" if language == "de" else "en"


def _filled(lines: tuple[str, ...], **values: str) -> tuple[str, ...]:
    return tuple(line.format(**values) for line in lines)


def in_mail(rng: random.Random, language: str, automated: bool, pw: str) -> tuple[str, ...]:
    """The lines a carrying mail gets for its own password."""
    pool = (_IN_AUTOMATED if automated else _IN_MAIL)[_language(language)]
    return _filled(rng.choice(pool), pw=pw)


def announced(rng: random.Random, language: str, file: str) -> tuple[str, ...]:
    return _filled(rng.choice(_ANNOUNCED[_language(language)]), file=file)


def in_text_file(rng: random.Random, language: str, txt: str) -> tuple[str, ...]:
    return (rng.choice(_IN_TEXT_FILE[_language(language)]).format(txt=txt),)


def follow_up(rng: random.Random, language: str, file: str, pw: str | None) -> tuple[str, ...]:
    """The reply of the sender; without pw it points at its attached text file."""
    key = _language(language)
    if pw is None:
        return (rng.choice(_FOLLOW_UP_FILE[key]).format(file=file),)
    return _filled(rng.choice(_FOLLOW_UP[key]), file=file, pw=pw)


def new_mail(rng: random.Random, language: str, file: str, pw: str) -> tuple[str, tuple[str, ...]]:
    """Subject and lines of the new mail of the sender."""
    key = _language(language)
    subject = rng.choice(_NEW_SUBJECTS[key]).format(file=file)
    return subject, _filled(rng.choice(_NEW_MAIL[key]), file=file, pw=pw)


def passed_on(
    rng: random.Random, language: str, file: str, name: str, pw: str
) -> tuple[str, tuple[str, ...]]:
    """Subject and lines of a mail between others that passes the password on."""
    key = _language(language)
    subject = rng.choice(_PASSED_ON_SUBJECTS[key]).format(file=file)
    return subject, _filled(rng.choice(_PASSED_ON[key]), file=file, name=name, pw=pw)


def text_file(rng: random.Random, language: str, file: str, pw: str) -> AttachmentSpec:
    """A text attachment holding the password."""
    if _language(language) == "de":
        content = f"Zugangsdaten {file}\n\nKennwort: {pw}\n"
    else:
        content = f"Access data for {file}\n\nPassword: {pw}\n"
    data = content.encode()
    return AttachmentSpec(rng.choice(TEXT_FILES), "text/plain", len(data), content=data)


# Encrypted mails -----------------------------------------------------------------------------

# The DER start of a CMS EnvelopedData (OID 1.2.840.113549.1.7.3) and the tag of an OpenPGP
# public-key encrypted session key packet: what the noise behind them begins with.
_CMS = bytes.fromhex("3080 06092a864886f70d010703 a080".replace(" ", ""))
_PGP = bytes.fromhex("8502 0c03")


def encrypted_payload(rng: random.Random, kind: str, size: int) -> bytes:
    """The bytes of an encrypted mail's content: noise behind the start its format has."""
    head = _CMS if kind == "smime" else _PGP
    return head + rng.randbytes(max(size, 256))


def armoured(data: bytes) -> bytes:
    """ASCII armour of an OpenPGP message (RFC 4880 6.2), with its CRC-24."""
    crc = 0xB704CE
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    body = base64.b64encode(data)
    lines = [body[i : i + 64] for i in range(0, len(body), 64)]
    checksum = base64.b64encode((crc & 0xFFFFFF).to_bytes(3, "big"))
    return (
        b"\n".join(
            [
                b"-----BEGIN PGP MESSAGE-----",
                b"",
                *lines,
                b"=" + checksum,
                b"-----END PGP MESSAGE-----",
            ]
        )
        + b"\n"
    )
