"""DNS override table: DKIM key records resolved from a file instead of real DNS (SPEC 3.6).

File format (dns_override.json, written by the generator):

    {"version": 1,
     "records": {"<selector>._domainkey.<domain>": "v=DKIM1; k=rsa; p=..."},
     "temp_error": ["<selector>._domainkey.<domain>", ...]}

Names are lowercase without a trailing dot. A name in `temp_error` behaves like a DNS timeout,
a name in neither list like NXDOMAIN.

How the outcomes surface through dkimpy 1.1.8 (`dkim.DKIM.verify(idx, dnsfunc=...)`), the
convention every resolver in this project follows:

- Found: `dnsfunc` returns the TXT record as bytes and dkimpy verifies: `True`, `False` for a
  bad header signature, or a raised DKIMException (ValidationError "body hash mismatch",
  malformed tags), which is fail as well.
- NXDOMAIN (no_key): `dnsfunc` returns None. dkimpy turns that into a KeyFormatError
  ("missing public key"), logs it and returns `False`, the same value as a bad signature.
  A verifier therefore has to notice the None itself (wrap `dnsfunc` or call `lookup` first)
  to report no_key instead of fail.
- Timeout (temp_error): `dnsfunc` raises `DnsTimeout`. dkimpy catches only its own exceptions
  around the key lookup (KeyFormatError, binascii.Error and its DnsTimeoutError, which it
  also maps to `False`), so `DnsTimeout` deliberately derives from neither: it propagates out
  of `DKIM.verify` and out of the module-level `dkim.verify` unchanged.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

FORMAT_VERSION = 1


class DnsTimeout(Exception):
    """A temporary DNS failure for the given name: the DKIM result is temp_error."""


def normalise_name(name: str) -> str:
    """Lowercase, no surrounding whitespace, no trailing dot."""
    return name.strip().rstrip(".").lower()


def key_name(selector: str, domain: str) -> str:
    """DNS name of a DKIM key record: '<selector>._domainkey.<domain>'."""
    return normalise_name(f"{selector}._domainkey.{domain}")


@dataclass(frozen=True, slots=True)
class DnsOverrideTable:
    records: Mapping[str, str] = field(default_factory=dict)
    temp_error: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        records = {normalise_name(name): txt for name, txt in self.records.items()}
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "temp_error", frozenset(map(normalise_name, self.temp_error)))

    @classmethod
    def load(cls, path: Path) -> "DnsOverrideTable":
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != FORMAT_VERSION:
            raise ValueError(f"{path}: unsupported DNS override table version")
        return cls(records=data["records"], temp_error=frozenset(data["temp_error"]))

    def dump(self, path: Path) -> None:
        data = {
            "version": FORMAT_VERSION,
            "records": dict(sorted(self.records.items())),
            "temp_error": sorted(self.temp_error),
        }
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def lookup(self, name: str) -> str | None:
        """TXT record for name, None for NXDOMAIN; raises DnsTimeout for temp_error names.

        A name listed in both `temp_error` and `records` times out.
        """
        key = normalise_name(name)
        if key in self.temp_error:
            raise DnsTimeout(key)
        return self.records.get(key)

    def dnsfunc(self, name: bytes, timeout: float = 5) -> bytes | None:
        """`lookup` with the signature dkimpy expects for its `dnsfunc` argument."""
        record = self.lookup(name.decode("utf-8", errors="replace"))
        return None if record is None else record.encode("ascii")
