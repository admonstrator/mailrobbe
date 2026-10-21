"""The key sources without a database: records quoted in texts, the ZK Email archive's answers,
manual records."""

import json
import textwrap
from datetime import UTC, datetime

import pytest

from mailrobbe.config import Settings
from mailrobbe.dkim.keys import archive, zkemail
from mailrobbe.dkim.keys.identity import key_identity
from mailrobbe.dkim.keys.store import manual_record
from mailrobbe.dkim.verify import signature_material
from mailrobbe.enums import KeyOrigin
from tests.dkim.test_verify import MESSAGE, NAME, bare_rsa_record, record, sign


def _p(kind: str = "rsa2048") -> str:
    return record(kind).partition("p=")[2]


def _chunks(value: str, size: int) -> list[str]:
    return [value[i : i + size] for i in range(0, len(value), size)]


# Records in texts ------------------------------------------------------------------------------


def test_a_record_split_over_quoted_strings_as_a_zone_file_writes_it() -> None:
    strings = "\n".join(f'    "{part}"' for part in _chunks("p=" + _p(), 60))
    text = (
        textwrap.dedent("""\
        Hallo, hier der Eintrag für Ihre Zone:

        s1._domainkey IN TXT ( "v=DKIM1; k=rsa; h=sha256; "
        """)
        + strings
        + " )\n\nMit freundlichen Grüßen\n"
    )
    [found] = archive.find_records(text)
    assert found.record == f"v=DKIM1; k=rsa; h=sha256; p={_p()}"
    assert key_identity(found.record) == key_identity(record())
    assert found.passage.startswith("v=DKIM1") and found.passage.endswith(_p()[-10:])


def test_text_after_the_key_does_not_stick_to_it() -> None:
    # the DER header tells the key's length, so "AQAB" plus a word in base64 letters stays out
    text = f"Bitte eintragen: v=DKIM1; k=rsa; p={_p('rsa1024')}Danke und Gruss"
    [found] = archive.find_records(text)
    assert found.record == record("rsa1024")


def test_a_bare_key_needs_to_look_like_one() -> None:
    bare = bare_rsa_record().partition("p=")[2]
    text = f"p={bare}\nv=DMARC1; p=reject; rua=mailto:dmarc@nordwind.example\np=MIIBnotakey"
    [found] = archive.find_records(text)
    assert found.record == f"v=DKIM1; k=rsa; p={bare}"
    assert found.passage == f"p={bare}"


def test_ed25519_and_repeated_records() -> None:
    line = record("ed25519")
    [found] = archive.find_records(f"{line}\n\n> {line}\n")
    assert found.record == line
    assert archive.find_records("v=DKIM1; k=rsa; p=") == []
    assert archive.find_records("v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOC") == []  # cut


def test_a_record_counts_for_the_names_whose_signature_it_verifies() -> None:
    signatures = signature_material(sign(MESSAGE, "rsa1024"))
    assert archive.fitting_names(record("rsa1024"), signatures) == [NAME]
    assert archive.fitting_names(record("rsa2048"), signatures) == []
    assert archive.fitting_names("v=DKIM1; p=", signatures) == []


# The ZK Email archive --------------------------------------------------------------------------


def _answer(entries: object, status: int = 200) -> zkemail.Answer:
    return zkemail.Answer(status, json.dumps(entries).encode(), "application/json")


def _entry(selector: str, value: str, *sources: str, **times: str) -> dict[str, object]:
    ends = ("2020-01-01T00:00:00Z", "2023-06-30T12:00:00Z")
    observations = [
        {"source": source, "firstSeenAt": "2019-03-01T00:00:00Z", "lastSeenAt": end}
        for source, end in zip(sources, ends[: len(sources)], strict=True)
    ]
    return {
        "domain": "nordwind.example",
        "selector": selector,
        "value": value,
        "id": 7,
        "observations": observations,
        **times,
    }


def test_live_dns_makes_a_key_observed_with_those_times() -> None:
    answer = _answer(
        [
            _entry("s1", record(), "gcd_recovered", "live_dns"),
            _entry("s2", record("rsa1024"), "gcd_recovered"),
            _entry("s3", record("rsa1024")),
            _entry("s4", "v=DKIM1; k=rsa; p="),  # revoked: ignored
            _entry("", record()),  # no selector
            "not an entry",
        ]
    )
    entries, error = zkemail._entries(answer, "http://127.0.0.1/api/key?domain=nordwind.example")
    assert error is None
    assert [(e.name, e.evidence.origin) for e in entries] == [
        ("s1._domainkey.nordwind.example", KeyOrigin.OBSERVED),
        ("s2._domainkey.nordwind.example", KeyOrigin.RECONSTRUCTED),
        ("s3._domainkey.nordwind.example", KeyOrigin.RECONSTRUCTED),
    ]
    live = entries[0].evidence
    assert (live.observed_from, live.observed_to) == (
        datetime(2019, 3, 1, tzinfo=UTC),
        datetime(2023, 6, 30, 12, tzinfo=UTC),
    )
    assert live.details == {"entry_id": 7, "sources": ["gcd_recovered", "live_dns"]}
    assert live.reference == "http://127.0.0.1/api/key?domain=nordwind.example"
    assert entries[2].evidence.observed_from is None  # neither observations nor own times


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        (zkemail.Answer(500, b"oops", "text/plain", "HTTP 500"), "HTTP 500"),
        (zkemail.Answer(200, b"<html>", "text/html"), "the answer is no JSON"),
        (_answer({"keys": []}), "the answer is no JSON list"),
        (zkemail.Answer(None, None, None, "no answer within 2 s"), "no answer within 2 s"),
    ],
)
def test_answers_that_are_no_valid_answer(answer: zkemail.Answer, error: str) -> None:
    assert zkemail._entries(answer, "http://127.0.0.1") == ([], error)


def test_the_archive_url() -> None:
    assert zkemail.archive_url(Settings(dkim_key_archive_url=" OFF ")) is None
    assert zkemail.archive_url(Settings(dkim_key_archive_url="http://127.0.0.1:9/")) == (
        "http://127.0.0.1:9"
    )
    assert zkemail.query_url("https://archive.zk.email", "nordwind.example") == (
        "https://archive.zk.email/api/key?domain=nordwind.example"
    )
    assert zkemail.is_local("http://127.0.0.1:8101") and zkemail.is_local("http://localhost")
    assert zkemail.is_local("http://[::1]:80")
    assert not zkemail.is_local("https://archive.zk.email")
    assert not zkemail.is_local("http://192.0.2.1")
    assert zkemail.USER_AGENT.startswith("Mailrobbe/")


# Manual records --------------------------------------------------------------------------------


def test_a_manual_record_in_the_forms_people_paste() -> None:
    whole = record("rsa1024")
    assert manual_record(f"  {whole}\n") == whole
    quoted = " ".join(f'"{part}"' for part in _chunks(whole, 50))
    assert manual_record(f"s1._domainkey IN TXT ( {quoted} )") == whole
    assert manual_record(_p("rsa1024")) == f"v=DKIM1; k=rsa; p={_p('rsa1024')}"
    wrapped = "\n  ".join(_chunks(_p("rsa1024"), 64))  # copied from a mail, line by line
    assert manual_record(wrapped) == f"v=DKIM1; k=rsa; p={_p('rsa1024')}"
    assert manual_record(_p("ed25519")) == f"v=DKIM1; k=ed25519; p={_p('ed25519')}"
    assert manual_record("v=DKIM1; k=rsa; p=") is None
    assert manual_record("kein Schlüssel") is None
