"""stored_settings without a database: what the page may change and how stored values apply."""

import logging

import pytest
from pydantic import ByteSize, SecretStr

from mailrobbe.config import Settings
from mailrobbe.stored_settings import EDITABLE, FIXED, apply, json_value


def test_every_setting_is_either_editable_or_fixed() -> None:
    assert set(Settings.model_fields) >= FIXED
    assert set(EDITABLE) | FIXED == set(Settings.model_fields)
    assert not FIXED & set(EDITABLE)


def test_stored_values_go_over_the_environments() -> None:
    base = Settings(timezone="UTC", ai_text_model="small")
    settings = apply(base, {"timezone": "Europe/Berlin", "import_attachment_hash_limit": 1024})
    assert (settings.timezone, settings.ai_text_model) == ("Europe/Berlin", "small")
    assert settings.import_attachment_hash_limit == 1024
    assert base.timezone == "UTC"


def test_a_value_no_longer_taken_is_left_out(caplog: pytest.LogCaptureFixture) -> None:
    base = Settings(database_url="postgresql+asyncpg://db/mailrobbe")
    stored = {
        "ai_context_tokens": 100,  # below its bound
        "block_min_mails": 5,
        "database_url": "postgresql+asyncpg://elsewhere/x",  # fixed: never from the table
        "renamed_setting": 1,
    }
    with caplog.at_level(logging.WARNING):
        settings = apply(base, stored)
    assert (settings.ai_context_tokens, settings.block_min_mails) == (4096, 5)
    assert settings.database_url == base.database_url
    assert "ai_context_tokens" in caplog.text


def test_json_values_are_plain() -> None:
    assert json_value(SecretStr("key")) == "key"
    assert json_value(ByteSize(2048)) == 2048
    assert type(json_value(ByteSize(2048))) is int
    assert json_value(True) is True
