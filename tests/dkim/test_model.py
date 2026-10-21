from datetime import UTC, datetime

from mailrobbe.dkim.model import MailVerdict, SignatureResult
from mailrobbe.enums import DkimReason, DkimStatus

CHECKED_AT = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)


def _signature(status: DkimStatus, reason: DkimReason | None = None) -> SignatureResult:
    return SignatureResult(
        status=status,
        reason=reason,
        domain="nordwind.example",
        selector="s1",
        algorithm="rsa-sha256",
        key_bits=2048,
        signed_headers=("from", "to", "subject"),
        body_hash_ok=True,
        signed_at=datetime(2019, 3, 4, 9, 30, tzinfo=UTC),
        aligned=True,
        dns_cached=False,
    )


def test_status_is_the_best_signature() -> None:
    verdict = MailVerdict(
        (_signature(DkimStatus.FAIL, DkimReason.BODY_HASH_MISMATCH), _signature(DkimStatus.PASS))
    )
    assert verdict.status is DkimStatus.PASS
    assert MailVerdict().status is DkimStatus.UNSIGNED


def test_result_rows_follow_the_dkim_result_columns() -> None:
    verdict = MailVerdict(
        (_signature(DkimStatus.PASS), _signature(DkimStatus.NO_KEY, DkimReason.KEY_NOT_FOUND))
    )
    rows = verdict.result_rows(7, CHECKED_AT)
    assert [row["signature_index"] for row in rows] == [0, 1]
    assert rows[1] == {
        "mail_id": 7,
        "signature_index": 1,
        "status": "no_key",
        "domain": "nordwind.example",
        "selector": "s1",
        "algorithm": "rsa-sha256",
        "key_bits": 2048,
        "signed_headers": ["from", "to", "subject"],
        "body_hash_ok": True,
        "signed_at": datetime(2019, 3, 4, 9, 30, tzinfo=UTC),
        "aligned": True,
        "reason": "key_not_found",
        "checked_at": CHECKED_AT,
        "dns_cached": False,
        "key_id": None,
        "key_origin": None,
    }
    assert rows[0]["reason"] is None
    assert MailVerdict().result_rows(7, CHECKED_AT) == []
