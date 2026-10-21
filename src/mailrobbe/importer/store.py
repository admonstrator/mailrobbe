"""Writing parsed mails in batches: one transaction per batch, together with the file's progress.

A batch commits its mails with mbox_file.bytes_done, so a killed import loses at most the batch
it was writing and the next run continues after the last committed record (D15); the unique
(mbox_file_id, byte_offset) rules out a second copy in any case. Persons are created first, in a
short transaction of their own: popular addresses turn up in the batches of every worker, and
their rows must not stay locked while a whole batch is written. All other rows go in with COPY,
so a batch costs a handful of round trips however many mails it holds.
"""

import time
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.enums import ParticipationRole
from mailrobbe.importer import dkim_hook
from mailrobbe.importer.dkim_hook import DkimChecker, DkimVerdict
from mailrobbe.importer.model import Issue, ParsedAddress, ParsedMail
from mailrobbe.importer.split import MboxRecord

# A batch ends at whichever limit it reaches first.
BATCH_RECORDS = 500
BATCH_BYTES = 64 * 1024**2  # MBOX bytes, so that progress is committed often in large files
BATCH_SECONDS = 5.0

MAIL_COLUMNS = (
    "id",
    "mbox_file_id",
    "byte_offset",
    "byte_length",
    "message_id",
    "in_reply_to",
    "reference_ids",
    "subject",
    "date_utc",
    "raw_sha256",
    "has_attachments",
    "body_text",
    "dkim_status",
    "list_id",
    "automated",
)
PARTICIPATION_COLUMNS = ("mail_id", "person_id", "role", "display_name")
ATTACHMENT_COLUMNS = ("mail_id", "filename", "mime_type", "size_bytes", "sha256")
IMPORT_ERROR_COLUMNS = ("mbox_file_id", "byte_offset", "kind", "message")

_NEXT_MAIL_IDS = text(
    "SELECT nextval(pg_get_serial_sequence('mail', 'id')) FROM generate_series(1, :n)"
)
# Addresses that are already known through person_email (possibly as the alias of another
# person) get no person of their own.
_INSERT_PERSONS = text(
    "INSERT INTO person (canonical_email, domain) "
    "SELECT n.email, n.domain FROM unnest(CAST(:emails AS text[]), CAST(:domains AS text[])) "
    "AS n(email, domain) "
    "WHERE NOT EXISTS (SELECT 1 FROM person_email e WHERE e.email = n.email) "
    "ORDER BY n.email ON CONFLICT (canonical_email) DO NOTHING"
)
_INSERT_PERSON_EMAILS = text(
    "INSERT INTO person_email (email, person_id) "
    "SELECT canonical_email, id FROM person WHERE canonical_email = ANY(CAST(:emails AS text[])) "
    "ORDER BY canonical_email ON CONFLICT (email) DO NOTHING"
)
_PERSON_IDS = text(
    "SELECT email, person_id FROM person_email WHERE email = ANY(CAST(:emails AS text[]))"
)
_PROGRESS = text(
    "UPDATE mbox_file SET bytes_done = :end, mails_parsed = mails_parsed + :mails, "
    "error_count = error_count + :errors WHERE id = :id"
)


@dataclass(frozen=True, slots=True)
class BatchEntry:
    byte_offset: int
    byte_length: int
    raw_sha256: str
    mail: ParsedMail
    issues: tuple[Issue, ...]  # framing, parse and DKIM issues of the record
    verdict: DkimVerdict | None


class Batch:
    """The records read since the last commit: framing data and ParsedMail, no raw messages."""

    def __init__(self) -> None:
        self.entries: list[BatchEntry] = []
        self.size = 0  # MBOX bytes covered
        self._started = time.monotonic()

    def __len__(self) -> int:
        return len(self.entries)

    def add(
        self,
        record: MboxRecord,
        mail: ParsedMail,
        verdict: DkimVerdict | None = None,
        issues: Sequence[Issue] = (),
    ) -> None:
        if not self.entries:
            self._started = time.monotonic()
        all_issues = (*record.issues, *mail.issues, *issues)
        self.entries.append(
            BatchEntry(
                record.byte_offset,
                record.byte_length,
                record.raw_sha256,
                mail,
                all_issues,
                verdict,
            )
        )
        self.size += record.byte_length

    def is_full(self) -> bool:
        return (
            len(self.entries) >= BATCH_RECORDS
            or self.size >= BATCH_BYTES
            or time.monotonic() - self._started >= BATCH_SECONDS
        )

    @property
    def end(self) -> int:
        """Offset just past the last record: the file's progress once the batch is stored."""
        last = self.entries[-1]
        return last.byte_offset + last.byte_length

    @property
    def issue_count(self) -> int:
        return sum(len(entry.issues) for entry in self.entries)

    @property
    def verdict_count(self) -> int:
        """Mails checked for DKIM: all but those above the size limit or whose check failed."""
        return sum(entry.verdict is not None for entry in self.entries)


class Store:
    """Writes the batches of one worker and remembers person ids across batches."""

    def __init__(self, checker: DkimChecker | None = None) -> None:
        self._checker = checker
        self._person_ids: dict[str, int] = {}

    async def write(self, session: AsyncSession, mbox_file_id: int, batch: Batch) -> None:
        """Store a non-empty batch and the file's progress; nothing of it when this raises."""
        person_ids = await self._persons(session, batch)
        checked_at = datetime.now(UTC)
        async with session.begin():
            mail_ids = list(await session.scalars(_NEXT_MAIL_IDS, {"n": len(batch)}))
            mails: list[tuple[Any, ...]] = []
            participations: list[tuple[Any, ...]] = []
            attachments: list[tuple[Any, ...]] = []
            errors: list[tuple[Any, ...]] = []
            dkim_rows: list[dict[str, Any]] = []
            for mail_id, entry in zip(mail_ids, batch.entries, strict=True):
                mails.append(_mail_row(mail_id, mbox_file_id, entry))
                participations.extend(_participation_rows(mail_id, entry.mail, person_ids))
                attachments.extend(
                    (mail_id, a.filename, a.mime_type, a.size_bytes, a.sha256)
                    for a in entry.mail.attachments
                )
                errors.extend(
                    (mbox_file_id, entry.byte_offset, issue.kind.value, issue.message)
                    for issue in entry.issues
                )
                if entry.verdict is not None:
                    dkim_rows.extend(entry.verdict.result_rows(mail_id, checked_at))
            await copy_rows(session, "mail", MAIL_COLUMNS, mails)
            await copy_rows(session, "participation", PARTICIPATION_COLUMNS, participations)
            await copy_rows(session, "attachment", ATTACHMENT_COLUMNS, attachments)
            await _copy_dicts(session, "dkim_result", dkim_rows)
            await copy_rows(session, "import_error", IMPORT_ERROR_COLUMNS, errors)
            if self._checker is not None:
                await dkim_hook.save_answers(session, self._checker.take_new_answers())
            await session.execute(
                _PROGRESS,
                {
                    "id": mbox_file_id,
                    "end": batch.end,
                    "mails": len(batch),
                    "errors": len(errors),
                },
            )

    async def _persons(self, session: AsyncSession, batch: Batch) -> Mapping[str, int]:
        """Person ids of every address in the batch, creating persons for new addresses."""
        emails = {address.email for entry in batch.entries for address in _addresses(entry.mail)}
        unknown = sorted(emails - self._person_ids.keys())  # sorted: no deadlock between workers
        if unknown:
            domains = [email.rpartition("@")[2] for email in unknown]
            async with session.begin():
                await session.execute(_INSERT_PERSONS, {"emails": unknown, "domains": domains})
                await session.execute(_INSERT_PERSON_EMAILS, {"emails": unknown})
                rows = await session.execute(_PERSON_IDS, {"emails": unknown})
                self._person_ids.update((email, person_id) for email, person_id in rows)
        return self._person_ids


def _addresses(mail: ParsedMail) -> Iterator[ParsedAddress]:
    yield from mail.sender
    yield from mail.to
    yield from mail.cc
    yield from mail.bcc


def _mail_row(mail_id: int, mbox_file_id: int, entry: BatchEntry) -> tuple[Any, ...]:
    mail = entry.mail
    return (
        mail_id,
        mbox_file_id,
        entry.byte_offset,
        entry.byte_length,
        mail.message_id,
        mail.in_reply_to,
        list(mail.reference_ids) or None,
        mail.subject,
        mail.date_utc,
        entry.raw_sha256,
        mail.has_attachments,
        mail.body_text,
        None if entry.verdict is None else entry.verdict.status.value,
        mail.list_id,
        mail.automated,
    )


def _participation_rows(
    mail_id: int, mail: ParsedMail, person_ids: Mapping[str, int]
) -> list[tuple[int, int, str, str | None]]:
    """One row per (person, role): an address repeated in a role, or two addresses of the same
    person, count once, with the first display name given."""
    names: dict[tuple[int, ParticipationRole], str | None] = {}
    roles = (
        (ParticipationRole.FROM, mail.sender),
        (ParticipationRole.TO, mail.to),
        (ParticipationRole.CC, mail.cc),
        (ParticipationRole.BCC, mail.bcc),
    )
    for role, addresses in roles:
        for address in addresses:
            key = (person_ids[address.email], role)
            if names.get(key) is None:
                names[key] = address.display_name
    return [(mail_id, person_id, role.value, name) for (person_id, role), name in names.items()]


async def copy_rows(
    session: AsyncSession, table: str, columns: Sequence[str], rows: Sequence[tuple[Any, ...]]
) -> None:
    """COPY rows into a table inside the session's current transaction."""
    if not rows:
        return
    connection = await session.connection()
    driver = (await connection.get_raw_connection()).driver_connection
    assert driver is not None
    await driver.copy_records_to_table(table, records=rows, columns=list(columns))


async def _copy_dicts(session: AsyncSession, table: str, rows: Sequence[dict[str, Any]]) -> None:
    """COPY rows given as dicts; rows with different keys go in separate COPYs, so a column a
    row leaves out keeps its default."""
    groups: defaultdict[tuple[str, ...], list[tuple[Any, ...]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row)].append(tuple(row.values()))
    for columns, values in groups.items():
        await copy_rows(session, table, columns, values)
