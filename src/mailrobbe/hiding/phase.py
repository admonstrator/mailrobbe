"""The import's step hidden (D221): the mails of every hide rule computed again, so new mails and
the addresses merges gave a person are covered. Database only.

Each rule is one transaction (model.store_rule, which locks the rule's row against a save from
the UI at the same moment): an enabled rule's rows are replaced by its matches, a disabled one's
removed. A rule whose statement fails is logged and stays as it was; the others go on. A stop
(D46) ends the step between two rules. Then the figures in global_stats 'hidden' are counted
again (model.refresh_figures), also after a stop, since the rules computed so far changed them.
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mailrobbe.db.models import HideRule
from mailrobbe.hiding.model import refresh_figures, store_rule
from mailrobbe.jobrun import Step, describe

log = logging.getLogger(__name__)

STEP = "hidden"


async def refresh_hidden(
    sessionmaker: async_sessionmaker[AsyncSession], stop: asyncio.Event, step: Step
) -> int:
    """The step hidden; the rules computed."""
    async with sessionmaker() as session:
        rule_ids = list(await session.scalars(select(HideRule.id).order_by(HideRule.id)))
    step.total = len(rule_ids)
    computed = 0
    for rule_id in rule_ids:
        if stop.is_set():
            break
        try:
            async with sessionmaker() as session, session.begin():
                rule = await store_rule(session, rule_id)
        except Exception as error:  # one rule's statement: the others still get computed
            log.warning("hide rules: rule %d left as it was: %s", rule_id, describe(error))
        else:
            if rule is not None:  # deleted since: nothing to compute
                computed += 1
                log.info("hide rules: rule %d matches %d mails", rule_id, rule.mails)
        step.advance()
    async with sessionmaker() as session, session.begin():
        figures = await refresh_figures(session)
    log.info("hide rules: %d computed, %d mails matched", computed, figures.mails)
    return computed
