from datetime import date, timedelta
from pathlib import Path

import pytest

from mailspider.cli import build_parser, main
from mailspider.generator.cli import config_from_args
from mailspider.generator.config import GeneratorConfig, parse_size


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1024", 1024),
        ("128MB", 128 * 1024**2),
        ("4GB", 4 * 1024**3),
        ("512KiB", 512 * 1024),
        ("1.5g", int(1.5 * 1024**3)),
    ],
)
def test_parse_size(text: str, expected: int) -> None:
    assert parse_size(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "12XB", "0", "-5MB"])
def test_parse_size_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        parse_size(text)


def test_config_validation() -> None:
    with pytest.raises(ValueError):
        GeneratorConfig(out_dir=Path("o"), meta_dir=Path("m"), mails=0)
    with pytest.raises(ValueError):
        GeneratorConfig(
            out_dir=Path("o"),
            meta_dir=Path("m"),
            date_from=date(2020, 1, 1),
            date_to=date(2019, 1, 1),
        )
    with pytest.raises(ValueError):
        GeneratorConfig(out_dir=Path("o"), meta_dir=Path("m"), fault_rate=1.5)
    with pytest.raises(ValueError, match="future"):
        GeneratorConfig(
            out_dir=Path("o"),
            meta_dir=Path("m"),
            date_to=date.today() + timedelta(days=1),
        )


def test_cli_maps_onto_config(tmp_path: Path) -> None:
    args = build_parser().parse_args(
        ["generate", "--out", str(tmp_path), "--mails", "500", "--file-size", "4MB", "--jobs", "2"]
    )
    config = config_from_args(args)
    assert config.out_dir == tmp_path
    assert config.meta_dir == tmp_path / "_generator"
    assert config.mails == 500
    assert config.file_size == 4 * 1024**2
    assert config.jobs == 2


def test_cli_refuses_existing_output(tmp_path: Path) -> None:
    (tmp_path / "mbox-0001.mbox").write_bytes(b"")
    assert main(["generate", "--out", str(tmp_path), "--mails", "10", "--quiet"]) == 2
