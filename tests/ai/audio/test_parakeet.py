"""ai.audio.parakeet without the model: the files and their download (D291), the pieces and the
lines (D293)."""

import hashlib
import itertools
import math
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from mailrobbe.ai.audio import parakeet
from mailrobbe.ai.audio.parakeet import (
    MODEL_BYTES,
    PAD_SECONDS,
    ModelFile,
    ModelMissing,
    Piece,
    Transcriber,
    cut_pieces,
    download_model,
    model_state,
    token_lines,
)
from mailrobbe.ai.model import PIECE_SECONDS, SEGMENT_SECONDS

# The model files ------------------------------------------------------------------------------

ENCODER = bytes(range(256)) * 40  # 10,240 bytes
VOCAB = "".join(f"tok{n} {n}\n" for n in range(300)).encode()


def _file(name: str, data: bytes) -> ModelFile:
    return ModelFile("test/model", "rev1", name, len(data), hashlib.sha256(data).hexdigest())


FILES = {"parakeet": (_file("encoder.onnx", ENCODER),), "silero": (_file("vocab.txt", VOCAB),)}
TOTAL = len(ENCODER) + len(VOCAB)


class _Server(ThreadingHTTPServer):
    files: dict[str, bytes]
    ranges: list[str | None]  # the Range header of each request
    cuts: int  # responses still to cut after cut_after bytes of their body
    cut_after: int
    ignore_range: bool


class _Handler(BaseHTTPRequestHandler):
    server: _Server

    def do_GET(self) -> None:
        state = self.server
        asked = self.headers.get("Range")
        state.ranges.append(asked)
        data = state.files.get(self.path)
        if data is None:
            self.send_error(404)
            return
        start = 0
        if asked and not state.ignore_range:
            start = int(asked.removeprefix("bytes=").partition("-")[0])
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
        else:
            self.send_response(200)
        body = data[start:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if state.cuts > 0:
            state.cuts -= 1
            body = body[: state.cut_after]
            self.close_connection = True
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> Iterator[_Server]:
    found = _Server(("127.0.0.1", 0), _Handler)
    found.files = {"/test/model/encoder.onnx": ENCODER, "/test/model/vocab.txt": VOCAB}
    found.ranges, found.cuts, found.cut_after, found.ignore_range = [], 0, 0, False
    thread = threading.Thread(target=found.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{found.server_address[1]}"
    monkeypatch.setattr(ModelFile, "url", property(lambda f: f"{base}/{f.repository}/{f.name}"))
    monkeypatch.setattr(parakeet, "MODEL_FILES", FILES)
    monkeypatch.setattr(parakeet, "_CHUNK", 1000)
    yield found
    found.shutdown()
    found.server_close()


def _download(model_dir: Path, stop: threading.Event | None = None) -> list[int]:
    chunks: list[int] = []
    download_model(model_dir, progress=chunks.append, stop=stop or threading.Event(), timeout=5)
    return chunks


def _complete(model_dir: Path) -> bool:
    return (model_dir / "parakeet" / "encoder.onnx").read_bytes() == ENCODER and (
        model_dir / "silero" / "vocab.txt"
    ).read_bytes() == VOCAB


def test_the_pinned_files_add_up_to_the_model() -> None:
    assert sum(f.size for files in parakeet.MODEL_FILES.values() for f in files) == MODEL_BYTES
    assert 600_000_000 < MODEL_BYTES < 700_000_000
    encoder = parakeet.MODEL_FILES[parakeet.PARAKEET_DIR][-1]
    assert encoder.url == (
        "https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx/resolve/"
        "8f23f0c03c8761650bdb5b40aaf3e40d2c15f1ce/encoder-model.int8.onnx"
    )
    state = model_state(Path("/nonexistent"))
    assert state == parakeet.ModelState(False, MODEL_BYTES, MODEL_BYTES)


def test_a_download_puts_every_file_in_place(server: _Server, tmp_path: Path) -> None:
    assert model_state(tmp_path).missing_bytes == TOTAL
    chunks = _download(tmp_path)
    assert sum(chunks) == TOTAL and max(chunks) <= 1000
    assert _complete(tmp_path) and not list(tmp_path.rglob("*.part"))
    assert model_state(tmp_path) == parakeet.ModelState(True, 0, TOTAL)
    asked = len(server.ranges)
    assert _download(tmp_path) == [] and len(server.ranges) == asked  # nothing to do


def test_a_cut_transfer_resumes_where_it_stopped(server: _Server, tmp_path: Path) -> None:
    server.cuts, server.cut_after = 1, 3000
    chunks = _download(tmp_path)
    assert _complete(tmp_path) and sum(chunks) == TOTAL
    assert server.ranges[:2] == ["bytes=0-", "bytes=3000-"]


def test_a_part_left_by_failed_tries_is_resumed_by_the_next_run(
    server: _Server, tmp_path: Path
) -> None:
    server.cuts, server.cut_after = 3, 2000
    with pytest.raises(ModelMissing, match=r"encoder\.onnx: .*copied into .* by hand"):
        _download(tmp_path)
    part = tmp_path / "parakeet" / "encoder.onnx.part"
    assert part.read_bytes() == ENCODER[:6000]
    assert model_state(tmp_path).missing_bytes == TOTAL - 6000
    chunks = _download(tmp_path)
    assert server.ranges[-2] == "bytes=6000-" and sum(chunks) == TOTAL - 6000
    assert _complete(tmp_path)


def test_a_server_answering_200_starts_the_file_again(server: _Server, tmp_path: Path) -> None:
    part = tmp_path / "parakeet" / "encoder.onnx.part"
    part.parent.mkdir(parents=True)
    part.write_bytes(b"x" * 5000)  # not what the server has: the hash would catch it
    server.ignore_range = True
    chunks = _download(tmp_path)
    assert server.ranges[0] == "bytes=5000-" and sum(chunks) == TOTAL
    assert _complete(tmp_path)


def test_a_wrong_hash_drops_the_download(
    server: _Server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    wrong = {"parakeet": (ModelFile("test/model", "rev1", "encoder.onnx", len(ENCODER), "0" * 64),)}
    monkeypatch.setattr(parakeet, "MODEL_FILES", wrong)
    with pytest.raises(ModelMissing, match="not the pinned file"):
        _download(tmp_path)
    assert not list((tmp_path / "parakeet").iterdir())


def test_a_stop_keeps_what_came(server: _Server, tmp_path: Path) -> None:
    stop = threading.Event()
    chunks: list[int] = []

    def progress(size: int) -> None:
        chunks.append(size)
        stop.set()

    download_model(tmp_path, progress=progress, stop=stop, timeout=5)
    assert chunks == [1000]
    assert (tmp_path / "parakeet" / "encoder.onnx.part").stat().st_size == 1000
    assert not (tmp_path / "parakeet" / "encoder.onnx").exists()
    assert sum(_download(tmp_path)) == TOTAL - 1000 and _complete(tmp_path)


def test_unreachable_files_raise_model_missing(
    server: _Server, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del server.files["/test/model/vocab.txt"]
    with pytest.raises(ModelMissing, match=r"vocab\.txt: 127\.0\.0\.1 answered HTTP 404"):
        _download(tmp_path)
    assert (tmp_path / "parakeet" / "encoder.onnx").exists()  # what came stays
    monkeypatch.setattr(ModelFile, "url", property(lambda f: f"http://127.0.0.1:9/{f.name}"))
    with pytest.raises(ModelMissing, match=r"vocab\.txt: .*refused.*by hand"):
        _download(tmp_path)
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")
    with pytest.raises(ModelMissing, match="cannot write"):
        _download(blocked)


def test_the_transcriber_needs_the_model(tmp_path: Path) -> None:
    with pytest.raises(ModelMissing, match=f"{MODEL_BYTES:,} bytes of the model are missing"):
        Transcriber(tmp_path, threads=1)


# Pieces ---------------------------------------------------------------------------------------


def test_no_speech_gives_no_pieces() -> None:
    assert cut_pieces([], end=30.0) == []


def test_speech_across_short_pauses_is_one_padded_piece() -> None:
    speech = [(1.0, 3.0), (3.5, 6.0), (6.9, 9.0)]  # pauses below a second
    assert cut_pieces(speech, end=10.0) == [Piece(0.8, 9.2)]
    assert cut_pieces([(0.05, 2.0)], end=2.1) == [Piece(0.0, 2.1)]  # the recording's bounds


def test_a_long_pause_parts_pieces_and_their_padding_never_overlaps() -> None:
    pieces = cut_pieces([(1.0, 4.0), (5.2, 8.0)], end=8.1)
    assert pieces == [Piece(0.8, 4.2), Piece(5.0, 8.1)]


def test_a_long_stretch_is_cut_at_the_longest_pause_of_each_window() -> None:
    speech = []
    start = 0.0
    for sentence in range(21):  # of 3 s with pauses of 0.3 s, one of 0.7 s after 19.5 s
        speech.append((round(start, 2), round(start + 3, 2)))
        start += 3.7 if sentence == 5 else 3.3
    pieces = cut_pieces(speech, end=80.0)
    assert all(p.end - p.start <= PIECE_SECONDS + 1e-3 for p in pieces)
    assert all(a.end <= b.start for a, b in itertools.pairwise(pieces))
    assert pieces[0] == Piece(0.0, 19.7)  # at the longest pause, padded
    assert all(p.end - p.start > PIECE_SECONDS / 2 for p in pieces[:-1])
    for piece in pieces:  # each ends at the end of a sentence and its padding
        ended = max(end for _, end in speech if end <= piece.end)
        assert 0 < piece.end - ended <= PAD_SECONDS + 1e-9
    assert pieces[-1].end == pytest.approx(speech[-1][1] + PAD_SECONDS)
    assert len(pieces) == 4


def test_speech_without_a_pause_is_cut_where_it_must() -> None:
    pieces = cut_pieces([(2.0, 62.0)], end=64.0)
    width = PIECE_SECONDS - 2 * PAD_SECONDS
    assert pieces == [
        Piece(1.8, 2.0 + width),
        Piece(2.0 + width, 2.0 + 2 * width),
        Piece(2.0 + 2 * width, 62.2),
    ]


def test_pieces_start_where_the_reading_goes_on() -> None:
    assert cut_pieces([(10.05, 12.0)], start=10.0, end=20.0) == [Piece(10.0, 12.2)]


# Lines ----------------------------------------------------------------------------------------

PIECE = Piece(10.0, 40.0)


def lines(tokens: list[tuple[str, float]], *, logprob: float = math.log(0.9), **kwargs: Any) -> Any:
    piece = kwargs.pop("piece", PIECE)
    uncertain = kwargs.pop("uncertain", 0.5)
    return token_lines(
        [token for token, _ in tokens],
        [time for _, time in tokens],
        kwargs.pop("logprobs", [logprob] * len(tokens)),
        piece=piece,
        uncertain=uncertain,
    )


def test_a_line_ends_with_its_sentence() -> None:
    found = lines([(" Hallo", 0.0), (",", 0.32), (" hier", 0.48), (" ist", 0.8), (" Anna", 0.96),
                   (".", 1.28), (" Wie", 1.44), (" geht", 1.6), (" es", 1.76), ("?", 1.92),
                   (" Gut", 2.4), ("!", 2.56)])  # fmt: skip
    assert [(s.start, s.end, s.text) for s in found] == [
        (10.0, 11.44, "Hallo, hier ist Anna."),  # up to the next line's start
        (11.44, 12.16, "Wie geht es?"),  # its last token and a step
        (12.4, 12.8, "Gut!"),
    ]
    assert all(s.confidence == 0.9 and not s.uncertain for s in found)


def test_a_pause_ends_a_line_and_words_stay_whole() -> None:
    found = lines([(" Der", 0.0), (" Be", 0.16), ("trag", 0.24), (" ist", 0.4),
                   (" ge", 1.6), ("bucht", 1.68), (" 1", 1.92), (".", 2.0), ("000", 2.08),
                   (" Euro", 2.24)])  # fmt: skip
    assert [s.text for s in found] == ["Der Betrag ist", "gebucht 1.000 Euro"]
    assert found[1].start == 11.6


def test_a_line_lasts_at_most_segment_seconds() -> None:
    tokens = [(f" w{n}", n * 0.5) for n in range(80)]  # 40 s without an end or a pause
    found = lines(tokens, piece=Piece(0.0, 45.0))
    assert len(found) == 3 and all(s.end - s.start <= SEGMENT_SECONDS for s in found)
    assert found[-1].end == 39.74 and " ".join(s.text for s in found) == " ".join(
        token.strip() for token, _ in tokens
    )


def test_times_stay_inside_the_piece() -> None:
    found = lines([(" Ende", 0.4), (".", 0.56)], piece=Piece(3.0, 3.6))
    assert (found[0].start, found[0].end) == (3.4, 3.6)


def test_confidence_is_the_mean_token_probability() -> None:
    probabilities = [0.9, 0.3, 0.2, 0.95]
    found = lines([(" Sit", 0.0), ("zung", 0.08), (" ver", 0.24), ("legt", 0.32)],
                  logprobs=[math.log(p) for p in probabilities], uncertain=0.6)  # fmt: skip
    assert found[0].confidence == round(sum(probabilities) / 4, 3) and found[0].uncertain
    assert not lines([(" a", 0.0)], logprobs=None)[0].uncertain
    assert lines([(" a", 0.0)], logprobs=None)[0].confidence is None


def test_humming_and_hesitation_alone_make_no_line() -> None:
    hum = [(" M", 0.0), ("m", 0.08), ("-", 0.16), ("h", 0.24), ("mm", 0.32), (".", 0.4)]
    assert lines(hum) == []
    assert lines([(" Hmm", 0.0), ("?", 0.08), (" Äh", 1.2), ("m", 1.28)]) == []
    found = lines([(" Äh", 0.0), (",", 0.08), (" ja", 0.24), (".", 0.32)])
    assert [s.text for s in found] == ["Äh, ja."]
    assert lines([]) == [] and lines([(" ", 0.0)]) == []
