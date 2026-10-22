"""Protected and packed documents in the API (milestone 19, D230 to D239) on ARCHIVE
(tests/passwords/samples.py) imported twice, so that the opened Paket.zip is unpacked too: the
document list and its summary, the document page of locked, opened, packed and packing documents,
the passwords typed in, the decrypted downloads and previews, the mail detail's members and the
documents of the signal reasons."""

import asyncio
import io
import zipfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from pypdf import PdfReader

from mailrobbe.config import Settings
from tests.api.conftest import _client
from tests.passwords.samples import (
    AKTEN,
    BERICHT,
    GEHEIM_PASSWORD,
    LISTE_PASSWORD,
    LISTE_TEXT,
    PAKET_PASSWORD,
    PLAN,
    VERTRAG_PASSWORD,
    VERTRAG_TEXT,
    copied,
    documents,
    execute,
    fetch,
    imported,
    mail_ids,
    needs_seven_zip,
    write_archive,
)

pytestmark = [pytest.mark.db, pytest.mark.slow, needs_seven_zip]

EDITOR = {"X-Mailrobbe-Editor": "Aaron"}


@pytest.fixture(scope="module")
def mbox_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_archive(tmp_path_factory.mktemp("protected") / "mbox")


@pytest.fixture(scope="module")
def imported_url(database_server_url: str, mbox_dir: Path) -> Iterator[str]:
    with imported(database_server_url, mbox_dir, runs=2) as url:
        yield url


@pytest.fixture(scope="module")
def doc(imported_url: str) -> dict[str, int]:
    """Document id by name."""
    return {name: row.id for name, row in asyncio.run(documents(imported_url)).items()}


@pytest.fixture(scope="module")
def mail(imported_url: str) -> dict[int, int]:
    """Mail id by index in ARCHIVE."""
    return asyncio.run(mail_ids(imported_url))


def settings(url: str, mbox_dir: Path, tmp_path: Path) -> Settings:
    return Settings(
        database_url=url,
        mbox_dir=mbox_dir,
        frontend_dir=tmp_path / "no-frontend",
        preview_dir=tmp_path / "previews",
    )


@pytest.fixture
async def client(
    imported_url: str, mbox_dir: Path, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    """Read only."""
    async for http in _client(settings(imported_url, mbox_dir, tmp_path)):
        yield http


@pytest.fixture
def mutable_url(database_server_url: str, imported_url: str) -> Iterator[str]:
    with copied(database_server_url, imported_url) as url:
        yield url


@pytest.fixture
async def mutable_client(
    mutable_url: str, mbox_dir: Path, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    async for http in _client(settings(mutable_url, mbox_dir, tmp_path)):
        yield http


async def get(client: httpx.AsyncClient, path: str, **params: Any) -> Any:
    response = await client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def error(response: httpx.Response, status: int) -> str:
    assert response.status_code == status, response.text
    return str(response.json()["detail"]["code"])


# The list and its summary ---------------------------------------------------------------------


async def test_the_list_filters_by_protection_and_marks_contained_documents(
    client: httpx.AsyncClient,
) -> None:
    async def names(**params: Any) -> set[str]:
        page = await get(client, "/api/documents", **params)
        return {item["name"] for item in page["items"]}

    assert await names(protection="locked") == {"Geheim.pdf", "Notiz.odt"}
    assert await names(protection="open") == {"Liste.pdf", "Vertrag.docx", "Paket.zip"}
    assert len(await names(protection=["locked", "open"])) == 5
    items = {item["name"]: item for item in (await get(client, "/api/documents"))["items"]}
    assert {name for name, item in items.items() if item["contained"]} == {
        "Bericht.txt",
        "Notiz.txt",
        "inner.zip",
        "Anlage.txt",
        "Plan.txt",
    }
    assert {name: item["protection"] for name, item in items.items() if item["protection"]} == {
        "Liste.pdf": "open",
        "Vertrag.docx": "open",
        "Paket.zip": "open",
        "Geheim.pdf": "locked",
        "Notiz.odt": "locked",
    }
    summary = await get(client, "/api/documents/summary")
    assert summary["protection"] == {"locked": 2, "open": 3}
    assert summary["total"] == len(items)
    locked = await get(client, "/api/documents/summary", protection="locked")
    assert (locked["total"], locked["protection"]) == (2, {"locked": 2, "open": 0})


# The document page ----------------------------------------------------------------------------


async def test_the_page_of_a_locked_document(
    client: httpx.AsyncClient, doc: dict[str, int]
) -> None:
    geheim = await get(client, f"/api/documents/{doc['Geheim.pdf']}")
    assert (geheim["protection"], geheim["password_trial"], geheim["password_tries"]) == (
        "locked",
        True,
        3,
    )
    assert geheim["password_tried_at"] is not None
    assert (geheim["password"], geheim["preview"], geheim["text_status"]) == (
        None,
        None,
        "encrypted",
    )
    assert (geheim["members"], geheim["containers"]) == (None, [])
    # ODF is detected, not opened (D239)
    notiz = await get(client, f"/api/documents/{doc['Notiz.odt']}")
    assert (notiz["protection"], notiz["password_trial"], notiz["preview"]) == (
        "locked",
        False,
        None,
    )


async def test_the_page_of_an_opened_document_says_where_its_password_stands(
    client: httpx.AsyncClient, doc: dict[str, int], mail: dict[int, int]
) -> None:
    liste = await get(client, f"/api/documents/{doc['Liste.pdf']}")
    assert (liste["protection"], liste["preview"], liste["text_status"]) == ("open", "pdf", "text")
    password = liste["password"]
    assert (password["value"], password["tier"], password["found_by"]) == (
        LISTE_PASSWORD,
        "thread",
        None,
    )
    finding = password["finding"]
    assert finding["context"] == f"Das Kennwort lautet: {LISTE_PASSWORD}"
    assert (finding["mail"]["id"], finding["mail"]["subject"]) == (mail[1], "Re: Spendenliste")
    assert finding["mail"]["sender"]["email"] == "bert@b.example"
    assert [(p["email"], p["name"]) for p in finding["recipients"]] == [
        ("anna@a.example", "Anna Adler")
    ]
    assert (finding["document"], finding["editor"]) == (None, None)

    vertrag = await get(client, f"/api/documents/{doc['Vertrag.docx']}")
    assert (vertrag["preview"], vertrag["password"]["value"], vertrag["password"]["tier"]) == (
        "html",
        VERTRAG_PASSWORD,
        "mail",
    )
    assert vertrag["password"]["finding"]["mail"]["id"] == mail[2]
    assert [p["email"] for p in vertrag["password"]["finding"]["recipients"]] == ["carl@c.example"]
    text = await get(client, f"/api/documents/{doc['Liste.pdf']}/text")
    assert text["text"] == "\n\n".join(LISTE_TEXT)


async def test_the_pages_of_containers_and_their_members(
    client: httpx.AsyncClient, doc: dict[str, int]
) -> None:
    akten = await get(client, f"/api/documents/{doc['Akten.zip']}")
    assert (akten["members"]["status"], akten["members"]["error"]) == ("done", None)
    entries = akten["members"]["entries"]
    assert [
        (e["position"], e["path"], e["status"], e["document_id"], e["kind"]) for e in entries
    ] == [
        (0, "Bericht.txt", "document", doc["Bericht.txt"], "text"),
        (1, "Ordner/Notiz.txt", "document", doc["Notiz.txt"], "text"),
        (2, "inner.zip", "document", doc["inner.zip"], "archive"),
    ]
    inner = await get(client, f"/api/documents/{doc['inner.zip']}")
    sizes = [len(BERICHT), len(AKTEN["Ordner/Notiz.txt"]), inner["size"]]
    assert [e["size"] for e in entries] == sizes
    assert (akten["containers"], akten["password_trial"], akten["protection"]) == ([], True, None)
    notiz = await get(client, f"/api/documents/{doc['Notiz.txt']}")
    assert notiz["containers"] == [
        {"document_id": doc["Akten.zip"], "name": "Akten.zip", "path": "Ordner/Notiz.txt"}
    ]
    assert notiz["members"] is None
    assert inner["members"] == {"status": "too_deep", "error": None, "entries": []}
    assert [c["name"] for c in inner["containers"]] == ["Akten.zip"]
    # opened with its password, unpacked by the second run
    paket = await get(client, f"/api/documents/{doc['Paket.zip']}")
    assert (paket["protection"], paket["password"]["tier"], paket["password"]["value"]) == (
        "open",
        "contacts",
        PAKET_PASSWORD,
    )
    [entry] = paket["members"]["entries"]
    assert (entry["path"], entry["status"], entry["document_id"], entry["text_status"]) == (
        "Plan.txt",
        "document",
        doc["Plan.txt"],
        "text",
    )
    eml = await get(client, f"/api/documents/{doc['Weitergeleitet.eml']}")
    assert [e["path"] for e in eml["members"]["entries"]] == ["Anlage.txt"]


# The mail detail and the signals --------------------------------------------------------------


async def test_the_mail_detail_nests_the_members_under_their_container(
    client: httpx.AsyncClient, doc: dict[str, int], mail: dict[int, int]
) -> None:
    def tree(attachments: list[dict[str, Any]]) -> list[Any]:
        return [
            (a["filename"], a["path"], a["protection"], a["members_status"], tree(a["members"]))
            for a in attachments
        ]

    akten = await get(client, f"/api/mails/{mail[4]}")
    assert tree(akten["attachments"]) == [
        (
            "Akten.zip",
            None,
            None,
            "done",
            [
                ("Bericht.txt", "Bericht.txt", None, None, []),
                ("Notiz.txt", "Ordner/Notiz.txt", None, None, []),
                ("inner.zip", "inner.zip", None, "too_deep", []),
            ],
        )
    ]
    [bericht] = [m for m in akten["attachments"][0]["members"] if m["filename"] == "Bericht.txt"]
    assert (bericht["document_id"], bericht["text_status"]) == (doc["Bericht.txt"], "text")
    forwarded = await get(client, f"/api/mails/{mail[5]}")
    assert tree(forwarded["attachments"]) == [
        ("Weitergeleitet.eml", None, None, "done", [("Anlage.txt", "Anlage.txt", None, None, [])])
    ]
    paket = await get(client, f"/api/mails/{mail[6]}")
    assert tree(paket["attachments"]) == [
        ("Paket.zip", None, "open", "done", [("Plan.txt", "Plan.txt", None, None, [])])
    ]
    vorstand = await get(client, f"/api/mails/{mail[3]}")
    assert [(a["filename"], a["protection"], a["preview"]) for a in vorstand["attachments"]] == [
        ("Geheim.pdf", "locked", None),
        ("Notiz.odt", "locked", None),
    ]


async def test_the_signal_reasons_name_their_documents(
    client: httpx.AsyncClient, mail: dict[int, int]
) -> None:
    async def reasons(index: int) -> dict[str, list[str]]:
        found = await get(client, f"/api/mails/{mail[index]}/signals")
        return {
            s["key"]: sorted(d["name"] for d in s["documents"])  # by id, which the import sets
            for s in found["signals"]
            if s["key"] in ("encrypted_attachment", "password_separate")
        }

    assert await reasons(0) == {"encrypted_attachment": ["Liste.pdf"]}
    # the password stands in another mail than the document it opened (D238)
    assert await reasons(1) == {"password_separate": ["Liste.pdf"]}
    assert await reasons(2) == {"encrypted_attachment": ["Vertrag.docx"]}  # in the same mail
    assert await reasons(3) == {"encrypted_attachment": ["Geheim.pdf", "Notiz.odt"]}
    assert await reasons(6) == {"encrypted_attachment": ["Paket.zip"]}
    assert await reasons(7) == {"password_separate": ["Paket.zip"]}
    assert await reasons(4) == {}


# Passwords typed in ---------------------------------------------------------------------------


async def test_a_password_typed_in_for_one_document(
    mutable_client: httpx.AsyncClient, mutable_url: str, doc: dict[str, int]
) -> None:
    def post(document_id: int, password: str) -> Any:
        return mutable_client.post(
            f"/api/documents/{document_id}/password", json={"password": password}, headers=EDITOR
        )

    assert error(await post(10**9, "x"), 404) == "not_found"
    for name in ("Liste.pdf", "Bericht.txt", "Notiz.odt"):  # open, not protected, ODF
        assert error(await post(doc[name], "x"), 409) == "not_locked", name
    for blank in ("", "   "):
        assert (await post(doc["Geheim.pdf"], blank)).status_code == 422
    # a wrong one is tried, and kept for the documents found later (tier manual)
    response = await post(doc["Geheim.pdf"], "Falsch-9")
    assert response.status_code == 200, response.text
    assert response.json() == {"tried": 1, "opened": [], "errors": 0}
    geheim = await get(mutable_client, f"/api/documents/{doc['Geheim.pdf']}")
    assert (geheim["protection"], geheim["password_tries"]) == ("locked", 4)
    [kept] = await fetch(
        mutable_url,
        "SELECT f.mail_id, f.document_id, f.context, f.editor FROM password_finding f "
        "JOIN password pw ON pw.id = f.password_id WHERE pw.value = 'Falsch-9'",
    )
    assert tuple(kept) == (None, None, "", "Aaron")
    # the right one, white space around it left out
    response = await post(doc["Geheim.pdf"], f" {GEHEIM_PASSWORD}\n")
    assert response.json() == {"tried": 1, "opened": [doc["Geheim.pdf"]], "errors": 0}
    geheim = await get(mutable_client, f"/api/documents/{doc['Geheim.pdf']}")
    assert (geheim["protection"], geheim["text_status"], geheim["password_tries"]) == (
        "open",
        "text",
        5,
    )
    password = geheim["password"]
    assert (password["value"], password["tier"], password["found_by"]) == (
        GEHEIM_PASSWORD,
        "typed",
        "Aaron",
    )
    assert (password["finding"]["editor"], password["finding"]["mail"]) == ("Aaron", None)
    text = await get(mutable_client, f"/api/documents/{doc['Geheim.pdf']}/text")
    assert text["text"] == "Nur für den Vorstand"
    assert error(await post(doc["Geheim.pdf"], GEHEIM_PASSWORD), 409) == "not_locked"


async def test_a_password_typed_in_for_every_locked_document(
    mutable_client: httpx.AsyncClient, mutable_url: str, doc: dict[str, int]
) -> None:
    await execute(
        mutable_url,
        "DELETE FROM document_password WHERE document_id = :id",
        "UPDATE document SET protection = 'locked' WHERE id = :id",
        id=doc["Liste.pdf"],
    )

    async def post(password: str) -> Any:
        response = await mutable_client.post(
            "/api/documents/passwords", json={"password": password}, headers=EDITOR
        )
        assert response.status_code == 200, response.text
        return response.json()

    # Liste.pdf and Geheim.pdf; not Notiz.odt (D239)
    assert await post("Falsch-9") == {"tried": 2, "opened": [], "errors": 0}
    assert await post(LISTE_PASSWORD) == {"tried": 2, "opened": [doc["Liste.pdf"]], "errors": 0}
    liste = await get(mutable_client, f"/api/documents/{doc['Liste.pdf']}")
    assert (liste["password"]["tier"], liste["password"]["found_by"]) == ("typed", "Aaron")
    assert await post(GEHEIM_PASSWORD) == {"tried": 1, "opened": [doc["Geheim.pdf"]], "errors": 0}
    assert await post(GEHEIM_PASSWORD) == {"tried": 0, "opened": [], "errors": 0}
    blank = await mutable_client.post("/api/documents/passwords", json={"password": " "})
    assert blank.status_code == 422


# Decrypted downloads and previews -------------------------------------------------------------


async def test_an_opened_document_is_downloaded_decrypted_on_request(
    client: httpx.AsyncClient, doc: dict[str, int]
) -> None:
    async def content(name: str, **params: Any) -> httpx.Response:
        page = await get(client, f"/api/documents/{doc[name]}")
        return await client.get(f"/api/attachments/{page['attachment_id']}/content", params=params)

    stored = await content("Liste.pdf")
    assert PdfReader(io.BytesIO(stored.content)).is_encrypted  # as it was sent
    plain = await content("Liste.pdf", decrypted="true")
    assert plain.status_code == 200, plain.text
    assert plain.headers["content-disposition"] == 'attachment; filename="Liste.pdf"'
    reader = PdfReader(io.BytesIO(plain.content))
    assert not reader.is_encrypted
    assert [page.extract_text().strip() for page in reader.pages] == list(LISTE_TEXT)
    docx = await content("Vertrag.docx", decrypted="true")
    with zipfile.ZipFile(io.BytesIO(docx.content)) as package:
        assert VERTRAG_TEXT in package.read("word/document.xml").decode()
    # a member of an opened container: read through it with its password
    assert (await content("Plan.txt")).content == PLAN
    assert error(await content("Geheim.pdf", decrypted="true"), 409) == "not_locked"
    assert error(await content("Bericht.txt", decrypted="true"), 409) == "not_locked"


async def test_a_wrong_stored_password_fails_to_decrypt(
    mutable_client: httpx.AsyncClient, mutable_url: str, doc: dict[str, int]
) -> None:
    await execute(
        mutable_url,
        "UPDATE document_password SET password_id = "
        "(SELECT id FROM password WHERE value = :wrong) WHERE document_id = :id",
        wrong=VERTRAG_PASSWORD,
        id=doc["Liste.pdf"],
    )
    page = await get(mutable_client, f"/api/documents/{doc['Liste.pdf']}")
    response = await mutable_client.get(
        f"/api/attachments/{page['attachment_id']}/content", params={"decrypted": "true"}
    )
    assert error(response, 422) == "decrypt_failed"
    assert response.json()["detail"]["message"] == "the password does not open the document"


async def test_the_html_preview_of_an_opened_docx(
    client: httpx.AsyncClient, doc: dict[str, int]
) -> None:
    page = await get(client, f"/api/documents/{doc['Vertrag.docx']}")
    response = await client.get(f"/api/attachments/{page['attachment_id']}/html")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert VERTRAG_TEXT in response.text
