"""Generator orchestration: population, planning, worker pool, writer, manifest, summary.

The main process plans the stream and sends it in chunks to a pool of config.jobs worker
processes, each running render -> apply_faults -> sign_mail and hashing the result. Results are
consumed in stream order through a bounded window of chunks, so memory does not grow with the
number of mails, and the output is the same for any number of workers. The main process then
injects duplicates, writes the MBOX records and the manifest, and finally summary.json.

Workers are started with "spawn" on every platform, so code that calls generate() with
jobs > 1 must be importable without side effects (the usual `if __name__ == "__main__"`).
"""

import hashlib
import itertools
import json
import logging
import multiprocessing
import time
from collections import Counter, deque
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from multiprocessing.pool import AsyncResult
from typing import Any

from mailspider.generator.config import SUMMARY_NAME, GeneratorConfig
from mailspider.generator.dkim import DkimSetup, build_dkim_setup, sign_mail, write_dkim_artifacts
from mailspider.generator.faults import DuplicateInjector, apply_faults
from mailspider.generator.model import PlannedMail, RenderedMail, stage_rng
from mailspider.generator.planner import plan
from mailspider.generator.population import build_population
from mailspider.generator.render import render
from mailspider.generator.writer import ManifestWriter, MboxWriter, manifest_record, prepare_output

log = logging.getLogger(__name__)

CHUNK = 64  # mails per task sent to a worker
WINDOW_PER_JOB = 3  # chunks in flight per worker: the bounded look-ahead
PROGRESS_SECONDS = 5.0


@dataclass(slots=True)
class GenerationSummary:
    """Written to summary.json and printed by the CLI."""

    mails: int
    files: dict[str, int]  # MBOX file name -> size in bytes
    bytes_total: int
    dkim_expected: dict[str, int]  # DkimStatus value -> number of mails
    faults: dict[str, int]  # Fault value -> number of mails
    duplicates: int
    elapsed_seconds: float
    config: dict[str, Any] = field(default_factory=dict)


def generate(config: GeneratorConfig) -> GenerationSummary:
    """Generate the whole data set described by config; see the module docstring."""
    started = time.monotonic()
    prepare_output(config)
    population = build_population(config, stage_rng(config.seed, "population"))
    setup = build_dkim_setup(population.domains, config, stage_rng(config.seed, "dkim-setup"))
    write_dkim_artifacts(setup, config.meta_dir)

    injector = DuplicateInjector(config)
    progress = _Progress(config.mails, started)
    dkim: Counter[str] = Counter()
    faults: Counter[str] = Counter()
    duplicates = 0
    written = 0
    with (
        MboxWriter(config.out_dir, config.file_size) as mbox,
        ManifestWriter(config.meta_dir) as manifest,
    ):
        produced = _produce(plan(config, population), config, setup)
        for index, (made, digest) in enumerate(produced):
            mail = injector.process(made)
            if mail.raw is not made.raw:  # a duplicate or a changed mail: hash what is written
                digest = hashlib.sha256(mail.raw).hexdigest()
            file, offset, length = mbox.write(mail)
            manifest.write(manifest_record(index, mail, file, offset, length, digest))
            dkim[mail.dkim.expected.value] += 1
            faults.update(fault.value for fault in mail.faults)
            duplicates += mail.duplicate_of is not None
            written += 1
            progress.update(written, length)
        files = dict(mbox.files)

    summary = GenerationSummary(
        mails=written,
        files=files,
        bytes_total=sum(files.values()),
        dkim_expected=dict(sorted(dkim.items())),
        faults=dict(sorted(faults.items())),
        duplicates=duplicates,
        elapsed_seconds=round(time.monotonic() - started, 3),
        config=config_dict(config),
    )
    text = json.dumps(asdict(summary), indent=2, ensure_ascii=False) + "\n"
    (config.meta_dir / SUMMARY_NAME).write_text(text, encoding="utf-8")
    progress.finish(written)
    return summary


def config_dict(config: GeneratorConfig) -> dict[str, Any]:
    """The configuration as JSON values (paths and dates as strings)."""
    return {
        name: value if isinstance(value, bool | int | float) else str(value)
        for name, value in ((name, getattr(config, name)) for name in config.__slots__)
    }


# Workers -----------------------------------------------------------------------------------

_Made = tuple[RenderedMail, str]  # a finished mail and the SHA-256 of its raw bytes


def _make(planned: PlannedMail, config: GeneratorConfig, setup: DkimSetup) -> _Made:
    mail = render(planned)
    mail = apply_faults(mail, config, stage_rng(planned.seed, "faults"))
    mail = sign_mail(mail, setup, stage_rng(planned.seed, "dkim"))
    return mail, hashlib.sha256(mail.raw).hexdigest()


def _chunks(mails: Iterable[PlannedMail]) -> Iterator[list[PlannedMail]]:
    iterator = iter(mails)
    while chunk := list(itertools.islice(iterator, CHUNK)):
        yield chunk


def _produce(
    mails: Iterable[PlannedMail], config: GeneratorConfig, setup: DkimSetup
) -> Iterator[_Made]:
    """Rendered, faulted and signed mails in stream order."""
    if config.jobs == 1:
        for planned in mails:
            yield _make(planned, config, setup)
        return
    # Pool.imap would read the whole plan ahead; apply_async with a window keeps it bounded.
    context = multiprocessing.get_context("spawn")
    window = config.jobs * WINDOW_PER_JOB
    with context.Pool(config.jobs, initializer=_init_worker, initargs=(config, setup)) as pool:
        pending: deque[AsyncResult[list[_Made]]] = deque()
        for chunk in _chunks(mails):
            pending.append(pool.apply_async(_work, (chunk,)))
            if len(pending) >= window:
                yield from pending.popleft().get()
        while pending:
            yield from pending.popleft().get()


_worker: tuple[GeneratorConfig, DkimSetup] | None = None


def _init_worker(config: GeneratorConfig, setup: DkimSetup) -> None:
    """Pool initializer: the setup reaches each worker once, not with every chunk."""
    global _worker
    _worker = (config, setup)


def _work(chunk: list[PlannedMail]) -> list[_Made]:
    assert _worker is not None, "worker not initialised"
    config, setup = _worker
    return [_make(planned, config, setup) for planned in chunk]


class _Progress:
    """Logs mails, megabytes, rate and ETA every few seconds."""

    def __init__(self, total: int, started: float) -> None:
        self._total = total
        self._started = started
        self._next = started + PROGRESS_SECONDS
        self._bytes = 0

    def update(self, done: int, length: int) -> None:
        self._bytes += length
        now = time.monotonic()
        if now < self._next:
            return
        self._next = now + PROGRESS_SECONDS
        rate = done / max(now - self._started, 1e-9)
        eta = (self._total - done) / rate if rate else 0.0
        log.info(
            "%d/%d mails, %.1f MB, %.0f mails/s, ETA %s",
            done,
            self._total,
            self._bytes / 1024**2,
            rate,
            _duration(eta),
        )

    def finish(self, done: int) -> None:
        elapsed = time.monotonic() - self._started
        log.info(
            "done: %d mails, %.1f MB in %s (%.0f mails/s)",
            done,
            self._bytes / 1024**2,
            _duration(elapsed),
            done / max(elapsed, 1e-9),
        )


def _duration(seconds: float) -> str:
    minutes, rest = divmod(int(seconds + 0.5), 60)
    return f"{minutes}m{rest:02d}s" if minutes else f"{rest}s"
