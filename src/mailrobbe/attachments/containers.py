"""The archives step of an import (D231): the contents of container attachments as documents.

After the finalize and before the text extraction, so the members get their text in the same
run, the step unpacks every container document that waits (ZIP, 7z, an
attached mail) and is not still locked without a password:

    work list   container documents (kind archive or email) with a top-level occurrence (an
                attachment that is itself a MIME part, container_id IS NULL), whose
                members_status is new, unreadable or of an older MEMBERS_VERSION, or locked
                while a password is now known (an opened container, D236). Without the 7-Zip
                command only attached mails are unpacked; ZIP and 7z wait. A container that
                appears only inside another container is too_deep and left as a listing (D231:
                depth 2).
    unpack      each container's bytes are read from one occurrence (content.read_attachment,
                via its own container when it is nested) and listed in a worker process
                (packed.list_members) with the container's password when it has one; a worker
                reads one container at a time, a broken or missing MBOX file makes it unreadable.
    store       document_member holds every entry once per distinct container content; each
                readable entry becomes an attachment row of every mail carrying the container
                (container_id, path), so finalize assigns it a document and the list, the search,
                the entities and the export treat it like any attachment (D231). The container's
                members_status and protection are set (locked when an entry needs a password).
    assign      when any member attachment changed, refresh_documents assigns the new member
                documents and counts them, and document_member.member_id is filled; the text
                extraction and the metadata step that follow treat the new members.

Nothing is read from the MBOX files beyond the containers; a stop (D46) ends it between two
containers, and the next run continues with the containers still waiting.
"""

import asyncio
import logging
import mimetypes
import multiprocessing
import posixpath
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.attachments.content import (
    AttachmentChanged,
    AttachmentSource,
    attachment_source,
    read_attachment,
)
from mailrobbe.attachments.documents import refresh_documents
from mailrobbe.attachments.packed import SEVEN_ZIP, Members, list_members
from mailrobbe.config import Settings
from mailrobbe.db.models import MEMBERS_VERSION
from mailrobbe.enums import DocumentMembersStatus, DocumentMemberStatus
from mailrobbe.jobrun import Step, describe, ignore_interrupts, spawning_workers

log = logging.getLogger(__name__)

MS = DocumentMembersStatus
ES = DocumentMemberStatus
BATCH = 50  # containers stored per transaction


@dataclass(frozen=True, slots=True)
class WaitingContainer:
    document_id: int
    attachment_id: int  # a top-level occurrence to read it from
    filename: str | None
    mime_type: str
    password: str | None  # when the container was opened before (D236)


# A container document with a top-level occurrence (an attachment that is a MIME part), waiting;
# one marked too_deep before waits again once a mail carries it itself.
_WAITING = text("""
    SELECT DISTINCT ON (d.id) d.id AS document_id, a.id AS attachment_id, a.filename, a.mime_type,
        pw.value AS password
    FROM document d
    JOIN attachment a ON a.document_id = d.id AND a.container_id IS NULL
    LEFT JOIN document_password dp ON dp.document_id = d.id
    LEFT JOIN password pw ON pw.id = dp.password_id
    WHERE (d.kind = 'email' OR (d.kind = 'archive' AND :seven_zip))
      AND (
        d.members_status IS NULL
        OR d.members_status IN ('unreadable', 'too_deep')
        OR d.members_version < :version
        OR (d.members_status = 'locked' AND pw.value IS NOT NULL)
      )
    ORDER BY d.id, a.id
""")


async def waiting_containers(session: AsyncSession) -> list[WaitingContainer]:
    rows = await session.execute(_WAITING, {"version": MEMBERS_VERSION, "seven_zip": SEVEN_ZIP})
    await session.commit()
    return [
        WaitingContainer(r.document_id, r.attachment_id, r.filename, r.mime_type, r.password)
        for r in rows
    ]


# Worker side -----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Task:
    container: WaitingContainer
    source: AttachmentSource


@dataclass(frozen=True, slots=True)
class _Result:
    document_id: int
    members: Members | None  # None when the bytes could not be read
    problem: str | None = None


@dataclass(frozen=True, slots=True)
class _State:
    mbox_dir: Path
    max_members: int
    max_size: int


_state: _State | None = None


def _init(state: _State) -> None:
    ignore_interrupts()
    global _state
    _state = state


def _unpack(task: _Task) -> _Result:
    assert _state is not None
    try:
        data = read_attachment(_state.mbox_dir, task.source)
    except (OSError, AttachmentChanged) as error:
        return _Result(task.container.document_id, None, describe(error))
    members = list_members(
        data,
        task.container.filename,
        task.container.mime_type,
        max_members=_state.max_members,
        max_size=_state.max_size,
        password=task.container.password,
    )
    return _Result(task.container.document_id, members)


# Main process ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArchivesResult:
    containers: int  # containers waiting at the start
    unpacked: int  # containers listed (done or locked) by this run
    members: int  # readable member entries found
    seconds: float


async def unpack_containers(
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    mbox_dir: Path,
    waiting: Sequence[WaitingContainer],
    workers: int,
    stop: asyncio.Event,
    step: Step,
) -> ArchivesResult:
    """Unpack the containers and store their members; see the module docstring."""
    started = time.monotonic()
    tasks = await _tasks(sessionmaker, waiting)
    store = _Store(sessionmaker)
    if tasks and not stop.is_set():
        log.info("unpacking %d containers with %d workers", len(tasks), min(workers, len(tasks)))
        state = _State(mbox_dir, settings.archive_max_members, int(settings.archive_max_size))
        await _run(tasks, min(workers, len(tasks)), state, store, step, stop)
    await store.flush()
    if store.changed:
        async with sessionmaker() as session, session.begin():
            await refresh_documents(session)
            await _fill_member_ids(session)
            await session.execute(_TOO_DEEP, {"version": MEMBERS_VERSION})
    seconds = time.monotonic() - started
    log.info(
        "%s: %d of %d containers unpacked, %d members, %.1f s",
        "archives stopped" if stop.is_set() else "archives done",
        store.unpacked,
        len(waiting),
        store.members,
        seconds,
    )
    return ArchivesResult(len(waiting), store.unpacked, store.members, seconds)


async def _tasks(
    sessionmaker: async_sessionmaker[AsyncSession], waiting: Sequence[WaitingContainer]
) -> list[_Task]:
    tasks: list[_Task] = []
    async with sessionmaker() as session:
        for container in waiting:
            source = await attachment_source(session, container.attachment_id)
            if source is not None:
                tasks.append(_Task(container, source))
        await session.commit()
    return tasks


async def _run(
    tasks: list[_Task],
    count: int,
    state: _State,
    store: "_Store",
    step: Step,
    stop: asyncio.Event,
) -> None:
    context = multiprocessing.get_context("spawn")
    loop = asyncio.get_running_loop()
    queue = list(reversed(tasks))
    pool = _new_pool(count, state, context)
    try:
        running: dict[asyncio.Future[_Result], _Task] = {}
        while (queue or running) and not stop.is_set():
            while queue and len(running) < count:
                task = queue.pop()
                with spawning_workers():
                    running[loop.run_in_executor(pool, _unpack, task)] = task
            done, _ = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
            broke = False
            for future in done:
                task = running.pop(future)
                try:
                    await store.add(future.result())
                except BrokenProcessPool:
                    await store.add(_Result(task.container.document_id, None, "worker died"))
                    broke = True
                except Exception as error:  # a result that never came back
                    await store.add(_Result(task.container.document_id, None, describe(error)))
                step.advance()
            if broke and not stop.is_set():
                pool.shutdown(wait=False, cancel_futures=True)
                pool = _new_pool(count, state, context)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def _new_pool(
    count: int, state: _State, context: "multiprocessing.context.BaseContext"
) -> ProcessPoolExecutor:
    return ProcessPoolExecutor(count, mp_context=context, initializer=_init, initargs=(state,))


class _Store:
    """Stores each container's members in batches, one transaction each."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker
        self._results: list[_Result] = []
        self.unpacked = 0
        self.members = 0
        self.changed = False

    async def add(self, result: _Result) -> None:
        self._results.append(result)
        if len(self._results) >= BATCH:
            await self.flush()

    async def flush(self) -> None:
        results, self._results = self._results, []
        if not results:
            return
        async with self._sessionmaker() as session, session.begin():
            for result in results:
                await self._store_one(session, result)

    async def _store_one(self, session: AsyncSession, result: _Result) -> None:
        if result.members is None:
            await session.execute(
                text(
                    "UPDATE document SET members_status = 'unreadable', members_error = :error, "
                    "members_version = :version WHERE id = :id"
                ),
                {"id": result.document_id, "error": result.problem, "version": MEMBERS_VERSION},
            )
            return
        members = result.members
        await session.execute(
            text("DELETE FROM document_member WHERE container_id = :id"),
            {"id": result.document_id},
        )
        readable = [m for m in members.members if m.status == ES.DOCUMENT]
        rows = [
            {
                "container_id": result.document_id,
                "position": index,
                "path": member.path,
                "size_bytes": member.size_bytes,
                "status": member.status.value,
                "error": member.error,
            }
            for index, member in enumerate(members.members)
        ]
        if rows:
            await session.execute(
                text(
                    "INSERT INTO document_member "
                    "(container_id, position, path, size_bytes, status, error) "
                    "VALUES (:container_id, :position, :path, :size_bytes, "
                    "CAST(:status AS document_member_status), :error)"
                ),
                rows,
            )
        protection = _protection(members)
        await session.execute(
            text(
                "UPDATE document SET members_status = CAST(:status AS document_members_status), "
                "members_version = :version, members_error = :error, "
                "protection = coalesce(CAST(:protection AS document_protection), protection) "
                "WHERE id = :id"
            ),
            {
                "id": result.document_id,
                "status": members.status.value,
                "version": MEMBERS_VERSION,
                "error": members.error,
                "protection": protection,
            },
        )
        await self._materialize(session, result.document_id, members)
        self.unpacked += 1
        self.members += len(readable)

    async def _materialize(self, session: AsyncSession, cid: int, members: Members) -> None:
        """Replace the member attachments of every mail carrying this container."""
        carriers = (
            await session.execute(
                text(
                    "SELECT id, mail_id, mime_type FROM attachment "
                    "WHERE document_id = :cid AND container_id IS NULL"
                ),
                {"cid": cid},
            )
        ).all()
        await session.execute(
            text(
                "DELETE FROM attachment WHERE container_id IN "
                "(SELECT id FROM attachment WHERE document_id = :cid AND container_id IS NULL)"
            ),
            {"cid": cid},
        )
        readable = [
            (index, member)
            for index, member in enumerate(members.members)
            if member.status == ES.DOCUMENT and member.sha256 is not None
        ]
        if not (carriers and readable):
            if carriers:  # a container that now has no readable member: its documents went
                self.changed = True
            return
        rows = [
            {
                "mail_id": carrier.mail_id,
                "container_id": carrier.id,
                "position": index,
                "path": member.path,
                "filename": posixpath.basename(member.path) or member.path,
                "sha256": member.sha256,
                "size_bytes": member.size_bytes or 0,
                "mime_type": _member_mime(member.path),
            }
            for carrier in carriers
            for index, member in readable
        ]
        await session.execute(
            text(
                "INSERT INTO attachment "
                "(mail_id, container_id, position, path, filename, sha256, size_bytes, mime_type) "
                "VALUES (:mail_id, :container_id, :position, :path, :filename, :sha256, "
                ":size_bytes, :mime_type)"
            ),
            rows,
        )
        self.changed = True


def _protection(members: Members) -> str | None:
    """Locked when an entry needs a password; None leaves it (an opened container stays open)."""
    return "locked" if members.status == MS.LOCKED else None


def _member_mime(path: str) -> str:
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


# Containers found only inside another container (D231: depth 2) are listed there, not unpacked.
_TOO_DEEP = text("""
    UPDATE document d SET members_status = 'too_deep', members_version = :version
    WHERE d.kind IN ('archive', 'email') AND d.members_status IS NULL
      AND NOT EXISTS (
        SELECT 1 FROM attachment a WHERE a.document_id = d.id AND a.container_id IS NULL)
""")

# document_member.member_id: the member document assigned to the attachment with that path.
_FILL = text("""
    UPDATE document_member dm SET member_id = a.document_id
    FROM attachment a JOIN attachment c ON c.id = a.container_id
    WHERE c.document_id = dm.container_id AND a.path = dm.path
      AND dm.status = 'document' AND a.document_id IS NOT NULL
      AND dm.member_id IS DISTINCT FROM a.document_id
""")


async def _fill_member_ids(session: AsyncSession) -> None:
    await session.execute(_FILL)
