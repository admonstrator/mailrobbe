"""The ZIP of an export (D62), streamed: one mail at a time, so neither the ZIP nor more than
one mail is ever held in memory.

    mailrobbe-export-<id>/
        0001-<mail id>/mail.eml    the message as stored, checked against raw_sha256 first
        0001-<mail id>/mail.pdf    pdf.render_pdf
        0001-<mail id>/anhaenge/   (a later milestone puts the attachments here)
        ...
        manifest.json, manifest.csv
        LIESMICH.txt
        SHA256SUMS                 every other file, for sha256sum -c and shasum -a 256 -c

Same bytes again: entries carry the export's created_at as their time, the order is the
stored one, the PDFs take created_at as their date, and nothing reads the clock or a random
source, so a second download gives the same files as long as the archive and the research
data did not change. The end of the first complete download records the SHA-256 of SHA256SUMS,
which vouches for every other file.
"""

import asyncio
import hashlib
import logging
import zipfile
from collections.abc import AsyncGenerator
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.api.schemas import MailResearch
from mailrobbe.config import Settings
from mailrobbe.db.models import MailExport
from mailrobbe.export import records
from mailrobbe.export.manifest import (
    Manifest,
    ManifestExport,
    ManifestFile,
    ManifestFiles,
    ManifestMail,
    mail_entry,
    manifest_csv,
    manifest_json,
)
from mailrobbe.export.pdf import render_pdf
from mailrobbe.export.readme import readme
from mailrobbe.mbox import read_verified

log = logging.getLogger(__name__)

BATCH = 100  # mails whose metadata is read with one set of queries
SUMS = "SHA256SUMS"


def folder_name(export_id: int) -> str:
    return f"mailrobbe-export-{export_id}"


async def stream_export(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, export: MailExport
) -> AsyncGenerator[bytes, None]:
    """The ZIP in pieces. Reads and renders in a worker thread, holds a database connection
    only while it reads a batch of metadata, and records the download after the last piece."""
    archive = _Zip(folder_name(export.id), export.created_at)
    entries: list[ManifestMail] = []
    hashes = export.mail_sha256
    for start in range(0, len(hashes), BATCH):
        batch = hashes[start : start + BATCH]
        async with sessionmaker() as session:
            mails = await records.originals(session, batch)
            notes = await records.research(session, batch) if export.include_research else {}
        for number, sha in enumerate(batch, start + 1):
            entry = await asyncio.to_thread(
                _add_mail, archive, settings, export, number, sha, mails.get(sha), notes.get(sha)
            )
            entries.append(entry)
            if chunk := archive.take():
                yield chunk
    head = ManifestExport(
        id=export.id,
        label=export.label,
        created_by=export.created_by,
        created_at=export.created_at,
        include_research=export.include_research,
        mails=len(entries),
        errors=sum(entry.error is not None for entry in entries),
        selection=export.selection,
    )
    yield await asyncio.to_thread(archive.finish, Manifest(export=head, mails=entries))
    assert archive.sums_sha256 is not None
    await _record_download(sessionmaker, export.id, archive.sums_sha256)


def _add_mail(
    archive: "_Zip",
    settings: Settings,
    export: MailExport,
    number: int,
    sha: str,
    mail: records.ExportMail | None,
    research: MailResearch | None,
) -> ManifestMail:
    """Writes the files of one mail and returns its manifest entry, with an error instead of
    files when its content is not in the archive or not readable as imported."""
    if mail is None:
        return mail_entry(number, sha, None, research, error="not_in_archive")
    source = mail.source
    try:
        message = read_verified(
            settings.mbox_dir / source.path, source.byte_offset, source.byte_length, sha
        )
    except OSError as error:
        log.warning(
            "export %d: mail %d: cannot read %s: %s", export.id, mail.id, source.path, error
        )
        return mail_entry(number, sha, mail, research, error="source_missing")
    if message is None:
        log.warning(
            "export %d: mail %d: %s at offset %d is not the imported mail any more",
            export.id,
            mail.id,
            source.path,
            source.byte_offset,
        )
        return mail_entry(number, sha, mail, research, error="source_changed")
    folder = f"{number:04d}-{mail.id}"
    eml = archive.add(f"{folder}/mail.eml", message)
    pdf = render_pdf(
        mail,
        message,
        created_at=export.created_at,
        export_id=export.id,
        research=research,
    )
    files = ManifestFiles(eml=eml, pdf=archive.add(f"{folder}/mail.pdf", pdf))
    return mail_entry(number, sha, mail, research, folder=folder, files=files)


async def _record_download(
    sessionmaker: async_sessionmaker[AsyncSession], export_id: int, sums_sha256: str
) -> None:
    """Keeps the SHA-256 of the first complete download; a later one that differs is logged."""
    async with sessionmaker() as session:
        recorded = await session.scalar(
            update(MailExport)
            .where(MailExport.id == export_id, MailExport.manifest_sha256.is_(None))
            .values(manifest_sha256=sums_sha256, downloaded_at=func.now())
            .returning(MailExport.id)
        )
        if recorded is None:
            first = await session.scalar(
                select(MailExport.manifest_sha256).where(MailExport.id == export_id)
            )
            if first not in (None, sums_sha256):
                log.warning(
                    "export %d: SHA256SUMS of this download is %s, the first one's %s; the "
                    "archive, the research data or Mailrobbe changed in between",
                    export_id,
                    sums_sha256,
                    first,
                )
        await session.commit()


class _Sink:
    """The file the ZipFile writes to: it keeps what was written until take() hands it over."""

    def __init__(self) -> None:
        self._parts: list[bytes] = []

    def write(self, data: bytes) -> int:
        self._parts.append(bytes(data))
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        pass

    def take(self) -> bytes:
        data = b"".join(self._parts)
        self._parts.clear()
        return data


class _Zip:
    """A ZIP written file by file into a _Sink. The sink cannot seek, so zipfile puts sizes
    and checksums behind each file (data descriptors), as streaming ZIPs do."""

    def __init__(self, folder: str, created_at: datetime) -> None:
        self.folder = folder
        utc = created_at.astimezone(UTC)  # ZIP times have no zone
        self.time = (utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second)
        self.sums: list[str] = []  # lines of SHA256SUMS
        self.sums_sha256: str | None = None
        self._sink = _Sink()
        self._zip = zipfile.ZipFile(self._sink, "w")

    def add(self, path: str, data: bytes) -> ManifestFile:
        """Adds folder/path; path is relative to the export's folder, as SHA256SUMS lists it."""
        info = zipfile.ZipInfo(f"{self.folder}/{path}", date_time=self.time)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3  # Unix on every platform, so external_attr is a file mode
        info.external_attr = 0o644 << 16
        self._zip.writestr(info, data)
        digest = hashlib.sha256(data).hexdigest()
        self.sums.append(f"{digest}  {path}\n")
        return ManifestFile(path=path, size=len(data), sha256=digest)

    def take(self) -> bytes:
        return self._sink.take()

    def finish(self, manifest: Manifest) -> bytes:
        """Adds the manifests, LIESMICH.txt and SHA256SUMS, closes the ZIP and returns the rest."""
        self.add("manifest.json", manifest_json(manifest))
        self.add("manifest.csv", manifest_csv(manifest))
        self.add("LIESMICH.txt", readme(manifest.export, self.folder))
        sums = "".join(self.sums).encode()
        self.sums_sha256 = hashlib.sha256(sums).hexdigest()
        self.add(SUMS, sums)
        self._zip.close()
        return self.take()
