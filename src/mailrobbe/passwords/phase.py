"""The passwords step of an import (D234 to D236): find passwords in the archive and open the
protected documents with them. Nothing is read from the MBOX files beyond the locked documents.

The step runs only when a locked document waits (encrypted PDF, OOXML or ODF, or a ZIP or 7z
with protected entries). Then:

    mark        every document the text extraction found encrypted is set protection locked, so
                the UI and the figures see one "locked" for every format (D233).
    findings    the subject and body text of every mail not scanned yet and the extracted text
                of every document extracted since the last scan are scanned for candidates
                (passwords.candidates): `password` keeps each distinct value once,
                `password_finding` where it stands, with the line around it (D208). How far the
                scan got is kept in global_stats 'passwords' (SCAN_KEY); a new
                CANDIDATES_VERSION scans everything again.
    try         each locked document that trial_format can open (PDF, OOXML, ZIP, 7z; ODF is
                detected, not opened, D239) is offered the candidates in the order the plan sets,
                nearest first (passwords.order), up to password_seconds per document and run
                (D235), `workers` documents at a time; the try runs in a process of its own
                (attachments.protected.try_passwords). password_tried_until then holds the
                highest password_finding id when it was offered, so a later run offers only
                passwords found since, at any new place; what the time budget cut off of the far
                tiers is not offered again.
    open        a hit stores document_password with where the password was found and its tier
                (passwords.store.store_opened, D236) and sets the document open, with the text
                the child extracted with the password; its metadata is read again by the
                metadata step that follows. An opened container is unpacked by the next run's
                archives step. The decrypted bytes are never stored (D209).

The step waits (`waiting`) while a document is locked and something is new: mails or document
texts not scanned yet, a newly encrypted document, or a password a locked document was not
offered. A stop (D46) ends it between two documents; the next run tries the rest. Passwords
typed in by hand go the same way through the API (api.passwords), tier typed or manual.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.attachments.content import AttachmentChanged, document_sources, read_attachment
from mailrobbe.attachments.extract import ExtractionLimits
from mailrobbe.attachments.protected import trial_format, try_passwords
from mailrobbe.config import Settings
from mailrobbe.db.models import GlobalStats
from mailrobbe.jobrun import Step, describe
from mailrobbe.passwords.candidates import CANDIDATES_VERSION, candidates
from mailrobbe.passwords.order import ordered_candidates
from mailrobbe.passwords.store import Finding, Opener, record_tried, store_findings, store_opened

log = logging.getLogger(__name__)

MAIL_PAGE = 5000  # mails scanned for candidates per query
DOC_PAGE = 2000

SCAN_KEY = "passwords"  # global_stats: how far the findings scan got

# A document is locked when its text extraction found it encrypted, or an archives step marked it
# (protection locked); a container whose format is not unpacked is left alone.
_LOCKED_WHERE = """
    (protection = 'locked' OR text_status = 'encrypted')
    AND members_status IS DISTINCT FROM 'unsupported'
"""
_LOCKED = text(f"SELECT count(*) FROM document WHERE {_LOCKED_WHERE}")
_NEW = text(f"""
    SELECT EXISTS (SELECT 1 FROM mail WHERE id > :mail_until)
        OR EXISTS (
            SELECT 1 FROM document WHERE extracted_text IS NOT NULL
            AND extracted_at > coalesce(CAST(:scanned_at AS timestamptz), '-infinity'))
        OR EXISTS (
            SELECT 1 FROM document WHERE text_status = 'encrypted' AND protection IS NULL)
        OR EXISTS (
            SELECT 1 FROM document WHERE {_LOCKED_WHERE}
            AND password_tried_until < (SELECT coalesce(max(id), 0) FROM password_finding))
""")
_MARK_LOCKED = text(
    "UPDATE document SET protection = 'locked' "
    "WHERE text_status = 'encrypted' AND protection IS NULL"
)


@dataclass(frozen=True, slots=True)
class _Scan:
    """How far the findings scan got (global_stats 'passwords')."""

    mail_until: int = 0  # every mail up to this id was scanned
    scanned_at: datetime | None = None  # every document text extracted before this was scanned

    def to_json(self) -> dict[str, Any]:
        return {
            "version": CANDIDATES_VERSION,
            "mail_until": self.mail_until,
            "scanned_at": None if self.scanned_at is None else self.scanned_at.isoformat(),
        }


async def _read_scan(session: AsyncSession) -> _Scan:
    value = await session.scalar(select(GlobalStats.value).where(GlobalStats.key == SCAN_KEY))
    if not isinstance(value, dict) or value.get("version") != CANDIDATES_VERSION:
        return _Scan()
    at = value.get("scanned_at")
    return _Scan(
        int(value.get("mail_until") or 0), None if at is None else datetime.fromisoformat(at)
    )


async def _write_scan(session: AsyncSession, scan: _Scan) -> None:
    statement = postgresql.insert(GlobalStats).values(key=SCAN_KEY, value=scan.to_json())
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[GlobalStats.key],
            set_={"value": statement.excluded.value, "updated_at": func.now()},
        )
    )


async def waiting(session: AsyncSession) -> int:
    """The locked documents when something new could open one, else 0 (skips the step)."""
    locked = int((await session.execute(_LOCKED)).scalar_one())
    if not locked:
        return 0
    scan = await _read_scan(session)
    new = await session.scalar(_NEW, {"mail_until": scan.mail_until, "scanned_at": scan.scanned_at})
    return locked if new else 0


@dataclass(frozen=True, slots=True)
class PasswordsResult:
    locked: int  # locked documents at the start
    opened: int  # documents opened by this run
    found: int  # distinct passwords found in the new texts
    seconds: float


async def run_passwords(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    mbox_dir: Path,
    workers: int,
    stop: asyncio.Event,
    step: Step,
) -> PasswordsResult:
    """The whole step; see the module docstring."""
    started = time.monotonic()
    async with sessionmaker() as session, session.begin():
        await session.execute(_MARK_LOCKED)
    found = await _collect_findings(sessionmaker, stop)
    opened, locked = await _try_all(sessionmaker, settings, mbox_dir, workers, stop, step)
    seconds = time.monotonic() - started
    log.info(
        "%s: %d of %d locked documents opened, %d passwords found, %.1f s",
        "passwords stopped" if stop.is_set() else "passwords done",
        opened,
        locked,
        found,
        seconds,
    )
    return PasswordsResult(locked, opened, found, seconds)


# Findings --------------------------------------------------------------------------------------


async def _collect_findings(
    sessionmaker: async_sessionmaker[AsyncSession], stop: asyncio.Event
) -> int:
    """Scan the new mails and document texts for candidates and store them (D234); the
    passwords found."""
    async with sessionmaker() as session:
        scan = await _read_scan(session)
        started = (await session.execute(text("SELECT clock_timestamp()"))).scalar_one()
    findings: list[Finding] = []
    mail_until = scan.mail_until
    async with sessionmaker() as session:
        result = await session.stream(
            text(
                "SELECT id, subject, body_text FROM mail WHERE id > :after ORDER BY id"
            ).execution_options(yield_per=MAIL_PAGE),
            {"after": scan.mail_until},
        )
        async for row in result:
            if stop.is_set():
                break
            whole = f"{row.subject or ''}\n{row.body_text or ''}"
            findings.extend(Finding(c.value, c.context, mail_id=row.id) for c in candidates(whole))
            mail_until = row.id
    scanned_at = scan.scanned_at
    if not stop.is_set():
        async with sessionmaker() as session:
            result = await session.stream(
                text(
                    "SELECT id, extracted_text FROM document WHERE extracted_text IS NOT NULL "
                    "AND extracted_at > coalesce(CAST(:at AS timestamptz), '-infinity')"
                ).execution_options(yield_per=DOC_PAGE),
                {"at": scan.scanned_at},
            )
            async for row in result:
                if stop.is_set():
                    break
                findings.extend(
                    Finding(c.value, c.context, document_id=row.id)
                    for c in candidates(row.extracted_text)
                )
        if not stop.is_set():
            scanned_at = started
    async with sessionmaker() as session, session.begin():
        ids = await store_findings(session, findings)
        await _write_scan(session, _Scan(mail_until, scanned_at))
    return len(ids)


# Trying ----------------------------------------------------------------------------------------


_LAST_FINDING = text("SELECT coalesce(max(id), 0) FROM password_finding")
_LOCKED_DOCS = text(f"""
    SELECT id, name, mime_type, password_tried_until
    FROM document WHERE {_LOCKED_WHERE}
    ORDER BY id
""")


@dataclass(frozen=True, slots=True)
class _LockedDoc:
    id: int
    name: str | None
    mime_type: str
    password_tried_until: int


async def _try_all(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    mbox_dir: Path,
    workers: int,
    stop: asyncio.Event,
    step: Step,
) -> tuple[int, int]:
    """Try every locked document, `workers` at a time; opened and locked documents."""
    async with sessionmaker() as session:
        docs = [
            _LockedDoc(r.id, r.name, r.mime_type, r.password_tried_until)
            for r in await session.execute(_LOCKED_DOCS)
        ]
    limits = ExtractionLimits(
        timeout=settings.attachment_text_timeout, memory=int(settings.attachment_text_memory)
    )
    gate = asyncio.Semaphore(max(1, workers))
    opened = 0

    async def one(doc: _LockedDoc) -> None:
        nonlocal opened
        async with gate:
            if stop.is_set():
                return
            try:
                if await _try_one(sessionmaker, settings, mbox_dir, limits, doc):
                    opened += 1
            except Exception as error:  # one document must never end the step
                log.warning("document %d: trying passwords failed: %s", doc.id, describe(error))
            step.advance()

    await asyncio.gather(*(one(doc) for doc in docs))
    return opened, len(docs)


async def _try_one(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    mbox_dir: Path,
    limits: ExtractionLimits,
    doc: _LockedDoc,
) -> bool:
    async with sessionmaker() as session:
        source = (await document_sources(session, [doc.id])).get(doc.id)
        until = (await session.execute(_LAST_FINDING)).scalar_one()
        offered = await ordered_candidates(session, doc.id, after_id=doc.password_tried_until)
    if source is None or not offered:
        return False
    try:
        data = await asyncio.to_thread(read_attachment, mbox_dir, source)
    except (OSError, AttachmentChanged) as error:
        log.warning("document %d could not be read to open it: %s", doc.id, describe(error))
        return False
    if trial_format(doc.name, doc.mime_type, data) is None:
        # ODF or another format no password opens here (D239): offered, so not offered again
        # until a password turns up at a new place.
        async with sessionmaker() as session, session.begin():
            await record_tried(session, doc.id, until, 0)
        return False
    tried = await try_passwords(
        data,
        doc.name,
        doc.mime_type,
        [c.value for c in offered],
        seconds=settings.password_seconds,
        limits=limits,
    )
    if tried.error is not None:
        log.warning("document %d: trying passwords: %s", doc.id, tried.error)
    async with sessionmaker() as session, session.begin():
        await record_tried(session, doc.id, until, tried.tried)
        if tried.index is None:
            return False
        winner = offered[tried.index]
        opener = Opener(winner.password_id, winner.finding_id, winner.tier)
        await store_opened(session, doc.id, opener, tried.extraction)
    log.info(
        "document %d opened with a password of tier %s (%s)",
        doc.id,
        winner.tier,
        "unpacked by the next run" if tried.extraction is None else tried.extraction.status.value,
    )
    return True
