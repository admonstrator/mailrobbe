import base64
import json
from pathlib import Path

import dkim
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from mailrobbe.dkim.override import DnsOverrideTable, DnsTimeout, key_name

MESSAGE = (
    b"From: Max Mueller <max.mueller@nordwind.example>\nTo: anna@hafen.example\n"
    b"Subject: Test\nDate: Mon, 04 Mar 2019 10:22:33 +0100\n"
    b"Message-ID: <1@nordwind.example>\n\nHallo Anna,\n\nbis morgen.\n"
)


@pytest.fixture(scope="module")
def key() -> bytes:
    private = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    return private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )


def _record(key: bytes) -> str:
    public = serialization.load_pem_private_key(key, password=None).public_key()
    der = public.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return "v=DKIM1; k=rsa; p=" + base64.b64encode(der).decode()


def test_dump_and_load_round_trip(tmp_path: Path) -> None:
    table = DnsOverrideTable(
        records={"s1._domainkey.a.example": "v=DKIM1; k=rsa; p=AAAA"},
        temp_error=frozenset({"s2._domainkey.b.example"}),
    )
    path = tmp_path / "dns_override.json"
    table.dump(path)
    assert json.loads(path.read_text()) == {
        "version": 1,
        "records": {"s1._domainkey.a.example": "v=DKIM1; k=rsa; p=AAAA"},
        "temp_error": ["s2._domainkey.b.example"],
    }
    assert DnsOverrideTable.load(path) == table


def test_load_rejects_unknown_version(tmp_path: Path) -> None:
    path = tmp_path / "dns_override.json"
    path.write_text(json.dumps({"version": 2, "records": {}, "temp_error": []}))
    with pytest.raises(ValueError):
        DnsOverrideTable.load(path)


def test_lookup_normalises_names() -> None:
    table = DnsOverrideTable(records={"S1._DomainKey.A.Example.": "txt"})
    assert table.records == {"s1._domainkey.a.example": "txt"}
    assert table.lookup("s1._domainkey.a.example") == "txt"
    assert table.lookup(" S1._DOMAINKEY.a.example. ") == "txt"
    assert table.lookup("s2._domainkey.a.example") is None
    assert key_name("S1", "A.Example.") == "s1._domainkey.a.example"


def test_temp_error_raises_and_wins_over_a_record() -> None:
    name = "s1._domainkey.a.example"
    table = DnsOverrideTable(records={name: "txt"}, temp_error=frozenset({name.upper() + "."}))
    with pytest.raises(DnsTimeout):
        table.lookup(name)
    with pytest.raises(DnsTimeout):
        table.dnsfunc(name.encode() + b".")


def test_dnsfunc_returns_bytes_or_none() -> None:
    table = DnsOverrideTable(records={"s1._domainkey.a.example": "v=DKIM1; p=x"})
    assert table.dnsfunc(b"s1._domainkey.a.example.") == b"v=DKIM1; p=x"
    assert table.dnsfunc(b"s9._domainkey.a.example.", timeout=1) is None


def _signed(key: bytes) -> bytes:
    signature: bytes = dkim.sign(MESSAGE, b"s1", b"nordwind.example", key, linesep=b"\n")
    return signature + MESSAGE


def test_dnsfunc_with_dkimpy(key: bytes) -> None:
    message = _signed(key)
    name = "s1._domainkey.nordwind.example"
    found = DnsOverrideTable(records={name: _record(key)})
    assert dkim.verify(message, dnsfunc=found.dnsfunc)
    # A missing record comes back from dkimpy as a plain False, like a bad signature ...
    assert not dkim.verify(message, dnsfunc=DnsOverrideTable().dnsfunc)
    assert not dkim.verify(message.replace(b"bis morgen", b"bis heute"), dnsfunc=found.dnsfunc)
    # ... while DnsTimeout propagates out of both entry points, so temp_error stays visible.
    timeout = DnsOverrideTable(temp_error=frozenset({name}))
    with pytest.raises(DnsTimeout):
        dkim.verify(message, dnsfunc=timeout.dnsfunc)
    with pytest.raises(DnsTimeout):
        dkim.DKIM(message).verify(dnsfunc=timeout.dnsfunc)


def test_dkimpy_swallows_its_own_timeout_error(key: bytes) -> None:
    """Why DnsTimeout is not a dkim.DnsTimeoutError: dkimpy would turn it into False."""

    def dnsfunc(name: bytes, timeout: float = 5) -> bytes | None:
        raise dkim.DnsTimeoutError("timeout")

    assert dkim.DKIM(_signed(key)).verify(dnsfunc=dnsfunc) is False
