"""What the text model reads about a pair of persons (D322), from the database only.

Per person (a root with its aliases): the name, its addresses and the names the mails give them,
the period of its mails, mails sent and received and contacts, its most frequent contacts, the
subjects of its newest own mails and the closing lines of up to CLOSINGS of them. Per pair: how
many contacts both have (humans only, without each other) with the busiest of them, and the
mails between the two. Nothing else of a mail's text: a closing is the signature (quotes.py) of
the own text before the first quote or forward, else its last CLOSING_LINES lines.

The material is German, labelled line by line, and kept short (at most a few thousand
characters), so that system prompt, material and answer fit a context of 4,096 tokens.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text

from mailrobbe.persons.roots import Executor
from mailrobbe.quotes import split_text

ADDRESSES = 5  # addresses shown per person, most named mails first
NAMES = 5  # display names shown per person
CONTACTS = 6  # frequent contacts per person
SHARED = 5  # shared contacts named
SUBJECTS = 5  # subjects of the newest own mails
CLOSINGS = 2  # distinct closings
CLOSING_LINES = 6  # lines of a closing without a signature delimiter
LINE_CHARS = 120  # longer lines are cut
CLOSING_CHARS = 600  # of a closing
SENT_READ = 8  # newest own mails read for subjects and closings

_ROOT = text("""
    SELECT p.display_name, p.canonical_email, s.sent, s.received, s.contacts, s.first_date,
        s.last_date
    FROM person p LEFT JOIN person_stats s ON s.person_id = p.id
    WHERE p.id = :root AND p.merged_into IS NULL AND p.kind IS NULL
""")
_ADDRESSES = text("""
    SELECT e.email, e.display_names FROM person_email e JOIN person p ON p.id = e.person_id
    WHERE p.id = :root OR p.merged_into = :root
""")
_EDGES = """
    SELECT person_b AS other, mails_total AS mails FROM edge WHERE person_a = {root}
    UNION ALL SELECT person_a, mails_total FROM edge WHERE person_b = {root}
"""
_CONTACTS = text(f"""
    SELECT coalesce(p.display_name, p.canonical_email) AS name
    FROM ({_EDGES.format(root=":root")}) e JOIN person p ON p.id = e.other
    WHERE e.other <> :other
    ORDER BY e.mails DESC, p.id LIMIT :limit
""")
_SHARED = text(f"""
    SELECT count(*) OVER () AS shared, coalesce(p.display_name, p.canonical_email) AS name
    FROM ({_EDGES.format(root=":a")}) x JOIN ({_EDGES.format(root=":b")}) y ON y.other = x.other
    JOIN person p ON p.id = x.other
    WHERE x.other NOT IN (:a, :b) AND p.kind IS NULL
    ORDER BY x.mails + y.mails DESC, p.id LIMIT :limit
""")
_BETWEEN = text("""
    SELECT mails_a_to_b, mails_b_to_a, mails_cc FROM edge WHERE person_a = :a AND person_b = :b
""")
_SENT = text("""
    SELECT m.subject, m.body_text FROM participation pa JOIN mail m ON m.id = pa.mail_id
    WHERE pa.role = 'from' AND m.is_duplicate_of IS NULL
      AND pa.person_id IN (SELECT id FROM person WHERE id = :root OR merged_into = :root)
    ORDER BY m.date_utc DESC NULLS LAST, m.id DESC LIMIT :limit
""")


@dataclass(frozen=True, slots=True)
class PersonFacts:
    """What the material says about one person."""

    name: str | None
    email: str
    addresses: list[tuple[str, int]]  # address, mails naming it
    names: list[tuple[str, int]]  # display name, mails
    sent: int
    received: int
    contacts: int
    first: datetime | None
    last: datetime | None
    frequent: list[str]  # names of the most frequent contacts
    subjects: list[str]
    closings: list[str]


@dataclass(frozen=True, slots=True)
class PairFacts:
    a: PersonFacts
    b: PersonFacts
    shared: int  # contacts both have
    shared_names: list[str]
    a_to_b: int
    b_to_a: int
    cc: int


def closing(body: str) -> str:
    """The closing lines of a mail's text (module docstring), "" without any."""
    own_end, signature = len(body), None
    for segment in split_text(body):
        if segment.kind in ("quote", "original", "forward"):
            own_end = min(own_end, segment.start)
        elif segment.kind == "signature" and signature is None and segment.start < own_end:
            signature = (segment.start, segment.end)
    if signature is not None:
        lines = body[signature[0] : min(signature[1], own_end)].split("\n")
    else:
        lines = body[:own_end].split("\n")
    kept = [line.strip()[:LINE_CHARS] for line in lines if line.strip() and line.strip() != "--"]
    return "\n".join(kept if signature is not None else kept[-CLOSING_LINES:])[:CLOSING_CHARS]


async def read_pair(db: Executor, a: int, b: int) -> PairFacts | None:
    """The facts of roots a < b; None when either is no human root any more."""
    first, second = await _person(db, a, b), await _person(db, b, a)
    if first is None or second is None:
        return None
    shared = list(await db.execute(_SHARED, {"a": a, "b": b, "limit": SHARED}))
    between = (await db.execute(_BETWEEN, {"a": a, "b": b})).first()
    return PairFacts(
        a=first,
        b=second,
        shared=shared[0].shared if shared else 0,
        shared_names=[row.name for row in shared],
        a_to_b=between.mails_a_to_b if between else 0,
        b_to_a=between.mails_b_to_a if between else 0,
        cc=between.mails_cc if between else 0,
    )


async def _person(db: Executor, root: int, other: int) -> PersonFacts | None:
    row = (await db.execute(_ROOT, {"root": root})).first()
    if row is None:
        return None
    addresses: list[tuple[str, int]] = []
    names: Counter[str] = Counter()
    for email, used in await db.execute(_ADDRESSES, {"root": root}):
        addresses.append((email, sum(used.values())))
        names.update(used)
    addresses.sort(key=lambda item: (-item[1], item[0]))
    frequent = await db.scalars(_CONTACTS, {"root": root, "other": other, "limit": CONTACTS})
    subjects: list[str] = []
    closings: list[str] = []
    for subject, body in await db.execute(_SENT, {"root": root, "limit": SENT_READ}):
        line = " ".join((subject or "").split())[:LINE_CHARS]
        if line and line not in subjects and len(subjects) < SUBJECTS:
            subjects.append(line)
        found = closing(body or "")
        if found and found not in closings and len(closings) < CLOSINGS:
            closings.append(found)
    return PersonFacts(
        name=row.display_name,
        email=row.canonical_email,
        addresses=addresses[:ADDRESSES],
        names=sorted(names.items(), key=lambda item: (-item[1], item[0]))[:NAMES],
        sent=row.sent or 0,
        received=row.received or 0,
        contacts=row.contacts or 0,
        first=row.first_date,
        last=row.last_date,
        frequent=list(frequent),
        subjects=subjects,
        closings=closings,
    )


def material(facts: PairFacts) -> str:
    """The facts as the model reads them, German, one labelled line each."""
    blocks = [_person_text("Person A", facts.a), _person_text("Person B", facts.b)]
    shared = f"Gemeinsame Kontakte: {facts.shared}"
    if facts.shared_names:
        shared += f" (darunter {', '.join(facts.shared_names)})"
    between = (
        f"Mails zwischen beiden: {facts.a_to_b} von A an B, {facts.b_to_a} von B an A, "
        f"{facts.cc} mit einem von beiden in Kopie"
    )
    blocks.append("\n".join(["Beide", shared, between]))
    return "\n\n".join(blocks)


def _person_text(title: str, person: PersonFacts) -> str:
    lines = [title, f"Name: {person.name or '(keiner)'}"]
    lines.append("Adressen: " + ", ".join(_counted(email, n) for email, n in person.addresses))
    if person.names:
        lines.append("Namen in Mails: " + ", ".join(f"{name} ({n})" for name, n in person.names))
    lines.append(f"Zeitraum: {_period(person.first, person.last)}")
    lines.append(
        f"Mails: {person.sent} gesendet, {person.received} empfangen, {person.contacts} Kontakte"
    )
    if person.frequent:
        lines.append(f"Häufige Kontakte: {', '.join(person.frequent)}")
    if person.subjects:
        lines.append("Betreffzeilen eigener Mails: " + "; ".join(f"„{s}“" for s in person.subjects))
    for number, found in enumerate(person.closings, 1):
        lines.append(f"Schlusszeilen einer eigenen Mail ({number}):")
        lines += [f"| {line}" for line in found.split("\n")]
    return "\n".join(lines)


def _counted(email: str, mails: int) -> str:
    return f"{email} ({mails} Mails mit Namen)" if mails else email


def _period(first: datetime | None, last: datetime | None) -> str:
    if first is None or last is None:
        return "unbekannt"
    return f"{first:%m.%Y} bis {last:%m.%Y}"
