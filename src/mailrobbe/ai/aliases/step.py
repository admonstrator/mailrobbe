"""The run's step aliases (D321 to D323): the candidate pairs one at a time, for ai.run.

    read    the candidates once, when the run checks (ai.aliases.candidates); their number is
            the step's total
    facts   per pair what the model reads (ai.aliases.material); a pair whose persons are no
            human roots any more (merged meanwhile) is passed over
    ask     one request: the prompt of ai.toml [aliases] as the system message, the material
            between the markers as the user's, the answer bound to VERDICT_SCHEMA
    check   the verdict one of same, different and unclear, the reason with its spaces tidied
            and cut at ALIAS_REASON_MAX_CHARS. An answer cut at its length, an HTTP error or an
            answer the schema does not read is an attempt: the pair is asked again, and after
            AI_TASK_ATTEMPTS attempts left for a later run and counted as failed
    store   one row of alias_check per pair, for the roots of now, replacing an older one

A request goes out through the run (_Run._answer: a service that does not answer is waited for,
a missing model or a stop request ends the run). ai.run hands this step a service on this machine
only (D322): the material holds names, addresses, subjects and closing lines.
"""

import logging
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from mailrobbe.ai.aliases.candidates import Candidate, read_candidates
from mailrobbe.ai.aliases.material import material, read_pair
from mailrobbe.ai.model import (
    AI_TASK_ATTEMPTS,
    ALIAS_ANSWER_TOKENS,
    ALIAS_REASON_MAX_CHARS,
    Protocol,
    Service,
)
from mailrobbe.ai.prompts import MATERIAL_END, MATERIAL_START, AliasPrompts, load_prompts
from mailrobbe.ai.services import AnswerError, ChatAnswer, chat_text, cut_at_length
from mailrobbe.ai.summarize.answer import answer_object, shown
from mailrobbe.enums import AliasVerdict
from mailrobbe.jobrun import Step, describe

if TYPE_CHECKING:
    from mailrobbe.ai.run import _Run

log = logging.getLogger(__name__)

VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": [verdict.value for verdict in AliasVerdict]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}
_STORE = text("""
    INSERT INTO alias_check (person_a, person_b, verdict, reason, model, service_url,
        prompt_version, seconds, tokens_in, tokens_out, job_id)
    VALUES (:a, :b, CAST(:verdict AS alias_verdict), :reason, :model, :service_url,
        :prompt_version, :seconds, :tokens_in, :tokens_out, :job_id)
    ON CONFLICT (person_a, person_b) DO UPDATE SET verdict = excluded.verdict,
        reason = excluded.reason, model = excluded.model, service_url = excluded.service_url,
        prompt_version = excluded.prompt_version, seconds = excluded.seconds,
        tokens_in = excluded.tokens_in, tokens_out = excluded.tokens_out,
        job_id = excluded.job_id, created_at = now()
""")


class _Attempt(Exception):
    """The pair's request failed this time (English reason)."""


def read_verdict(answer: str) -> tuple[AliasVerdict, str]:
    """The verdict and the reason of an answer (module docstring); raises AnswerError."""
    found = answer_object(answer)
    if found is None:
        raise AnswerError(f"no JSON object in the answer: {shown(answer)}")
    verdict, reason = found.get("verdict"), found.get("reason")
    if verdict not in {value.value for value in AliasVerdict}:
        raise AnswerError(f"the answer has no verdict of same, different, unclear: {shown(answer)}")
    if not isinstance(reason, str):
        raise AnswerError(f"the answer has no text under reason: {shown(answer)}")
    tidied = " ".join(reason.split())
    if len(tidied) > ALIAS_REASON_MAX_CHARS:
        tidied = tidied[: ALIAS_REASON_MAX_CHARS - 1].rstrip() + "…"
    return AliasVerdict(verdict), tidied


class AliasStep:
    """The step aliases of a run with --aliases: its candidates, the text service it uses, and
    the work on each pair (module docstring). ai.run checks the service and runs the step."""

    def __init__(self, run: "_Run") -> None:
        self.run = run
        self.candidates: list[Candidate] = []
        self.service: Service | None = None
        self.protocol: Protocol | None = None
        self._prompts: AliasPrompts | None = None

    async def read(self) -> int:
        """The pairs to ask about now."""
        async with self.run.sessionmaker() as session:
            self.candidates = await read_candidates(session)
        self.run.summary.aliases_queued = len(self.candidates)
        return len(self.candidates)

    def use(self, service: Service, protocol: Protocol) -> None:
        self.service, self.protocol = service, protocol
        self.run.summary.text = service.display_url
        log.info("text: %s, model %s (local)", service.display_url, service.model)

    async def work(self, counter: Step) -> None:
        """Every candidate in order, until the run is asked to stop."""
        self._prompts = load_prompts().aliases
        for candidate in self.candidates:
            if self.run.job.stop.is_set():
                return
            await self._check(candidate)
            counter.advance()

    async def _check(self, candidate: Candidate) -> None:
        run = self.run
        async with run.sessionmaker() as session:
            facts = await read_pair(session, candidate.a, candidate.b)
        if facts is None:
            log.info("persons %d and %d: no longer two persons", candidate.a, candidate.b)
            return
        user = f"{MATERIAL_START}\n{material(facts)}\n{MATERIAL_END}"
        reason = ""
        for _ in range(AI_TASK_ATTEMPTS):
            try:
                verdict, said, found, seconds = await self._ask(user)
                break
            except _Attempt as attempt:
                reason = str(attempt)
                log.warning("persons %d and %d: %s", candidate.a, candidate.b, reason)
        else:
            run.summary.aliases_failed += 1
            return
        assert self.service is not None and self._prompts is not None
        async with run.sessionmaker.begin() as session:
            await session.execute(
                _STORE,
                {
                    "a": candidate.a,
                    "b": candidate.b,
                    "verdict": verdict.value,
                    "reason": said,
                    "model": self.service.model,
                    "service_url": self.service.display_url,
                    "prompt_version": self._prompts.version,
                    "seconds": seconds,
                    "tokens_in": found.tokens_in,
                    "tokens_out": found.tokens_out,
                    "job_id": run.job.job_id,
                },
            )
        run.summary.aliases += 1
        run.progress.aliases += 1
        if verdict is AliasVerdict.SAME:
            run.summary.aliases_same += 1
            run.progress.aliases_same += 1
        log.info("%s / %s: %s", facts.a.email, facts.b.email, verdict.value)

    async def _ask(self, user: str) -> tuple[AliasVerdict, str, ChatAnswer, float]:
        """One request with this material; _Attempt for an answer that is no valid one."""
        service, protocol, run, prompts = self.service, self.protocol, self.run, self._prompts
        assert service is not None and protocol is not None and prompts is not None

        def request() -> tuple[ChatAnswer, float]:
            started = time.monotonic()
            found = chat_text(
                service,
                protocol,
                system=prompts.system,
                user=user,
                schema=VERDICT_SCHEMA,
                max_tokens=ALIAS_ANSWER_TOKENS,
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
            raise _Attempt(f"the answer was {cut_at_length(found, ALIAS_ANSWER_TOKENS)}")
        try:
            verdict, reason = read_verdict(found.text)
        except AnswerError as error:
            raise _Attempt(str(error)) from None
        return verdict, reason, found, seconds
