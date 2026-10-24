"""Questions about persons, "KI fragen" on a person's page (D347, D348): GET and POST
/api/persons/{id}/questions, DELETE /api/person-questions/{id}. Models are in schemas.py.

Asking queues what the answer waits for first (ai.questions.queue_prework: summaries, OCR and
transcription of attachments, first in the queue, D329), keeps the question with its estimate
(prework_estimate) and starts an AI run for it, or a live run takes it next. The card asks again
every 3 s while a question is open: the questions of the person by ix_person_question_person_id
and ix_person_question_other_id, each counting its prework still open (ai.questions.open_prework).
A question is about root persons; an alias's id stands for its root (D28).
"""

import json
from typing import Annotated, Any

import fastapi
from fastapi import APIRouter
from fastapi.responses import Response
from sqlalchemy import text

from mailrobbe import jobs
from mailrobbe.ai.model import AiOptions
from mailrobbe.ai.questions import TEMPLATES, open_prework, question_text, queue_prework
from mailrobbe.api.ai import _start_for, _text_estimate, alias_check_usable, prework_estimate
from mailrobbe.api.deps import AppSettings, Editor, Session, api_error
from mailrobbe.api.imports import JSON_BODY, Runs, ai_job
from mailrobbe.api.schemas import (
    AiPrework,
    PersonQuestionAsked,
    PersonQuestionItem,
    PersonQuestionPerson,
    PersonQuestionRequest,
    PersonQuestions,
    PersonQuestionTemplate,
)
from mailrobbe.enums import AiTaskStatus, JobKind
from mailrobbe.persons.roots import resolve_root

router = APIRouter(prefix="/api", tags=["persons"])

RowId = Annotated[int, fastapi.Path(ge=-(2**63), le=2**63 - 1)]
SHOWN = 20  # questions of a person on its card, newest first

_QUESTIONS = text(f"""
    SELECT q.*, a.display_name AS a_name, a.canonical_email AS a_email,
        b.display_name AS b_name, b.canonical_email AS b_email,
        CASE WHEN q.status = 'waiting' THEN ({open_prework("q.prework")}) ELSE 0 END AS open
    FROM person_question q
    JOIN person a ON a.id = q.person_id
    LEFT JOIN person b ON b.id = q.other_id
    WHERE q.person_id = :person OR q.other_id = :person
    ORDER BY q.id DESC LIMIT {SHOWN}
""")
_ONE = text(f"""
    SELECT q.*, a.display_name AS a_name, a.canonical_email AS a_email,
        b.display_name AS b_name, b.canonical_email AS b_email,
        CASE WHEN q.status = 'waiting' THEN ({open_prework("q.prework")}) ELSE 0 END AS open
    FROM person_question q
    JOIN person a ON a.id = q.person_id
    LEFT JOIN person b ON b.id = q.other_id
    WHERE q.id = :id
""")
_INSERT = text("""
    INSERT INTO person_question (person_id, other_id, template, question, prework, queued_by)
    VALUES (:person, :other, :template, :question, CAST(:prework AS jsonb), :editor)
    RETURNING id
""")
_DELETE = text("DELETE FROM person_question WHERE id = :id AND status <> 'running' RETURNING id")


def _templates() -> list[PersonQuestionTemplate]:
    return [
        PersonQuestionTemplate(
            key=key, label=item.label, question=item.question, compare=item.compare
        )
        for key, item in TEMPLATES.items()
    ]


def _item(row: Any) -> PersonQuestionItem:
    prework = row.prework if isinstance(row.prework, dict) else {}
    template = TEMPLATES.get(row.template)
    return PersonQuestionItem(
        id=row.id,
        template=row.template,
        label=template.label if template else row.template,
        question=row.question,
        person=PersonQuestionPerson(id=row.person_id, name=row.a_name, email=row.a_email),
        other=None
        if row.other_id is None
        else PersonQuestionPerson(id=row.other_id, name=row.b_name, email=row.b_email),
        status=AiTaskStatus(row.status),
        answer=row.answer,
        contents=row.contents,
        model=row.model,
        error=row.error,
        queued_at=row.queued_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        prework=AiPrework.model_validate(prework) if "seconds" in prework else None,
        open=int(row.open),
    )


async def _root(session: Session, person_id: int) -> int:
    root = await resolve_root(session, person_id)
    if root is None:
        raise api_error(404, "not_found", f"no person with id {person_id}")
    return root


@router.get("/persons/{person_id}/questions")
async def person_questions(
    person_id: RowId, session: Session, settings: AppSettings
) -> PersonQuestions:
    person = await _root(session, person_id)
    items = [_item(row) for row in await session.execute(_QUESTIONS, {"person": person})]
    run = None
    if any(item.status in (AiTaskStatus.WAITING, AiTaskStatus.RUNNING) for item in items):
        latest = await jobs.latest_job(session, JobKind.AI)
        run = None if latest is None else await ai_job(session, settings, latest)
        run = run if run is not None and run.alive else None
    return PersonQuestions(
        available=await alias_check_usable(settings),
        templates=_templates(),
        questions=items,
        run=run,
    )


@router.post("/persons/{person_id}/questions", dependencies=JSON_BODY)
async def ask(
    person_id: RowId,
    request: PersonQuestionRequest,
    session: Session,
    settings: AppSettings,
    editor: Editor,
    runs: Runs,
) -> PersonQuestionAsked:
    template = TEMPLATES.get(request.template)
    if template is None:
        raise api_error(400, "invalid_option", f"no question template {request.template!r}")
    question = question_text(request.template, request.text)
    if not question:
        raise api_error(400, "invalid_option", "the free question is empty")
    if not await alias_check_usable(settings):
        raise api_error(400, "invalid_option", "no text service on this machine is configured")
    person = await _root(session, person_id)
    other = None
    if template.compare:
        if request.other_id is None:
            raise api_error(400, "invalid_selection", "a comparison needs other_id")
        other = await _root(session, request.other_id)
        if other == person:
            raise api_error(400, "invalid_selection", "compare two different persons")
    prework = await queue_prework(session, person, other, editor=editor)
    defaults = AiOptions.from_settings(settings)
    queued = prework.summaries
    estimate = await _text_estimate(
        session, defaults.text_model, queued.queued + queued.raised, queued.characters
    )
    figures = await prework_estimate(session, defaults, prework.pending, estimate)
    question_id = await session.scalar(
        _INSERT,
        {
            "person": person,
            "other": other,
            "template": request.template,
            "question": question,
            "prework": json.dumps({**figures.model_dump(), **prework.keys()}),
            "editor": editor,
        },
    )
    await session.commit()
    run = await _start_for(session, settings, runs, [], questions=[int(question_id or 0)])
    row = (await session.execute(_ONE, {"id": question_id})).one()
    return PersonQuestionAsked(question=_item(row), run=run)


@router.delete("/person-questions/{question_id}", status_code=204)
async def discard(question_id: RowId, session: Session) -> Response:
    if (await session.execute(_DELETE, {"id": question_id})).first() is None:
        raise api_error(404, "not_found", f"no question {question_id} that is not running")
    await session.commit()
    return Response(status_code=204)
