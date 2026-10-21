"""A slow `mailrobbe dkim` in a process of its own, for tests that signal it.

run() makes chunks of SLOW_CHUNK mails and hands them to slow_work, which waits before checking;
the spawned workers import this module to unpickle slow_work, so they wait too.
"""

import sys
import time

from mailrobbe.cli import main
from mailrobbe.dkim import recheck
from mailrobbe.dkim.recheck import _Checked, _Mail

SLOW_CHUNK = 10
CHUNK_SECONDS = 0.2


def slow_work(chunk: list[_Mail]) -> _Checked:
    time.sleep(CHUNK_SECONDS)
    return recheck._work(chunk)  # the worker's own module is not patched


def run(argv: list[str]) -> int:
    """`mailrobbe <argv>` with slow DKIM chunks."""
    recheck.CHUNK = SLOW_CHUNK
    recheck._work = slow_work
    return main(argv)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
