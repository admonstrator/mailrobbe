"""Questions about persons, "KI fragen" on a person's page (D347, D348).

    templates   TEMPLATES: what the team can ask, one of them about two persons (compare), and a
                free question
    choose      conversations(): the conversations of a person, or of two, that the model reads:
                its threads (a mail without one is a conversation of its own) among the mails it
                took part in that no hide rule hides and that are no duplicates, those with both
                persons first, then the most mails of theirs, then the latest; at most
                QUESTION_CONVERSATIONS. A conversation of THREAD_MIN_MAILS mails or more is read
                by its thread's summary, else by its mail's
    prework     queue_prework(): what the answer waits for, first in the queue (D329): the
                summaries those conversations lack, the OCR or transcription of their attachments
                and the attachments' summaries (ai.queue.enqueue_attachments). The question keeps
                their keys (person_question.prework), so the page counts what is still open
                (open_prework) and the run takes the question once none is
    ask         the step ask of the AI run (QuestionStep): the facts of the persons (figures,
                years, most frequent contacts, the mails between the two) and the summaries of
                the conversations and their attachments, within the characters the context
                leaves, between the markers; then the question. One request, the answer bound to
                {"answer": "..."}; an answer cut at its length, an HTTP error or no valid answer
                is an attempt, and the question fails after AI_TASK_ATTEMPTS

Every run takes a waiting question, whatever it was started for (D329). The material names
persons, addresses and what they wrote, so the step uses a text service on this machine only, as
the alias check does (D322). Nothing is read from the MBOX files: the summaries are what the
model reads.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, case, func, literal, or_, select, text
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from mailrobbe.ai import queue
from mailrobbe.ai.model import (
    AI_TASK_ATTEMPTS,
    ALIAS_THINKING_TOKENS,
    CHARS_PER_TOKEN,
    QUESTION_ANSWER_TOKENS,
    QUESTION_CONTACTS,
    QUESTION_CONVERSATIONS,
    QUESTION_MAILS,
    THREAD_MIN_MAILS,
    Protocol,
    Service,
    locality,
)
from mailrobbe.ai.prompts import MATERIAL_END, MATERIAL_START, QuestionPrompts, load_prompts
from mailrobbe.ai.services import AnswerError, ChatAnswer, chat_text, cut_at_length
from mailrobbe.ai.summarize.answer import answer_object, shown
from mailrobbe.ai.summarize.prompt import material as defused
from mailrobbe.db.models import Mail, Participation, Person
from mailrobbe.hiding.model import visible
from mailrobbe.jobrun import Step, describe

if TYPE_CHECKING:
    from mailrobbe.ai.run import _Run

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Template:
    label: str  # the button's words
    question: str  # what the model is asked; "" for the free question
    compare: bool = False  # needs a second person (Person B)


TEMPLATES: dict[str, Template] = {
    "contacts": Template(
        "Wichtigste Kontakte",
        "Mit wem hat Person A am meisten geschrieben, und worum ging es dabei?",
    ),
    "compare": Template(
        "Mit einer zweiten Person vergleichen",
        "Vergleiche Person A mit Person B: Welche Zusammenhänge siehst du? Wo haben sie "
        "miteinander zu tun, welche Kontakte und Themen teilen sie?",
        compare=True,
    ),
    "timeline": Template(
        "Verlauf über die Zeit",
        "Wie hat sich der Austausch von Person A über die Zeit verändert? Gibt es Phasen mit "
        "auffällig viel oder wenig Kontakt, und was geschah da?",
    ),
    "topics": Template(
        "Häufigste Themen",
        "Welche Themen kommen bei Person A am häufigsten vor?",
    ),
    "notable": Template(
        "Auffälligkeiten",
        "Gibt es bei Person A Auffälligkeiten, die eine genauere Prüfung lohnen? Nenne die "
        "Stellen, ohne sie zu bewerten.",
    ),
    "role": Template(
        "Rolle im Umfeld",
        "Welche Rolle hat Person A im Kreis ihrer Kontakte: entscheidet sie, arbeitet sie zu, "
        "vermittelt sie? Begründe mit Belegen aus dem Material.",
    ),
    "outside": Template(
        "Kontakte außerhalb",
        "Wer sind die wichtigsten Gesprächspartner von Person A außerhalb der eigenen "
        "Organisation, und worum ging es mit ihnen?",
    ),
    "free": Template("Eigene Frage", ""),
}


# choose ---------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Conversation:
    """One conversation the model reads: a thread, or a mail without one."""

    thread_id: int | None  # the thread read by its summary; None: the mail by its own
    mail_id: int  # the latest mail of the persons in it
    mails: list[int]  # their mails in it, the latest first, at most QUESTION_MAILS
    count: int  # their mails in it
    first: datetime | None
    last: datetime | None


def _members(root: int | None) -> Any:
    return select(Person.id).where(or_(Person.id == root, Person.merged_into == root))


async def conversations(
    session: AsyncSession, person: int, other: int | None = None
) -> list[Conversation]:
    """The conversations of a root person, or of two (module docstring)."""
    a, b = _members(person), _members(other)
    taking = (
        select(
            Participation.mail_id,
            func.bool_or(Participation.person_id.in_(a)).label("of_a"),
            func.bool_or(Participation.person_id.in_(b)).label("of_b"),
        )
        .where(or_(Participation.person_id.in_(a), Participation.person_id.in_(b)))
        .group_by(Participation.mail_id)
        .subquery()
    )
    key = func.coalesce(Mail.thread_id, -Mail.id)
    both = (
        and_(func.bool_or(taking.c.of_a), func.bool_or(taking.c.of_b))
        if other is not None
        else literal(True)
    )
    statement = (
        select(
            func.max(Mail.thread_id).label("thread_id"),
            func.array_agg(aggregate_order_by(Mail.id, Mail.date_utc.desc().nulls_last())).label(
                "mails"
            ),
            func.count().label("taken"),
            func.min(Mail.date_utc).label("first"),
            func.max(Mail.date_utc).label("last"),
        )
        .join(taking, taking.c.mail_id == Mail.id)
        .where(Mail.is_duplicate_of.is_(None), visible())
        .group_by(key)
        .order_by(
            case((both, 0), else_=1),
            func.count().desc(),
            func.max(Mail.date_utc).desc().nulls_last(),
            key,
        )
        .limit(QUESTION_CONVERSATIONS)
    )
    rows = (await session.execute(statement)).all()
    threads = [row.thread_id for row in rows if row.thread_id is not None]
    sizes: dict[int, int] = dict((await session.execute(_SIZES, {"thread_ids": threads})).all())
    return [
        Conversation(
            thread_id=row.thread_id if sizes.get(row.thread_id, 0) >= THREAD_MIN_MAILS else None,
            mail_id=row.mails[0],
            mails=list(row.mails[:QUESTION_MAILS]),
            count=int(row.taken),
            first=row.first,
            last=row.last,
        )
        for row in rows
    ]


_SIZES = text("""
    SELECT m.thread_id, count(DISTINCT m.raw_sha256) FROM mail m
    WHERE m.thread_id = ANY(CAST(:thread_ids AS bigint[])) AND m.is_duplicate_of IS NULL
    GROUP BY m.thread_id
""")


# prework --------------------------------------------------------------------------------------

_SUMMARIZED_THREADS = text("""
    SELECT thread_id FROM ai_result
    WHERE kind = 'summarize' AND target = 'thread' AND state = 'valid'
      AND thread_id = ANY(CAST(:ids AS bigint[]))
""")
_SUMMARIZED_MAILS = text("""
    SELECT m.id FROM mail m
    WHERE m.id = ANY(CAST(:ids AS bigint[]))
      AND EXISTS (SELECT 1 FROM ai_result r
                  WHERE r.kind = 'summarize' AND r.target = 'mail'
                    AND r.target_sha256 = m.raw_sha256 AND r.state = 'valid')
""")
# The open tasks among a question's prework (person_question.prework, D348): {threads}, {mails}
# and {documents} are its keys as bigint[] (open_prework).
_OPEN_PREWORK = """
    SELECT count(*) FROM ai_task t
    WHERE t.status IN ('waiting', 'running') AND (
        (t.target = 'thread' AND t.thread_id = ANY({threads}))
        OR (t.target = 'mail' AND t.target_sha256 IN
            (SELECT raw_sha256 FROM mail WHERE id = ANY({mails})))
        OR (t.target = 'document' AND t.target_sha256 IN
            (SELECT sha256 FROM document WHERE id = ANY({documents}))))
"""


def open_prework(keys: str | None = None) -> str:
    """_OPEN_PREWORK over the bind parameters :threads, :mails and :documents, or over the JSONB
    column keys (a question's prework)."""

    def key(name: str) -> str:
        if keys is None:
            return f"CAST(:{name} AS bigint[])"
        return (
            f"ARRAY(SELECT jsonb_array_elements_text(COALESCE({keys} -> '{name}', "
            "'[]'::jsonb))::bigint)"
        )

    return _OPEN_PREWORK.format(
        threads=key("threads"), mails=key("mails"), documents=key("documents")
    )


@dataclass(frozen=True, slots=True)
class Prework:
    """What queue_prework queued: the keys the question waits for and the figures."""

    threads: list[int]
    mails: list[int]
    documents: list[int]  # attachments read or summarised first
    pending: list[int]  # among them those read by OCR or the transcriber first
    summaries: queue.QueuedSummaries
    recognized: queue.Queued

    def keys(self) -> dict[str, list[int]]:
        return {"threads": self.threads, "mails": self.mails, "documents": self.documents}


async def queue_prework(
    session: AsyncSession, person: int, other: int | None, *, editor: str | None
) -> Prework:
    """Queue what the answer waits for (module docstring), first in the queue; in the caller's
    transaction."""
    found = await conversations(session, person, other)
    threads = sorted({c.thread_id for c in found if c.thread_id is not None})
    mails = sorted({c.mail_id for c in found if c.thread_id is None})
    if threads:
        done = set((await session.scalars(_SUMMARIZED_THREADS, {"ids": threads})).all())
        threads = [thread for thread in threads if thread not in done]
    if mails:
        done = set((await session.scalars(_SUMMARIZED_MAILS, {"ids": mails})).all())
        mails = [mail for mail in mails if mail not in done]
    attached = await queue.enqueue_attachments(
        session, sorted({mail for c in found for mail in c.mails}), editor=editor
    )
    summaries = await queue.enqueue_summaries(
        session,
        mail_ids=mails,
        document_ids=attached.summarize,
        thread_ids=threads,
        pending=attached.pending,
        editor=editor,
        single=True,
    )
    return Prework(
        threads, mails, attached.summarize, attached.pending, summaries, attached.recognized
    )


# ask ------------------------------------------------------------------------------------------

_PERSON = text("""
    SELECT p.id, p.display_name, p.canonical_email, p.domain, s.sent, s.received, s.first_date,
        s.last_date
    FROM person p LEFT JOIN person_stats s ON s.person_id = p.id
    WHERE p.id = :id
""")
_ADDRESSES = text("""
    SELECT e.email FROM person_email e JOIN person p ON p.id = e.person_id
    WHERE p.id = :id OR p.merged_into = :id
    ORDER BY e.email LIMIT 10
""")
_YEARS = text("""
    SELECT year, sent, received FROM person_year WHERE person_id = :id ORDER BY year
""")
_CONTACTS = text("""
    SELECT p.display_name, p.canonical_email, p.domain, e.mails_total,
        CASE WHEN e.person_a = :id THEN e.mails_a_to_b ELSE e.mails_b_to_a END AS sent,
        CASE WHEN e.person_a = :id THEN e.mails_b_to_a ELSE e.mails_a_to_b END AS received,
        e.first_date, e.last_date
    FROM edge e
    JOIN person p ON p.id = CASE WHEN e.person_a = :id THEN e.person_b ELSE e.person_a END
    WHERE e.person_a = :id OR e.person_b = :id
    ORDER BY e.mails_total DESC, p.id LIMIT :limit
""")
_PAIR = text("""
    SELECT mails_a_to_b, mails_b_to_a, mails_cc, first_date, last_date FROM edge
    WHERE person_a = LEAST(CAST(:a AS bigint), CAST(:b AS bigint))
      AND person_b = GREATEST(CAST(:a AS bigint), CAST(:b AS bigint))
""")
_HEADS = text("""
    SELECT id, subject FROM mail WHERE id = ANY(CAST(:ids AS bigint[]))
""")
_THREAD_SUMMARIES = text("""
    SELECT thread_id, body FROM ai_result
    WHERE kind = 'summarize' AND target = 'thread' AND state = 'valid'
      AND thread_id = ANY(CAST(:ids AS bigint[]))
""")
_MAIL_SUMMARIES = text("""
    SELECT m.id, r.body FROM mail m
    JOIN ai_result r ON r.kind = 'summarize' AND r.target = 'mail'
        AND r.target_sha256 = m.raw_sha256 AND r.state = 'valid'
    WHERE m.id = ANY(CAST(:ids AS bigint[]))
""")
_ATTACHMENT_SUMMARIES = text("""
    SELECT DISTINCT ON (d.id) a.mail_id, d.name, r.body
    FROM attachment a
    JOIN document d ON d.id = a.document_id
    JOIN ai_result r ON r.kind = 'summarize' AND r.target = 'document'
        AND r.target_sha256 = d.sha256 AND r.state = 'valid'
    WHERE a.mail_id = ANY(CAST(:ids AS bigint[])) AND a.container_id IS NULL
    ORDER BY d.id, a.mail_id
""")


def _day(value: datetime | None) -> str:
    return value.date().isoformat() if value else "?"


def _who(name: str | None, email: str) -> str:
    return f"{name} <{email}>" if name else email


async def _facts(session: AsyncSession, letter: str, person: int, internal: set[str]) -> str:
    """What the archive knows about one person, as lines of the material."""
    row = (await session.execute(_PERSON, {"id": person})).one()
    addresses = list(await session.scalars(_ADDRESSES, {"id": person}))
    lines = [f"Person {letter}: {_who(row.display_name, row.canonical_email)}"]
    if len(addresses) > 1:
        lines.append(f"Adressen: {', '.join(addresses)}")
    if row.sent is not None:
        lines.append(
            f"Mails: {row.sent} gesendet, {row.received} empfangen, "
            f"von {_day(row.first_date)} bis {_day(row.last_date)}"
        )
    years = (await session.execute(_YEARS, {"id": person})).all()
    if years:
        lines.append(
            "Je Jahr (gesendet/empfangen): "
            + ", ".join(f"{y.year}: {y.sent}/{y.received}" for y in years)
        )
    contacts = await session.execute(_CONTACTS, {"id": person, "limit": QUESTION_CONTACTS})
    lines.append(f"Häufigste Kontakte von Person {letter}:")
    for c in contacts:
        own = " (eigene Organisation)" if c.domain in internal else ""
        lines.append(
            f"- {_who(c.display_name, c.canonical_email)}{own}: {c.mails_total} Mails "
            f"({c.sent} an, {c.received} von), {_day(c.first_date)} bis {_day(c.last_date)}"
        )
    return "\n".join(lines)


async def material(
    session: AsyncSession,
    person: int,
    other: int | None,
    internal: set[str],
    limit: int,
) -> tuple[str, int]:
    """The material of a question within limit characters, and the summaries it holds."""
    head = [await _facts(session, "A", person, internal)]
    if other is not None:
        head.append(await _facts(session, "B", other, internal))
        pair = (await session.execute(_PAIR, {"a": person, "b": other})).first()
        if pair is None:
            head.append("Zwischen Person A und Person B gibt es keine Mails.")
        else:
            a_to_b, b_to_a = (
                (pair.mails_a_to_b, pair.mails_b_to_a)
                if person < other
                else (pair.mails_b_to_a, pair.mails_a_to_b)
            )
            head.append(
                f"Zwischen Person A und Person B: {a_to_b} Mails von A an B, {b_to_a} von B an "
                f"A, {pair.mails_cc} in Kopie, {_day(pair.first_date)} bis {_day(pair.last_date)}"
            )
    if internal:
        head.append(f"Eigene Organisation: {', '.join(sorted(internal))}")
    found = await conversations(session, person, other)
    threads = [c.thread_id for c in found if c.thread_id is not None]
    singles = [c.mail_id for c in found if c.thread_id is None]
    every = [mail for c in found for mail in c.mails]
    subjects: dict[int, str | None] = dict(
        (await session.execute(_HEADS, {"ids": [c.mail_id for c in found]})).all()
    )
    by_thread: dict[int, str] = dict(
        (await session.execute(_THREAD_SUMMARIES, {"ids": threads})).all()
    )
    by_mail: dict[int, str] = dict((await session.execute(_MAIL_SUMMARIES, {"ids": singles})).all())
    attached: dict[int, list[tuple[str, str]]] = {}
    for row in await session.execute(_ATTACHMENT_SUMMARIES, {"ids": every}):
        attached.setdefault(row.mail_id, []).append((row.name or "Anhang", row.body))
    text_ = "\n\n".join(head) + "\n\nGespräche, die wichtigsten zuerst:"
    used = 0
    for c in found:
        summary = by_thread.get(c.thread_id) if c.thread_id is not None else by_mail.get(c.mail_id)
        files = [item for mail in c.mails for item in attached.get(mail, [])]
        if not summary and not files:
            continue
        kind = "Thread" if c.thread_id is not None else "Mail"
        block = [
            f"\n{kind} „{subjects.get(c.mail_id) or '(kein Betreff)'}“, {c.count} Mails, "
            f"{_day(c.first)} bis {_day(c.last)}"
        ]
        if summary:
            block.append(f"Zusammenfassung: {summary}")
        block += [f"Anhang „{name}“: {body}" for name, body in files]
        joined = "\n".join(block)
        if len(text_) + len(joined) > limit:
            break
        text_ += joined
        used += 1 + len(files)
    if not used:
        text_ += "\n(keine Zusammenfassungen vorhanden)"
    return defused([text_[:limit]], ""), used


_TAKE = text(f"""
    UPDATE person_question q SET status = 'running', job_id = :job_id, started_at = now()
    WHERE q.id = (
        SELECT w.id FROM person_question w
        WHERE w.status = 'waiting' AND ({open_prework("w.prework")}) = 0
        ORDER BY w.id LIMIT 1 FOR UPDATE OF w SKIP LOCKED)
    RETURNING q.id, q.person_id, q.other_id, q.question
""")
_COUNT = text("SELECT count(*) FROM person_question WHERE status = 'waiting'")
_DONE = text("""
    UPDATE person_question SET status = 'done', answer = :answer, contents = :contents,
        model = :model, prompt_version = :prompt_version, seconds = :seconds,
        tokens_in = :tokens_in, tokens_out = :tokens_out, error = NULL, finished_at = now()
    WHERE id = :id
""")
_FAIL = text("""
    UPDATE person_question SET status = 'failed', error = :error, attempts = :attempts,
        finished_at = now()
    WHERE id = :id
""")
_BACK = text("UPDATE person_question SET status = 'waiting' WHERE id = :id")
_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


class _Attempt(Exception):
    """The answer was no valid one (English reason)."""


class QuestionStep:
    """The step ask of one run (module docstring); ai.run checks the service and runs it."""

    def __init__(self, run: "_Run") -> None:
        self.run = run
        self.waiting = 0
        self.service: Service | None = None
        self.protocol: Protocol | None = None
        self.problem: str | None = None
        self._prompts: QuestionPrompts | None = None

    async def count(self) -> int:
        async with self.run.sessionmaker() as session:
            self.waiting = int(await session.scalar(_COUNT) or 0)
        return self.waiting

    def use(self, service: Service, protocol: Protocol) -> None:
        if locality(service.url) == "remote":
            self.leave(
                f"questions about persons go to a text service on this machine only, not to "
                f"{service.display_url}"
            )
            return
        self.service, self.protocol = service, protocol

    def leave(self, problem: str) -> None:
        self.problem = problem
        log.warning("%d questions about persons wait: %s", self.waiting, problem)

    async def take(self) -> Any:
        async with self.run.sessionmaker.begin() as session:
            return (await session.execute(_TAKE, {"job_id": self.run.job.job_id})).first()

    def _answer_tokens(self) -> int:
        thinks = self.service is not None and self.service.reasoning != "off"
        return QUESTION_ANSWER_TOKENS + (ALIAS_THINKING_TOKENS if thinks else 0)

    async def work(self, question: Any, counter: Step) -> None:
        """One question to its end: done, failed, or back to waiting when the run ends."""
        run = self.run
        if self._prompts is None:
            self._prompts = load_prompts().questions
        prompts = self._prompts
        internal = {
            domain
            for part in run.settings.internal_domains.split(",")
            if (domain := part.strip().lower())
        }
        room = run.options.context_tokens - self._answer_tokens() - len(prompts.system) // 3
        limit = max(0, int(room * CHARS_PER_TOKEN) - len(question.question) - 100)
        run.progress.current = "Frage zu einer Person"
        try:
            async with run.sessionmaker() as session:
                found, contents = await material(
                    session, question.person_id, question.other_id, internal, limit
                )
            user = f"{MATERIAL_START}\n{found}\n{MATERIAL_END}\n\nFrage: {question.question}"
            error = "no answer"
            for _ in range(AI_TASK_ATTEMPTS):
                try:
                    answer, reply, seconds = await self._ask(user)
                    break
                except _Attempt as attempt:
                    error = str(attempt)
                    log.warning("question %d: %s", question.id, attempt)
            else:
                async with run.sessionmaker.begin() as session:
                    await session.execute(
                        _FAIL, {"id": question.id, "error": error, "attempts": AI_TASK_ATTEMPTS}
                    )
                run.summary.questions_failed += 1
                counter.advance()
                return
            assert self.service is not None
            async with run.sessionmaker.begin() as session:
                await session.execute(
                    _DONE,
                    {
                        "id": question.id,
                        "answer": answer,
                        "contents": contents,
                        "model": self.service.model,
                        "prompt_version": prompts.version,
                        "seconds": seconds,
                        "tokens_in": reply.tokens_in,
                        "tokens_out": reply.tokens_out,
                    },
                )
            run.summary.questions += 1
            counter.advance()
        except BaseException:
            async with run.sessionmaker.begin() as session:
                await session.execute(_BACK, {"id": question.id})
            raise
        finally:
            run.progress.current = None

    async def _ask(self, user: str) -> tuple[str, ChatAnswer, float]:
        service, protocol, run, prompts = self.service, self.protocol, self.run, self._prompts
        assert service is not None and protocol is not None and prompts is not None
        tokens = self._answer_tokens()

        def request() -> tuple[ChatAnswer, float]:
            started = time.monotonic()
            found = chat_text(
                service,
                protocol,
                system=prompts.system,
                user=user,
                schema=_SCHEMA,
                max_tokens=tokens,
                timeout=run.settings.ai_timeout,
                context_tokens=run.options.context_tokens,
            )
            return found, round(time.monotonic() - started, 3)

        try:
            found, seconds = await run._answer(service, request)
        except AnswerError as error:
            raise _Attempt(describe(error)) from None
        for figures in (run.summary, run.progress):
            figures.tokens_in += found.tokens_in
            figures.tokens_out += found.tokens_out
        if found.finish == "length":
            raise _Attempt(f"the answer was {cut_at_length(found, tokens)}")
        data = answer_object(found.text)
        answer = data.get("answer") if data else None
        if not isinstance(answer, str) or not answer.strip():
            raise _Attempt(f"no answer in {shown(found.text)}")
        return answer.strip(), found, seconds


def question_text(template: str, free: str | None) -> str:
    """What the model is asked for a template, or the free question."""
    return (free or "").strip() if template == "free" else TEMPLATES[template].question
