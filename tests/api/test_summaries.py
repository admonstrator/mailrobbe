"""The summary of one mail or document (milestone 17, D307): GET /api/ai/summary, what the card
"KI-Zusammenfassung" shows. Summaries are rows inserted as a run writes them (test_ai.summarized)
on a copy of the imported archive with a local text service configured."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from mailrobbe.ai.queue import THREAD_KEY
from mailrobbe.enums import AiTarget
from tests.api.test_ai import (
    SUMMARY_OPTIONS,
    TEXT_SERVICE,
    ai_settings,
    original_mails,
    queue,
    summarized,
    summary_tasks,
)
from tests.api.test_imports import Dashboard, serve
from tests.api.test_mails import get, rows
from tests.conftest import GeneratedArchive

pytestmark = pytest.mark.db


@pytest.fixture
async def texts(
    mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> AsyncIterator[Dashboard]:
    """The API on a copy of the imported archive, with a local text service configured."""
    await rows(mutable_database_url, "DELETE FROM job")
    settings = ai_settings(mutable_database_url, generated_archive, tmp_path, **TEXT_SERVICE)
    async with serve(settings) as served:
        yield served


async def view(dashboard: Dashboard, **params: int) -> Any:
    return await get(dashboard.client, "/api/ai/summary", [(k, str(v)) for k, v in params.items()])


async def carried(url: str) -> Any:
    """An original mail carrying a document with a text, and that document."""
    [found] = await rows(
        url,
        """SELECT m.id AS mail, m.raw_sha256, d.id AS document, d.sha256, d.name
           FROM mail m
           JOIN attachment a ON a.mail_id = m.id AND a.container_id IS NULL
           JOIN document d ON d.id = a.document_id
           WHERE d.sha256 IS NOT NULL AND COALESCE(d.extracted_text, '') <> ''
             AND m.is_duplicate_of IS NULL
           ORDER BY m.id LIMIT 1""",
    )
    return found


async def described(url: str, mail_sha256: str, document_id: int) -> int:
    """The mails a tag of this mail's summary and its document's summary describes (D309)."""
    found = await rows(
        url,
        """SELECT count(*) FROM (
               SELECT id FROM mail WHERE raw_sha256 = :sha
               UNION SELECT mail_id FROM attachment WHERE document_id = :document) mails""",
        sha=mail_sha256,
        document=document_id,
    )
    return int(found[0][0])


async def test_a_mail_without_a_summary_can_be_summarised(texts: Dashboard) -> None:
    [mail] = await original_mails(texts.url, 1)
    assert await view(texts, mail=mail.id) == {
        "available": True,
        "summarizable": True,
        "result": None,
        "task": None,
        "failed": None,
        "attachments": [],
        "preparing": 0,
        "stale": False,
        "run": None,
    }


async def test_a_mail_shows_its_summary_tags_hints_and_attachments(
    texts: Dashboard,
) -> None:
    element = await carried(texts.url)
    parts = [
        {"number": 1, "characters": 9000, "summary": "Erster Teil"},
        {"number": 2, "characters": 8000, "summary": "Zweiter Teil"},
    ]
    own = await summarized(
        texts.url,
        "mail",
        element.raw_sha256,
        "Der Vorstand bittet um Quittungen.",
        tags=["Vorstand", "spenden"],
        themes=[
            ("spenden", "Quittungen ohne Namen", 120),
            ("spenden", "Spende", None),  # in the subject
            ("rassismus", "fremd", 40),
            ("geloescht", "alt", 3),  # a theme no longer in themes.toml
        ],
        parts=parts,
        parts_total=5,
    )
    attachment = await summarized(
        texts.url, "document", element.sha256, "Eine Quittung.", tags=["Spenden"]
    )
    # replaced and discarded summaries describe nothing
    for state in ("replaced", "discarded"):
        await summarized(texts.url, "mail", element.raw_sha256, tags=["Vorstand"], state=state)
    found = await view(texts, mail=element.mail)
    assert (found["available"], found["summarizable"], found["task"], found["failed"]) == (
        True,
        True,
        None,
        None,
    )
    result = found["result"]
    assert {key: result[key] for key in result if key not in ("tags", "themes")} == {
        "id": own,
        "target": "mail",
        "summary": "Der Vorstand bittet um Quittungen.",
        "short": False,
        "parts_read": 2,
        "parts_total": 5,
        "origin": None,
        "model": "text-test",
        "remote": False,
        "prompt_version": 1,
        "created_at": result["created_at"],
    }
    # "spenden" and "Spenden" are one tag (D305): the mail's own and its document's
    mails = await described(texts.url, element.raw_sha256, element.document)
    [spenden] = [tag for tag in result["tags"] if tag["label"] == "spenden"]
    [vorstand] = [tag for tag in result["tags"] if tag["label"] == "Vorstand"]
    assert [tag["label"] for tag in result["tags"]] == ["spenden", "Vorstand"]
    assert spenden["mails"] == mails
    duplicates = await rows(
        texts.url, "SELECT count(*) FROM mail WHERE raw_sha256 = :sha", sha=element.raw_sha256
    )
    assert vorstand["mails"] == duplicates[0][0]
    # in the order of themes.toml, the head first, then by position
    assert [(hint["theme"], hint["label"], hint["position"]) for hint in result["themes"]] == [
        ("rassismus", "Rassismus", 40),
        ("spenden", "Spendenaffären", None),
        ("spenden", "Spendenaffären", 120),
        ("geloescht", "geloescht", 3),
    ]
    assert result["themes"][2]["quote"] == "Quittungen ohne Namen"
    [summary] = found["attachments"]
    assert (summary["document_id"], summary["name"]) == (element.document, element.name)
    assert (summary["result"]["id"], summary["result"]["target"]) == (attachment, "document")
    # shown by the spelling it was first given
    assert summary["result"]["tags"] == [spenden]
    assert summary["result"]["summary"] == "Eine Quittung."


async def test_a_document_says_which_text_it_read(texts: Dashboard) -> None:
    element = await carried(texts.url)
    options = {**SUMMARY_OPTIONS, "origin": "ocr"}
    await summarized(texts.url, "document", element.sha256, options=options)
    found = await view(texts, document=element.document)
    assert (found["summarizable"], found["result"]["origin"], found["attachments"]) == (
        True,
        "ocr",
        [],
    )
    # a mail's summary of the same content is not the document's (D301)
    mail_view = await view(texts, mail=element.mail)
    assert mail_view["result"] is None and len(mail_view["attachments"]) == 1


async def test_a_short_mail_has_tags_and_hints_only(texts: Dashboard) -> None:
    [mail] = await original_mails(texts.url, 1)
    options = {**SUMMARY_OPTIONS, "short": True, "words": 12, "origin": "nonsense"}
    await summarized(texts.url, "mail", mail.raw_sha256, "", tags=["Termin"], options=options)
    result = (await view(texts, mail=mail.id))["result"]
    assert (result["summary"], result["short"], result["origin"]) == ("", True, None)
    assert [tag["label"] for tag in result["tags"]] == ["Termin"]


async def test_an_open_task_shows_its_parts(texts: Dashboard) -> None:
    [mail] = await original_mails(texts.url, 1)
    await queue(texts, {"kind": "summarize", "mail_ids": [mail.id], "single": True})
    task = (await view(texts, mail=mail.id))["task"]
    assert (task["status"], task["parts_done"], task["parts_total"]) == ("waiting", 0, None)
    partial = {"parts": [{"number": 1, "characters": 9000, "summary": "Teil"}], "parts_total": 4}
    await rows(
        texts.url,
        "UPDATE ai_task SET status = 'running', partial = CAST(:p AS jsonb)",
        p=json.dumps(partial),
    )
    found = await view(texts, mail=mail.id)
    assert (found["task"]["status"], found["task"]["parts_done"]) == ("running", 1)
    assert (found["task"]["parts_total"], found["failed"]) == (4, None)


async def test_a_failure_shows_until_a_summary_follows(texts: Dashboard) -> None:
    [mail] = await original_mails(texts.url, 1)
    await queue(texts, {"kind": "summarize", "mail_ids": [mail.id]})
    await rows(
        texts.url,
        """UPDATE ai_task SET status = 'failed', attempts = 3, finished_at = now(),
               error = 'the answer is no JSON object'""",
    )
    found = await view(texts, mail=mail.id)
    assert (found["task"], found["failed"]) == (None, "the answer is no JSON object")
    # queued again, the open task shows instead
    await queue(texts, {"kind": "summarize", "mail_ids": [mail.id]})
    found = await view(texts, mail=mail.id)
    assert found["task"] is not None and found["failed"] is None
    await rows(texts.url, "UPDATE ai_task SET status = 'done', finished_at = now()")
    await summarized(texts.url, "mail", mail.raw_sha256)
    found = await view(texts, mail=mail.id)
    assert (found["failed"], found["result"]["target"]) == (None, AiTarget.MAIL)


async def a_thread(url: str) -> Any:
    """A thread of at least two mails with contents of their own, with its content and the
    number of its mails, duplicates too."""
    [found] = await rows(
        url,
        f"""SELECT m.thread_id AS id, {THREAD_KEY} AS sha256,
               (SELECT count(*) FROM mail t WHERE t.thread_id = m.thread_id) AS mails,
               (SELECT t.id FROM mail t WHERE t.thread_id = m.thread_id
                  AND t.is_duplicate_of IS NULL ORDER BY t.date_utc NULLS LAST, t.id
                LIMIT 1) AS earliest
           FROM mail m WHERE m.thread_id IS NOT NULL AND m.is_duplicate_of IS NULL
           GROUP BY m.thread_id HAVING count(DISTINCT m.raw_sha256) >= 3
           ORDER BY m.thread_id LIMIT 1""",
    )
    return found


async def test_a_thread_is_summarised_as_a_whole_and_says_when_it_changed(
    texts: Dashboard,
) -> None:
    thread = await a_thread(texts.url)
    found = await view(texts, thread=thread.id)
    assert (found["summarizable"], found["result"], found["attachments"]) == (True, None, [])
    body = {"kind": "summarize", "thread_ids": [thread.id], "single": True}
    assert (await queue(texts, body))["queued"] == 1
    # the task lists name a thread by its earliest mail
    [task] = await summary_tasks(texts)
    assert (task["target"], task["mail"]["id"], task["document"]) == (
        "thread",
        thread.earliest,
        None,
    )
    assert (await view(texts, thread=thread.id))["task"]["status"] == "waiting"
    await rows(texts.url, "UPDATE ai_task SET status = 'done', finished_at = now()")
    await summarized(
        texts.url, "thread", thread.sha256, "Ein Verlauf.", tags=["Verlauf"], thread_id=thread.id
    )
    found = await view(texts, thread=thread.id)
    assert (found["result"]["target"], found["result"]["summary"], found["stale"]) == (
        "thread",
        "Ein Verlauf.",
        False,
    )
    # its tags describe every mail of the thread (D309)
    assert [(tag["label"], tag["mails"]) for tag in found["result"]["tags"]] == [
        ("Verlauf", thread.mails)
    ]
    # read before a mail joined the thread: still shown, said to be older
    await rows(texts.url, "UPDATE ai_result SET target_sha256 = repeat('0', 64)")
    found = await view(texts, thread=thread.id)
    assert (found["result"]["summary"], found["stale"]) == ("Ein Verlauf.", True)
    # a thread of one mail is that mail's summary
    [mail] = await original_mails(texts.url, 1)
    await rows(texts.url, "UPDATE mail SET thread_id = 2^40 WHERE id = :id", id=mail.id)
    assert (await view(texts, thread=2**40))["summarizable"] is False


async def test_a_mail_counts_its_attachments_under_way(texts: Dashboard) -> None:
    element = await carried(texts.url)
    await rows(
        texts.url,
        """INSERT INTO ai_task (kind, target_sha256, engine, priority)
           VALUES ('ocr', :sha, 'auto', 100)""",
        sha=element.sha256,
    )
    found = await view(texts, mail=element.mail)
    # no AI run lives, so there are no steps to show
    assert (found["preparing"], found["task"], found["run"]) == (1, None, None)
    await rows(texts.url, "UPDATE ai_task SET status = 'done'")
    assert (await view(texts, mail=element.mail))["preparing"] == 0


async def test_one_element_is_asked_for(texts: Dashboard) -> None:
    for params in ({}, {"mail": 1, "document": 1}, {"mail": 1, "thread": 1}):
        response = await texts.client.get("/api/ai/summary", params=params)
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "invalid_selection"
    for params in ({"mail": 2**40}, {"document": 2**40}, {"mail": 2**70}, {"thread": 2**40}):
        response = await texts.client.get("/api/ai/summary", params=params)
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "not_found"


async def test_a_document_without_a_hash_or_a_text_cannot_be_summarised(
    texts: Dashboard,
) -> None:
    element = await carried(texts.url)
    await rows(texts.url, "UPDATE document SET sha256 = NULL WHERE id = :id", id=element.document)
    found = await view(texts, document=element.document)
    assert (found["summarizable"], found["result"], found["task"]) == (False, None, None)
    [empty] = await rows(
        texts.url,
        "SELECT id FROM document WHERE COALESCE(extracted_text, '') = '' ORDER BY id LIMIT 1",
    )
    assert (await view(texts, document=empty.id))["summarizable"] is False


async def test_without_a_text_service_nothing_is_offered(
    mutable_database_url: str, generated_archive: GeneratedArchive, tmp_path: Path
) -> None:
    [mail] = await original_mails(mutable_database_url, 1)
    await summarized(mutable_database_url, "mail", mail.raw_sha256)
    for extra in ({}, {**TEXT_SERVICE, "ai_text_url": "https://203.0.113.5/v1"}):
        settings = ai_settings(mutable_database_url, generated_archive, tmp_path, **extra)
        async with serve(settings) as served:
            found = await view(served, mail=mail.id)
        # a summary made earlier still shows, and can be discarded (D185)
        assert (found["available"], found["result"]["model"]) == (False, "text-test")
