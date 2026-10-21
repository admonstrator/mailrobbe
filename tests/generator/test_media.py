"""Pictures and recordings of the generator (D125): real files that browsers show and play,
their ground truth in the manifest, and their way through the importer into the database."""

import asyncio
import hashlib
import json
import random
import struct
import zlib
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import pool, text
from sqlalchemy.ext.asyncio import create_async_engine

from mailrobbe import migrate
from mailrobbe.attachments.kinds import HEAD_SIZE, classify
from mailrobbe.config import Settings
from mailrobbe.enums import DocumentKind
from mailrobbe.generator import documents
from mailrobbe.generator import fileformats as ff
from mailrobbe.generator.config import DNS_OVERRIDE_NAME, MANIFEST_NAME, GeneratorConfig
from mailrobbe.generator.model import AttachmentSpec, DocumentSpec
from mailrobbe.generator.pipeline import generate
from mailrobbe.importer.cli import run_import
from mailrobbe.preview.kinds import preview_kind
from tests.conftest import _temporary_database
from tests.generator.conftest import small_config

WHEN = datetime(2021, 5, 4, 10, 0, tzinfo=UTC)
RECORDINGS = [
    f"{form}-{number}.{form}"
    for form, (_, count) in documents.RECORDING_FORMS.items()
    for number in range(1, count + 1)
]
PHOTOS = ["jpeg-1.jpeg", "jpeg-2.jpeg", "jpeg-3.jpeg"]
RECORDED = frozenset(documents.RECORDING_FORMS)
ASF = bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")


def _format(data: bytes) -> str:
    """The format the first bytes prove, read here without attachments.kinds."""
    if data.startswith(b"ID3"):
        tag = 10 + sum(byte << (7 * (3 - i)) for i, byte in enumerate(data[6:10]))
        return "mp3" if data[tag] == 0xFF and data[tag + 1] & 0xE0 == 0xE0 else "?"
    if data[0] == 0xFF and data[1] & 0xE0 == 0xE0:
        return "mp3"  # an MPEG audio frame
    if data[4:8] == b"ftyp":
        return {b"M4A ": "m4a", b"qt  ": "mov", b"isom": "mp4"}.get(data[8:12], "?")
    if data.startswith(b"RIFF"):
        return {b"WAVE": "wav", b"AVI ": "avi"}.get(data[8:12], "?")
    if data.startswith(b"OggS"):
        return "ogg" if b"OpusHead" in data[:64] or b"\x01vorbis" in data[:64] else "?"
    if data.startswith(b"\x1aE\xdf\xa3"):
        return "webm" if b"\x42\x82\x84webm" in data[:64] else "?"
    if data.startswith(b"\xff\xd8\xff\xe0") and data[6:11] == b"JFIF\x00":
        return "jpeg"
    if data.startswith(b"fLaC"):
        return "flac"
    if data.startswith(ASF):
        return "wma"
    return "?"


@pytest.mark.parametrize("name", RECORDINGS + PHOTOS)
def test_media_files_are_what_their_names_say(name: str) -> None:
    data = ff.fixture(name)
    form = name.rpartition(".")[2]
    assert _format(data) == form
    assert len(data) <= 60_000
    kind = DocumentKind.IMAGE if form == "jpeg" else DocumentKind.MEDIA
    assert classify(f"Datei.{form}", "application/octet-stream", data[:HEAD_SIZE]).kind is kind
    if form in ("mp4", "m4a", "mov"):
        index, media = data.find(b"moov"), data.find(b"mdat")
        assert (index < media) == (form != "mov")  # faststart; QuickTime as phones write it
        assert b"mp4a" in data and (form == "m4a" or b"avc1" in data)
    if form == "webm":
        assert (b"V_VP8" in data or b"V_VP9" in data) and (b"A_OPUS" in data or b"A_VORBIS" in data)


def test_media_holds_the_files_the_generator_uses() -> None:
    names = {path.name for path in ff.MEDIA_DIR.iterdir()}
    assert names == {*RECORDINGS, *PHOTOS, "README.md"}
    contents = [ff.fixture(name) for name in RECORDINGS + PHOTOS]
    assert len({hashlib.sha256(data).digest() for data in contents}) == len(contents)
    assert sum(map(len, contents)) < 320_000


def _png_chunks(data: bytes) -> list[tuple[bytes, bytes, bool]]:
    """(type, data, CRC correct) of every chunk, the last one possibly cut short."""
    chunks = []
    position = 8
    while position < len(data):
        length, kind = struct.unpack(">I4s", data[position : position + 8])
        body = data[position + 8 : position + 8 + length]
        crc = data[position + 8 + length : position + 12 + length]
        chunks.append((kind, body, crc == struct.pack(">I", zlib.crc32(kind + body))))
        position += 12 + length
    return chunks


def _jpeg_segments(data: bytes) -> list[int]:
    """The markers up to the scan, in order; stops where the bytes end."""
    markers = []
    position = 2
    while position + 4 <= len(data):
        marker = data[position + 1]
        markers.append(marker)
        if marker == 0xDA:
            break
        position += 2 + int.from_bytes(data[position + 2 : position + 4], "big")
    return markers


@pytest.mark.parametrize("size", [100, 3_000, 70_000, 700_000, 2_500_000])
def test_pictures_have_their_size_and_bytes_of_their_own(size: int) -> None:
    pictures = [ff.png(random.Random(seed), size) for seed in range(3)]
    for data in pictures:
        chunks = _png_chunks(data)
        assert [kind for kind, _, _ in chunks] == [b"IHDR", b"paDd", b"IDAT", b"IEND"]
        assert all(ok for _, _, ok in chunks)
        width, height = struct.unpack(">II", chunks[0][1][:8])
        assert len(zlib.decompress(chunks[2][1])) == height * (1 + 3 * width)
        assert len(data) == size or len(chunks[1][1]) == 64  # the least noise
    photos = [ff.jpeg(random.Random(seed), size) for seed in range(3)]
    for data in photos:
        markers = _jpeg_segments(data)
        assert markers[0] == 0xE0 and markers[1] == 0xFE and markers[-1] == 0xDA
        assert {0xDB, 0xC4, 0xC0} <= set(markers)
        assert data.endswith(b"\xff\xd9")
        assert abs(len(data) - size) <= 4 or size < 15_000
    for found in (pictures, photos):
        assert len({hashlib.sha256(data).digest() for data in found}) == 3


def test_damaged_pictures_stop_before_their_image() -> None:
    for seed in range(20):
        png = ff.png(random.Random(seed), 50_000, damaged=True)
        chunks = _png_chunks(png)
        assert [kind for kind, _, _ in chunks] == [b"IHDR", b"paDd"] and not chunks[1][2]
        jpeg = ff.jpeg(random.Random(seed), 50_000, damaged=True)
        markers = _jpeg_segments(jpeg)
        assert markers[:2] == [0xE0, 0xFE] and 0xC0 not in markers and len(jpeg) < 50_000
        for data, name in ((png, "Foto.png"), (jpeg, "IMG_1.jpg")):
            assert classify(name, "image/png", data[:HEAD_SIZE]).kind is DocumentKind.IMAGE


@pytest.mark.parametrize(
    ("form", "filename", "mime_type", "preview", "media_type"),
    [
        ("png", "Foto.png", "image/png", "image", "image/png"),
        ("png_damaged", "image001.png", "image/png", "image", "image/png"),
        ("jpeg", "IMG_1234.jpg", "application/octet-stream", "image", "image/jpeg"),
        ("m4a", "Sprachnachricht_1.m4a", "audio/x-m4a", "audio", "audio/mp4"),
        ("mp3", "Mitschnitt_2021-05-04.mp3", "application/octet-stream", "audio", "audio/mpeg"),
        ("wav", "Ansage.wav", "audio/x-wav", "audio", "audio/wav"),
        ("ogg", "Interview_Peters.ogg", "audio/ogg", "audio", "audio/ogg"),
        ("flac", "Aufnahme.flac", "audio/flac", "audio", "audio/flac"),
        ("mp4", "Video_1234.mp4", "video/mp4", "video", "video/mp4"),
        ("mov", "IMG_1234.MOV", "video/quicktime", "video", "video/quicktime"),
        ("webm", "Clip_Atlas.webm", "application/octet-stream", "video", "video/webm"),
        ("wma", "Diktat_1234.wma", "audio/x-ms-wma", None, None),
        ("avi", "MVI_1234.AVI", "video/x-msvideo", None, None),
    ],
)
def test_truths_of_pictures_and_recordings(
    form: str, filename: str, mime_type: str, preview: str | None, media_type: str | None
) -> None:
    spec = AttachmentSpec(filename, mime_type, 40_000, document=DocumentSpec(5, form, "x", WHEN))
    truth = documents.build(spec).truth(filename, mime_type)
    kind = "image" if form.startswith(("png", "jpeg")) else "media"
    assert (truth.kind, truth.status, truth.marker, truth.pages) == (
        kind,
        "unsupported",
        None,
        None,
    )
    assert (truth.preview, truth.media_type) == (preview, media_type)
    if kind == "media":
        assert truth.size < 60_000  # its recording's size, not the planned one


def test_truths_of_filler() -> None:
    def truth(name: str, mime_type: str, size: int) -> tuple[str | None, str | None]:
        found = documents.filler_truth(AttachmentSpec(name, mime_type, size), "0" * 64)
        return found.preview, found.media_type

    assert truth("Aufzeichnung_Workshop.mp4", "video/mp4", 2 * 1024**2) == ("video", "video/mp4")
    assert truth("Aufzeichnung_Workshop.mp4", "video/mp4", 60 * 1024**2) == (None, None)
    assert truth("Baupläne_komplett.pdf", "application/pdf", 2 * 1024**2) == ("pdf", None)
    assert truth("Projektarchiv_2021.zip", "application/zip", 2 * 1024**2) == (None, None)


def test_the_pool_sends_recordings_and_keeps_pictures() -> None:
    pool = documents.DocumentPool(7)
    offer = AttachmentSpec("Angebot_Atlas.pdf", "application/pdf", 30_000)
    made = [pool.attach(offer, "Angebot_{project}.pdf", WHEN) for _ in range(6000)]
    new = {spec.document: spec for spec in made}
    recordings = [s for s in new.values() if s.document and s.document.form in RECORDED]
    assert 0.015 < len(recordings) / len(new) < 0.05
    types = {mime_type for _, mime_type, _ in documents.RECORDINGS} | {"application/octet-stream"}
    for spec in recordings:
        assert spec.document is not None
        assert spec.filename.lower().endswith(f".{spec.document.form}") and spec.mime_type in types
    photo = AttachmentSpec("IMG_1234.jpg", "image/jpeg", 700_000)
    photos = {pool.attach(photo, "IMG_{n}.jpg", WHEN).document for _ in range(3000)} - set(new)
    forms = Counter(document.form for document in photos if document is not None)
    assert set(forms) == {"jpeg", "jpeg_damaged"}  # never swapped for a paper or a recording
    assert 0.01 < forms["jpeg_damaged"] / forms.total() < 0.12
    logo = AttachmentSpec("image001.png", "image/png", 3_000, inline=True)
    inline = {pool.inline(logo, WHEN).document for _ in range(50)}
    assert len(inline) == 50 and {d.form for d in inline if d is not None} == {"png"}
    later = {pool.attach(offer, "Angebot_{project}.pdf", WHEN).document for _ in range(500)}
    assert not later & inline  # inline pictures do not circulate


# A generated archive full of recordings -----------------------------------------------------


@pytest.fixture(scope="module")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> tuple[GeneratorConfig, GeneratorConfig]:
    """240 mails in which most new documents of people are recordings, made with one job and
    with three."""
    configs = [
        small_config(
            tmp_path_factory.mktemp(f"recorded{jobs}"), mails=240, persons=120, domains=20,
            file_size=2 * 1024**2, large_attachments=0, fault_rate=0.1, duplicate_rate=0.05,
            jobs=jobs,
        )
        for jobs in (1, 3)
    ]  # fmt: skip
    with pytest.MonkeyPatch.context() as patch:  # the planner runs in this process
        patch.setattr(documents, "RECORDING_SHARE", 0.8)
        for config in configs:
            generate(config)
    return configs[0], configs[1]


def test_recordings_do_not_depend_on_jobs(
    recorded: tuple[GeneratorConfig, GeneratorConfig],
) -> None:
    one, three = (
        {
            path.name: path.read_bytes()
            for path in (*c.out_dir.glob("*.mbox"), c.meta_dir / MANIFEST_NAME)
        }
        for c in recorded
    )
    assert one == three


def _manifest(config: GeneratorConfig) -> list[dict[str, Any]]:
    lines = (config.meta_dir / MANIFEST_NAME).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_recordings_in_a_generated_archive_are_their_files(
    recorded: tuple[GeneratorConfig, GeneratorConfig],
) -> None:
    files = {hashlib.sha256(ff.fixture(name)).hexdigest(): name for name in RECORDINGS}
    forms: Counter[str] = Counter()
    for record in _manifest(recorded[1]):
        for truth in record["documents"]:
            if truth["kind"] != "media" or truth["sha256"] is None:
                continue
            form = files[truth["sha256"]].partition("-")[0]
            forms[form] += 1
            media_type, _ = documents.RECORDING_FORMS[form]
            assert truth["media_type"] == media_type
            assert truth["preview"] == (media_type.partition("/")[0] if media_type else None)
            assert truth["status"] == "unsupported" and truth["marker"] is None
    assert len(forms) >= 5, forms


@pytest.fixture(scope="module")
def imported(
    database_server_url: str, recorded: tuple[GeneratorConfig, GeneratorConfig]
) -> Iterator[str]:
    config = recorded[1]
    with _temporary_database(database_server_url) as url:
        migrate.upgrade("head", url)
        settings = Settings(database_url=url, dkim_dns_override=config.meta_dir / DNS_OVERRIDE_NAME)
        assert asyncio.run(run_import(settings, config.out_dir, 2)) == 0
        yield url


async def _attachments(url: str) -> dict[tuple[str, int], list[dict[str, Any]]]:
    """(file, offset) of the mail -> its attachments with their document, by position."""
    engine = create_async_engine(url, poolclass=pool.NullPool)
    found: dict[tuple[str, int], list[dict[str, Any]]] = {}
    async with engine.connect() as connection:
        rows = await connection.execute(
            text(
                "SELECT f.path, m.byte_offset, a.filename, a.mime_type, a.size_bytes, a.sha256, "
                "d.kind::text AS kind, d.text_status::text AS status FROM attachment a "
                "JOIN mail m ON m.id = a.mail_id JOIN mbox_file f ON f.id = m.mbox_file_id "
                "JOIN document d ON d.id = a.document_id ORDER BY a.mail_id, a.position"
            )
        )
        for row in rows:
            found.setdefault((row.path, row.byte_offset), []).append(row._asdict())
    await engine.dispose()
    return found


@pytest.mark.db
@pytest.mark.slow
def test_imported_pictures_and_recordings_match_the_manifest(
    imported: str, recorded: tuple[GeneratorConfig, GeneratorConfig]
) -> None:
    stored = asyncio.run(_attachments(imported))
    max_size = Settings().preview_max_size
    kinds: Counter[str] = Counter()
    for record in _manifest(recorded[1]):
        attachments = stored.get((record["file"], record["offset"]), [])
        assert [a["filename"] for a in attachments] == [t["filename"] for t in record["documents"]]
        for truth, attachment in zip(record["documents"], attachments, strict=True):
            if truth["sha256"] is None:  # the invalid_base64 fault: bytes unknown
                continue
            where = (record["index"], truth["filename"])
            found = [attachment[key] for key in ("sha256", "size_bytes", "kind", "status")]
            assert found == [truth[key] for key in ("sha256", "size", "kind", "status")], where
            hint = preview_kind(
                DocumentKind(attachment["kind"]), attachment["filename"], attachment["mime_type"],
                attachment["size_bytes"], hashed=attachment["sha256"] is not None,
                max_size=max_size,
            )  # fmt: skip
            assert hint == truth["preview"], where
            kinds[truth["kind"]] += 1
    assert kinds["media"] > 10 and kinds["image"] > 0, kinds
