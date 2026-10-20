"""Checking imported mails again from their MBOX files (`mailrobbe dkim`, SPEC 3.4, D13).

The main process selects the mails in file order, with keyset pagination on (mbox_file_id,
byte_offset), so a run over 400,000 mails never holds more than one page and every file is read
front to back. Pages go as chunks to a pool of worker processes; each worker reads the messages
with mbox.read_message, makes sure they are still the bytes that were imported (raw_sha256) and
checks them with its own DkimChecker, built once from the dns_cache rows the main process
loaded. The main process writes every finished chunk (save_verdicts, upsert_dns_cache) and
commits it, so an interrupted run keeps what it finished.

A mail whose file is missing, whose record cannot be read or whose bytes changed is skipped:
counted by kind and logged, never written, and the run goes on.

Workers are started with "spawn", like the generator's (generator/pipeline.py); jobs == 1 runs
the same code in the main process.
"""

import asyncio
import functools
import hashlib
import logging
import math
import multiprocessing
import signal
import time
from collections import Counter, deque
from collections.abc import AsyncIterator, Callable, Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import ColumnElement, false, func, or_, select, true, tuple_
from sqlalchemy.ext.asyncio import AsyncConnection

from mailrobbe.config import Settings
from mailrobbe.db.models import Mail, MboxFile
from mailrobbe.db.session import create_engine
from mailrobbe.dkim import store
from mailrobbe.dkim.checker import DkimChecker
from mailrobbe.dkim.model import DnsAnswer, MailVerdict
from mailrobbe.enums import DkimStatus
from mailrobbe.mbox import read_message

log = logging.getLogger(__name__)

CHUNK = 250  # mails per database page, per worker task and per commit
WINDOW_PER_JOB = 3  # chunks in flight per worker
PROGRESS_SECONDS = 5.0

# D13: the mails not checked yet, and those whose key was missing or did not answer in time.
DEFAULT_STATUSES: frozenset[DkimStatus | None] = frozenset(
    {None, DkimStatus.NO_KEY, DkimStatus.TEMP_ERROR}
)
UNCHECKED = "unchecked"  # how a NULL mail.dkim_status appears in the summary


class Skip(StrEnum):
    """Why a selected mail was not checked."""

    MISSING_FILE = "missing_file"  # its MBOX file is not there
    UNREADABLE = "unreadable"  # read error, or no MBOX record at the stored offset
    HASH_MISMATCH = "hash_mismatch"  # the bytes differ from the imported ones (raw_sha256)


@dataclass(slots=True)
class RecheckSummary:
    """Printed as JSON by `mailrobbe dkim`."""

    selected: int  # mails matching the selection when the run started
    checked: int
    skipped: dict[str, int]  # Skip value -> mails
    statuses: dict[str, int]  # DkimStatus value -> checked mails with that status now
    transitions: dict[str, int]  # "no_key -> pass" -> checked mails whose status changed
    dns_answers_saved: int  # dns_cache rows written
    elapsed_seconds: float


def recheck(
    settings: Settings,
    *,
    statuses: Collection[DkimStatus | None] | None = DEFAULT_STATUSES,
    mail_ids: Collection[int] = (),
    jobs: int = 1,
) -> RecheckSummary:
    """Check the selected mails from their MBOX files and store the results.

    statuses: the mail.dkim_status values to select, None in it for mails not checked yet;
    statuses=None selects every mail. mail_ids, when not empty, selects exactly those mails,
    whatever their status. jobs: worker processes, at most one per chunk of selected mails.
    """
    if jobs < 1:
        raise ValueError("jobs must be at least 1")
    return asyncio.run(_run(settings, _selection(statuses, mail_ids), jobs))


def _selection(
    statuses: Collection[DkimStatus | None] | None, mail_ids: Collection[int]
) -> ColumnElement[bool]:
    if mail_ids:
        return Mail.id.in_(sorted(set(mail_ids)))
    if statuses is None:
        return true()
    known = sorted(status for status in statuses if status is not None)
    conditions = [Mail.dkim_status.in_(known)] if known else []
    if None in statuses:
        conditions.append(Mail.dkim_status.is_(None))
    return or_(false(), *conditions)


async def _run(settings: Settings, where: ColumnElement[bool], jobs: int) -> RecheckSummary:
    started = time.monotonic()
    engine = create_engine(settings.database_url)
    try:
        async with engine.connect() as connection:
            count = select(func.count()).select_from(Mail).where(where)
            selected = await connection.scalar(count) or 0
            files = await connection.execute(select(MboxFile.id, MboxFile.path))
            paths = {file_id: path for file_id, path in files}
            answers = await store.load_dns_cache(connection)
            await connection.commit()
            jobs = max(1, min(jobs, math.ceil(selected / CHUNK)))
            log.info(
                "%d mails selected, %d cached DNS answers, %d worker(s)",
                selected,
                len(answers),
                jobs,
            )
            tally = _Tally(selected, started)
            with _checkers(settings, answers, jobs) as submit:
                pending: deque[tuple[list[_Mail], Callable[[], _Checked]]] = deque()
                async for chunk in _chunks(connection, where, paths):
                    pending.append((chunk, submit(chunk)))
                    if len(pending) >= jobs * WINDOW_PER_JOB:
                        await _write(connection, *pending.popleft(), tally)
                while pending:
                    await _write(connection, *pending.popleft(), tally)
    finally:
        await engine.dispose()
    return tally.finish()


@dataclass(frozen=True, slots=True)
class _Mail:
    """One selected mail, as a worker needs it."""

    id: int
    path: str  # mbox_file.path, relative to settings.mbox_dir
    byte_offset: int
    byte_length: int
    raw_sha256: str
    dkim_status: DkimStatus | None


@dataclass(slots=True)
class _Checked:
    """A worker's result for one chunk: one outcome per mail, in chunk order."""

    outcomes: list[MailVerdict | Skip]
    answers: list[DnsAnswer]  # the worker's new key answers, for dns_cache


async def _chunks(
    connection: AsyncConnection, where: ColumnElement[bool], paths: dict[int, str]
) -> AsyncIterator[list[_Mail]]:
    """The selected mails in file order, CHUNK at a time; each page is one index range scan."""
    page = (
        select(
            Mail.id,
            Mail.mbox_file_id,
            Mail.byte_offset,
            Mail.byte_length,
            Mail.raw_sha256,
            Mail.dkim_status,
        )
        .where(where)
        .order_by(Mail.mbox_file_id, Mail.byte_offset)
        .limit(CHUNK)
    )
    key = tuple_(Mail.mbox_file_id, Mail.byte_offset)
    query = page
    while True:
        rows = (await connection.execute(query)).all()
        if rows:
            yield [
                _Mail(mail_id, paths[file_id], offset, length, sha256, status)
                for mail_id, file_id, offset, length, sha256, status in rows
            ]
        if len(rows) < CHUNK:
            return
        query = page.where(key > tuple_(rows[-1].mbox_file_id, rows[-1].byte_offset))


async def _write(
    connection: AsyncConnection, chunk: list[_Mail], result: Callable[[], _Checked], tally: "_Tally"
) -> None:
    checked = result()
    await store.save_verdicts(connection, tally.count(chunk, checked))
    await store.upsert_dns_cache(connection, checked.answers)
    await connection.commit()
    tally.progress()


# Workers -----------------------------------------------------------------------------------


class _Worker:
    """What a checking process keeps between chunks: the MBOX directory and its checker."""

    def __init__(self, settings: Settings, answers: list[DnsAnswer]) -> None:
        self._mbox_dir = settings.mbox_dir
        self._checker = DkimChecker.from_settings(settings, preload=answers, refresh_negative=True)

    def check(self, chunk: list[_Mail]) -> _Checked:
        outcomes = [self._check(mail) for mail in chunk]
        return _Checked(outcomes, self._checker.take_new_answers())

    def _check(self, mail: _Mail) -> MailVerdict | Skip:
        try:
            raw = read_message(self._mbox_dir / mail.path, mail.byte_offset, mail.byte_length)
        except FileNotFoundError:
            return Skip.MISSING_FILE
        except (OSError, ValueError):
            return Skip.UNREADABLE
        if hashlib.sha256(raw).hexdigest() != mail.raw_sha256:
            return Skip.HASH_MISMATCH
        return self._checker.check(raw)


@contextmanager
def _checkers(
    settings: Settings, answers: list[DnsAnswer], jobs: int
) -> Iterator[Callable[[list[_Mail]], Callable[[], _Checked]]]:
    """submit(chunk) starts checking a chunk and returns a function that waits for its result."""
    if jobs == 1:
        worker = _Worker(settings, answers)
        yield lambda chunk: functools.partial(worker.check, chunk)
        return
    context = multiprocessing.get_context("spawn")
    with context.Pool(jobs, initializer=_init_worker, initargs=(settings, answers)) as pool:
        yield lambda chunk: pool.apply_async(_work, (chunk,)).get


_worker: _Worker | Exception | None = None


def _init_worker(settings: Settings, answers: list[DnsAnswer]) -> None:
    """Pool initializer: the cached answers reach each worker once, not with every chunk."""
    global _worker
    # Ctrl-C goes to the main process, which stops the pool; finished chunks are committed.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        _worker = _Worker(settings, answers)
    except Exception as error:
        # Raised from the first task instead: a failing initializer makes the pool start new
        # workers forever.
        _worker = error


def _work(chunk: list[_Mail]) -> _Checked:
    if isinstance(_worker, Exception):
        raise _worker
    assert _worker is not None, "worker not initialised"
    return _worker.check(chunk)


# Counting and progress ---------------------------------------------------------------------


class _Tally:
    """The summary's counters, and a progress line every few seconds."""

    def __init__(self, selected: int, started: float) -> None:
        self._selected = selected
        self._started = started
        self._next = started + PROGRESS_SECONDS
        self._skipped: Counter[str] = Counter()
        self._statuses: Counter[str] = Counter()
        self._transitions: Counter[str] = Counter()
        self._missing_files: set[str] = set()
        self._answers_saved = 0

    def count(self, chunk: list[_Mail], checked: _Checked) -> list[tuple[int, MailVerdict]]:
        """Count a finished chunk; returns the verdicts to save."""
        verdicts: list[tuple[int, MailVerdict]] = []
        for mail, outcome in zip(chunk, checked.outcomes, strict=True):
            if isinstance(outcome, Skip):
                self._skip(mail, outcome)
                continue
            verdicts.append((mail.id, outcome))
            status = outcome.status
            self._statuses[status.value] += 1
            if status != mail.dkim_status:
                self._transitions[f"{mail.dkim_status or UNCHECKED} -> {status}"] += 1
        # what upsert_dns_cache writes: the last answer per name, ttl 0 left out
        self._answers_saved += len({answer.name for answer in checked.answers if answer.ttl > 0})
        return verdicts

    def _skip(self, mail: _Mail, reason: Skip) -> None:
        self._skipped[reason.value] += 1
        if reason is not Skip.MISSING_FILE:
            log.warning(
                "mail %d skipped (%s): %s at offset %d",
                mail.id,
                reason,
                mail.path,
                mail.byte_offset,
            )
        elif mail.path not in self._missing_files:
            self._missing_files.add(mail.path)
            log.warning("skipping the mails of %s: file not found", mail.path)

    def progress(self) -> None:
        now = time.monotonic()
        if now < self._next:
            return
        self._next = now + PROGRESS_SECONDS
        done = self._statuses.total() + self._skipped.total()
        log.info(
            "%d/%d mails, %d skipped, %.0f mails/s",
            done,
            self._selected,
            self._skipped.total(),
            done / max(now - self._started, 1e-9),
        )

    def finish(self) -> RecheckSummary:
        elapsed = time.monotonic() - self._started
        checked = self._statuses.total()
        log.info(
            "done: %d mails checked, %d skipped in %.1f s (%.0f mails/s)",
            checked,
            self._skipped.total(),
            elapsed,
            (checked + self._skipped.total()) / max(elapsed, 1e-9),
        )
        return RecheckSummary(
            selected=self._selected,
            checked=checked,
            skipped=dict(sorted(self._skipped.items())),
            statuses=dict(sorted(self._statuses.items())),
            transitions=dict(sorted(self._transitions.items())),
            dns_answers_saved=self._answers_saved,
            elapsed_seconds=round(elapsed, 3),
        )
