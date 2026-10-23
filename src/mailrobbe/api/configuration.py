"""The page "Einstellungen" (D313 to D315): GET and PUT /api/settings. Models are in schemas.py;
what is stored and who reads it is stored_settings.

A save checks every new value as the environment's would be checked (config.Settings) and a few
the environment never checks before a run uses them: resolvers are IP addresses, the map source
is protomaps, off or an https URL, a service is an http or https URL, PostgreSQL knows the time
zone. Then it writes all values in one transaction and the server takes them over at once
(deps.refresh_settings). A secret is never sent back, only whether one is set. Writes take the
editor from X-Mailrobbe-Editor (D54).
"""

import urllib.parse
from datetime import UTC, datetime
from typing import Any, Literal, get_args, get_origin

from fastapi import APIRouter, Request
from pydantic import ByteSize, SecretStr, ValidationError
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from mailrobbe.api.deps import AppSettings, Editor, Session, api_error, refresh_settings
from mailrobbe.api.schemas import SettingInfo, SettingKind, SettingsUpdate, SettingsView
from mailrobbe.config import Settings
from mailrobbe.db.models import Setting
from mailrobbe.dkim.keys.zkemail import OFF
from mailrobbe.dkim.resolver import parse_nameservers
from mailrobbe.places.tiles import source_setting
from mailrobbe.signals.model import known_timezone
from mailrobbe.stored_settings import EDITABLE, FIXED, apply, json_value, stored_rows, validate

router = APIRouter(prefix="/api", tags=["settings"])

# URLs and what switches them off instead: empty an AI service, "off" the key archive.
URLS = {"ai_vision_url": "", "ai_text_url": "", "dkim_key_archive_url": OFF}


@router.get("/settings")
async def settings_view(request: Request, session: Session, settings: AppSettings) -> SettingsView:
    return await _view(request, session, settings)


@router.put("/settings")
async def save_settings(
    update: SettingsUpdate, request: Request, session: Session, editor: Editor
) -> SettingsView:
    env: Settings = request.app.state.env_settings
    rows = await stored_rows(session)
    given = {name: value for name, value in update.values.items() if value is not None}
    for name, value in update.values.items():
        if name not in EDITABLE:
            raise api_error(400, "invalid_setting", f"{name}: not a setting of this page")
        if value is not None:
            _check(name, value)
    # The stored values not named here, then the new ones; a reset leaves the environment's.
    kept = {name: row.value for name, row in rows.items() if name not in update.values}
    others = apply(env, kept)
    try:
        checked = validate(others, given)
    except ValidationError as error:
        first = error.errors()[0]
        name = ".".join(str(part) for part in first["loc"])
        raise api_error(400, "invalid_setting", f"{name}: {first['msg']}") from None
    if "timezone" in given and not await known_timezone(session, checked.timezone):
        raise api_error(400, "invalid_setting", "timezone: PostgreSQL does not know it")
    now = datetime.now(UTC)
    for name in update.values:
        value = json_value(getattr(checked, name))
        if name not in given or value == json_value(getattr(env, name)):
            await session.execute(delete(Setting).where(Setting.name == name))
        elif name not in rows or rows[name].value != value:
            row = {"name": name, "value": value, "changed_at": now, "changed_by": editor}
            statement = insert(Setting).values(row)
            await session.execute(
                statement.on_conflict_do_update(index_elements=[Setting.name], set_=row)
            )
    await session.commit()
    await refresh_settings(request.app)
    return await _view(request, session, request.app.state.settings)


def _check(name: str, value: Any) -> None:
    """What the environment's value is checked for only when a run uses it."""
    if not isinstance(value, str):
        return
    try:
        if name == "dkim_nameservers":
            parse_nameservers(value)
        elif name == "map_source":
            source_setting(value)
        elif name in URLS and value.strip().lower() != URLS[name]:
            _http_url(value)
        elif name == "ai_ocr_languages" and not value.strip():
            raise ValueError("Tesseract needs at least one language")
    except ValueError as error:
        raise api_error(400, "invalid_setting", f"{name}: {error}") from None


def _http_url(value: str) -> None:
    parts = urllib.parse.urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"{value!r} is no http or https URL")


async def _view(request: Request, session: Session, settings: Settings) -> SettingsView:
    env: Settings = request.app.state.env_settings
    rows = await stored_rows(session)
    items = []
    for name in EDITABLE:
        field = Settings.model_fields[name]
        kind, choices = _kind(field.annotation)
        secret = kind == "secret"
        row = rows.get(name)
        bounds = {key: getattr(meta, key) for meta in field.metadata for key in meta.__slots__}
        items.append(
            SettingInfo(
                name=name,
                kind=kind,
                value=None if secret else json_value(getattr(settings, name)),
                base=None if secret else json_value(getattr(env, name)),
                source="stored" if row else "env" if name in env.model_fields_set else "default",
                secret_set=secret and bool(json_value(getattr(settings, name))),
                choices=choices,
                minimum=bounds.get("ge"),
                maximum=bounds.get("le"),
                changed_at=row.changed_at if row else None,
                changed_by=row.changed_by if row else None,
            )
        )
    return SettingsView(items=items, fixed=sorted(FIXED))


def _kind(annotation: Any) -> tuple[SettingKind, list[str]]:
    if get_origin(annotation) is Literal:
        return "choice", [str(choice) for choice in get_args(annotation)]
    kinds: dict[Any, SettingKind] = {
        SecretStr: "secret",
        ByteSize: "bytes",
        bool: "boolean",
        int: "integer",
        float: "number",
    }
    return kinds.get(annotation, "text"), []
