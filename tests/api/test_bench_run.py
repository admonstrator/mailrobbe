"""`mailrobbe bench` against a real server: uvicorn in a thread, on the imported test archive."""

import json
import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn
from pydantic import SecretStr

from mailrobbe import cli
from mailrobbe.api.app import create_app
from mailrobbe.config import Settings
from tests.api.conftest import api_settings
from tests.conftest import GeneratedArchive

pytestmark = pytest.mark.db


@contextmanager
def running_server(settings: Settings) -> Iterator[str]:
    """The API served by uvicorn in a thread on a free port; its URL."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(create_app(settings), log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline, "the server did not start"
            time.sleep(0.05)
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    finally:
        server.should_exit = True
        thread.join(20)
        sock.close()


def test_bench_measures_every_scenario_of_a_real_server(
    imported_database_url: str,
    generated_archive: GeneratedArchive,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = api_settings(imported_database_url, generated_archive, tmp_path / "no-frontend")
    report = tmp_path / "bench.json"
    with running_server(settings) as url:
        status = cli.main(
            ["bench", "--url", url, "--rounds", "1", "--with-export", "--json", str(report)]
        )
    output = capsys.readouterr().out
    assert status == 0, output
    results = json.loads(report.read_text())
    assert results["skipped"] == []
    assert results["failed"] == 0
    assert len(results["scenarios"]) == results["requests"] == 54
    assert all(row["errors"] == [] and row["size_bytes"] > 0 for row in results["scenarios"])
    assert results["samples"]["top_person"] is not None
    assert results["samples"]["document_words"] and results["samples"]["document_id"]
    assert "All 54 requests succeeded" in output
    for row in results["scenarios"]:
        assert row["name"] in output


def test_bench_signs_in_and_filters_by_name(
    imported_database_url: str,
    generated_archive: GeneratedArchive,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = api_settings(imported_database_url, generated_archive, tmp_path / "no-frontend")
    settings = settings.model_copy(
        update={"basic_auth_user": "aaron", "basic_auth_password": SecretStr("geheim")}
    )
    with running_server(settings) as url:
        args = ["bench", "--url", url, "--rounds", "2", "--only", "IMPORT"]
        assert cli.main([*args, "--user", "aaron", "--password", "geheim"]) == 0
        output = capsys.readouterr().out
        assert cli.main(args) == 1  # without credentials
        assert "HTTP 401" in capsys.readouterr().err
    measured = [line.split("  ")[0] for line in output.splitlines() if line.startswith("import ")]
    assert measured == ["import status", "import summary", "import errors"]
    assert "\nstats " not in output
    assert "All 6 requests succeeded" in output
