"""Which mails a hide rule matches (D221, D204), on the hand-made archive: each criterion, their
combination, LIKE wildcards taken literally; storing a rule's mails, keeping (D203) and the
figures of the hidden mails."""

from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.schemas import HideRuleFields
from mailrobbe.db.models import HideRule, Mail
from mailrobbe.hiding.model import (
    kept_counts,
    matches,
    read_figures,
    refresh_figures,
    shown,
    store_rule,
    visible,
)
from tests.hiding.archive import ARCHIVE, insert_archive, merge, person_id

pytestmark = pytest.mark.db


async def matched(session: AsyncSession, **criteria: Any) -> set[str]:
    """The names of the mails a rule with these (already cleaned) criteria matches."""
    rule = HideRuleFields(**criteria)
    return set(await session.scalars(select(Mail.raw_sha256).where(matches(rule))))


async def test_the_sender_is_any_address_of_its_person_row(db_session: AsyncSession) -> None:
    await insert_archive(db_session)
    assert await matched(db_session, sender="news@newsletter.example") == {"news1", "news2"}
    # a second address of the same person row
    assert await matched(db_session, sender="n@newsletter.example") == {"news1", "news2"}
    # an alias is a person row of its own
    assert await matched(db_session, sender="anna@a.example") == {"anna", "council"}
    assert await matched(db_session, sender="nobody@a.example") == set()


async def test_a_person_counts_every_address_of_its_root(db_session: AsyncSession) -> None:
    await insert_archive(db_session)
    anna = await person_id(db_session, "anna@a.example")
    alias = await person_id(db_session, "anna.alt@b.example")
    everything = {"anna", "alias", "council"}
    assert await matched(db_session, person_id=anna) == everything
    assert await matched(db_session, person_id=alias) == everything  # its root's addresses
    # a merge after the rule was made counts too
    await merge(db_session, "bert@a_b.example", "anna@a.example")
    assert await matched(db_session, person_id=anna) == everything | {"bert"}
    assert await matched(db_session, person_id=987654321) == set()  # gone: nothing


async def test_the_domain_counts_its_subdomains(db_session: AsyncSession) -> None:
    await insert_archive(db_session)
    assert await matched(db_session, domain="newsletter.example") == {"news1", "news2", "sub"}
    assert await matched(db_session, domain="mail.newsletter.example") == {"sub"}
    # "_" is no wildcard: mail.axb.example is no subdomain of a_b.example
    assert await matched(db_session, domain="a_b.example") == {"bert"}


async def test_list_id_and_automated(db_session: AsyncSession) -> None:
    await insert_archive(db_session)
    assert await matched(db_session, list_id="news.newsletter.example") == {"news1", "news2"}
    assert await matched(db_session, list_id="newsletter.example") == set()
    assert await matched(db_session, automated=True) == {"bot"}


async def test_the_subject_holds_or_starts_with_a_text_in_any_case(
    db_session: AsyncSession,
) -> None:
    await insert_archive(db_session)
    assert await matched(db_session, subject="wochenrückblick") == {"news1", "news2"}
    assert await matched(db_session, subject="Wochenrückblick", subject_match="starts") == {"news1"}
    assert await matched(db_session, subject="re: w", subject_match="starts") == {"news2"}
    # % and _ as written, not as wildcards of LIKE (D204)
    assert await matched(db_session, subject="10%") == {"alias"}
    assert await matched(db_session, subject="rat_s") == {"anna"}
    assert await matched(db_session, subject="\\") == set()


async def test_every_named_criterion_must_hold(db_session: AsyncSession) -> None:
    await insert_archive(db_session)
    both = {"domain": "newsletter.example", "subject": "wochenrückblick", "subject_match": "starts"}
    assert await matched(db_session, **both) == {"news1"}
    assert await matched(db_session, sender="anna@a.example", subject="rat") == {"anna", "council"}
    assert await matched(db_session, list_id="news.newsletter.example", automated=True) == set()
    assert await matched(db_session) == set()  # no criterion matches nothing


async def hidden_rows(session: AsyncSession, rule_id: int) -> set[str]:
    found = await session.scalars(
        text("""SELECT m.raw_sha256 FROM mail_hidden h JOIN mail m ON m.id = h.mail_id
            WHERE h.rule_id = :rule"""),
        {"rule": rule_id},
    )
    return set(found)


async def test_storing_a_rule_replaces_its_mails(db_session: AsyncSession) -> None:
    await insert_archive(db_session)
    rule = HideRule(domain="newsletter.example")
    db_session.add(rule)
    await db_session.flush()
    stored = await store_rule(db_session, rule.id)
    assert stored is not None and stored.computed_at is not None
    assert (stored.mails, await hidden_rows(db_session, rule.id)) == (3, {"news1", "news2", "sub"})
    before = stored.computed_at

    await db_session.execute(
        text("UPDATE hide_rule SET subject = 'angebot' WHERE id = :id"), {"id": rule.id}
    )
    stored = await store_rule(db_session, rule.id)
    assert stored is not None and stored.computed_at is not None and stored.computed_at >= before
    assert (stored.mails, await hidden_rows(db_session, rule.id)) == (1, {"sub"})

    await db_session.execute(
        text("UPDATE hide_rule SET enabled = false WHERE id = :id"), {"id": rule.id}
    )
    stored = await store_rule(db_session, rule.id)
    assert stored is not None
    assert (stored.mails, await hidden_rows(db_session, rule.id)) == (0, set())
    assert await store_rule(db_session, 987654321) is None


async def test_kept_mails_stay_visible_and_the_figures_count_them(
    db_session: AsyncSession,
) -> None:
    await insert_archive(db_session)
    for criteria in ({"domain": "newsletter.example"}, {"sender": "anna.alt@b.example"}):
        rule = HideRule(**criteria)
        db_session.add(rule)
        await db_session.flush()
        await store_rule(db_session, rule.id)
    figures = await refresh_figures(db_session)
    assert (figures.mails, figures.dkim) == (4, {"pass": 2, "no_key": 1, "fail": 1})
    assert await read_figures(db_session) == figures
    assert await kept_counts(db_session) == {}

    # in an Akte, with a note, bookmarked or relevant (D203); "seen" keeps nothing
    await db_session.execute(text("INSERT INTO note (mail_sha256, body) VALUES ('news1', 'Rat')"))
    await db_session.execute(
        text("INSERT INTO mail_mark (mail_sha256, review) VALUES ('sub', 'seen'), ('bot', 'seen')")
    )
    assert await kept_counts(db_session) == {"pass": 1}
    await db_session.execute(
        text("UPDATE mail_mark SET review = 'relevant' WHERE mail_sha256 = 'sub'")
    )
    await db_session.execute(
        text("INSERT INTO mail_mark (mail_sha256, flagged) VALUES ('alias', true)")
    )
    assert await kept_counts(db_session) == {"pass": 1, "no_key": 1, "fail": 1}

    assert await hidden_names(db_session) == {"news2"}

    await db_session.execute(
        text("""WITH akte AS (INSERT INTO collection (name) VALUES ('Spende') RETURNING id)
            INSERT INTO collection_mail (collection_id, mail_sha256)
            SELECT id, 'news2' FROM akte""")
    )
    assert await kept_counts(db_session) == {"pass": 2, "no_key": 1, "fail": 1}
    assert await hidden_names(db_session) == set()


async def hidden_names(session: AsyncSession) -> set[str]:
    """The mails visible() leaves out; shown(), its form for counts, must agree on every mail."""
    statement = select(Mail.raw_sha256, visible(), shown())
    flags = {name: (seen, column) for name, seen, column in await session.execute(statement)}
    assert set(flags) == set(ARCHIVE)
    assert all(seen == column for seen, column in flags.values())
    return {name for name, (seen, _) in flags.items() if not seen}
