"""generator.documents: recordings with German speech and what a transcript of them must contain
(milestone 16, D297)."""

import base64
import hashlib
import random
from datetime import UTC, datetime
from pathlib import Path

import pytest

from mailrobbe.generator import documents, protection, vocabulary
from mailrobbe.generator import fileformats as ff
from mailrobbe.generator.model import Address, AttachmentSpec, DocumentSpec, PlannedMail
from mailrobbe.generator.render import render

WHEN = datetime(2021, 5, 4, 10, 0, tzinfo=UTC)
FILES = {
    "ogg": ("Interview_Peters.ogg", "audio/ogg"),
    "mp3": ("Mitschnitt_2021-05-04.mp3", "audio/mpeg"),
    "m4a": ("Sprachnachricht_1234.m4a", "audio/x-m4a"),
    "mp4": ("Video_1234.mp4", "video/mp4"),
    "mov": ("IMG_1234.MOV", "video/quicktime"),
}


def with_speech(form: str) -> DocumentSpec:
    """The first recording of this form that carries speech."""
    for seed in range(200):
        spec = DocumentSpec(seed, form, "voice", WHEN)
        if documents.spoken(spec) is not None:
            return spec
    raise AssertionError(f"no {form} with speech")


def test_the_speech_table_names_files_of_its_forms_with_their_words() -> None:
    readme = (ff.MEDIA_DIR / "README.md").read_text(encoding="utf-8")
    sources = (vocabulary.__file__, protection.__file__)
    elsewhere = "".join(Path(source).read_text(encoding="utf-8") for source in sources)
    assert set(documents.SPOKEN) == set(FILES)
    markers = []
    for form, files in documents.SPOKEN.items():
        for speech in files:
            assert speech.file.endswith(f".{form}") and (ff.MEDIA_DIR / speech.file).is_file()
            assert len(speech.words) >= 5 and all(len(word) >= 6 for word in speech.words)
            assert speech.marker in readme and all(word in readme for word in speech.words)
            assert speech.marker not in elsewhere  # a search for it finds the transcript only
            markers.append(speech.marker)
    assert len(set(markers)) == len(markers)


def test_a_share_of_the_recordings_of_the_spoken_forms_carry_speech() -> None:
    for form in documents.RECORDING_FORMS:
        specs = [DocumentSpec(seed, form, "voice", WHEN) for seed in range(2000)]
        share = sum(documents.spoken(spec) is not None for spec in specs) / len(specs)
        expected = documents.SPOKEN_SHARE if form in documents.SPOKEN else 0
        assert share == pytest.approx(expected, abs=0.04), form
    assert documents.spoken(DocumentSpec(1, "pdf", "letter", WHEN)) is None


def test_recordings_without_speech_keep_the_tone_their_seed_chose() -> None:
    """Speech comes from a random stream of its own, so every other recording keeps its bytes."""
    for form, (_, count) in documents.RECORDING_FORMS.items():
        for seed in range(60):
            spec = DocumentSpec(seed, form, "voice", WHEN)
            data, pages = documents.document_bytes(spec, 40_000)
            speech = documents.spoken(spec)
            number = random.Random(f"document:{seed}").randint(1, count)
            name = speech.file if speech else f"{form}-{number}.{form}"
            assert (data, pages) == (ff.fixture(name), None)


@pytest.mark.parametrize("form", sorted(FILES))
def test_a_spoken_recording_carries_its_marker_and_words_into_the_truth(form: str) -> None:
    spec = with_speech(form)
    speech = documents.spoken(spec)
    assert speech is not None and speech == documents.spoken(spec)  # a function of the seed
    filename, mime_type = FILES[form]
    built = documents.build(AttachmentSpec(filename, mime_type, 40_000, document=spec))
    truth = built.truth(filename, mime_type)
    data = base64.b64decode(b"".join(built.encoded))
    assert data == ff.fixture(speech.file) and truth.sha256 == hashlib.sha256(data).hexdigest()
    assert (truth.kind, truth.status, truth.marker, truth.size) == (
        "media",
        "unsupported",
        None,
        len(data),
    )
    assert truth.preview == ("video" if form in ("mp4", "mov") else "audio")
    assert truth.transcript_marker == speech.marker
    found = truth.as_json()
    assert found["transcript_marker"] == speech.marker
    assert found["transcript_words"] == list(speech.words)


def test_tones_and_documents_have_no_transcript_truth() -> None:
    for form, theme in (("ogg", "voice"), ("wma", "voice"), ("pdf", "letter")):
        for seed in range(40):
            spec = DocumentSpec(seed, form, theme, WHEN)
            if documents.spoken(spec) is None:
                break
        truth = documents.build(AttachmentSpec("x", "application/octet-stream", 30_000,
                                               document=spec)).truth("x", "audio/ogg")  # fmt: skip
        assert (truth.transcript_marker, truth.transcript_words) == (None, None)
        assert truth.as_json()["transcript_words"] is None


def test_a_damaged_attachment_loses_its_transcript_truth() -> None:
    filename, mime_type = FILES["ogg"]
    voice = AttachmentSpec(filename, mime_type, 40_000, document=with_speech("ogg"))
    mail = PlannedMail(
        index=0, seed=5, date=WHEN, sender=Address("a@x.example"), to=(Address("b@x.example"),),
        subject="Sprachnachricht", message_id="<1@x.example>", attachments=(voice,),
        client="outlook",
    )  # fmt: skip
    rendered = render(mail)
    assert rendered.documents[0].transcript_marker is not None
    line = b"".join(documents.build(voice).encoded).split(b"\n")[3]
    truths = documents.damaged(rendered.documents, rendered.raw.replace(line, b"!#" + line[2:], 1))
    assert (truths[0].sha256, truths[0].transcript_marker, truths[0].transcript_words) == (
        None,
        None,
        None,
    )
