"""The DKIM checker of one process: verify_mail with a cached key source (SPEC 3.4, D11).

Every process that verifies mails (importer worker, recheck worker, API) builds one checker with
DkimChecker.from_settings, preloaded with the dns_cache rows the main process read once
(store.load_dns_cache). Answers the checker had to look up are collected for persistence:
take_new_answers hands them out once, and the caller writes them with store.upsert_dns_cache.
lookups and hits give the cache hit rate for the import dashboard. The candidate keys of deleted
selectors (D100) come the same way: read once per run (keys.store.load_candidates) and handed
to every checker, which tries them when DNS gives no key that verifies (verify.py).

Key sources, chosen from the settings (resolver.py):

- the in-process cache, preloaded from dns_cache;
- the DNS override table (MAILROBBE_DKIM_DNS_OVERRIDE, or the generator's table found in
  MAILROBBE_MBOX_DIR/_generator/dns_override.json) answers the names it lists;
- names under reserved TLDs (.example, .test, .invalid, .localhost) are never looked up and
  count as not found;
- everything else goes to real DNS (dnspython, MAILROBBE_DKIM_DNS_TIMEOUT,
  MAILROBBE_DKIM_NAMESERVERS), or, with MAILROBBE_DKIM_OFFLINE, comes back as temp_error
  dns_offline when it is not in the cache.
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Self

from mailrobbe.config import Settings
from mailrobbe.dkim.model import NO_CANDIDATES, DnsAnswer, KeyCandidates, KeySource, MailVerdict
from mailrobbe.dkim.override import DnsOverrideTable
from mailrobbe.dkim.resolver import (
    DnsResolver,
    KeyCache,
    KeyChain,
    offline_answer,
    parse_nameservers,
)
from mailrobbe.dkim.verify import verify_mail

GENERATOR_OVERRIDE = Path("_generator") / "dns_override.json"


def dns_override_path(settings: Settings) -> Path | None:
    """MAILROBBE_DKIM_DNS_OVERRIDE, else the generator's table below mbox_dir if it exists."""
    if settings.dkim_dns_override is not None:
        return settings.dkim_dns_override
    found = settings.mbox_dir / GENERATOR_OVERRIDE
    return found if found.is_file() else None


class DkimChecker:
    """verify_mail with a KeyCache in front of the key source. Not shared between threads."""

    def __init__(self, keys: KeySource, candidates: KeyCandidates = NO_CANDIDATES) -> None:
        # A KeyCache is used as given; any other source gets an empty cache in front.
        self._keys = keys if isinstance(keys, KeyCache) else KeyCache(keys)
        self._candidates = candidates

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        preload: Iterable[DnsAnswer] = (),
        refresh_negative: bool = False,
        candidates: KeyCandidates = NO_CANDIDATES,
    ) -> Self:
        """The checker for this process; does no network access.

        preload: answers from dns_cache; expired ones are ignored unless offline.
        refresh_negative: ignore preloaded not_found and temp_error answers (recheck runs), so
        every missing or unreachable key is asked for once more.
        candidates: keys of deleted selectors by name (keys.store.load_candidates).

        Invalid DNS settings raise ValueError here, so a typo fails at start, not per mail.
        """
        nameservers = parse_nameservers(settings.dkim_nameservers)
        if settings.dkim_dns_timeout <= 0:
            raise ValueError("MAILROBBE_DKIM_DNS_TIMEOUT must be positive")
        path = dns_override_path(settings)
        table = None if path is None else DnsOverrideTable.load(path)
        if table is not None:
            # The table is the authority for its names, also over dns_cache rows written with
            # an earlier table (test data generated again with other keys).
            preload = [answer for answer in preload if not table.lists(answer.name)]
        last: KeySource = (
            offline_answer
            if settings.dkim_offline
            else DnsResolver(settings.dkim_dns_timeout, nameservers)
        )
        cache = KeyCache(
            KeyChain(table, last),
            preload=preload,
            refresh_negative=refresh_negative,
            offline=settings.dkim_offline,
        )
        return cls(cache, candidates)

    def check(self, raw: bytes) -> MailVerdict:
        """Verify one mail; never raises."""
        return verify_mail(raw, self._keys, self._candidates)

    def take_new_answers(self) -> list[DnsAnswer]:
        """Answers looked up since the last call, for store.upsert_dns_cache (ttl > 0 only).

        Each answer is handed out once, and each name at most once per call (its latest answer).
        """
        return self._keys.take_new_answers()

    @property
    def lookups(self) -> int:
        """Key lookups that went past the cache to the sources."""
        return self._keys.lookups

    @property
    def hits(self) -> int:
        """Key lookups the cache answered."""
        return self._keys.hits
