"""The DKIM checker of one process: verify_mail with a cached key source (SPEC 3.4).

Every process that verifies mails (importer worker, recheck worker, API) builds one checker with
DkimChecker.from_settings, preloaded with the dns_cache rows the main process read once
(store.load_dns_cache). Answers the checker had to look up are collected for persistence:
take_new_answers hands them out once, and the caller writes them with store.upsert_dns_cache.

Key sources, chosen from the settings:

- the DNS override table (MAILROBBE_DKIM_DNS_OVERRIDE, or the generator's table found in
  MAILROBBE_MBOX_DIR/_generator/dns_override.json) answers the names it lists;
- names under reserved TLDs (.example, .test, .invalid, .localhost) are never looked up and
  count as not found;
- everything else goes to real DNS (dnspython, MAILROBBE_DKIM_DNS_TIMEOUT,
  MAILROBBE_DKIM_NAMESERVERS), or, with MAILROBBE_DKIM_OFFLINE, comes back as temp_error
  dns_offline when it is not in the cache.

Contract baseline: only the override table, without cache and without real DNS.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Self

from mailrobbe.config import Settings
from mailrobbe.dkim.model import DnsAnswer, KeySource, MailVerdict
from mailrobbe.dkim.override import DnsOverrideTable
from mailrobbe.dkim.verify import verify_mail

GENERATOR_OVERRIDE = Path("_generator") / "dns_override.json"


def dns_override_path(settings: Settings) -> Path | None:
    """MAILROBBE_DKIM_DNS_OVERRIDE, else the generator's table below mbox_dir if it exists."""
    if settings.dkim_dns_override is not None:
        return settings.dkim_dns_override
    found = settings.mbox_dir / GENERATOR_OVERRIDE
    return found if found.is_file() else None


class DkimChecker:
    def __init__(self, keys: KeySource) -> None:
        self._keys = keys

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        preload: Iterable[DnsAnswer] = (),
        refresh_negative: bool = False,
    ) -> Self:
        """The checker for this process.

        preload: answers from dns_cache; expired ones are ignored unless offline.
        refresh_negative: ignore preloaded not_found and temp_error answers (recheck runs), so
        every missing or unreachable key is asked for once more.
        """
        path = dns_override_path(settings)
        if path is None:
            raise NotImplementedError("real DNS lookups are not implemented yet")
        return cls(DnsOverrideTable.load(path).answer)

    def check(self, raw: bytes) -> MailVerdict:
        """Verify one mail; never raises."""
        return verify_mail(raw, self._keys)

    def take_new_answers(self) -> list[DnsAnswer]:
        """Answers looked up since the last call, for store.upsert_dns_cache (ttl > 0 only)."""
        return []
