"""Keys of deleted selectors (D100 to D104): the selector list and page, manual keys, the sources'
answers, the preview of a key archive fetch and the runs of `mailrobbe dkim-keys`.

Routes: GET /api/dkim/selectors/summary, /api/dkim/selectors, /api/dkim/selectors/{name},
POST /api/dkim/selectors/{name}/keys, GET /api/dkim/lookups/{id}/raw, /api/dkim/archive/preview,
POST /api/dkim/keys/run, /api/dkim/keys/run/stop.

A key name's figures come from dkim_result grouped by (domain, selector) over the mails that are
no duplicates, which an anti join with the few duplicates leaves out (ix_mail_is_duplicate_of),
so no mail row is read for them. The list and the summary scan dkim_result once; the list's mail
counts take a second, narrow pass over the signatures with signature_index above 0, which finds
the rare mail signed twice under one name (count(DISTINCT mail_id) sorted every signature and
took several times as long). The page of one name walks ix_dkim_result_domain_selector.

A signature is open when it is no_key, or fail with signature_mismatch and an intact body (a new
key under the old name), and resolved when a key from another source verified it
(dkim_result.key_id). The list shows the names with open signatures, with resolved ones, or
every name with a signature; a name with both kinds is open and resolved at once.

The POSTs take JSON only, as the dashboard's (imports.py). A manual key is stored with the
editor of D54 and starts a `check` run for its name like the dashboard starts runs; while
another run is alive the key is stored all the same and waits for the next check, which the
page shows as a key with 0 signatures.
"""

import base64
import binascii
import hashlib
import logging
import mimetypes
import re
from typing import Annotated, Any

import fastapi
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import RowMapping, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.functions import count

from mailrobbe.api import processes
from mailrobbe.api.deps import AppSettings, Editor, Session, api_error
from mailrobbe.api.detail import key_infos, mail_senders
from mailrobbe.api.documents import CONTENT_HEADERS, content_disposition
from mailrobbe.api.filters import _contains
from mailrobbe.api.imports import JSON_BODY, NoOptions, Runs, _keys_job, _start, _stop
from mailrobbe.api.schemas import (
    EVIDENCE_FILE_LIMIT,
    SELECTOR_MAILS_LIMIT,
    DkimKeysJob,
    DkimKeysRunRequest,
    KeyArchivePreview,
    KeyLookupInfo,
    ManualKeyRequest,
    SelectorDetail,
    SelectorItem,
    SelectorListParams,
    SelectorMail,
    SelectorPage,
    SelectorSummary,
)
from mailrobbe.db.models import (
    DkimKey,
    DkimKeyEvidence,
    DkimKeyLookup,
    DkimResult,
    DnsCache,
    Mail,
)
from mailrobbe.dkim.keys import store, zkemail
from mailrobbe.dkim.keys.identity import split_key_name
from mailrobbe.dkim.keys.store import NAMED, NOT_DUPLICATE
from mailrobbe.enums import (
    DkimStatus,
    JobKind,
)
from mailrobbe.persons.labels import attach_labels

router = APIRouter(prefix="/api", tags=["keys"])
log = logging.getLogger(__name__)

LookupId = Annotated[int, fastapi.Path(ge=-(2**63), le=2**63 - 1)]

# The SQL below names statuses and origins by their values, which are fixed by the migrations.
_OPEN = (
    "r.status = 'no_key' OR (r.status = 'fail' AND r.reason = 'signature_mismatch' "
    "AND r.body_hash_ok)"
)
_STATUSES = "".join(
    f", count(*) FILTER (WHERE r.status = '{status}') AS status_{status}" for status in DkimStatus
)


def _names(where: str) -> str:
    """CTEs counted, repeated and names: the figures of each key name (dkim.override.key_name)
    with a signature on a mail that is no duplicate. A mail signed twice under one name counts
    once among its mails: its later signatures are repeated ones."""
    return f"""
    counted AS (
        SELECT r.domain, r.selector,
               count(*) AS signatures,
               count(*) FILTER (WHERE r.algorithm LIKE 'rsa-%') AS rsa_signatures,
               min(r.signed_at) AS first_signed,
               max(r.signed_at) AS last_signed,
               count(*) FILTER (WHERE {_OPEN}) AS open,
               count(*) FILTER (WHERE r.key_id IS NOT NULL) AS resolved
               {_STATUSES}
        FROM dkim_result r
        WHERE {NAMED} AND {NOT_DUPLICATE} AND {where}
        GROUP BY r.domain, r.selector
    ),
    repeated AS (
        SELECT r.domain, r.selector, count(*) AS signatures
        FROM dkim_result r
        WHERE r.signature_index > 0 AND {NAMED} AND {NOT_DUPLICATE} AND {where}
          AND EXISTS (
              SELECT FROM dkim_result e
              WHERE e.mail_id = r.mail_id AND e.signature_index < r.signature_index
                AND e.domain = r.domain AND e.selector = r.selector
          )
        GROUP BY r.domain, r.selector
    ),
    names AS (
        SELECT c.*, rtrim(c.selector || '._domainkey.' || c.domain, '.') AS name,
               c.signatures - COALESCE(p.signatures, 0) AS mails
        FROM counted c LEFT JOIN repeated p USING (domain, selector)
    )"""


# Factorable keys count among a name's keys but give it no origin: they are never used (D104).
_KEYS_BY_NAME = """
    SELECT name, count(*) AS keys, min(origin) FILTER (WHERE NOT factorable) AS best_origin
    FROM dkim_key GROUP BY name
"""
_SHOW = {"open": "n.open > 0", "resolved": "n.resolved > 0", "all": "TRUE"}
# One row also for an empty page, so the total is known; ties by name in byte order.
_LIST = """
    WITH {names},
    shown AS (
        SELECT n.*, k.keys, k.best_origin, c.status AS dns_status
        FROM names n
        LEFT JOIN ({keys}) k ON k.name = n.name
        LEFT JOIN dns_cache c ON c.name = n.name
        WHERE {show} AND n.name ILIKE :pattern
    )
    SELECT t.total, p.*
    FROM (SELECT count(*) AS total FROM shown) t
    LEFT JOIN LATERAL (
        SELECT * FROM shown ORDER BY mails DESC, name COLLATE "C" LIMIT :limit OFFSET :offset
    ) p ON TRUE
"""
_ONE_NAME = "r.domain = :domain AND r.selector = :selector"


# The selector list and its summary ------------------------------------------------------------


@router.get("/dkim/selectors/summary")
async def selector_summary(session: Session) -> SelectorSummary:
    return await store.selector_summary(session)


@router.get("/dkim/selectors")
async def selector_list(
    params: Annotated[SelectorListParams, Query()], session: Session
) -> SelectorPage:
    sql = _LIST.format(names=_names("TRUE"), keys=_KEYS_BY_NAME, show=_SHOW[params.show])
    rows = (
        await session.execute(
            text(sql),
            {
                "pattern": _contains(params.q.strip().lower()),
                "limit": params.limit,
                "offset": params.offset,
            },
        )
    ).mappings()
    items, total = [], 0
    for row in rows:
        total = row["total"]
        if row["name"] is not None:
            items.append(
                SelectorItem(
                    **_figures(row),
                    keys=row["keys"] or 0,
                    best_origin=row["best_origin"],
                    dns_status=row["dns_status"],
                )
            )
    return SelectorPage(items=items, total=total)


def _figures(row: RowMapping) -> dict[str, Any]:
    """The fields SelectorItem and SelectorDetail share, from a row of names."""
    return {
        "name": row["name"],
        "domain": row["domain"],
        "selector": row["selector"],
        "signatures": row["signatures"],
        "mails": row["mails"],
        "statuses": {
            status: row[f"status_{status}"] for status in DkimStatus if row[f"status_{status}"]
        },
        "rsa_signatures": row["rsa_signatures"],
        "first_signed": row["first_signed"],
        "last_signed": row["last_signed"],
    }


# One key name -------------------------------------------------------------------------------


@router.get("/dkim/selectors/{name}")
async def selector_detail(name: str, session: Session) -> SelectorDetail:
    return await _selector(session, _key_name(name))


async def _selector(session: AsyncSession, name: str) -> SelectorDetail:
    """The page of a normalised key name; 404 when it has no signature."""
    figures = await _name_figures(session, name)
    if figures is None:
        raise api_error(404, "not_found", f"no signature names the key {name}")
    selector, domain = figures["selector"], figures["domain"]
    cached = await session.get(DnsCache, name)
    key_ids = await session.scalars(select(DkimKey.id).where(DkimKey.name == name))
    keys = await key_infos(session, set(key_ids))
    detail = SelectorDetail(
        **_figures(figures),
        dns_status=cached.status if cached else None,
        dns_record=cached.record if cached else None,
        dns_fetched_at=cached.fetched_at if cached else None,
        keys=list(keys.values()),
        lookups=await _lookups(session, name, domain),
        recent_mails=await _recent_mails(session, domain, selector),
    )
    await attach_labels(session, detail)
    return detail


async def _name_figures(session: AsyncSession, name: str) -> RowMapping | None:
    parts = split_key_name(name)
    assert parts is not None, "a normalised key name"
    selector, domain = parts
    sql = f"WITH {_names(_ONE_NAME)} SELECT * FROM names"
    found = await session.execute(text(sql), {"domain": domain, "selector": selector})
    return found.mappings().one_or_none()


async def _lookups(session: AsyncSession, name: str, domain: str) -> list[KeyLookupInfo]:
    """The lookups about this name, about its whole domain (a key archive's answer), and those
    that gave evidence for one of its keys; newest first."""
    evidence_for = (
        select(DkimKeyEvidence.lookup_id)
        .join(DkimKey, DkimKey.id == DkimKeyEvidence.key_id)
        .where(DkimKey.name == name)
    )
    keys = (
        select(count())
        .where(DkimKeyEvidence.lookup_id == DkimKeyLookup.id)
        .scalar_subquery()
        .label("keys")
    )
    rows = await session.execute(
        select(
            *(c for c in DkimKeyLookup.__table__.columns if c.name != "raw"),
            func.octet_length(DkimKeyLookup.raw).label("raw_size"),
            keys,
        )
        .where(
            or_(
                DkimKeyLookup.name == name,
                (DkimKeyLookup.name.is_(None)) & (DkimKeyLookup.domain == domain),
                DkimKeyLookup.id.in_(evidence_for),
            )
        )
        .order_by(DkimKeyLookup.asked_at.desc(), DkimKeyLookup.id.desc())
    )
    return [KeyLookupInfo.model_validate(row, from_attributes=True) for row in rows]


async def _recent_mails(session: AsyncSession, domain: str, selector: str) -> list[SelectorMail]:
    """The newest signatures of the name by t=, on mails that are no duplicates: sorted within
    dkim_result, so only the mails shown are read."""
    duplicate = select(Mail.id).where(
        Mail.id == DkimResult.mail_id, Mail.is_duplicate_of.is_not(None)
    )
    newest = (
        select(DkimResult)
        .where(DkimResult.domain == domain, DkimResult.selector == selector, ~duplicate.exists())
        .order_by(
            DkimResult.signed_at.desc().nulls_last(),
            DkimResult.mail_id.desc(),
            DkimResult.signature_index,
        )
        .limit(SELECTOR_MAILS_LIMIT)
        .subquery()
    )
    rows = (
        await session.execute(
            select(Mail.id, Mail.date_utc, Mail.subject, newest)
            .join(Mail, Mail.id == newest.c.mail_id)
            .order_by(
                newest.c.signed_at.desc().nulls_last(),
                newest.c.mail_id.desc(),
                newest.c.signature_index,
            )
        )
    ).all()
    senders = await mail_senders(session, list(dict.fromkeys(row.id for row in rows)))
    return [
        SelectorMail(
            id=row.id,
            date=row.date_utc,
            subject=row.subject,
            sender=senders.get(row.id),
            signature_index=row.signature_index,
            status=row.status,
            reason=row.reason,
            key_origin=row.key_origin,
            key_id=row.key_id,
            signed_at=row.signed_at,
        )
        for row in rows
    ]


def _key_name(name: str) -> str:
    """'<selector>._domainkey.<domain>' normalised; 400 invalid_key for anything else."""
    parts = split_key_name(name)
    if parts is None:
        raise api_error(400, "invalid_key", f"{name!r} is no DKIM key name")
    selector, domain = parts
    return f"{selector}._domainkey.{domain}"


# Manual keys (D103) --------------------------------------------------------------------------

_DATA_URL = re.compile(r"data:([^,;]*)(?:;[^,;]*)*;base64,", re.IGNORECASE)
_MEDIA_TYPE = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*")


@router.post("/dkim/selectors/{name}/keys", status_code=201, dependencies=JSON_BODY)
async def add_key(
    name: str,
    request: ManualKeyRequest,
    session: Session,
    settings: AppSettings,
    runs: Runs,
    editor: Editor,
) -> SelectorDetail:
    """Store a key a person found elsewhere, as documented, and check the name's mails with it."""
    name = _key_name(name)
    if await _name_figures(session, name) is None:
        raise api_error(404, "not_found", f"no signature names the key {name}")
    if (
        request.observed_from
        and request.observed_to
        and request.observed_from > request.observed_to
    ):
        raise api_error(400, "invalid_option", "observed_from is after observed_to")
    file = _evidence_file(request)
    try:
        key_id = await store.add_manual_key(
            session,
            name,
            request.record,
            reference=request.reference.strip(),
            note=request.note.strip() or None,
            observed_from=request.observed_from,
            observed_to=request.observed_to,
            file_name=None if file is None else (request.file_name or "beleg"),
            file_bytes=None if file is None else file[0],
            file_type=None if file is None else file[1],
            editor=editor,
        )
    except store.KeyRejected as error:
        raise api_error(400, "invalid_key", str(error)) from None
    await session.commit()
    try:
        arguments = ["check", f"--name={name}"]
        environment = processes.child_environment(settings)
        await _start(session, settings, runs, JobKind.DKIM_KEYS, arguments, environment)
    except HTTPException as error:
        log.info("key %d of %s waits for the next check: %s", key_id, name, error.detail)
    return await _selector(session, name)


def _evidence_file(request: ManualKeyRequest) -> tuple[bytes, str] | None:
    """The evidence file's bytes and media type; 400 invalid_option when they are no base64 or
    too large. A data: URL (as FileReader gives it) is taken with its media type."""
    if not request.file_base64:
        return None
    encoded = request.file_base64.strip()
    media_type = None
    if prefix := _DATA_URL.match(encoded):
        media_type = prefix.group(1).lower()
        encoded = encoded[prefix.end() :]
    if len(encoded) > (EVIDENCE_FILE_LIMIT + 2) // 3 * 4 + 1024:  # base64 and some line breaks
        raise api_error(400, "invalid_option", "the evidence file is larger than 10 MiB")
    try:
        data = base64.b64decode(re.sub(r"\s+", "", encoded), validate=True)
    except binascii.Error as error:
        raise api_error(400, "invalid_option", "file_base64 is no base64") from error
    if len(data) > EVIDENCE_FILE_LIMIT:
        raise api_error(400, "invalid_option", "the evidence file is larger than 10 MiB")
    if not media_type or not _MEDIA_TYPE.fullmatch(media_type):
        guessed, _ = mimetypes.guess_type(request.file_name or "")
        media_type = guessed or "application/octet-stream"
    return data, media_type


# Raw answers --------------------------------------------------------------------------------


@router.get("/dkim/lookups/{lookup_id}/raw")
async def lookup_raw(lookup_id: LookupId, session: Session) -> Response:
    """A source's answer, or a manual key's evidence file, byte for byte as stored, as a
    download; X-Mailrobbe-SHA256 is the SHA-256 recorded when it was stored."""
    row = (
        await session.execute(
            select(
                DkimKeyLookup.raw,
                DkimKeyLookup.raw_sha256,
                DkimKeyLookup.raw_type,
                DkimKeyLookup.raw_name,
                DkimKeyLookup.source,
            ).where(DkimKeyLookup.id == lookup_id)
        )
    ).one_or_none()
    if row is None or row.raw is None:
        raise api_error(404, "not_found", f"no stored answer for lookup {lookup_id}")
    media_type = (row.raw_type or "").lower()
    if not _MEDIA_TYPE.fullmatch(media_type):
        media_type = "application/octet-stream"
    name = row.raw_name or f"lookup-{lookup_id}-{row.source}{_extension(media_type)}"
    headers = {
        **CONTENT_HEADERS,
        "Content-Disposition": content_disposition(name),
        "X-Mailrobbe-SHA256": row.raw_sha256 or hashlib.sha256(row.raw).hexdigest(),
    }
    return Response(row.raw, media_type=media_type, headers=headers)


def _extension(media_type: str) -> str:
    return mimetypes.guess_extension(media_type) or ".bin"


# The key archive's preview (D102) ------------------------------------------------------------


@router.get("/dkim/archive/preview")
async def archive_preview(session: Session, settings: AppSettings) -> KeyArchivePreview:
    """The domains a fetch would ask the key archive for, before anything is sent."""
    plan = await zkemail.fetch_plan(session, zkemail.archive_url(settings))
    return KeyArchivePreview.model_validate(plan, from_attributes=True)


# Runs (D101) -------------------------------------------------------------------------------

_DOMAIN = re.compile(r"[a-z0-9_-]+(?:\.[a-z0-9_-]+)+")


@router.post("/dkim/keys/run", status_code=202, dependencies=JSON_BODY)
async def start_keys(
    run: DkimKeysRunRequest, session: Session, settings: AppSettings, runs: Runs
) -> DkimKeysJob:
    """Start `mailrobbe dkim-keys <task>` as the dashboard starts its runs (D46)."""
    arguments: list[str] = [run.task]
    if run.names and run.task not in ("reconstruct", "check"):
        raise api_error(400, "invalid_option", f"the task {run.task} takes no key names")
    if run.domains and run.task != "fetch":
        raise api_error(400, "invalid_option", f"the task {run.task} takes no domains")
    if run.task == "fetch" and zkemail.archive_url(settings) is None:
        raise api_error(409, "archive_off", "the key archive is switched off")
    arguments += [f"--name={name}" for name in dict.fromkeys(map(_key_name, run.names))]
    arguments += [f"--domain={domain}" for domain in dict.fromkeys(map(_domain, run.domains))]
    if run.workers is not None:
        arguments.append(f"--jobs={run.workers}")
    environment = processes.child_environment(settings)
    job = await _start(session, settings, runs, JobKind.DKIM_KEYS, arguments, environment)
    return await _keys_job(session, settings, job)


@router.post("/dkim/keys/run/stop", dependencies=JSON_BODY)
async def stop_keys(_: NoOptions, session: Session, settings: AppSettings) -> DkimKeysJob:
    return await _keys_job(session, settings, await _stop(session, JobKind.DKIM_KEYS))


def _domain(domain: str) -> str:
    normal = domain.strip().rstrip(".").lower()
    if not _DOMAIN.fullmatch(normal):
        raise api_error(400, "invalid_option", f"{domain!r} is no domain")
    return normal
