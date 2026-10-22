"""Hide rules (milestone 18, D221 to D223): the rules, their preview and suggestions. Routes:
GET, POST /api/hide-rules, POST /api/hide-rules/preview, GET /api/hide-rules/suggestions,
PUT and DELETE /api/hide-rules/{id}. Models are in schemas.py; which mails a rule matches is
hiding.model, the one place that turns a rule into SQL.

A rule's text fields are trimmed, empty ones not given; sender, domain and List-Id are compared
in lower case, as the archive stores them. Saving computes the rule's mails and the figures of
the hidden mails in the same transaction (hiding.model.store_rule, refresh_figures), so the
lists, their figures and the mail detail follow at once; the step hidden of every import run
computes all of them again (D221). Writes take the editor from X-Mailrobbe-Editor (D54).
"""

from collections.abc import Sequence
from typing import cast

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import BigInteger, any_, delete, exists, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from mailrobbe.api.deps import Editor, Session, api_error
from mailrobbe.api.filters import order
from mailrobbe.api.mails import mail_items
from mailrobbe.api.research import RowId
from mailrobbe.api.schemas import (
    HIDE_EXAMPLES,
    HIDE_SUGGESTIONS,
    HideRuleFields,
    HideRuleInfo,
    HideRuleList,
    HideRulePreview,
    HideRuleUpdate,
    HideSuggestion,
    MailHiding,
    PersonRef,
    SubjectMatch,
)
from mailrobbe.db.models import HideRule, Mail, MailHidden, MailSignal, Person, PersonStats
from mailrobbe.enums import PersonKind
from mailrobbe.hiding.model import (
    kept,
    kept_counts,
    matches,
    read_figures,
    refresh_figures,
    store_rule,
)
from mailrobbe.persons.labels import attach_labels

router = APIRouter(prefix="/api", tags=["hiding"])

_NEWEST = (HideRule.created_at.desc(), HideRule.id.desc())


@router.get("/hide-rules")
async def list_rules(session: Session) -> HideRuleList:
    """Every rule, newest first, with the mails the enabled ones hide and keep (D203)."""
    rules = list(await session.scalars(select(HideRule).order_by(*_NEWEST)))
    figures = await read_figures(session)
    matched = 0 if figures is None else figures.mails
    kept_now = sum((await kept_counts(session)).values()) if matched else 0
    listed = HideRuleList(
        rules=await rule_infos(session, rules), hidden=max(0, matched - kept_now), kept=kept_now
    )
    await attach_labels(session, listed)
    return listed


@router.post("/hide-rules/preview")
async def preview_rule(fields: HideRuleFields, session: Session) -> HideRulePreview:
    """What the rule would hide (D223): its mails, those kept visible, those with a word-field
    signal (D138), and the newest of them as the list shows them."""
    rule = await _cleaned(session, fields)
    term = exists().where(MailSignal.mail_id == Mail.id, MailSignal.signal.like("term:%"))
    mails, kept_mails, with_terms = (
        await session.execute(
            select(func.count(), func.count().filter(kept()), func.count().filter(term)).where(
                matches(rule)
            )
        )
    ).one()
    newest = select(Mail.id).where(matches(rule)).order_by(*order("date_desc"))
    ids = list(await session.scalars(newest.limit(HIDE_EXAMPLES)))
    shown = HideRulePreview(
        mails=mails, kept=kept_mails, with_terms=with_terms, examples=await mail_items(session, ids)
    )
    await attach_labels(session, shown)
    return shown


@router.post("/hide-rules", status_code=201)
async def create_rule(fields: HideRuleFields, session: Session, editor: Editor) -> HideRuleInfo:
    rule = await _cleaned(session, fields)
    created = HideRule(**rule.model_dump(), created_by=editor, updated_by=editor)
    session.add(created)
    await session.flush()
    return await _stored(session, created.id)


@router.put("/hide-rules/{rule_id}")
async def update_rule(
    rule_id: RowId, change: HideRuleUpdate, session: Session, editor: Editor
) -> HideRuleInfo:
    """Every field anew, enabled included; the rule's mails computed again."""
    rule = await _cleaned(session, change)
    found = await session.scalar(
        update(HideRule)
        .where(HideRule.id == rule_id)
        .values(**rule.model_dump(), updated_by=editor, updated_at=func.now())
        .returning(HideRule.id)
    )
    if found is None:
        raise _not_found(rule_id)
    return await _stored(session, rule_id)


@router.delete("/hide-rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: RowId, session: Session) -> Response:
    """The rule and, through the foreign key, its mails: they show again at once."""
    gone = await session.scalar(
        delete(HideRule).where(HideRule.id == rule_id).returning(HideRule.id)
    )
    if gone is None:
        raise _not_found(rule_id)
    await refresh_figures(session)
    await session.commit()
    return Response(status_code=204)


@router.get("/hide-rules/suggestions")
async def suggestions(session: Session) -> list[HideSuggestion]:
    """The mailing lists and the automated senders with most mails that no enabled rule names
    yet (D223), most mails first: lists by their mails (ix_mail_list_id), senders as root
    persons of kind list or automated by the mails they sent (person_stats)."""
    enabled = select(HideRule).where(HideRule.enabled).subquery()
    named_lists = select(enabled.c.list_id).where(enabled.c.list_id.is_not(None))
    mails = func.count().label("mails")
    lists = await session.execute(
        select(Mail.list_id, mails)
        .where(Mail.list_id.is_not(None), Mail.list_id.not_in(named_lists))
        .group_by(Mail.list_id)
        .order_by(mails.desc(), Mail.list_id)
        .limit(HIDE_SUGGESTIONS)
    )
    named = aliased(Person)  # the roots of the persons and sender addresses rules name
    roots = select(func.coalesce(named.merged_into, named.id)).where(
        or_(
            named.id.in_(select(enabled.c.person_id).where(enabled.c.person_id.is_not(None))),
            named.canonical_email.in_(
                select(enabled.c.sender).where(enabled.c.sender.is_not(None))
            ),
        )
    )
    senders = await session.execute(
        select(Person.id, Person.canonical_email, Person.display_name, PersonStats.sent)
        .join(PersonStats, PersonStats.person_id == Person.id)
        .where(
            Person.merged_into.is_(None),
            Person.kind.in_([PersonKind.LIST, PersonKind.AUTOMATED]),
            PersonStats.sent > 0,
            Person.id.not_in(roots),
        )
        .order_by(PersonStats.sent.desc(), Person.id)
        .limit(HIDE_SUGGESTIONS)
    )
    found = [
        HideSuggestion(kind="list", list_id=list_id, person=None, mails=count)
        for list_id, count in lists
    ] + [
        HideSuggestion(
            kind="sender",
            list_id=None,
            person=PersonRef(person_id=person_id, email=email, name=name),
            mails=sent,
        )
        for person_id, email, name, sent in senders
    ]
    found.sort(key=lambda suggestion: -suggestion.mails)
    await attach_labels(session, *found)
    return found


# Parts shared with the mail detail -------------------------------------------------------------


async def mail_hiding(session: AsyncSession, mail_id: int) -> MailHiding | None:
    """The enabled rules matching the mail, newest first, and whether the team keeps it visible
    (D203); None when no rule matches it."""
    rules = list(
        await session.scalars(
            select(HideRule)
            .join(MailHidden, MailHidden.rule_id == HideRule.id)
            .where(MailHidden.mail_id == mail_id, HideRule.enabled)
            .order_by(*_NEWEST)
        )
    )
    if not rules:
        return None
    stays = await session.scalar(select(kept()).where(Mail.id == mail_id))
    return MailHiding(rules=await rule_infos(session, rules), kept=bool(stays))


async def rule_infos(session: AsyncSession, rules: Sequence[HideRule]) -> list[HideRuleInfo]:
    """The rules as the API shows them, each with its person when it still exists."""
    person_ids = sorted({rule.person_id for rule in rules if rule.person_id is not None})
    persons = {}
    if person_ids:
        rows = await session.execute(
            select(Person.id, Person.canonical_email, Person.display_name).where(
                Person.id == any_(literal(person_ids, ARRAY(BigInteger)))
            )
        )
        persons = {
            person_id: PersonRef(person_id=person_id, email=email, name=name)
            for person_id, email, name in rows
        }
    return [
        HideRuleInfo(
            id=rule.id,
            name=rule.name,
            sender=rule.sender,
            person_id=rule.person_id,
            domain=rule.domain,
            list_id=rule.list_id,
            automated=rule.automated,
            subject=rule.subject,
            subject_match=cast(SubjectMatch, rule.subject_match),
            enabled=rule.enabled,
            person=None if rule.person_id is None else persons.get(rule.person_id),
            mails=rule.mails,
            computed_at=rule.computed_at,
            created_by=rule.created_by,
            created_at=rule.created_at,
            updated_by=rule.updated_by,
            updated_at=rule.updated_at,
        )
        for rule in rules
    ]


# Helpers ---------------------------------------------------------------------------------------


async def _cleaned(session: AsyncSession, fields: HideRuleFields) -> HideRuleFields:
    """The criteria as stored and matched (400 invalid_rule without any, or for a person that
    does not exist); an update keeps its enabled."""

    def text(value: str | None) -> str | None:
        return (value or "").strip() or None

    def lower(value: str | None, strip: str = "") -> str | None:
        return text((value or "").strip().strip(strip).lower())

    rule = fields.model_copy(
        update={
            "name": text(fields.name),
            "sender": lower(fields.sender, "<>"),
            "domain": lower(fields.domain, "@"),
            "list_id": lower(fields.list_id, "<>"),
            "subject": text(fields.subject),
        }
    )
    criteria = (rule.sender, rule.person_id, rule.domain, rule.list_id, rule.subject)
    if not rule.automated and all(criterion is None for criterion in criteria):
        raise api_error(400, "invalid_rule", "a hide rule needs at least one criterion")
    if rule.person_id is not None and not await session.scalar(
        select(exists().where(Person.id == rule.person_id))
    ):
        raise api_error(400, "invalid_rule", f"no person with id {rule.person_id}")
    return rule


async def _stored(session: AsyncSession, rule_id: int) -> HideRuleInfo:
    """Compute the rule's mails and the figures, commit, and answer with the rule."""
    rule = await store_rule(session, rule_id)
    assert rule is not None, "the caller wrote it in this transaction"
    await refresh_figures(session)
    await session.commit()
    (info,) = await rule_infos(session, [rule])
    await attach_labels(session, info)
    return info


def _not_found(rule_id: int) -> HTTPException:
    return api_error(404, "not_found", f"no hide rule with id {rule_id}")
