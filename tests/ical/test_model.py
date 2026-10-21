import pytest

from mailrobbe.ical.model import event_kind


@pytest.mark.parametrize(
    ("method", "status", "kind"),
    [
        ("REQUEST", None, "request"),
        ("publish", "CONFIRMED", "request"),
        (None, None, "request"),
        ("REPLY", None, "reply"),
        ("Counter", None, "reply"),
        ("DECLINECOUNTER", None, "reply"),
        ("CANCEL", None, "cancel"),
        ("REQUEST", "cancelled", "cancel"),
    ],
)
def test_event_kind(method: str | None, status: str | None, kind: str) -> None:
    assert event_kind(method, status) == kind
