"""The runs of `mailrobbe dkim-keys` (D101): one task each, recorded as a job of kind dkim_keys.

    reconstruct  select the concerned key names, most mails first, and up to READ_LIMIT RSA
                 signatures of each from mails that are no duplicates, oldest t= first; then
                 one name per task in worker processes, which read the mails, keep up to
                 MAX_SIGNATURES with distinct b= and rebuild their keys (reconstruct.py). Every
                 attempt is a lookup, its JSON the signatures read and the keys found, and
                 every key found is evidence with the signatures it verifies.
    search       key records quoted in the archive's mail and attachment texts (archive.py)
    fetch        the ZK Email DKIM archive, one request per domain (zkemail.py)
    check        only the check below, for the given names, or every name with a key

The first three continue with compare: a reconstructed key that today's DNS publishes under
another selector of the domain, or that another source holds under another name of the domain,
gets that as evidence too (observed through DNS, or what the other source says), and Batch-GCD
over every RSA modulus known (keys and today's DNS answers) marks the keys that share a prime
factor as factorable, never to be used. Every task ends with check, the mails with a signature
of a key name the run touched checked again with every candidate key (recheck.check_mails), and
the aggregates.

Each phase (DkimKeysPhase) is a step of the run's steps (D110) of the same name, but aggregates,
which are refresh_aggregates' four steps; a step with nothing to do is skipped. Steps count
key names (select, reconstruct, compare), domains (fetch) and mails (check); the search counts
mail and attachment texts together, without a unit.

A stop (Ctrl-C, SIGTERM, the dashboard) ends the task's phase after the names, domain or texts
in progress; what is stored stays, and the run still compares and checks what it found. A stop
during the check ends it after the chunks in flight. Reconstruction skips a name whose latest
attempt read the same signatures, so the next run goes on where a stopped one ended; names
given with --name are always tried.
"""

import asyncio
import base64
import hashlib
import json
import logging
import multiprocessing
import time
from collections import defaultdict, deque
from collections.abc import Collection, Iterator
from concurrent.futures import ProcessPoolExecutor
from contextlib import aclosing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection

from mailrobbe import aggregates
from mailrobbe.config import Settings
from mailrobbe.db.models import (
    DkimKey,
    DkimKeyEvidence,
    DkimKeyLookup,
    DkimResult,
    DnsCache,
    Mail,
    MboxFile,
)
from mailrobbe.db.session import create_engine
from mailrobbe.dkim.keys import archive, zkemail
from mailrobbe.dkim.keys.identity import key_identity, rsa_record, split_key_name
from mailrobbe.dkim.keys.model import (
    DkimKeysOptions,
    DkimKeysPhase,
    DkimKeysProgress,
    DkimKeysTask,
)
from mailrobbe.dkim.keys.reconstruct import RebuiltKey, RsaSignature, rebuild_keys, shared_factors
from mailrobbe.dkim.keys.store import (
    CONCERNED,
    Evidence,
    find_lookup,
    of_key_names,
    save_evidence,
    save_lookup,
)
from mailrobbe.dkim.model import MailVerdict
from mailrobbe.dkim.override import key_name, normalise_name
from mailrobbe.dkim.recheck import CheckTally, _Checked, _Mail, by_key_names, check_mails
from mailrobbe.dkim.verify import signature_material
from mailrobbe.enums import (
    DnsStatus,
    JobKind,
    JobOrigin,
    JobStatus,
    KeyLookupSource,
    KeyOrigin,
    LookupOutcome,
)
from mailrobbe.jobrun import (
    JobRun,
    RunRefused,
    Step,
    ignore_interrupts,
    job_run,
    spawning_workers,
)
from mailrobbe.jobs import StepUnit, application_name
from mailrobbe.mbox import read_message

log = logging.getLogger(__name__)

MAX_SIGNATURES = 8  # distinct signatures (b=) per name a reconstruction works with
READ_LIMIT = 3 * MAX_SIGNATURES  # signatures per name read to find them (b= repeats)

# The steps of each task (D110), in their order.
_TASK_STEPS: dict[DkimKeysTask, tuple[str, ...]] = {
    "reconstruct": ("select", "reconstruct", "compare", "check", *aggregates.STEPS),
    "search": ("select", "search", "compare", "check", *aggregates.STEPS),
    "fetch": ("select", "fetch", "compare", "check", *aggregates.STEPS),
    "check": ("select", "check", *aggregates.STEPS),
}


@dataclass(slots=True)
class KeysSummary:
    """Printed as JSON by `mailrobbe dkim-keys`."""

    task: str
    names: int  # key names the run worked on
    keys_found: int  # keys stored or given new evidence
    factorable: int  # keys this run found sharing a prime factor
    skipped_domains: list[str]  # fetch: under reserved TLDs, not sent
    mails_checked: int
    mails_changed: int
    transitions: dict[str, int]  # "no_key -> consistent" -> checked mails
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class KeysRun:
    summary: KeysSummary
    stopped: bool  # by Ctrl-C, SIGTERM or the dashboard


async def run_keys(
    settings: Settings, options: DkimKeysOptions, *, origin: JobOrigin = JobOrigin.CLI
) -> KeysRun:
    """One run of `mailrobbe dkim-keys`; raises jobrun.RunRefused when it cannot start, also
    for a fetch while the key archive is switched off."""
    if options.workers < 1:
        raise ValueError("workers must be at least 1")
    names = sorted({normalise_name(name) for name in options.names})
    domains = sorted({normalise_name(domain) for domain in options.domains})
    options = options.model_copy(update={"names": names, "domains": domains})
    if options.task == "fetch":
        url = zkemail.archive_url(settings)
        if url is None:
            raise RunRefused("the key archive is switched off (MAILROBBE_DKIM_KEY_ARCHIVE_URL=off)")
        options = options.model_copy(update={"archive_url": url})
    figures = DkimKeysProgress()

    async def report(_db: AsyncConnection) -> DkimKeysProgress:
        return figures.model_copy()  # the run adds its steps

    engine = create_engine(settings.database_url, application_name(JobKind.DKIM_KEYS))
    try:
        async with job_run(
            engine, JobKind.DKIM_KEYS, origin, options, phase="select", figures=report
        ) as job:
            job.steps.plan(*_TASK_STEPS[options.task])
            async with engine.connect() as connection:
                run = _Run(connection, settings, options, job, figures)
                await run.work()
            summary = run.summary()
            stopped = job.stop.is_set()
            job.end(JobStatus.STOPPED if stopped else JobStatus.DONE, _one_line(summary))
    finally:
        await engine.dispose()
    return KeysRun(summary, stopped)


def _one_line(summary: KeysSummary) -> str:
    """The summary in one line, for job.message."""
    line = (
        f"{summary.task}: {summary.names} key names, {summary.keys_found} keys found, "
        f"{summary.factorable} factorable; {summary.mails_checked} mails checked, "
        f"{summary.mails_changed} changed"
    )
    skipped = len(summary.skipped_domains)
    return f"{line}; {skipped} domains under reserved TLDs skipped" if skipped else line


class _CheckTally(CheckTally):
    """recheck's counters, also feeding the run's figures."""

    def __init__(self, figures: DkimKeysProgress) -> None:
        super().__init__()
        self._figures = figures

    def start(self, selected: int, workers: int) -> None:
        super().start(selected, workers)
        self._figures.workers = workers

    def count(self, chunk: list[_Mail], checked: _Checked) -> list[tuple[int, MailVerdict]]:
        verdicts = super().count(chunk, checked)
        self._figures.mails_checked = self.checked
        self._figures.mails_changed = self.changed
        return verdicts


class _Run:
    """One task and what follows it, on the run's own connection."""

    def __init__(
        self,
        db: AsyncConnection,
        settings: Settings,
        options: DkimKeysOptions,
        job: JobRun,
        figures: DkimKeysProgress,
    ) -> None:
        self.db = db
        self.settings = settings
        self.options = options
        self.job = job
        self.figures = figures
        self.tally = _CheckTally(figures)
        self.started = time.monotonic()
        self.touched: set[str] = set()  # key names whose mails the check takes
        self.keys: set[int] = set()  # dkim_key ids stored or given new evidence
        self.skipped: list[str] = []
        self.checked = False  # whether the check ran

    async def work(self) -> None:
        task = self.options.task
        if task == "reconstruct":
            await self._reconstruct()
        elif task == "search":
            await self._search()
        elif task == "fetch":
            await self._fetch()
        else:
            await self._names_to_check()
        if task != "check":
            await self._compare()
        await self._check()

    def summary(self) -> KeysSummary:
        transitions: dict[str, int] = {}
        if self.checked:
            transitions = self.tally.finish().transitions
        return KeysSummary(
            task=self.options.task,
            names=self.figures.names,
            keys_found=len(self.keys),
            factorable=self.figures.factorable,
            skipped_domains=self.skipped,
            mails_checked=self.tally.checked,
            mails_changed=self.tally.changed,
            transitions=transitions,
            elapsed_seconds=round(time.monotonic() - self.started, 3),
        )

    @contextmanager
    def _step(
        self, key: DkimKeysPhase, *, unit: StepUnit | None = None, total: int | None = None
    ) -> Iterator[Step]:
        """Phase and step `key`: every phase of the run starts here."""
        self.job.set_phase(key)
        with self.job.steps.step(key, unit=unit, total=total) as step:
            yield step

    def _found(self, keys: dict[int, str]) -> None:
        """Keys stored or given evidence: their names' mails are checked at the end."""
        self.keys.update(keys)
        self.touched.update(keys.values())
        self.figures.keys_found = len(self.keys)

    # reconstruct -------------------------------------------------------------------------

    async def _reconstruct(self) -> None:
        with self._step("select", unit="names") as step:
            plan = await self._reconstruction_plan()
            await self.db.commit()
            step.done = len(plan)
        self.figures.names = len(plan)
        if not plan:
            self.job.steps.skip("reconstruct")
            return
        workers = min(self.options.workers, len(plan))
        loop = asyncio.get_running_loop()
        queue = deque(plan)
        running: set[asyncio.Future[_Rebuilt]] = set()
        with (
            self._step("reconstruct", unit="names", total=len(plan)) as step,
            ProcessPoolExecutor(
                workers,
                mp_context=multiprocessing.get_context("spawn"),
                initializer=_init_worker,
                initargs=(self.settings.mbox_dir,),
            ) as pool,
        ):
            try:
                while queue or running:
                    while queue and len(running) < workers and not self.job.stop.is_set():
                        with spawning_workers():  # the pool starts its workers as names come
                            running.add(loop.run_in_executor(pool, _rebuild, queue.popleft()))
                    self.figures.workers = len(running)
                    if not running:
                        break
                    done, running = await asyncio.wait(running, return_when=asyncio.FIRST_COMPLETED)
                    for future in done:
                        await self._store_rebuilt(future.result())
                        step.advance()
            finally:
                self.figures.workers = 0
                # Names in flight when an error ends the run are dropped with it.
                await asyncio.gather(*running, return_exceptions=True)

    async def _reconstruction_plan(self) -> list["_NameTask"]:
        """The names to rebuild, most mails first, each with the signatures to read."""
        where = [
            CONCERNED,
            Mail.is_duplicate_of.is_(None),
            DkimResult.algorithm.like("rsa-%"),
            DkimResult.domain.is_not(None),
            DkimResult.selector.is_not(None),
        ]
        if self.options.names:
            where.append(of_key_names(self.options.names))
        rank = (
            func.row_number()
            .over(
                partition_by=(DkimResult.domain, DkimResult.selector),
                order_by=(
                    DkimResult.signed_at.asc().nulls_last(),
                    DkimResult.mail_id,
                    DkimResult.signature_index,
                ),
            )
            .label("rank")
        )
        ranked = (
            select(
                DkimResult.domain,
                DkimResult.selector,
                DkimResult.mail_id,
                DkimResult.signature_index,
                rank,
            )
            .join(Mail, Mail.id == DkimResult.mail_id)
            .where(*where)
            .subquery()
        )
        rows = await self.db.execute(
            select(
                ranked.c.domain,
                ranked.c.selector,
                ranked.c.signature_index,
                Mail.id,
                MboxFile.path,
                Mail.byte_offset,
                Mail.byte_length,
                Mail.raw_sha256,
            )
            .join(Mail, Mail.id == ranked.c.mail_id)
            .join(MboxFile, MboxFile.id == Mail.mbox_file_id)
            .where(ranked.c.rank <= READ_LIMIT)
            .order_by(ranked.c.domain, ranked.c.selector, ranked.c.rank)
        )
        reads: defaultdict[str, list[_Read]] = defaultdict(list)
        for domain, selector, index, mail_id, path, offset, length, sha256 in rows:
            reads[key_name(selector, domain)].append(
                _Read(mail_id, index, path, offset, length, sha256)
            )
        counts = await self.db.execute(
            select(
                DkimResult.domain, DkimResult.selector, func.count(DkimResult.mail_id.distinct())
            )
            .join(Mail, Mail.id == DkimResult.mail_id)
            .where(*where)
            .group_by(DkimResult.domain, DkimResult.selector)
        )
        mails: defaultdict[str, int] = defaultdict(int)
        for domain, selector, count in counts:
            if domain is not None and selector is not None:
                mails[key_name(selector, domain)] += count
        names = set(reads) | {name for name in self.options.names if split_key_name(name)}
        plan = [_NameTask(name, tuple(reads.get(name, ()))) for name in names]
        plan.sort(key=lambda task: (-mails[task.name], task.name.encode()))
        if self.options.names:
            return plan
        tried = await self._latest_attempts([task.name for task in plan])
        return [task for task in plan if tried.get(task.name) != task.selection()]

    async def _latest_attempts(self, names: list[str]) -> dict[str, list[list[int]]]:
        """The signatures the latest reconstruction of each name read."""
        rows = await self.db.execute(
            select(DkimKeyLookup.query, DkimKeyLookup.raw)
            .where(
                DkimKeyLookup.source == KeyLookupSource.RECONSTRUCTION.value,
                DkimKeyLookup.query.in_(names),
            )
            .order_by(DkimKeyLookup.query, DkimKeyLookup.id.desc())
            .ext(postgresql.distinct_on(DkimKeyLookup.query))
        )
        attempts = {}
        for name, raw in rows:
            try:
                attempts[name] = json.loads(raw or b"")["read"]
            except (TypeError, ValueError, KeyError):
                continue
        return attempts

    async def _store_rebuilt(self, result: "_Rebuilt") -> None:
        """One attempt as a lookup, each key found as evidence; committed."""
        name = result.task.name
        parts = split_key_name(name)
        assert parts is not None
        answer = {
            "name": name,
            "read": result.task.selection(),
            "signatures": [used.describe() for used in result.used],
            "keys": [
                {
                    "modulus": format(key.modulus, "x"),
                    "exponent": key.exponent,
                    "signatures": list(key.signatures),
                }
                for key in result.keys
            ],
            "unreadable": result.unreadable,
        }
        lookup_id = await save_lookup(
            self.db,
            KeyLookupSource.RECONSTRUCTION,
            name,
            LookupOutcome.FOUND if result.keys else LookupOutcome.NOT_FOUND,
            domain=parts[1],
            name=name,
            raw=json.dumps(answer, indent=1).encode(),
            raw_type="application/json",
            message=result.message,
        )
        for key in result.keys:
            used = [result.used[i] for i in key.signatures]
            times = [signature.signed_at for signature in used if signature.signed_at]
            hashes = sorted({signature.signature.hash_name for signature in used})
            evidence = Evidence(
                KeyOrigin.RECONSTRUCTED,
                observed_from=min(times, default=None),  # t= of the signatures it verifies
                observed_to=max(times, default=None),
                details={
                    "exponent": key.exponent,
                    "hash": ",".join(hashes),
                    "signatures": [signature.reference() for signature in used],
                },
            )
            record = rsa_record(key.modulus, key.exponent)
            key_id = await save_evidence(self.db, lookup_id, name, record, evidence)
            if key_id is not None:
                self._found({key_id: name})
        await self.db.commit()
        log.info("%s: %s", name, result.message)

    # search and fetch --------------------------------------------------------------------

    async def _search(self) -> None:
        with self._step("select", unit="names") as step:
            signatures = await archive.signatures_to_test(
                self.db, self.settings.mbox_dir, self.options.names
            )
            total = await archive.count_texts(self.db)
            await self.db.commit()
            self.figures.names = step.done = len({signature.name for signature in signatures})
        if not signatures or not total:
            self.job.steps.skip("search")
            return
        fitting: dict[str, list[str]] = {}  # record -> names whose signature it verifies
        # mail and attachment texts: counted, but in no unit of their own
        with self._step("search", total=total) as step:
            async with aclosing(archive.texts(self.db)) as batches:
                async for batch in batches:
                    for text in batch:
                        for found in archive.find_records(text.text):
                            names = fitting.get(found.record)
                            if names is None:
                                names = archive.fitting_names(found.record, signatures)
                                fitting[found.record] = names
                            if names:
                                self._found(await archive.store_find(self.db, text, found, names))
                    await self.db.commit()
                    step.advance(len(batch))
                    if self.job.stop.is_set():
                        break
        log.info("%d key records found, %d fit", len(fitting), sum(map(bool, fitting.values())))

    async def _fetch(self) -> None:
        url = self.options.archive_url
        assert url is not None
        with self._step("select", unit="names") as step:
            plan = await zkemail.fetch_plan(self.db, url, self.options.domains)
            await self.db.commit()
            self.figures.names = step.done = sum(domain.names for domain in plan.domains)
        self.skipped = plan.skipped
        if plan.skipped:
            log.info("not sent to %s (reserved TLDs): %s", url, ", ".join(plan.skipped))
        if not plan.domains:
            self.job.steps.skip("fetch")
            return
        timeout = self.settings.dkim_key_archive_timeout
        with self._step("fetch", unit="domains", total=len(plan.domains)) as step:
            for domain in plan.domains:
                if self.job.stop.is_set():
                    break
                query = zkemail.query_url(url, domain.domain)
                answer = await asyncio.to_thread(zkemail.ask, query, timeout)
                keys = await zkemail.store_answer(self.db, query, domain.domain, answer)
                await self.db.commit()
                self._found(keys)
                if answer.error:
                    log.warning("%s: %s", domain.domain, answer.error)
                else:
                    log.info("%s: %d keys", domain.domain, len(keys))
                step.advance()

    async def _names_to_check(self) -> None:
        with self._step("select", unit="names") as step:
            names = self.options.names or await self.db.scalars(select(DkimKey.name).distinct())
            self.touched.update(names)
            await self.db.commit()
            self.figures.names = step.done = len(self.touched)

    # compare -----------------------------------------------------------------------------

    async def _compare(self) -> None:
        with self._step("compare", unit="names") as step:
            await self._other_names(step)
            await self._factorable()

    async def _other_names(self, step: Step) -> None:
        """Reconstructed keys that today's DNS publishes under another selector of the domain,
        or that another source holds under another name of it, get that as evidence; the step
        counts their names."""
        keys = (
            await self.db.execute(
                select(DkimKey.id, DkimKey.name, DkimKey.domain, DkimKey.key_sha256, DkimKey.record)
                .where(DkimKey.origin == KeyOrigin.RECONSTRUCTED, DkimKey.factorable.is_(False))
                .order_by(DkimKey.name, DkimKey.id)
            )
        ).all()
        step.total = len({key.name for key in keys})
        if not keys:
            return
        domains = {key.domain for key in keys}
        published: defaultdict[tuple[str, str], list[tuple[str, str, datetime]]] = defaultdict(list)
        for name, record, fetched_at in await self.db.execute(
            select(DnsCache.name, DnsCache.record, DnsCache.fetched_at).where(
                DnsCache.status == DnsStatus.FOUND, DnsCache.record.is_not(None)
            )
        ):
            parts = split_key_name(name)
            if record is None or parts is None or parts[1] not in domains:
                continue
            identity = key_identity(record)
            if identity is not None:
                published[parts[1], identity.key_sha256].append((name, record, fetched_at))
        held: defaultdict[tuple[str, str], list[tuple[str, DkimKeyEvidence]]] = defaultdict(list)
        for other, domain, key_sha256, evidence in await self.db.execute(
            select(DkimKey.name, DkimKey.domain, DkimKey.key_sha256, DkimKeyEvidence)
            .join(DkimKeyEvidence, DkimKeyEvidence.key_id == DkimKey.id)
            .where(
                DkimKey.domain.in_(domains),
                DkimKey.factorable.is_(False),
                DkimKeyEvidence.origin != KeyOrigin.RECONSTRUCTED,
            )
            .order_by(DkimKeyEvidence.id)
        ):
            held[domain, key_sha256].append((other, evidence))
        for number, key in enumerate(keys):
            if number and key.name != keys[number - 1].name:
                step.advance()
            for name, record, fetched_at in published.get((key.domain, key.key_sha256), ()):
                if name != key.name:
                    seen = Evidence(
                        KeyOrigin.OBSERVED,
                        observed_from=fetched_at,
                        observed_to=fetched_at,
                        reference=name,
                        details={"name": name},
                    )
                    lookup_id = await self._dns_lookup(name, record, fetched_at)
                    await save_evidence(self.db, lookup_id, key.name, key.record, seen)
            for other, evidence in held.get((key.domain, key.key_sha256), ()):
                if other != key.name:
                    copy = Evidence(
                        evidence.origin,
                        observed_from=evidence.observed_from,
                        observed_to=evidence.observed_to,
                        reference=evidence.reference,
                        details={**evidence.details, "name": other},
                    )
                    await save_evidence(self.db, evidence.lookup_id, key.name, key.record, copy)
        step.advance()  # the last name
        stronger = await self.db.execute(
            select(DkimKey.id, DkimKey.name).where(
                DkimKey.id.in_([key.id for key in keys]),
                DkimKey.origin != KeyOrigin.RECONSTRUCTED,
            )
        )
        self._found({key_id: name for key_id, name in stronger})
        await self.db.commit()

    async def _dns_lookup(self, name: str, record: str, fetched_at: datetime) -> int:
        """Today's DNS answer of a name as a lookup (source dns), stored once per answer."""
        raw = record.encode("utf-8")
        lookup_id = await find_lookup(self.db, KeyLookupSource.DNS, name, raw)
        if lookup_id is not None:
            return lookup_id
        parts = split_key_name(name)
        return await save_lookup(
            self.db,
            KeyLookupSource.DNS,
            name,
            LookupOutcome.FOUND,
            domain=None if parts is None else parts[1],
            name=name,
            raw=raw,
            raw_type="text/plain; charset=utf-8",
            message="today's DNS answer, from the DNS cache",
            asked_at=fetched_at,
        )

    async def _factorable(self) -> None:
        """Batch-GCD over every RSA modulus known; keys sharing a prime factor are never used."""
        keys: dict[int, tuple[str, int, bool]] = {}
        for key_id, name, record, factorable in await self.db.execute(
            select(DkimKey.id, DkimKey.name, DkimKey.record, DkimKey.factorable).where(
                DkimKey.key_type == "rsa"
            )
        ):
            identity = key_identity(record)
            if identity is not None and identity.modulus is not None:
                keys[key_id] = (name, identity.modulus, factorable)
        published: dict[int, str] = {}
        for name, answer in await self.db.execute(
            select(DnsCache.name, DnsCache.record).where(
                DnsCache.status == DnsStatus.FOUND, DnsCache.record.is_not(None)
            )
        ):
            identity = None if answer is None else key_identity(answer)
            if identity is not None and identity.modulus is not None:
                published[identity.modulus] = name
        await self.db.commit()
        moduli = {modulus for _, modulus, _ in keys.values()} | set(published)
        shared = await asyncio.to_thread(shared_factors, moduli)
        for modulus in sorted(shared & set(published)):
            log.warning("today's DNS key of %s shares a prime factor", published[modulus])
        flagged = {
            key_id: name
            for key_id, (name, modulus, factorable) in keys.items()
            if modulus in shared and not factorable
        }
        if flagged:
            await self.db.execute(
                update(DkimKey).where(DkimKey.id.in_(list(flagged))).values(factorable=True)
            )
            await self.db.commit()
            for key_id, name in sorted(flagged.items()):
                log.warning("the key %d of %s shares a prime factor: not used", key_id, name)
        self.figures.factorable += len(flagged)
        self.touched.update(flagged.values())

    # check -------------------------------------------------------------------------------

    async def _check(self) -> None:
        if not self.touched:
            self.job.steps.skip("check", *aggregates.STEPS)
            return
        # A stop before the check still checks what the run found; one during it ends it.
        stop = asyncio.Event() if self.job.stop.is_set() else self.job.stop
        self.job.set_phase("check")
        self.checked = True
        await check_mails(
            self.db,
            self.settings,
            by_key_names(self.touched),
            self.options.workers,
            self.tally,
            self.job.steps,
            stop,
            refresh_negative=False,
        )
        self.figures.workers = 0
        if self.tally.checked:
            self.job.set_phase("aggregates")
            await aggregates.refresh_aggregates(self.db, steps=self.job.steps)
            await self.db.commit()
        else:
            self.job.steps.skip(*aggregates.STEPS)


# Reconstruction workers ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Read:
    """A signature to read for a reconstruction."""

    mail_id: int
    signature_index: int
    path: str  # mbox_file.path, relative to settings.mbox_dir
    byte_offset: int
    byte_length: int
    raw_sha256: str


@dataclass(frozen=True, slots=True)
class _NameTask:
    name: str
    reads: tuple[_Read, ...]  # oldest t= first

    def selection(self) -> list[list[int]]:
        """The signatures read, as the lookup's JSON keeps them ("read")."""
        return [[read.mail_id, read.signature_index] for read in self.reads]


@dataclass(frozen=True, slots=True)
class _Used:
    """A signature a reconstruction worked with."""

    mail_id: int
    signature_index: int
    mail_sha256: str
    signed_at: datetime | None
    signature: RsaSignature

    def reference(self) -> dict[str, Any]:
        return {
            "mail_id": self.mail_id,
            "signature_index": self.signature_index,
            "mail_sha256": self.mail_sha256,
        }

    def describe(self) -> dict[str, Any]:
        return self.reference() | {
            "signed_at": None if self.signed_at is None else self.signed_at.isoformat(),
            "hash": self.signature.hash_name,
            "header_hash": self.signature.header_hash.hex(),
            "b": base64.b64encode(self.signature.value).decode("ascii"),
        }


@dataclass(frozen=True, slots=True)
class _Rebuilt:
    task: _NameTask
    used: tuple[_Used, ...]
    keys: tuple[RebuiltKey, ...]
    unreadable: int  # mails missing, unreadable or changed since the import
    message: str


_mbox_dir: Path | None = None


def _init_worker(mbox_dir: Path) -> None:
    global _mbox_dir
    # Ctrl-C reaches the whole process group; the main process decides and stops submitting.
    ignore_interrupts()
    _mbox_dir = mbox_dir


def _rebuild(task: _NameTask) -> _Rebuilt:
    """Read the signatures of one name and rebuild their keys (in a worker process)."""
    assert _mbox_dir is not None, "worker not initialised"
    used: list[_Used] = []
    values: set[bytes] = set()
    unreadable = 0
    for read in task.reads:
        if len(used) == MAX_SIGNATURES:
            break
        try:
            raw = read_message(_mbox_dir / read.path, read.byte_offset, read.byte_length)
        except (OSError, ValueError):
            unreadable += 1
            continue
        if hashlib.sha256(raw).hexdigest() != read.raw_sha256:
            unreadable += 1
            continue
        material = next(
            (m for m in signature_material(raw) if m.index == read.signature_index), None
        )
        if (
            material is None
            or material.name != task.name
            or material.key_type != "rsa"
            or material.signature in values
        ):
            continue
        values.add(material.signature)
        signature = RsaSignature(material.signature, material.hash_name, material.header_hash)
        used.append(
            _Used(
                read.mail_id, read.signature_index, read.raw_sha256, material.signed_at, signature
            )
        )
    keys = rebuild_keys([u.signature for u in used]) if len(used) >= 2 else []
    return _Rebuilt(task, tuple(used), tuple(keys), unreadable, _message(used, keys, unreadable))


def _message(used: Collection[_Used], keys: list[RebuiltKey], unreadable: int) -> str:
    """Why the attempt found what it found, for the lookup's message."""
    if len(used) < 2:
        message = f"{len(used)} distinct RSA signatures, two are needed"
    elif not keys:
        message = (
            f"no pair of the {len(used)} signatures gives a key: signed headers changed "
            "after signing, or the signatures come from different keys"
        )
    else:
        verified = sum(len(key.signatures) for key in keys)
        bits = ", ".join(str(key.modulus.bit_length()) for key in keys)
        plural = "s" if len(keys) > 1 else ""
        message = (
            f"{len(keys)} key{plural} ({bits} bits) from {len(used)} signatures, "
            f"verifying {verified} of them"
        )
    return f"{message}; {unreadable} mails unreadable or changed" if unreadable else message
