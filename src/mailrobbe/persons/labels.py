"""Labels the team gives to addresses (D156, D157): the one place reading person_label.

A label belongs to an address, so it outlives re-imports, merges and unmerges. A person shows
the label of its own address, else that of its root, else the newest of the root's other
addresses. attach_labels sets it on every person a response names, in one query, so each
endpoint ends with one call instead of joining person_label itself.
"""

from collections.abc import Collection

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from mailrobbe.api.schemas import AccountLabel, GraphNode, PersonRef, PersonSummary

Executor = AsyncSession | AsyncConnection

# Models whose label is the label of a person id: PersonRef names an address (person_id),
# PersonSummary and GraphNode a root person (id).
_Labelled = PersonRef | PersonSummary | GraphNode


async def labels_of(db: Executor, person_ids: Collection[int]) -> dict[int, AccountLabel]:
    """The label each of these persons shows (D156); persons without one are left out."""
    return {}  # milestone 14: named accounts


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
