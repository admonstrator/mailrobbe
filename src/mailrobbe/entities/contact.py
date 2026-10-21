# ruff: noqa: RUF001  (typographic quotes, apostrophes and dashes in texts are meant)
"""Contact data: URLs, e-mail addresses, their domains, and phone numbers (D81).

Per kind, what is found and how it is normalised:

    url      http://, https:// and www. addresses; trailing punctuation and unbalanced closing
             brackets dropped; key with lowercased scheme and host, https:// added to www. forms,
             without fragment and without a trailing / on the path; label as written, detail the
             host. A URL longer than KEY_LIMIT is no entity, but its span is claimed.
    email    addresses in the text, key and label lowercase (mailto: is not part of them).
    domain   the registrable domain of every URL and address found: the last two labels of the
             host, three under a known second-level suffix (co.uk, gv.at); none for IP addresses.
             Its occurrences are the URLs and addresses with it.
    phone    numbers after Tel., Telefon, Fax, Mobil, Handy, Phone and the like, and international
             numbers starting with + anywhere; national numbers start with 0 and are read as
             German. At least 6 digits after the area code (or 8 after the country code when
             written without separators). Key E.164 (+49301234567, "(0)" after the country code
             dropped), label "+49 30 1234567" grouped as written, detail the country code.
"""

import re
from urllib.parse import urlsplit, urlunsplit

from mailrobbe.entities.occurrences import Occurrences
from mailrobbe.enums import EntityKind

# URLs and e-mail addresses -----------------------------------------------------------------------

# A pattern scanned over the whole text starts with a lookahead for its first character when a
# lookbehind follows: the scan then passes the other positions at once (dates._DATE).
_URL = re.compile(
    r"(?=[hw])(?<![\w@./-])(?:https?://|www\.)[^\s<>\"'`{}|\\^\[\]\x00-\x20\x7f]{1,2048}",
    re.IGNORECASE,
)
_TRAILING = ".,;:!?'\"*_)]}>»“”’"
_CLOSING = {")": "(", "]": "[", "}": "{"}
_EMAIL = re.compile(r"(?<![\w.%+'-])[\w.%+'-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,8}")
_LABEL = re.compile(r"[^\W_](?:[\w-]{0,61}[^\W_])?")
# Second-level suffixes under which the registrable domain has three labels.
SECOND_LEVEL = frozenset(
    ["ac.at", "co.at", "gv.at", "or.at", "ac.uk", "co.uk", "gov.uk", "ltd.uk", "me.uk", "net.uk",
     "org.uk", "plc.uk", "sch.uk", "com.au", "edu.au", "gov.au", "net.au", "org.au", "co.nz",
     "org.nz", "govt.nz", "co.jp", "ne.jp", "or.jp", "ac.jp", "co.za", "org.za", "gov.za",
     "com.br", "com.cn", "com.tr", "gov.tr", "org.tr", "co.il", "org.il", "com.mx", "com.ar",
     "co.in", "gov.in", "com.sg", "com.hk", "com.tw", "co.kr", "com.pl", "org.pl", "com.ua",
     "co.ua", "com.ru", "com.cy", "com.mt", "com.gr", "admin.ch"]
)  # fmt: skip


def find_urls(found: Occurrences) -> None:
    text = found.text
    for match in _URL.finditer(text):
        written = _trim(match.group())
        start, end = match.start(), match.start() + len(written)
        parsed = _url(written)
        if parsed is None:
            continue
        key, host = parsed
        found.add(EntityKind.URL, key, written, start, end, detail=host)
        found.hosts.append((start, host))


def _trim(url: str) -> str:
    """Without trailing punctuation, and without closing brackets that close nothing in it."""
    while url and url[-1] in _TRAILING:
        opening = _CLOSING.get(url[-1])
        if opening and url.count(opening) >= url.count(url[-1]):
            break
        url = url[:-1]
    return url


def _url(written: str) -> tuple[str, str] | None:
    """The key and host of a URL, None when it has no usable host."""
    absolute = written if "://" in written[:8] else f"https://{written}"
    try:
        parts = urlsplit(absolute)
        host = parts.hostname
    except ValueError:
        return None
    if not host or not _valid_host(host):
        return None
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, "")), host


def _valid_host(host: str) -> bool:
    """A name with a top-level domain of letters, or an IPv4 address."""
    labels = host.split(".")
    if len(labels) < 2 or not all(_LABEL.fullmatch(label) for label in labels):
        return False
    if all(label.isdigit() for label in labels):
        return len(labels) == 4
    return labels[-1].isalpha() and len(labels[-1]) >= 2


def find_emails(found: Occurrences) -> None:
    text = found.text
    for match in _EMAIL.finditer(text):
        local, _, host = match.group().partition("@")
        # The domain ends at its last label of letters: "a@b.example." or "a@b.example-"
        labels = host.split(".")
        while labels and not (labels[-1].isalpha() and len(labels[-1]) >= 2):
            labels.pop()
        written_host = ".".join(labels)
        start = match.start() + len(local) - len(local.lstrip(".'"))
        local = local.strip(".'")
        if not local or not _valid_host(written_host):
            continue
        end = match.start() + match.group().index("@") + 1 + len(written_host)
        if not found.free(start, end):
            continue
        host = written_host.lower()
        address = f"{local}@{host}".lower()
        found.add(EntityKind.EMAIL, address, address, start, end)
        found.hosts.append((start, host))


def add_domains(found: Occurrences) -> None:
    """A domain occurrence for every URL and address found."""
    for position, host in found.hosts:
        domain = registrable_domain(host)
        if domain:
            found.add(EntityKind.DOMAIN, domain, domain, position, position, claim=False)


def registrable_domain(host: str) -> str | None:
    labels = host.lower().rstrip(".").split(".")
    if len(labels) < 2 or all(label.isdigit() for label in labels):
        return None
    count = 3 if ".".join(labels[-2:]) in SECOND_LEVEL and len(labels) > 2 else 2
    return ".".join(labels[-count:])


# Phone numbers -----------------------------------------------------------------------------------

_PREFIX = re.compile(
    r"(?=[TFPMHC])(?<![\w-])"
    r"(?:Telefon|Telefax|Tel|Fax|Fon|Phone|Mobil(?:e|funk|telefon)?|Handy|Mob|Cell)"
    r"\.?(?:[ \t]?/[ \t]?(?:Fax|Fon|Mobil|WhatsApp)\.?)?(?:[ \t-]?(?:Nr|No)\.?)?"
    r"(?:[ \t]?\([^()\d\n][^()\n]{0,19}\))?[ \t]*:?[ \t]*"  # (Büro), not an area code
)
_NUMBER = re.compile(r"(?:\+|00(?=[1-9]))?\(?\d[\d \t()/–-]{4,24}\d(?![\d])")
_INTERNATIONAL = re.compile(r"(?=\+)(?<![\w+])\+\d{1,3}[\d \t()/–-]{5,24}\d(?![\d])")
_GROUPS = re.compile(r"\(0\)|\d+")
# E.164 country calling codes and their ISO 3166 codes (1 is the North American plan: US).
CALLING_CODES = {
    "1": "US", "20": "EG", "27": "ZA", "30": "GR", "31": "NL", "32": "BE", "33": "FR",
    "34": "ES", "36": "HU", "39": "IT", "40": "RO", "41": "CH", "43": "AT", "44": "GB",
    "45": "DK", "46": "SE", "47": "NO", "48": "PL", "49": "DE", "51": "PE", "52": "MX",
    "54": "AR", "55": "BR", "56": "CL", "57": "CO", "60": "MY", "61": "AU", "62": "ID",
    "63": "PH", "64": "NZ", "65": "SG", "66": "TH", "7": "RU", "81": "JP", "82": "KR",
    "84": "VN", "86": "CN", "90": "TR", "91": "IN", "92": "PK", "98": "IR", "212": "MA",
    "213": "DZ", "216": "TN", "218": "LY", "234": "NG", "254": "KE", "350": "GI", "351": "PT",
    "352": "LU", "353": "IE", "354": "IS", "355": "AL", "356": "MT", "357": "CY", "358": "FI",
    "359": "BG", "370": "LT", "371": "LV", "372": "EE", "373": "MD", "374": "AM", "375": "BY",
    "376": "AD", "377": "MC", "378": "SM", "380": "UA", "381": "RS", "382": "ME", "383": "XK",
    "385": "HR", "386": "SI", "387": "BA", "389": "MK", "420": "CZ", "421": "SK", "423": "LI",
    "852": "HK", "886": "TW", "961": "LB", "962": "JO", "963": "SY", "964": "IQ", "965": "KW",
    "966": "SA", "971": "AE", "972": "IL", "973": "BH", "974": "QA", "994": "AZ", "995": "GE",
}  # fmt: skip
_KEEPS_TRUNK_ZERO = frozenset({"39", "378"})  # Italy and San Marino dial their 0 from abroad


def find_phones(found: Occurrences) -> None:
    text = found.text
    for prefix in _PREFIX.finditer(text):
        number = _NUMBER.match(text, prefix.end())
        if number:
            _add_phone(found, number.group(), number.start())
    for number in _INTERNATIONAL.finditer(text):
        _add_phone(found, number.group(), number.start())


def _add_phone(found: Occurrences, written: str, start: int) -> None:
    written = written.rstrip(" \t(/–-")
    end = start + len(written)
    if not found.free(start, end):
        return
    phone = parse_phone(written)
    if phone is not None:
        key, label, country = phone
        found.add(EntityKind.PHONE, key, label, start, end, detail=country)


def parse_phone(written: str) -> tuple[str, str, str | None] | None:
    """Key (E.164), label and country code of a written number; None when it is no phone."""
    groups = _GROUPS.findall(written)
    if not groups or (len(groups) == 1 and len(groups[0]) < 8):
        return None
    international = written.startswith("+") or written.startswith("00")
    if international:
        if written.startswith("00"):
            groups[0] = groups[0][2:]
        if not groups[0]:
            groups.pop(0)
        if len(groups) > 1 and len(groups[0]) <= 3:
            code = groups[0]
            rest = [group for group in groups[1:] if group != "(0)"]
        else:  # written without a separator after the country code: +4930...
            digits = "".join(group for group in groups if group != "(0)")
            code = _calling_code(digits) or digits[:2]
            rest = [digits[len(code) :]]
        if rest and rest[0].startswith("0") and code not in _KEEPS_TRUNK_ZERO:
            rest[0] = rest[0][1:]
    else:
        if not groups[0].startswith("0") or groups[0].startswith("00"):
            return None
        code, rest = "49", [groups[0][1:], *groups[1:]]
    rest = [group for group in rest if group]
    if not rest or "(0)" in rest:
        return None
    national = "".join(rest)
    after_area = len(national) - len(rest[0]) if len(rest) > 1 else 0
    if not (after_area >= 6 or (len(rest) == 1 and len(national) >= 8)):
        return None
    if not 7 <= len(code) + len(national) <= 15:
        return None
    label = f"+{code} " + " ".join(_label_parts(written, international, code))
    return f"+{code}{national}", label, CALLING_CODES.get(_calling_code(code + national) or "")


def _label_parts(written: str, international: bool, code: str) -> list[str]:
    """The written number after the country code (or the trunk 0), split at spaces, slashes and
    brackets, dashes kept."""
    body = written.replace("(0)", " ") if international else written
    parts = [part for part in re.split(r"[\s/()]+", body) if part]
    if international:
        first = parts[0].lstrip("+")
        first = first[2:] if first.startswith("00") else first
        parts[0] = first[len(code) :] if first.startswith(code) else first
    if parts and parts[0].startswith("0") and code not in _KEEPS_TRUNK_ZERO:
        parts[0] = parts[0][1:]
    return [part for part in parts if part]


def _calling_code(digits: str) -> str | None:
    """The country calling code a number starts with (they are prefix-free)."""
    for length in (1, 2, 3):
        if digits[:length] in CALLING_CODES:
            return digits[:length]
    return None
