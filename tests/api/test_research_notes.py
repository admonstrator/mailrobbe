"""Notes (D56): writing, editing and deleting them, and the list of every note with its mail."""

from datetime import datetime
from urllib.parse import urlencode

import httpx
import pytest

from mailrobbe.api.schemas import NOTE_LIMIT
from tests.api.test_mails import rows
from tests.api.test_research import call, copies, error, research_of, single_mails

pytestmark = pytest.mark.db


async def test_notes_are_written_edited_and_deleted(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    http = mutable_client
    first, second = (await copies(mutable_database_url))[0][:2]
    note = await call(http, "POST", f"/api/mails/{first}/notes", {"body": "  Rückfrage  "}, 201)
    assert (note["body"], note["author"]) == ("Rückfrage", "Anna Müller")
    assert note["updated_at"] == note["created_at"]
    other = await call(
        http, "POST", f"/api/mails/{second}/notes", {"body": "Zweite"}, 201, editor={}
    )
    assert other["author"] is None
    # Byte-identical copies share their notes, oldest first.
    assert (await research_of(http, second))["notes"] == [note, other]
    assert (await research_of(http, first))["notes"] == [note, other]

    path = f"/api/notes/{note['id']}"
    same = await call(http, "PATCH", path, {"body": "Rückfrage "})
    assert same == note  # the same text changes nothing
    edited = await call(http, "PATCH", path, {"body": "Rückfrage beim Anwalt"}, editor={})
    assert (edited["body"], edited["author"], edited["created_at"]) == (
        "Rückfrage beim Anwalt",
        "Anna Müller",  # the author stays the one who wrote it
        note["created_at"],
    )
    assert datetime.fromisoformat(edited["updated_at"]) > datetime.fromisoformat(note["updated_at"])

    for body in ({"body": " \n "}, {"body": ""}, {"body": "x" * (NOTE_LIMIT + 1)}, {}):
        await call(http, "POST", f"/api/mails/{first}/notes", body, 422)
        await call(http, "PATCH", path, body, 422)
    await error(http, "POST", "/api/mails/987654321/notes", {"body": "x"}, 404, "not_found")
    await call(http, "DELETE", path, status=204)
    await error(http, "DELETE", path, None, 404, "not_found")
    await error(http, "PATCH", path, {"body": "x"}, 404, "not_found")
    assert (await research_of(http, first))["notes"] == [other]
    assert (await call(http, "GET", "/api/research"))["notes"] == 1


async def test_the_note_list_pages_newest_first_and_searches(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    http, url = mutable_client, mutable_database_url
    singles = await single_mails(url, 4)
    bodies = [
        "Termin mit dem ANWALT",
        "Spende in bar",
        "anwaltlich prüfen",
        "Ohne Treffer",
        "Spenden",
    ]
    written = []
    for index, body in enumerate(bodies):
        mail_id = singles[index % len(singles)]
        written.append(await call(http, "POST", f"/api/mails/{mail_id}/notes", {"body": body}, 201))
    newest_first = list(reversed(written))

    page = await call(http, "GET", "/api/notes?limit=2")
    assert [n["id"] for n in page["items"]] == [n["id"] for n in newest_first[:2]]
    assert page["total"] == 5
    seen = [n["id"] for n in page["items"]]
    while page["next_cursor"]:
        page = await call(http, "GET", f"/api/notes?limit=2&cursor={page['next_cursor']}")
        seen += [n["id"] for n in page["items"]]
    assert seen == [n["id"] for n in newest_first]

    # q: part of the text, any case; two letters work too, without the trigram index.
    for q, expected in (("anwalt", [2, 0]), ("SPENDE", [4, 1]), ("de", [4, 1, 0]), ("  ", None)):
        found = await call(http, "GET", "/api/notes?" + urlencode({"q": q, "limit": 1}))
        ids = [written[i]["id"] for i in expected] if expected else [n["id"] for n in newest_first]
        assert found["total"] == len(ids)
        assert [n["id"] for n in found["items"]] == ids[:1]
        if len(ids) > 1:
            more = urlencode({"q": q, "cursor": found["next_cursor"]})
            rest = await call(http, "GET", f"/api/notes?{more}")
            assert [n["id"] for n in rest["items"]] == ids[1:]
            assert rest["next_cursor"] is None
    cursor = (await call(http, "GET", "/api/notes?q=anwalt&limit=1"))["next_cursor"]
    await error(http, "GET", f"/api/notes?q=spende&cursor={cursor}", None, 400, "invalid_cursor")
    await error(http, "GET", "/api/notes?cursor=abc", None, 400, "invalid_cursor")
    await call(http, "GET", "/api/notes?limit=0", status=422)

    # Each note with its mail: subject, date and sender as the list shows them.
    mails = {
        row.id: row
        for row in await rows(
            url,
            "SELECT m.id, m.subject, m.date_utc, m.raw_sha256 FROM mail m WHERE m.id = ANY(:ids)",
            ids=singles,
        )
    }
    listed = await call(http, "GET", "/api/mails?has_note=true&limit=200")
    senders = {item["id"]: item["sender"] for item in listed["items"]}
    for item in (await call(http, "GET", "/api/notes"))["items"]:
        mail = mails[item["mail"]["id"]]
        assert item["mail_sha256"] == mail.raw_sha256
        assert item["mail"]["subject"] == mail.subject
        assert item["mail"]["sender"] == senders[mail.id]


async def test_a_note_shows_the_original_or_no_mail(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    http, url = mutable_client, mutable_database_url
    copied = await rows(
        url,
        "SELECT raw_sha256, array_agg(id ORDER BY is_duplicate_of IS NOT NULL, id) AS ids FROM mail"
        " GROUP BY raw_sha256 HAVING count(*) > 1 ORDER BY min(id) LIMIT 1",
    )
    original, *others = copied[0].ids
    await call(http, "POST", f"/api/mails/{others[-1]}/notes", {"body": "An der Kopie"}, 201)
    note = (await call(http, "GET", "/api/notes"))["items"][0]
    assert note["mail"]["id"] == original
    # The content leaves the archive: the note stays, without a mail.
    await rows(url, "DELETE FROM mail WHERE raw_sha256 = :sha", sha=copied[0].raw_sha256)
    gone = (await call(http, "GET", "/api/notes"))["items"][0]
    assert gone["id"] == note["id"]
    assert gone["mail"] == {"id": None, "subject": None, "date": None, "sender": None}
    assert gone["mail_sha256"] == copied[0].raw_sha256
