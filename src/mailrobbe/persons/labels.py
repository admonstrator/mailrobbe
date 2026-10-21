"""Labels the team gives to addresses (D156, D157): the one place reading person_label.

A label belongs to an address, so it outlives re-imports, merges and unmerges. A person shows
the label of its own address, else that of its root, else the newest of the root's other
addresses. attach_labels sets it on every person a response names, in one query, so each
endpoint ends with one call instead of joining person_label itself.

person_label holds what the team typed, a few hundred rows at most: every query starts from it
and reaches the persons through their unique address and ix_person_merged_into.
"""

from collections.abc import Collection
from typing import Any

from pydantic import BaseModel
from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Select,
    Subquery,
    any_,
    delete,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.orm.util import AliasedClass

from mailrobbe.api.schemas import (
    AccountLabel,
    GraphNode,
    PersonLabel,
    PersonLabelUpdate,
    PersonRef,
    PersonSummary,
)
from mailrobbe.db.models import Person
from mailrobbe.db.models import PersonLabel as LabelRow
from mailrobbe.persons.roots import ROOT

Executor = AsyncSession | AsyncConnection

# Models whose label is the label of a person id: PersonRef names an address (person_id),
# PersonSummary and GraphNode a root person (id).
_Labelled = PersonRef | PersonSummary | GraphNode

_OWNER = aliased(Person, name="owner")  # the person of a labelled address
_MEMBER = aliased(Person, name="member")  # a person of a labelled root


def _labelled() -> Subquery:
    """Every label with the person of its address (person_id) and that person's root; labels
    of addresses no longer in the archive are left out."""
    return (
        select(
            LabelRow,
            _OWNER.id.label("person_id"),
            func.coalesce(_OWNER.merged_into, _OWNER.id).label("root"),
        )
        .join(_OWNER, _OWNER.canonical_email == LabelRow.email)
        .subquery("labelled")
    )


def _shown_first(
    labelled: Subquery, person_id: ColumnElement[int], root: ColumnElement[int]
) -> list[Any]:
    """The order in which a person's candidates are shown (D156): its own address, the root's,
    then the newest of the others."""
    return [
        (labelled.c.person_id == person_id).desc(),
        (labelled.c.person_id == root).desc(),
        labelled.c.updated_at.desc(),
        labelled.c.email.collate("C"),
    ]


def _ids(values: Collection[int]) -> ColumnElement[list[int]]:
    return literal(list(values), ARRAY(BigInteger))


async def _shown(db: Executor, person_ids: Collection[int]) -> list[Any]:
    """Per person id that has one, the row of the label it shows (id and the label's columns)."""
    if not person_ids:
        return []
    asked = (
        select(Person.id, ROOT.label("root"))
        .where(Person.id == any_(_ids(person_ids)))
        .subquery("asked")
    )
    labelled = _labelled()
    statement = (
        select(asked.c.id, labelled)
        .join(labelled, labelled.c.root == asked.c.root)
        .ext(postgresql.distinct_on(asked.c.id))
        .order_by(asked.c.id, *_shown_first(labelled, asked.c.id, asked.c.root))
    )
    return list(await db.execute(statement))


async def labels_of(db: Executor, person_ids: Collection[int]) -> dict[int, AccountLabel]:
    """The label each of these persons shows (D156); persons without one are left out."""
    return {
        row.id: AccountLabel(name=row.name, role=row.role) for row in await _shown(db, person_ids)
    }


async def shown_labels(db: Executor, person_ids: Collection[int]) -> dict[int, PersonLabel]:
    """As labels_of, with each label's note, editor and the address it belongs to."""
    return {
        row.id: PersonLabel(
            email=row.email,
            name=row.name,
            role=row.role,
            note=row.note,
            editor=row.editor,
            updated_at=row.updated_at,
        )
        for row in await _shown(db, person_ids)
    }


async def address_labels(db: Executor, emails: Collection[str]) -> dict[str, AccountLabel]:
    """The label of each of these addresses itself; addresses without one are left out."""
    if not emails:
        return {}
    rows = await db.execute(
        select(LabelRow.email, LabelRow.name, LabelRow.role).where(
            LabelRow.email == any_(literal(list(emails), ARRAY(LabelRow.email.type)))
        )
    )
    return {email: AccountLabel(name=name, role=role) for email, name, role in rows}


async def root_labels(db: Executor) -> dict[int, AccountLabel]:
    """The label every labelled root person shows, by root id (the full GraphML export)."""
    labelled = _labelled()
    rows = await db.execute(
        select(labelled.c.root, labelled.c.name, labelled.c.role)
        .ext(postgresql.distinct_on(labelled.c.root))
        .order_by(labelled.c.root, *_shown_first(labelled, labelled.c.root, labelled.c.root))
    )
    return {root: AccountLabel(name=name, role=role) for root, name, role in rows}


async def labelled_persons(db: Executor) -> dict[int, tuple[str, AccountLabel]]:
    """Every person (address) that shows a label, with its address (the mail list's CSV)."""
    roots = labelled_roots()
    members = await db.execute(
        select(_MEMBER.id, _MEMBER.canonical_email).where(
            or_(_MEMBER.id.in_(roots), _MEMBER.merged_into.in_(roots))
        )
    )
    emails = {person_id: email for person_id, email in members}
    labels = await labels_of(db, emails)
    return {person_id: (emails[person_id], label) for person_id, label in labels.items()}


def label_text(label: AccountLabel, email: str) -> str | None:
    """ "Name, Rolle (Adresse)", as the exports name a labelled participant; None for a label
    with a note alone."""
    named = ", ".join(part for part in (label.name, label.role) if part)
    return f"{named} ({email})" if named else None


async def set_label(
    db: Executor, email: str, update: PersonLabelUpdate, editor: str | None
) -> None:
    """Write the label of this address: blank fields are none, all blank deletes it."""
    values = {
        "name": update.name.strip() or None,
        "role": update.role.strip() or None,
        "note": update.note.strip() or None,
    }
    if not any(values.values()):
        await db.execute(delete(LabelRow).where(LabelRow.email == email))
        return
    insert = postgresql.insert(LabelRow).values(email=email, editor=editor, **values)
    await db.execute(
        insert.on_conflict_do_update(
            index_elements=[LabelRow.email],
            set_={**values, "editor": editor, "updated_at": func.now()},
        )
    )


def labelled_roots(pattern: str | None = None) -> Select[int]:
    """The root persons showing a label (D157); with an ILIKE pattern, only those with a label
    on any of their addresses whose name or role matches it."""
    labelled = _labelled()
    statement = select(labelled.c.root)
    if pattern is not None:
        statement = statement.where(
            or_(labelled.c.name.ilike(pattern), labelled.c.role.ilike(pattern))
        )
    return statement


def label_matches(person: type[Person] | AliasedClass[Person], pattern: str) -> ColumnElement[bool]:
    """The person (any address) belongs to a root with a label whose name or role matches the
    ILIKE pattern (D157). The persons are listed first, as an array the primary key can look up,
    so the condition joins the trigram conditions on the person in one bitmap OR."""
    roots = func.array(labelled_roots(pattern).scalar_subquery())
    members = select(_MEMBER.id).where(
        or_(_MEMBER.id == any_(roots), _MEMBER.merged_into == any_(roots))
    )
    return person.id == any_(func.array(members.scalar_subquery()))


async def attach_labels(db: Executor, *responses: BaseModel) -> None:
    """Set the label of every PersonRef, PersonSummary and GraphNode inside these responses."""
    found: list[_Labelled] = []
    for response in responses:
        _collect(response, found)
    if not found:
        return
    labels = await labels_of(db, {_person_id(item) for item in found})
    for item in found:
        item.label = labels.get(_person_id(item))


def _person_id(item: _Labelled) -> int:
    return item.person_id if isinstance(item, PersonRef) else item.id


def _collect(value: object, found: list[_Labelled]) -> None:
    if isinstance(value, PersonRef | PersonSummary | GraphNode):
        found.append(value)
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            _collect(getattr(value, name), found)
    elif isinstance(value, list | tuple):
        for item in value:
            _collect(item, found)
    elif isinstance(value, dict):
        for item in value.values():
            _collect(item, found)
