"""The order passwords are tried in for one document (D235): nearest first.

ordered_candidates gathers the passwords to try on a locked document, in the tiers the plan
sets and deduplicated (each password in its nearest tier only), skipping those already tried
(password_tried_until). The tiers, in order:

    manual        typed in by hand for every locked document (no mail, no document; the editor
                  when the request named one, D54)
    mail          found in a mail that carries the document
    thread        found in a mail of the same thread
    contacts      found in a mail with a shared participant, 30 days before or after
    attachments   found in the text of a document attached to one of those mails
    opened        it already opened another document
    archive       every other password of the archive

The list is capped (MAX_CANDIDATES) so the archive tier of a huge corpus stays bounded; the time
budget per document (passwords.phase) bounds it further.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.enums import PasswordTier

MAX_CANDIDATES = 5000
CONTACTS_DAYS = 30


@dataclass(frozen=True, slots=True)
class OrderedCandidate:
    password_id: int
    value: str
    tier: str  # a PasswordTier value
    finding_id: int | None  # where it was found, for the evidence (D208); None for opened/archive


# Each tier selects password rows (id, value, finding_id) for a document; later tiers fill in the
# passwords the earlier ones did not cover. :doc is the document, :after the tried-until id.
_CARRIERS = "SELECT DISTINCT mail_id FROM attachment WHERE document_id = :doc"
_TIERS: tuple[tuple[str, str], ...] = (
    (
        PasswordTier.MANUAL.value,
        """
        SELECT pf.password_id, min(pf.id) AS finding_id FROM password_finding pf
        WHERE pf.mail_id IS NULL AND pf.document_id IS NULL
        GROUP BY pf.password_id
        """,
    ),
    (
        PasswordTier.MAIL.value,
        f"""
        SELECT pf.password_id, min(pf.id) AS finding_id FROM password_finding pf
        WHERE pf.mail_id IN ({_CARRIERS}) GROUP BY pf.password_id
        """,
    ),
    (
        PasswordTier.THREAD.value,
        f"""
        SELECT pf.password_id, min(pf.id) AS finding_id FROM password_finding pf
        JOIN mail m ON m.id = pf.mail_id
        WHERE m.thread_id IN (
            SELECT DISTINCT thread_id FROM mail
            WHERE id IN ({_CARRIERS}) AND thread_id IS NOT NULL
        ) GROUP BY pf.password_id
        """,
    ),
    (
        PasswordTier.CONTACTS.value,
        f"""
        SELECT pf.password_id, min(pf.id) AS finding_id FROM password_finding pf
        JOIN mail m ON m.id = pf.mail_id
        JOIN participation p ON p.mail_id = m.id
        WHERE p.person_id IN (
            SELECT DISTINCT person_id FROM participation WHERE mail_id IN ({_CARRIERS})
        )
        AND m.date_utc BETWEEN (
            SELECT min(date_utc) FROM mail WHERE id IN ({_CARRIERS})
        ) - make_interval(days => :days) AND (
            SELECT max(date_utc) FROM mail WHERE id IN ({_CARRIERS})
        ) + make_interval(days => :days)
        GROUP BY pf.password_id
        """,
    ),
    (
        PasswordTier.ATTACHMENTS.value,
        f"""
        SELECT pf.password_id, min(pf.id) AS finding_id FROM password_finding pf
        WHERE pf.document_id IN (
            SELECT DISTINCT document_id FROM attachment
            WHERE mail_id IN ({_CARRIERS}) AND document_id IS NOT NULL
        ) GROUP BY pf.password_id
        """,
    ),
    (
        PasswordTier.OPENED.value,
        """
        SELECT dp.password_id, min(pf.id) AS finding_id FROM document_password dp
        LEFT JOIN password_finding pf ON pf.password_id = dp.password_id
        GROUP BY dp.password_id
        """,
    ),
    (
        PasswordTier.ARCHIVE.value,
        """
        SELECT pw.id AS password_id, min(pf.id) AS finding_id FROM password pw
        LEFT JOIN password_finding pf ON pf.password_id = pw.id
        GROUP BY pw.id
        """,
    ),
)


async def ordered_candidates(
    session: AsyncSession, document_id: int, *, after_id: int
) -> list[OrderedCandidate]:
    """The passwords to try on this document, nearest tier first, deduplicated and capped."""
    seen: set[int] = set()
    out: list[OrderedCandidate] = []
    for tier, query in _TIERS:
        rows = await session.execute(
            text(
                f"SELECT c.password_id, pw.value, c.finding_id FROM ({query}) c "
                "JOIN password pw ON pw.id = c.password_id "
                "WHERE c.password_id > :after ORDER BY c.password_id"
            ),
            {"doc": document_id, "after": after_id, "days": CONTACTS_DAYS},
        )
        for password_id, value, finding_id in rows:
            if password_id in seen:
                continue
            seen.add(password_id)
            out.append(OrderedCandidate(password_id, value, tier, finding_id))
            if len(out) >= MAX_CANDIDATES:
                return out
    return out


def values(candidates: Sequence[OrderedCandidate]) -> list[str]:
    return [c.value for c in candidates]
