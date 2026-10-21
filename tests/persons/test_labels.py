"""Labels of addresses (D156, D157): which label a person shows, through merges and unmerges,
how they are written, and the conditions the searches build on them."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.api.schemas import AccountLabel, PersonLabelUpdate
from mailrobbe.db.models import Person
from mailrobbe.importer.finalize import finalize
from mailrobbe.persons.labels import (
    address_labels,
    label_matches,
    label_text,
    labelled_persons,
    labelled_roots,
    labels_of,
    root_labels,
    set_label,
    shown_labels,
)
from mailrobbe.persons.merge import merge_persons, unmerge_person
from tests.importer.doubles import fetch
from tests.persons.helpers import ids, mail, store

pytestmark = pytest.mark.db

ANNA, ANNA_MAIL, BERT, CARL = "anna@a.example", "anna@mail.test", "bert@b.example", "carl@c.example"
OLD = datetime(2020, 1, 1, tzinfo=UTC)


async def _persons(session: AsyncSession) -> dict[str, int]:
    await store(
        session,
        [
            mail(f"Anna Adler <{ANNA}>", to=[BERT, CARL]),
            mail(f"Anna Adler <{ANNA_MAIL}>", to=[BERT]),
            mail(f"Bert Brandt <{BERT}>", cc=[ANNA]),
        ],
    )
    await finalize(session)
    return await ids(session)


async def _label(
    session: AsyncSession, email: str, name: str | None, role: str | None = None, *, at: datetime
) -> None:
    await fetch(
        session,
        "INSERT INTO person_label (email, name, role, updated_at)"
        " VALUES (:email, :name, :role, :at)"
        " ON CONFLICT (email) DO UPDATE SET name = :name, role = :role, updated_at = :at"
        " RETURNING email",
        email=email,
        name=name,
        role=role,
        at=at,
    )


def _named(name: str | None, role: str | None = None) -> AccountLabel:
    return AccountLabel(name=name, role=role)


async def test_a_person_shows_its_own_label_else_its_roots_else_the_newest(
    db_session: AsyncSession,
) -> None:
    person = await _persons(db_session)
    everyone = list(person.values())
    assert await labels_of(db_session, everyone) == {}
    assert await labels_of(db_session, []) == {}

    # An alias's label shows on its root, and on the alias itself.
    await merge_persons(db_session, person[ANNA], [person[ANNA_MAIL]])
    await _label(db_session, ANNA_MAIL, "Kassenwart", at=OLD)
    shown = await labels_of(db_session, everyone)
    assert shown == {person[ANNA]: _named("Kassenwart"), person[ANNA_MAIL]: _named("Kassenwart")}

    # The root's own label wins on the root and on aliases without one; an alias keeps its own.
    await _label(db_session, ANNA, "Anna Adler", "Vorstand", at=datetime(2019, 1, 1, tzinfo=UTC))
    shown = await labels_of(db_session, everyone)
    assert shown[person[ANNA]] == _named("Anna Adler", "Vorstand")
    assert shown[person[ANNA_MAIL]] == _named("Kassenwart")
    assert person[BERT] not in shown

    # Several ids at once, one of them twice and one unknown.
    asked = [person[BERT], person[ANNA_MAIL], person[ANNA_MAIL], 987654321]
    assert await labels_of(db_session, asked) == {person[ANNA_MAIL]: _named("Kassenwart")}

    # Unmerged, the alias is a root of its own again and keeps its label; Anna keeps hers.
    await unmerge_person(db_session, person[ANNA_MAIL])
    shown = await labels_of(db_session, everyone)
    assert shown == {
        person[ANNA]: _named("Anna Adler", "Vorstand"),
        person[ANNA_MAIL]: _named("Kassenwart"),
    }


async def test_after_a_merge_the_root_shows_the_newest_label_of_its_aliases(
    db_session: AsyncSession,
) -> None:
    person = await _persons(db_session)
    await _label(db_session, BERT, "Bert", at=OLD)
    await _label(db_session, CARL, "Carl", at=datetime(2021, 1, 1, tzinfo=UTC))
    await merge_persons(db_session, person[ANNA], [person[BERT], person[CARL]])
    shown = await labels_of(db_session, person.values())
    assert shown[person[ANNA]] == _named("Carl")  # the newest
    assert person[ANNA_MAIL] not in shown  # a root of its own
    assert shown[person[BERT]] == _named("Bert")  # its own
    # On the same time the address decides, in byte order.
    await _label(db_session, CARL, "Carl", at=OLD)
    assert (await labels_of(db_session, [person[ANNA]]))[person[ANNA]] == _named("Bert")
    assert await root_labels(db_session) == {person[ANNA]: _named("Bert")}
    # Unmerged, the label goes back to its address alone.
    await unmerge_person(db_session, person[BERT])
    shown = await labels_of(db_session, person.values())
    assert shown[person[BERT]] == _named("Bert")
    assert shown[person[ANNA]] == _named("Carl")
    assert await root_labels(db_session) == {
        person[ANNA]: _named("Carl"),
        person[BERT]: _named("Bert"),
    }


async def test_set_label_trims_keeps_created_at_and_deletes_when_blank(
    db_session: AsyncSession,
) -> None:
    await _persons(db_session)
    update = PersonLabelUpdate(name="  Kassenwart ", role=" ", note="\nZeile 1\nZeile 2 \n")
    await set_label(db_session, ANNA, update, "Lena Vogt")
    await fetch(
        db_session,
        "UPDATE person_label SET created_at = :at, updated_at = :at RETURNING email",
        at=OLD,
    )
    await set_label(db_session, ANNA, update.model_copy(update={"role": "Vorstand"}), None)
    rows = await fetch(
        db_session,
        "SELECT email, name, role, note, editor, created_at, updated_at FROM person_label",
    )
    assert [row[:6] for row in rows] == [
        (ANNA, "Kassenwart", "Vorstand", "Zeile 1\nZeile 2", None, OLD)
    ]
    assert rows[0][6] > OLD
    labels = await address_labels(db_session, [ANNA, BERT])
    assert labels == {ANNA: _named("Kassenwart", "Vorstand")}

    await set_label(db_session, ANNA, PersonLabelUpdate(name=" ", role="", note="  "), "Lena Vogt")
    assert await fetch(db_session, "SELECT email FROM person_label") == []
    # A note alone is a label too: shown, without a name to show.
    await set_label(db_session, BERT, PersonLabelUpdate(name="", role="", note="Quelle?"), None)
    person = await ids(db_session)
    shown = await shown_labels(db_session, [person[BERT]])
    assert shown[person[BERT]].model_dump(exclude={"updated_at"}) == {
        "name": None,
        "role": None,
        "email": BERT,
        "note": "Quelle?",
        "editor": None,
    }


async def test_search_conditions_reach_every_address_of_a_labelled_root(
    db_session: AsyncSession,
) -> None:
    person = await _persons(db_session)
    await merge_persons(db_session, person[ANNA], [person[ANNA_MAIL]])
    await _label(db_session, ANNA_MAIL, "Kassen_wart 100%", "Schatzmeisterin", at=OLD)
    await _label(db_session, CARL, None, "Fahrer", at=OLD)

    async def matching(pattern: str) -> set[str]:
        rows = await db_session.scalars(
            select(Person.canonical_email).where(label_matches(Person, pattern))
        )
        return set(rows)

    assert await matching("%schatzmeister%") == {ANNA, ANNA_MAIL}
    assert await matching("%fahrer%") == {CARL}
    assert await matching("%kassen\\_wart 100\\%%") == {ANNA, ANNA_MAIL}
    assert await matching("%niemand%") == set()
    roots = set(await db_session.scalars(labelled_roots()))
    assert roots == {person[ANNA], person[CARL]}
    assert set(await db_session.scalars(labelled_roots("%fahr%"))) == {person[CARL]}

    named = await labelled_persons(db_session)
    assert named == {
        person[ANNA]: (ANNA, _named("Kassen_wart 100%", "Schatzmeisterin")),
        person[ANNA_MAIL]: (ANNA_MAIL, _named("Kassen_wart 100%", "Schatzmeisterin")),
        person[CARL]: (CARL, _named(None, "Fahrer")),
    }


def test_label_text_names_a_participant() -> None:
    assert label_text(_named("Kassenwart", "Vorstand"), ANNA) == f"Kassenwart, Vorstand ({ANNA})"
    assert label_text(_named("Kassenwart"), ANNA) == f"Kassenwart ({ANNA})"
    assert label_text(_named(None, "Fahrer"), ANNA) == f"Fahrer ({ANNA})"
    assert label_text(_named(None), ANNA) is None
