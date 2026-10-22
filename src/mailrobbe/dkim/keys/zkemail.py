"""The ZK Email DKIM archive (D102): the task fetch of `mailrobbe dkim-keys`.

`GET <archive>/api/key?domain=<domain>` answers with every key the archive knows for the domain
and its subdomains, as a JSON list of entries:

    {"domain", "selector", "firstSeenAt", "lastSeenAt", "value": "<TXT record>", "id",
     "observations": [{"source": "live_dns" | "gcd_recovered", "firstSeenAt", "lastSeenAt"}]}

An empty list means nothing. Each answer is stored unchanged as a lookup (also errors and empty
answers), and each entry with a usable key becomes evidence for its name: observed when the
archive saw it in DNS (live_dns, with the times of those observations), reconstructed when it
only computed it from signatures (gcd_recovered) or says nothing about it. One request per
domain, never per selector, so a request does not tell which selectors the archive holds; only
on request, never during an import, and nothing is ever sent but the domain.

fetch_plan is what a fetch would ask (the API's preview shows it): the domains of concerned names
and of names only keys from other sources verify, with their names, mails and when each was last
asked. Domains under reserved TLDs (.example, .test,
...) never leave this machine: they go only to an archive on a loopback address (tests,
generated data) and are skipped otherwise.

A fetch over every domain goes on where an interrupted one ended (D107): when the latest such
fetches did not run to their end (stopped, failed, or their process died), the domains the
archive answered since the first of them began are done and left out; an error is asked again.
A fetch that ran to its end starts the next one from the beginning; a fetch of given domains
asks them all and neither ends nor continues the series.
"""

import ipaddress
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from mailrobbe.config import Settings
from mailrobbe.db.models import DkimKeyLookup, DkimResult, Job, Mail
from mailrobbe.dkim.keys.identity import key_identity
from mailrobbe.dkim.keys.store import (
    CONCERNED,
    TOOL_VERSION,
    Evidence,
    Executor,
    save_evidence,
    save_lookup,
)
from mailrobbe.dkim.override import key_name, normalise_name
from mailrobbe.dkim.resolver import is_reserved
from mailrobbe.enums import JobKind, JobStatus, KeyLookupSource, KeyOrigin, LookupOutcome

OFF = "off"
USER_AGENT = f"Mailrobbe/{TOOL_VERSION}"
LIVE_DNS = "live_dns"


def archive_url(settings: Settings) -> str | None:
    """The archive's base URL without a trailing slash; None when switched off."""
    url = settings.dkim_key_archive_url.strip()
    return None if url.lower() == OFF else url.rstrip("/")


def query_url(base: str, domain: str) -> str:
    return f"{base}/api/key?" + urllib.parse.urlencode({"domain": domain})


def is_local(base: str) -> bool:
    """Whether the archive runs on this machine (a loopback address or localhost)."""
    host = urllib.parse.urlsplit(base).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True, slots=True)
class ArchiveDomain:
    domain: str
    names: int  # concerned key names of the domain
    mails: int  # mails with a signature of those names (no duplicates)
    last_asked_at: datetime | None  # the latest lookup of the domain at the archive
    done: bool = False  # answered by the interrupted fetch this one continues (D107)


@dataclass(frozen=True, slots=True)
class FetchPlan:
    url: str | None  # the archive's base URL; None: switched off
    domains: list[ArchiveDomain]  # most mails first; those done are left out of a fetch
    skipped: list[str]  # under reserved TLDs, not sent to an archive elsewhere
    continues: datetime | None = None  # start of the interrupted fetch this one continues

    @property
    def asked(self) -> list[ArchiveDomain]:
        """The domains a fetch sends requests for."""
        return [domain for domain in self.domains if not domain.done]


async def fetch_plan(
    db: Executor, url: str | None, domains: Collection[str] = (), skip: Collection[str] = ()
) -> FetchPlan:
    """The domains a fetch asks, or the given ones, with their figures: the domains of concerned
    names and of names a key from another source verifies, whose origin the archive may raise
    (a reconstructed key the archive saw in DNS becomes observed, D102). Without given domains
    those in skip are left out, and those an interrupted fetch got an answer for are done."""
    given = sorted({normalise_name(domain) for domain in domains if normalise_name(domain)})
    left_out = {normalise_name(domain) for domain in skip}
    concerned = (
        select(
            DkimResult.domain,
            func.count(DkimResult.selector.distinct()),
            func.count(DkimResult.mail_id.distinct()),
        )
        .join(Mail, Mail.id == DkimResult.mail_id)
        .where(
            or_(CONCERNED, DkimResult.key_id.is_not(None)),
            Mail.is_duplicate_of.is_(None),
            DkimResult.domain.is_not(None),
        )
        .group_by(DkimResult.domain)
    )
    if given:
        concerned = concerned.where(DkimResult.domain.in_(given))
    figures: dict[str, tuple[int, int]] = {
        domain: (names, mails) for domain, names, mails in await db.execute(concerned) if domain
    }
    asked = {
        domain: last
        for domain, last in await db.execute(
            select(DkimKeyLookup.domain, func.max(DkimKeyLookup.asked_at))
            .where(DkimKeyLookup.source == KeyLookupSource.ZKEMAIL.value)
            .group_by(DkimKeyLookup.domain)
        )
    }
    continues = None if given or url is None else await _interrupted_since(db)
    answered = set()
    if url is not None and continues is not None:
        answered = await _answered(db, url, continues)
    local = url is not None and is_local(url)
    plan: list[ArchiveDomain] = []
    skipped: list[str] = []
    for domain in given or sorted(set(figures) - left_out):
        if is_reserved(domain) and not local:
            skipped.append(domain)
            continue
        names, mails = figures.get(domain, (0, 0))
        plan.append(ArchiveDomain(domain, names, mails, asked.get(domain), domain in answered))
    plan.sort(key=lambda entry: (-entry.mails, entry.domain.encode()))
    return FetchPlan(url, plan, skipped, continues if answered else None)


async def _interrupted_since(db: Executor) -> datetime | None:
    """When the first of the latest fetches over every domain began that did not run to their
    end; None when the latest one did (D107). A running fetch counts as not ended yet."""
    since = None
    for status, started_at, options in await db.execute(
        select(Job.status, Job.started_at, Job.options)
        .where(Job.kind == JobKind.DKIM_KEYS, Job.options["task"].astext == "fetch")
        .order_by(Job.id.desc())
    ):
        if options.get("domains"):
            continue
        if status == JobStatus.DONE:
            break
        since = started_at
    return since


async def _answered(db: Executor, url: str, since: datetime) -> set[str]:
    """The domains this archive answered (keys or none, not an error) since then."""
    rows = await db.execute(
        select(DkimKeyLookup.domain, DkimKeyLookup.query).where(
            DkimKeyLookup.source == KeyLookupSource.ZKEMAIL.value,
            DkimKeyLookup.outcome != LookupOutcome.ERROR.value,
            DkimKeyLookup.asked_at >= since,
        )
    )
    return {domain for domain, query in rows if domain and query == query_url(url, domain)}


@dataclass(frozen=True, slots=True)
class Answer:
    """The archive's answer to one request, as it came."""

    status: int | None  # HTTP status; None without an answer
    body: bytes | None
    content_type: str | None
    error: str | None = None  # why there is no usable answer (English)


def ask(url: str, timeout: float) -> Answer:
    """One GET with the environment's proxy settings; never raises."""
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return Answer(response.status, response.read(), response.headers.get("Content-Type"))
    except urllib.error.HTTPError as error:
        body = error.read()
        return Answer(error.code, body, error.headers.get("Content-Type"), f"HTTP {error.code}")
    except TimeoutError:
        return Answer(None, None, None, f"no answer within {timeout:g} s")
    except (urllib.error.URLError, OSError, ValueError) as error:
        reason = getattr(error, "reason", error)
        if isinstance(reason, TimeoutError):
            return Answer(None, None, None, f"no answer within {timeout:g} s")
        return Answer(None, None, None, f"{type(reason).__name__}: {reason}"[:500])


@dataclass(frozen=True, slots=True)
class _Entry:
    name: str
    record: str
    evidence: Evidence


async def store_answer(
    db: AsyncConnection, url: str, domain: str, answer: Answer
) -> dict[int, str]:
    """Store one answer as a lookup and its entries' keys as evidence; those keys' ids and
    names."""
    entries, error = _entries(answer, url)
    if error is not None:
        outcome, message = LookupOutcome.ERROR, error
    elif entries:
        outcome, message = LookupOutcome.FOUND, f"{len(entries)} keys"
    else:
        outcome, message = LookupOutcome.NOT_FOUND, "no usable key"
    lookup_id = await save_lookup(
        db,
        KeyLookupSource.ZKEMAIL,
        url,
        outcome,
        domain=domain,
        raw=answer.body,
        raw_type=answer.content_type,
        http_status=answer.status,
        message=message,
    )
    keys = {}
    for entry in entries:
        key_id = await save_evidence(db, lookup_id, entry.name, entry.record, entry.evidence)
        if key_id is not None:
            keys[key_id] = entry.name
    return keys


def _entries(answer: Answer, url: str) -> tuple[list[_Entry], str | None]:
    """The usable entries of an answer, or why it is no valid answer."""
    if answer.error is not None:
        return [], answer.error
    if answer.status != 200 or answer.body is None:
        return [], f"HTTP {answer.status}"
    try:
        data = json.loads(answer.body)
    except ValueError:
        return [], "the answer is no JSON"
    if not isinstance(data, list):
        return [], "the answer is no JSON list"
    entries = []
    for item in data:
        entry = _entry(item, url) if isinstance(item, dict) else None
        if entry is not None:
            entries.append(entry)
    return entries, None


def _entry(item: dict[str, Any], url: str) -> _Entry | None:
    """An entry with a usable key (empty p= and other records are ignored)."""
    selector, domain, record = item.get("selector"), item.get("domain"), item.get("value")
    if not all(isinstance(value, str) and value for value in (selector, domain, record)):
        return None
    assert isinstance(selector, str) and isinstance(domain, str) and isinstance(record, str)
    if key_identity(record) is None:
        return None
    observations = [o for o in item.get("observations") or [] if isinstance(o, dict)]
    sources = sorted({o["source"] for o in observations if isinstance(o.get("source"), str)})
    live = [o for o in observations if o.get("source") == LIVE_DNS]
    # Seen in DNS by the archive: observed. Only computed from signatures (gcd_recovered), or
    # nothing said about it: reconstructed, which never passes (D100).
    origin = KeyOrigin.OBSERVED if live else KeyOrigin.RECONSTRUCTED
    times = live or observations or [item]
    evidence = Evidence(
        origin,
        observed_from=min(_times(times, "firstSeenAt"), default=None),
        observed_to=max(_times(times, "lastSeenAt"), default=None),
        reference=url,
        details={"entry_id": item.get("id"), "sources": sources},
    )
    return _Entry(key_name(selector, domain), record, evidence)


def _times(items: list[dict[str, Any]], field: str) -> list[datetime]:
    found = []
    for item in items:
        value = item.get(field)
        if isinstance(value, str):
            try:
                moment = datetime.fromisoformat(value)
            except ValueError:
                continue
            if moment.tzinfo is not None:
                found.append(moment)
    return found
