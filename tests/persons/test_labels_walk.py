from collections.abc import Collection
from typing import Any

import pytest

from mailrobbe.api.schemas import AccountLabel, MailPage, PersonRef
from mailrobbe.persons import labels


async def test_attach_labels_sets_every_person_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[set[int]] = []

    async def labels_of(db: Any, person_ids: Collection[int]) -> dict[int, AccountLabel]:
        asked.append(set(person_ids))
        return {2: AccountLabel(name="Kassenwart", role=None)}

    monkeypatch.setattr(labels, "labels_of", labels_of)
    sender = PersonRef(person_id=1, email="a@example.test", name="A")
    recipient = PersonRef(person_id=2, email="b@example.test", name=None)
    page = MailPage.model_validate(
        {
            "items": [
                {
                    "id": 7,
                    "date": None,
                    "subject": None,
                    "dkim_status": None,
                    "has_attachments": False,
                    "sender": sender.model_dump(),
                    "recipients": [recipient.model_dump()],
                    "recipient_count": 1,
                    "thread_id": None,
                    "is_duplicate": False,
                    "flagged": False,
                    "size": 1,
                    "mbox_file_id": 1,
                }
            ],
            "next_cursor": None,
            "prev_cursor": None,
            "query_terms": [],
        }
    )
    await labels.attach_labels(None, page)  # type: ignore[arg-type]
    assert asked == [{1, 2}]
    item = page.items[0]
    assert item.sender is not None and item.sender.label is None
    assert item.recipients[0].label == AccountLabel(name="Kassenwart", role=None)
