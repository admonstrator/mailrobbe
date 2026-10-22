"""The runs the import dashboard starts: `mailrobbe import` and `mailrobbe dkim` as child processes
of the API server (D46), and `mailrobbe map download` beside them (D246).

A child is the command a shell would run, with `--origin ui` so its job row says where it came
from. It runs in the server's container with the server's settings (passed as MAILROBBE_*
variables, since tests build Settings in code) and MBOX mount, and writes to the server's stdout
and stderr, which is `docker compose logs backend`. It runs in a session of its own: a Ctrl-C
in the terminal of `mailrobbe serve` reaches only the server, which then stops its children.

A start waits until the child has recorded its run in `job` and answers with that row, so the
dashboard shows the run at once; starts are serialised, so two quick clicks start one run. A
background task awaits every child, so none is left a zombie, and logs how it ended. An import,
a DKIM check and a key run exclude each other; a map download excludes only another one
(excluded), and its starts have a lock of their own.

When the server stops, every child still running gets SIGTERM, which a run handles like Ctrl-C
(an import commits its batches and pauses its files, D15), and SIGKILL with its process group
(its worker processes) if it has not ended within STOP_TIMEOUT.
"""

import asyncio
import logging
import os
import signal
import sys
from collections.abc import Collection, Mapping, Sequence

from pydantic import ByteSize, SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.config import Settings
from mailrobbe.db.models import Job
from mailrobbe.enums import JobKind

log = logging.getLogger(__name__)

CLI: tuple[str, ...] = (sys.executable, "-m", "mailrobbe.cli")  # tests put a stand-in here
START_TIMEOUT = 15.0  # seconds a child may take to record its run
POLL_SECONDS = 0.2
STOP_TIMEOUT = 50.0  # within the backend's stop_grace_period of 60 s (docker-compose.yml)


class StartFailed(Exception):
    """The child ended, or did not record its run in time; the message says which."""


def child_environment(settings: Settings, overrides: Mapping[str, str] = {}) -> dict[str, str]:
    """The server's environment with every setting as its MAILROBBE_* variable, then overrides.

    A setting that is None is removed, so the child falls back to the same default.
    """
    environment = dict(os.environ)
    prefix = settings.model_config.get("env_prefix", "")
    for name in type(settings).model_fields:
        variable = f"{prefix}{name}".upper()
        value = getattr(settings, name)
        if value is None:
            environment.pop(variable, None)
        elif isinstance(value, SecretStr):
            environment[variable] = value.get_secret_value()
        elif isinstance(value, ByteSize):
            environment[variable] = str(int(value))
        elif isinstance(value, bool):
            environment[variable] = "true" if value else "false"
        else:
            environment[variable] = str(value)
    environment.update(overrides)
    return environment


def excluded(kind: JobKind) -> tuple[JobKind, ...]:
    """The kinds whose live runs keep a run of this kind from starting: an import, a DKIM check
    and a key run exclude each other (D46), a map download only another one (D246)."""
    if kind is JobKind.MAP:
        return (JobKind.MAP,)
    return tuple(other for other in JobKind if other is not JobKind.MAP)


class Runs:
    """The children this server started, and the locks that serialise starting them."""

    def __init__(self) -> None:
        self.lock = asyncio.Lock()  # held by a start and by a rescan of the MBOX directory
        self.map_lock = asyncio.Lock()  # held by the start of a map download
        self._children: dict[asyncio.subprocess.Process, JobKind] = {}
        self._reapers: set[asyncio.Task[None]] = set()

    @property
    def children(self) -> list[asyncio.subprocess.Process]:
        """The children that have not ended yet."""
        return list(self._children)

    def children_of(self, kinds: Collection[JobKind]) -> list[asyncio.subprocess.Process]:
        """The children of these kinds that have not ended yet."""
        return [child for child, kind in self._children.items() if kind in kinds]

    def lock_of(self, kind: JobKind) -> asyncio.Lock:
        """The lock a start of this kind holds."""
        return self.map_lock if kind is JobKind.MAP else self.lock

    async def start(
        self,
        session: AsyncSession,
        kind: JobKind,
        arguments: Sequence[str],
        environment: Mapping[str, str],
    ) -> int:
        """Run `mailrobbe <kind> --origin ui <arguments>` (dkim_keys: `dkim-keys`; for map and
        dkim_keys the arguments begin with the task); the id of the job row it recorded.

        The caller holds `lock_of(kind)`. StartFailed when the child ends before recording its
        run or has not recorded it after START_TIMEOUT; it is left running then.
        """
        before = await session.scalar(select(func.max(Job.id)).where(Job.kind == kind)) or 0
        await session.commit()
        command = [*CLI, kind.value.replace("_", "-"), "--origin", "ui", *arguments]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                env=dict(environment),
                start_new_session=True,
            )
        except OSError as error:
            raise StartFailed(f"cannot start mailrobbe {kind}: {error}") from error
        log.info("started mailrobbe %s (pid %d)", " ".join(command[len(CLI) :]), process.pid)
        self._children[process] = kind
        reaper = asyncio.create_task(self._reap(process, kind))
        self._reapers.add(reaper)
        reaper.add_done_callback(self._reapers.discard)

        deadline = asyncio.get_running_loop().time() + START_TIMEOUT
        while True:
            ended = process.returncode is not None  # before the query: a fast run may be over
            job_id = await session.scalar(
                select(func.max(Job.id)).where(Job.kind == kind, Job.id > before)
            )
            await session.commit()
            if job_id is not None:
                return int(job_id)
            if ended:
                raise StartFailed(
                    f"mailrobbe {kind} ended with exit status {process.returncode} before "
                    "recording its run; see the server log"
                )
            if asyncio.get_running_loop().time() >= deadline:
                raise StartFailed(
                    f"mailrobbe {kind} (pid {process.pid}) has not recorded its run after "
                    f"{START_TIMEOUT:.0f} s; see the server log"
                )
            await asyncio.sleep(POLL_SECONDS)

    async def _reap(self, process: asyncio.subprocess.Process, kind: JobKind) -> None:
        status = await process.wait()
        self._children.pop(process, None)
        level = logging.INFO if status == 0 else logging.WARNING
        log.log(level, "mailrobbe %s (pid %d) ended with exit status %d", kind, process.pid, status)

    async def stop(self) -> None:
        """SIGTERM to every child, SIGKILL to the process groups of those left after
        STOP_TIMEOUT."""
        timeout = STOP_TIMEOUT
        children = [child for child in self._children if child.returncode is None]
        for child in children:
            log.warning("stopping mailrobbe run (pid %d)", child.pid)
            _signal(child, signal.SIGTERM, group=False)
        try:
            await asyncio.wait_for(_wait_all(children), timeout)
        except TimeoutError:
            for child in children:
                if child.returncode is None:
                    log.warning("killing mailrobbe run (pid %d) after %.0f s", child.pid, timeout)
                    # The group: the run's worker processes must not go on writing alone.
                    _signal(child, signal.SIGKILL, group=True)
            await _wait_all(children)
        await asyncio.gather(*self._reapers)


async def _wait_all(children: Sequence[asyncio.subprocess.Process]) -> None:
    await asyncio.gather(*(child.wait() for child in children))


def _signal(child: asyncio.subprocess.Process, signum: int, *, group: bool) -> None:
    try:
        if group:
            os.killpg(child.pid, signum)  # its own session: the group id is its pid
        else:
            child.send_signal(signum)
    except ProcessLookupError:  # ended meanwhile
        pass
