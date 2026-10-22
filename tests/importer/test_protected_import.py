"""End to end (milestone 19): `mailrobbe import` of two MBOX files with a protected PDF whose
password stands in a reply of the same thread, and an AES ZIP whose password stands in a later
mail between the same persons. The first run opens both, the second unpacks the ZIP and reads
its member, the third has nothing left to do in the archives and passwords steps."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from mailrobbe import migrate
from mailrobbe.jobs import ImportProgress
from tests.conftest import _temporary_database
from tests.importer.doubles import write_mbox
from tests.passwords.samples import (
    ANNA,
    BERT,
    LISTE_PASSWORD,
    LISTE_TEXT,
    PAKET_PASSWORD,
    PDF_MIME,
    PLAN,
    ZIP_MIME,
    documents,
    fetch,
    import_archive,
    mail,
    needs_seven_zip,
    protected_pdf,
    seven_zip,
)

pytestmark = [pytest.mark.db, pytest.mark.slow, needs_seven_zip]


@pytest.fixture
def url(database_server_url: str) -> Iterator[str]:
    with _temporary_database(database_server_url) as created:
        migrate.upgrade("head", created)
        yield created


def write_files(mbox_dir: Path) -> Path:
    liste = protected_pdf(*LISTE_TEXT, password=LISTE_PASSWORD)
    paket = seven_zip(
        {"Plan.txt": PLAN}, "Paket.zip", "-tzip", f"-p{PAKET_PASSWORD}", "-mem=AES256"
    )
    files = {
        "liste.mbox": [
            mail(0, ANNA, BERT, "Liste", "Anbei.\n", [("Liste.pdf", PDF_MIME, liste)]),
            mail(1, BERT, ANNA, "Re: Liste", f"Kennwort: {LISTE_PASSWORD}\n", reply_to=0),
        ],
        "paket.mbox": [
            mail(5, ANNA, BERT, "Paket", "Das Paket.\n", [("Paket.zip", ZIP_MIME, paket)]),
            mail(9, BERT, ANNA, "Zugang", f"Das Passwort lautet {PAKET_PASSWORD}\n"),
        ],
    }
    mbox_dir.mkdir()
    for name, messages in files.items():
        write_mbox(mbox_dir / name, [message.as_bytes() for message in messages])
    return mbox_dir


async def run(url: str, mbox_dir: Path) -> dict[str, str]:
    """One import run; the status of each of its steps."""
    await asyncio.to_thread(import_archive, url, mbox_dir)
    [job] = await fetch(url, "SELECT progress FROM job ORDER BY id DESC LIMIT 1")
    return {step.key: step.status for step in ImportProgress.model_validate(job.progress).steps}


def opened(doc: Any) -> tuple[Any, ...]:
    return (doc.protection, doc.tier, doc.members_status, doc.text_status)


async def test_three_runs_open_unpack_and_leave_alone(url: str, tmp_path: Path) -> None:
    mbox_dir = write_files(tmp_path / "mbox")
    steps = await run(url, mbox_dir)
    assert (steps["archives"], steps["passwords"]) == ("done", "done")
    docs = await documents(url)
    assert opened(docs["Liste.pdf"]) == ("open", "thread", None, "text")
    assert docs["Liste.pdf"].extracted_text == "\n\n".join(LISTE_TEXT)
    # opened after the archives step listed it locked: unpacked by the next run
    assert opened(docs["Paket.zip"]) == ("open", "contacts", None, "text")
    assert "Plan.txt" not in docs

    steps = await run(url, mbox_dir)
    assert (steps["archives"], steps["attachments"], steps["passwords"]) == (
        "done",
        "done",
        "skipped",  # nothing locked
    )
    docs = await documents(url)
    assert docs["Paket.zip"].members_status == "done"
    plan = docs["Plan.txt"]
    assert (plan.text_status, plan.extracted_text, plan.protection) == (
        "text",
        "Geheimer Plan",
        None,
    )
    [member] = await fetch(
        url,
        "SELECT member_id FROM document_member WHERE container_id = :id",
        id=docs["Paket.zip"].id,
    )
    assert member.member_id == plan.id

    steps = await run(url, mbox_dir)
    assert (steps["archives"], steps["passwords"]) == ("skipped", "skipped")
    assert await documents(url) == docs
