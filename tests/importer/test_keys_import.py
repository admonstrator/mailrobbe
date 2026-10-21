"""The import checks new mails against the keys of deleted selectors already found (D101)."""

from pathlib import Path

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import migrate
from mailrobbe.config import Settings
from mailrobbe.dkim.keys.store import Evidence, save_evidence, save_lookup
from mailrobbe.enums import KeyLookupSource, KeyOrigin, LookupOutcome
from mailrobbe.importer.cli import run_import
from tests.dkim.samples import INTERNAL, sample_mail
from tests.dkim.test_verify import NAME, record, sign
from tests.importer.doubles import PIPELINE, write_mbox


@pytest.fixture
def database_url(empty_database_url: str) -> str:
    migrate.upgrade("head", empty_database_url)
    return empty_database_url


@pytest.mark.db
async def test_a_new_mail_is_checked_against_a_candidate_key(
    database_url: str, tmp_path: Path
) -> None:
    engine = create_async_engine(database_url, poolclass=pool.NullPool)
    try:
        async with engine.begin() as db:  # a key an earlier run rebuilt from signatures
            lookup = await save_lookup(
                db, KeyLookupSource.RECONSTRUCTION, NAME, LookupOutcome.FOUND, name=NAME
            )
            evidence = Evidence(KeyOrigin.RECONSTRUCTED)
            key_id = await save_evidence(db, lookup, NAME, record("rsa1024"), evidence)
        # The selector is gone from DNS (a reserved TLD: nothing is asked). The first mail is
        # signed with the key found, the second with another key under the same name.
        mbox_dir = tmp_path / "mbox"
        mbox_dir.mkdir()
        mails = [
            sign(sample_mail(index, "plain_8bit", sender=INTERNAL).raw, kind)
            for index, kind in ((1, "rsa1024"), (2, "rsa2048"))
        ]
        write_mbox(mbox_dir / "a.mbox", mails)
        settings = Settings(database_url=database_url)
        assert await run_import(settings, mbox_dir, 1, pipeline=PIPELINE) == 0
        async with engine.connect() as db:
            rows = await db.execute(
                text(
                    "SELECT m.dkim_status, r.status, r.reason, r.key_id, r.key_origin, r.key_bits"
                    " FROM mail m JOIN dkim_result r ON r.mail_id = m.id ORDER BY m.byte_offset"
                )
            )
            assert [tuple(row) for row in rows] == [
                ("consistent", "consistent", None, key_id, "reconstructed", 1024),
                ("no_key", "no_key", "key_mismatch", None, None, None),
            ]
    finally:
        await engine.dispose()
