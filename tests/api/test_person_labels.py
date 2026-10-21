"""Named accounts over HTTP (D156, D157): the label endpoint and the profile, the person list and
the mail search, labels in the responses that name persons, GraphML, the mail list's CSV and the
export. Every test writes labels, so each works on its own copy of the imported archive."""

import csv
import io
import json
import zipfile
from typing import Any

import httpx
import pypdf
import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe.api.schemas import LABEL_NAME_LIMIT, LABEL_NOTE_LIMIT

pytestmark = pytest.mark.db

EDITOR = {"X-Mailrobbe-Editor": "Lena%20Vogt"}
NAME, ROLE, NOTE = "Kassenwart Nord", "Schatzmeister", "Zeile eins\nZeile zwei"


async def rows(url: str, sql: str, **params: Any) -> list[Any]:
    engine = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(sql), params)
            return list(result.all()) if result.returns_rows else []
    finally:
        await engine.dispose()


async def get(client: httpx.AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def get_csv(client: httpx.AsyncClient, **params: Any) -> list[list[str]]:
    response = await client.get("/api/mails/export.csv", params=params)
    assert response.status_code == 200, response.text
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))


async def put_label(
    client: httpx.AsyncClient, person_id: int, status: int = 200, **fields: str
) -> Any:
    response = await client.put(f"/api/persons/{person_id}/label", json=fields, headers=EDITOR)
    assert response.status_code == status, response.text
    return response.json()


async def merge(client: httpx.AsyncClient, target: int, source: int) -> Any:
    response = await client.post("/api/persons/merge", json={"target": target, "sources": [source]})
    assert response.status_code == 200, response.text
    return response.json()


async def busiest(url: str, count: int) -> list[Any]:
    """The root persons that send most, with their address, busiest first."""
    return await rows(
        url,
        "SELECT p.id, p.canonical_email AS email FROM participation pa"
        " JOIN person p ON p.id = pa.person_id WHERE pa.role = 'from' AND p.merged_into IS NULL"
        " GROUP BY p.id ORDER BY count(*) DESC, p.id LIMIT :count",
        count=count,
    )


async def test_the_label_belongs_to_the_roots_address(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    root, alias = await busiest(mutable_database_url, 2)
    merged = await merge(mutable_client, root.id, alias.id)
    assert merged["label"] is None
    assert [a["label"] for a in merged["aliases"]] == [None]

    # Named through the alias's id: the label is the root's, trimmed, with the editor.
    profile = await put_label(
        mutable_client, alias.id, name=f"  {NAME} ", role=ROLE, note=f"\n{NOTE}\n"
    )
    assert profile["id"] == root.id
    label = profile["label"]
    assert {key: label[key] for key in ("email", "name", "role", "note", "editor")} == {
        "email": root.email,
        "name": NAME,
        "role": ROLE,
        "note": NOTE,
        "editor": "Lena Vogt",
    }
    assert [a["label"] for a in profile["aliases"]] == [None]  # an alias's own label only
    stored = await rows(
        mutable_database_url, "SELECT email, created_at, updated_at FROM person_label"
    )
    assert [(row.email, row.created_at == row.updated_at) for row in stored] == [(root.email, True)]
    assert await get(mutable_client, f"/api/persons/{alias.id}") == profile

    # Changed: created_at stays; blank fields are none.
    profile = await put_label(mutable_client, root.id, name=NAME, role=" ", note="")
    label = profile["label"]
    assert (label["name"], label["role"], label["note"]) == (NAME, None, None)
    again = await rows(mutable_database_url, "SELECT created_at, updated_at FROM person_label")
    assert again[0].created_at == stored[0].created_at
    assert again[0].updated_at > stored[0].updated_at

    # All blank removes it; an unknown person and too long fields are refused.
    profile = await put_label(mutable_client, root.id, name=" ", role="", note="")
    assert profile["label"] is None
    assert await rows(mutable_database_url, "SELECT email FROM person_label") == []
    missing = await put_label(mutable_client, 987654321, status=404, name=NAME)
    assert missing["detail"]["code"] == "not_found"
    await put_label(mutable_client, root.id, status=422, name="x" * (LABEL_NAME_LIMIT + 1))
    await put_label(mutable_client, root.id, status=422, role="x" * (LABEL_NAME_LIMIT + 1))
    await put_label(mutable_client, root.id, status=422, note="x" * (LABEL_NOTE_LIMIT + 1))
    await put_label(mutable_client, root.id, name="x" * LABEL_NAME_LIMIT)


async def test_labels_follow_merges_and_unmerges(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    root, alias = await busiest(mutable_database_url, 2)
    await put_label(mutable_client, alias.id, name=NAME, role=ROLE)  # alias is still a root

    merged = await merge(mutable_client, root.id, alias.id)
    assert (merged["label"]["email"], merged["label"]["name"]) == (alias.email, NAME)
    assert [a["label"] for a in merged["aliases"]] == [{"name": NAME, "role": ROLE}]
    listed = await get(mutable_client, "/api/persons", q=root.email)
    assert [item["label"] for item in listed["items"]] == [{"name": NAME, "role": ROLE}]

    unmerged = (await mutable_client.post(f"/api/persons/{alias.id}/unmerge")).json()
    assert unmerged["id"] == root.id
    assert unmerged["label"] is None
    assert (await get(mutable_client, f"/api/persons/{alias.id}"))["label"]["name"] == NAME


async def test_the_person_list_finds_and_filters_labels(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    first, second, third = await busiest(mutable_database_url, 3)
    await rows(
        mutable_database_url,
        "UPDATE person SET merged_into = :root WHERE id = :alias",
        root=first.id,
        alias=third.id,
    )
    # Through the alias's id the root's address is named; the alias gets a label of its own.
    await put_label(mutable_client, third.id, name="Zz Unauffindbar", role="Kassen_wart")
    await put_label(mutable_client, second.id, role="Fahrer")
    await rows(
        mutable_database_url,
        "INSERT INTO person_label (email, name) VALUES (:email, 'Deckname Alias')",
        email=third.email,
    )

    found = await get(mutable_client, "/api/persons", q="deckname")
    assert [item["id"] for item in found["items"]] == [first.id]
    assert found["items"][0]["label"] == {"name": "Zz Unauffindbar", "role": "Kassen_wart"}
    found = await get(mutable_client, "/api/persons", q="kassen_w")
    assert [item["id"] for item in found["items"]] == [first.id]
    found = await get(mutable_client, "/api/persons", q="FAHRER")
    assert [item["id"] for item in found["items"]] == [second.id]

    labelled = await get(mutable_client, "/api/persons", labelled="true", limit=1)
    assert labelled["total"] == 2
    following = await get(
        mutable_client, "/api/persons", labelled="true", limit=1, cursor=labelled["next_cursor"]
    )
    assert following["next_cursor"] is None
    listed = [item["id"] for page in (labelled, following) for item in page["items"]]
    assert sorted(listed) == sorted([first.id, second.id])
    # A cursor belongs to its list: the unfiltered list refuses the labelled one's.
    response = await mutable_client.get(
        "/api/persons", params={"limit": 1, "cursor": labelled["next_cursor"]}
    )
    assert response.status_code == 400
    both = await get(mutable_client, "/api/persons", labelled="true", q="fahr")
    assert [item["id"] for item in both["items"]] == [second.id]


async def test_from_to_and_cc_match_labels(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    root, alias = await busiest(mutable_database_url, 2)
    await rows(
        mutable_database_url,
        "UPDATE person SET merged_into = :root WHERE id = :alias",
        root=root.id,
        alias=alias.id,
    )
    await put_label(mutable_client, alias.id, name="Graf Zahl", role="Kassierer")

    async def mail_ids(q: str) -> set[int]:
        return {int(row[0]) for row in (await get_csv(mutable_client, q=q))[1:]}

    for role in ("from", "to", "cc"):
        expected = await rows(
            mutable_database_url,
            "SELECT DISTINCT mail_id FROM participation WHERE role = CAST(:role AS"
            " participation_role) AND person_id IN (:root, :alias)",
            role=role,
            root=root.id,
            alias=alias.id,
        )
        assert expected or role != "from"
        wanted = {row.mail_id for row in expected}
        assert await mail_ids(f"{role}:zahl") == wanted
        assert await mail_ids(f'{role}:"graf zahl"') == wanted
        assert await mail_ids(f"{role}:kassierer") == wanted
    assert await mail_ids("from:niemandsname") == set()


async def test_names_everywhere(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    (sender,) = await busiest(mutable_database_url, 1)
    named = {"name": NAME, "role": ROLE}
    await put_label(mutable_client, sender.id, name=NAME, role=ROLE, note=NOTE)

    page = await get(mutable_client, "/api/mails", q=f"from:{sender.email}", limit=5)
    assert page["items"] and all(item["sender"]["label"] == named for item in page["items"])
    detail = await get(mutable_client, f"/api/mails/{page['items'][0]['id']}")
    assert [p["label"] for p in detail["participants"] if p["person_id"] == sender.id] == [named]

    graph = await get(mutable_client, "/api/graph", center=sender.id)
    labels = {node["id"]: node["label"] for node in graph["nodes"]}
    assert labels.pop(sender.id) == named
    assert set(labels.values()) == {None}
    contact = next(node["id"] for node in graph["nodes"] if node["id"] != sender.id)
    contacts = await get(mutable_client, f"/api/persons/{contact}/contacts", limit=200)
    shown = [
        c["person"]["label"] for c in contacts["items"] if c["person"]["person_id"] == sender.id
    ]
    assert shown == [named]

    timeline = await get(mutable_client, "/api/timeline", split="person", split_id=sender.id)
    (series,) = timeline["series"]
    assert (series["label"], series["person"]["label"]) == (NAME, named)

    response = await mutable_client.get("/api/graph/export.graphml", params={"center": sender.id})
    assert response.status_code == 200
    document = response.text
    assert '<key id="label_name" for="node" attr.name="label_name" attr.type="string"/>' in document
    assert (
        f'<node id="{sender.id}"><data key="label">{NAME}</data>'
        f'<data key="email">{sender.email}</data>'
    ) in document
    labelled = f'<data key="label_name">{NAME}</data><data key="label_role">{ROLE}</data></node>'
    assert labelled in document
    assert document.count('<data key="label_name">') == 1  # only the labelled node has one

    exported = await get_csv(mutable_client)
    assert exported[0][-1] == "Benennungen"
    sent = await rows(
        mutable_database_url,
        "SELECT mail_id FROM participation WHERE person_id = :id AND role = 'from'",
        id=sender.id,
    )
    cells = {int(row[0]): row[-1] for row in exported[1:]}
    named_text = f"{NAME}, {ROLE} ({sender.email})"
    assert {cells[row.mail_id] for row in sent} == {named_text}
    assert set(cells.values()) == {"", named_text}  # as a recipient, or no one labelled


async def test_the_export_carries_labels_only_with_research_data(
    mutable_client: httpx.AsyncClient, mutable_database_url: str
) -> None:
    (sender,) = await busiest(mutable_database_url, 1)
    await put_label(mutable_client, sender.id, name=NAME, role=ROLE, note=NOTE)
    (mail,) = await rows(
        mutable_database_url,
        "SELECT m.id FROM mail m JOIN participation pa ON pa.mail_id = m.id"
        " WHERE pa.person_id = :id AND pa.role = 'from' AND m.is_duplicate_of IS NULL"
        " ORDER BY m.id LIMIT 1",
        id=sender.id,
    )

    async def download(**options: Any) -> zipfile.ZipFile:
        created = await mutable_client.post(
            "/api/exports", json={"ids": [mail.id], **options}, headers=EDITOR
        )
        assert created.status_code == 201, created.text
        response = await mutable_client.get(created.json()["download_url"])
        assert response.status_code == 200
        return zipfile.ZipFile(io.BytesIO(response.content))

    def read(archive: zipfile.ZipFile, suffix: str) -> bytes:
        (name,) = [name for name in archive.namelist() if name.endswith(suffix)]
        return archive.read(name)

    def pdf_text(archive: zipfile.ZipFile) -> str:
        reader = pypdf.PdfReader(io.BytesIO(read(archive, "/mail.pdf")))
        return " ".join(" ".join(page.extract_text() for page in reader.pages).split())

    plain = await download()
    (entry,) = json.loads(read(plain, "/manifest.json"))["mails"]
    assert [address["label"] for address in entry["from"]] == [None]
    assert "Benennung" not in pdf_text(plain)
    assert NAME not in read(plain, "/manifest.csv").decode()
    readme = read(plain, "/LIESMICH.txt").decode()
    assert "Benennungen von Beteiligten und die Suchkriterien" in readme

    full = await download(include_research=True)
    (entry,) = json.loads(read(full, "/manifest.json"))["mails"]
    assert [address["label"] for address in entry["from"]] == [
        {"name": NAME, "role": ROLE, "note": NOTE}
    ]
    assert all(address["label"] is None for address in entry["to"] + entry["cc"])
    assert f"Benennung {NAME}, {ROLE} ({sender.email})" in pdf_text(full)
    readme = read(full, "/LIESMICH.txt").decode()
    assert "hat das Rechercheteam selbst vergeben; sie stehen nicht in den Mails" in readme
