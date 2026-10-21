"""The calendar phase of an import (D154): the candidates among the mails not looked at yet are
read from their MBOX files, and the events of their iCalendar parts stored.

    work list   mails without a calendar_scan row of the current CALENDAR_VERSION; waiting()
                counts them for the import's step
    candidates  an iCalendar attachment, or a subject or text of invitations (D154); the others
                get their calendar_scan row without being read
    read        each candidate by read_message, in file and offset order; every text/calendar
                part and iCalendar attachment, attached mails included, parsed
    store       per batch one transaction: the mails' events and attendees replaced, their scan
                rows written; at the end the figures in global_stats 'calendar'

A stop (D46) ends the phase between two batches: the stored batches stay, the rest waits for the
next import. A mail whose MBOX file is missing or changed gets no scan row and is tried again.
"""

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.jobrun import Step


async def waiting(session: AsyncSession) -> int:
    """Mails without a calendar_scan row of the current CALENDAR_VERSION."""
    return 0  # milestone 14: calendar invitations


async def scan_calendar(
    sessionmaker: async_sessionmaker[AsyncSession],
    mbox_dir: Path,
    workers: int,
    stop: asyncio.Event,
    step: Step,
) -> int:
    """The step calendar: look at the waiting mails; the events stored in this run."""
    raise NotImplementedError("milestone 14: calendar invitations")
