"""The runs of `mailrobbe dkim-keys` as the job table holds them (D47, D101).

job.options and job.progress of kind dkim_keys hold the models below as JSON; the API serves
them as they are. Every task ends with the phases check (the mails with a signature of a key
name the run touched, checked again with every candidate key) and aggregates.
"""

from typing import Literal

from pydantic import BaseModel

from mailrobbe.jobs import RunProgress

# reconstruct: keys from two or more signatures of the names whose signatures are no_key, or
#   fail with signature_mismatch and an intact body (a new key under an old name)
# search: key records quoted in the archive's mails and attachment texts
# fetch: the ZK Email DKIM archive, one request per domain
# check: only the check of the given names' mails (after a manual key, D103)
DkimKeysTask = Literal["reconstruct", "search", "fetch", "check"]
# select: find the names and signatures to work on; compare: reconstructed keys against today's
# DNS of the domain's other selectors and against the keys of other sources
DkimKeysPhase = Literal[
    "select", "reconstruct", "search", "fetch", "compare", "check", "aggregates"
]


class DkimKeysOptions(BaseModel):
    """What a dkim-keys run works on (job.options of kind dkim_keys)."""

    task: DkimKeysTask
    names: list[str] = []  # key names; empty: every name concerned
    domains: list[str] = []  # fetch: the domains asked; empty: every domain concerned
    skip_domains: list[str] = []  # fetch without domains: every domain concerned but these
    workers: int = 1
    archive_url: str | None = None  # fetch: the key archive asked


class DkimKeysProgress(RunProgress):
    """Live figures of a dkim-keys run (job.progress of kind dkim_keys); done, total, rate and
    remaining time of each phase are its steps' (D110)."""

    workers: int = 0  # worker processes busy right now
    names: int = 0  # key names the run works on
    keys_found: int = 0  # keys this run stored or confirmed with new evidence
    factorable: int = 0  # keys found sharing a prime factor with another (Batch-GCD)
    mails_checked: int = 0
    mails_changed: int = 0  # checked mails whose status changed
