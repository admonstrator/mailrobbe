"""DKIM verification of a generated mail with dkimpy against a DNS override table.

For the generator tests and the acceptance suite. It follows the convention documented in
mailspider.dkim.override: DnsTimeout from the lookup is temp_error, a missing record no_key.
"""

import dkim

from mailspider.dkim.override import DnsOverrideTable, DnsTimeout
from mailspider.enums import DkimStatus, best_dkim_status


def verify_mail(raw: bytes, table: DnsOverrideTable) -> tuple[DkimStatus, list[DkimStatus]]:
    """Overall status and the status of each DKIM-Signature header, topmost first."""
    verifier = dkim.DKIM(raw)
    count = sum(1 for name, _ in verifier.headers if name.lower() == b"dkim-signature")
    statuses = [_verify(verifier, index, table) for index in range(count)]
    return best_dkim_status(statuses), statuses


def _verify(verifier: dkim.DKIM, index: int, table: DnsOverrideTable) -> DkimStatus:
    records: list[bytes | None] = []

    def dnsfunc(name: bytes, timeout: float = 5) -> bytes | None:
        records.append(table.dnsfunc(name, timeout))
        return records[-1]

    try:
        valid = verifier.verify(idx=index, dnsfunc=dnsfunc)
    except DnsTimeout:
        return DkimStatus.TEMP_ERROR
    except dkim.DKIMException:
        return DkimStatus.FAIL
    if valid:
        return DkimStatus.PASS
    return DkimStatus.NO_KEY if records == [None] else DkimStatus.FAIL
