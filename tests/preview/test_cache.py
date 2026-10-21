"""The preview cache (D124): its layout, atomic writes, remembered failures, versions, and a
directory that cannot be used."""

import logging
import os
from pathlib import Path

import pytest

from mailrobbe.preview import cache as cache_module
from mailrobbe.preview import convert, media
from mailrobbe.preview.cache import Failed, PreviewCache

SHA = "ab" + "0" * 62
OTHER = "cd" + "1" * 62


def files(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


def test_pages_failures_and_media(tmp_path: Path) -> None:
    cache = PreviewCache(tmp_path / "previews")
    assert cache.page(SHA) is None and cache.media(SHA) is None
    cache.store_page(SHA, b"<!doctype html>Seite")
    cache.store_failure(OTHER, "damaged document: kaputt")
    stored = cache.store_media(SHA, b"RIFF....WAVE")
    assert cache.page(SHA) == b"<!doctype html>Seite"
    assert cache.page(OTHER) == Failed("damaged document: kaputt")
    assert stored == cache.media(SHA) == tmp_path / "previews" / f"media/ab/{SHA}.v1"
    assert stored is not None and stored.read_bytes() == b"RIFF....WAVE"
    assert files(tmp_path / "previews") == [
        f"html/ab/{SHA}.v{convert.VERSION}.html",
        f"html/cd/{OTHER}.v{convert.VERSION}.failed",
        f"media/ab/{SHA}.v{media.VERSION}",
    ]
    assert convert.VERSION == media.VERSION == 1


def test_a_new_version_converts_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = PreviewCache(tmp_path)
    cache.store_page(SHA, b"alt")
    cache.store_failure(OTHER, "alt")
    cache.store_media(SHA, b"alt")
    monkeypatch.setattr(convert, "VERSION", 2)
    monkeypatch.setattr(media, "VERSION", 2)
    assert cache.page(SHA) is None and cache.page(OTHER) is None and cache.media(SHA) is None


def test_writes_are_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = PreviewCache(tmp_path)
    cache.store_page(SHA, b"erste Fassung")

    def broken(fd: int) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", broken)  # fails after the bytes were written
    cache.store_page(SHA, b"zweite Fassung, halb geschrieben")
    assert cache.store_media(SHA, b"Ton") is None
    assert cache.page(SHA) == b"erste Fassung"
    assert files(tmp_path) == [f"html/ab/{SHA}.v1.html"]  # no temporary file left


def test_an_unusable_directory_only_means_no_cache(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = tmp_path / "previews"
    root.write_text("a file where the directory should be")
    cache = PreviewCache(root)
    with caplog.at_level(logging.WARNING, logger=cache_module.__name__):
        cache.store_page(SHA, b"Seite")
        cache.store_failure(OTHER, "kaputt")
        assert cache.store_media(SHA, b"Ton") is None
        assert cache.page(SHA) is None and cache.page(OTHER) is None
        assert cache.media(SHA) is None
    assert [record.getMessage() for record in caplog.records] == [
        f"preview cache {root} is not usable ([Errno 20] Not a directory: '{root}/html/ab'); "
        "previews are not cached"
    ]


def test_only_sha256_names(tmp_path: Path) -> None:
    cache = PreviewCache(tmp_path)
    for name in ("../" + SHA[3:], SHA.upper(), SHA[:-1], ""):
        with pytest.raises(ValueError, match="not a SHA-256"):
            cache.page(name)
