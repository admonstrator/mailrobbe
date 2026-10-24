"""Questions about persons, "KI fragen" (D347, D348): GET and POST /api/persons/{id}/questions,
DELETE /api/person-questions/{id}. A question queues what it waits for first and starts a run
for itself; the run is fake_run.py, so the answers are written here as the step would."""

from typing import Any

import pytest

from tests.api.test_ai import status
from tests.api.test_imports import Dashboard, fake, post, reaped
from tests.api.test_mails import get, rows
from tests.api.test_summaries import texts

pytestmark = pytest.mark.db

__all__ = ["texts"]


async def busiest(url: str, count: int = 2) -> list[int]:
    """The root persons with the most mails."""
    found = await rows(
        url,
        """SELECT s.person_id FROM person_stats s JOIN person p ON p.id = s.person_id
           WHERE p.merged_into IS NULL ORDER BY s.mails DESC, s.person_id LIMIT :count""",
        count=count,
    )
    return [int(row[0]) for row in found]


async def card(dashboard: Dashboard, person: int) -> Any:
    return await get(dashboard.client, f"/api/persons/{person}/questions")


async def test_a_question_waits_for_its_prework_and_shows_its_answer(
    texts: Dashboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "wait")
    person, other = await busiest(texts.url)
    found = await card(texts, person)
    assert found["available"] and found["questions"] == []
    assert [t["key"] for t in found["templates"]][:2] == ["contacts", "compare"]
    asked = await post(
        texts.client,
        f"/api/persons/{person}/questions",
        {"template": "compare", "other_id": other},
    )
    assert asked["run"] == "started"
    question = asked["question"]
    assert (question["status"], question["person"]["id"], question["other"]["id"]) == (
        "waiting",
        person,
        other,
    )
    # the summaries of their conversations come first, first in the queue (D329, D348)
    prework = question["prework"]
    assert prework["summaries"] > 0 and prework["seconds"] > 0
    assert question["open"] == prework["summaries"] + prework["recognize"]
    priorities = await rows(texts.url, "SELECT DISTINCT priority FROM ai_task")
    assert [row[0] for row in priorities] == [100]
    job = (await status(texts))["job"]
    assert job["alive"] and job["options"]["questions"] == [question["id"]]
    # it stands on both persons' cards, newest first
    assert [q["id"] for q in (await card(texts, other))["questions"]] == [question["id"]]
    await rows(texts.url, "UPDATE ai_task SET status = 'done', finished_at = now()")
    assert (await card(texts, person))["questions"][0]["open"] == 0
    await rows(
        texts.url,
        """UPDATE person_question SET status = 'done', answer = 'Sie schreiben sich oft.',
               contents = 3, model = 'text-test', finished_at = now()""",
    )
    [done] = (await card(texts, person))["questions"]
    assert (done["status"], done["answer"], done["contents"]) == (
        "done",
        "Sie schreiben sich oft.",
        3,
    )
    await post(texts.client, "/api/ai/run/stop", {})
    await reaped(texts)
    response = await texts.client.delete(f"/api/person-questions/{done['id']}")
    assert response.status_code == 204
    assert (await card(texts, person))["questions"] == []


async def test_a_question_needs_a_template_and_what_it_names(
    texts: Dashboard, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake(monkeypatch, "exit")
    [person] = await busiest(texts.url, 1)
    path = f"/api/persons/{person}/questions"
    for body, code in (
        ({"template": "nothing"}, "invalid_option"),
        ({"template": "free", "text": "  "}, "invalid_option"),
        ({"template": "compare"}, "invalid_selection"),
        ({"template": "compare", "other_id": person}, "invalid_selection"),
    ):
        response = await texts.client.post(path, json=body)
        assert response.status_code == 400, body
        assert response.json()["detail"]["code"] == code
    response = await texts.client.post("/api/persons/0/questions", json={"template": "topics"})
    assert response.status_code == 404
