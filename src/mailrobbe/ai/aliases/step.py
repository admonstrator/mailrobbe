"""The run's step aliases (D321 to D325): the candidate groups, for ai.run (several at once, D327).

    read    the groups once, when the run checks (ai.aliases.candidates); their number is the
            step's total
    facts   per group what the model reads (ai.aliases.material), within the characters the
            context leaves; persons that are no human roots any more (merged meanwhile) are
            passed over, and a group with fewer than two left is skipped
    ask     one request: the prompt of ai.toml [aliases] as the system message, the material
            between the markers as the user's, the answer bound to answer_schema
    check   read_answer: the persons the model sees, each with its letters, sure and a reason
            (spaces tidied, cut at ALIAS_REASON_MAX_CHARS). A letter in two entries or one not in
            the group makes the answer invalid; a letter missing is a person of its own, not
            sure. An answer cut at its length, an HTTP error or an answer that is no valid one
            is an attempt: the group is asked again, and after AI_TASK_ATTEMPTS attempts left
            for a later run and counted as failed
    store   one row of alias_check for every pair of the group (verdicts), replacing older ones

Pairs from the answer (verdicts): two letters of one entry are the same person, certain when
the entry is sure; two letters of different entries are different persons when both entries are
sure, else unclear.

A request goes out through the run (_Run._answer: a service that does not answer is waited for,
a missing model or a stop request ends the run). ai.run hands this step a service on this machine
only (D322): the material holds names, addresses, subjects and closing lines.
"""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING, Any

from sqlalchemy import text

from mailrobbe.ai.aliases.candidates import Group, read_groups
from mailrobbe.ai.aliases.material import LETTERS, material, read_group
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

CHARS_PER_TOKEN = 3  # what a token of German material holds at least, for the material's limit

_STORE = text("""
    INSERT INTO alias_check (person_a, person_b, verdict, certain, reason, model, service_url,
        prompt_version, seconds, tokens_in, tokens_out, job_id)
    SELECT a, b, CAST(verdict AS alias_verdict), certain, reason, :model, :service_url,
        :prompt_version, :seconds, :tokens_in, :tokens_out, :job_id
    FROM unnest(CAST(:a AS bigint[]), CAST(:b AS bigint[]), CAST(:verdict AS text[]),
        CAST(:certain AS boolean[]), CAST(:reason AS text[])) AS v (a, b, verdict, certain, reason)
    ON CONFLICT (person_a, person_b) DO UPDATE SET verdict = excluded.verdict,
        certain = excluded.certain, reason = excluded.reason, model = excluded.model,
        service_url = excluded.service_url, prompt_version = excluded.prompt_version,
        seconds = excluded.seconds, tokens_in = excluded.tokens_in,
        tokens_out = excluded.tokens_out, job_id = excluded.job_id, created_at = now()
""")


@dataclass(frozen=True, slots=True)
class Seen:
    """One person the model sees in a group: the places of its letters, ascending."""

    members: tuple[int, ...]
    sure: bool
    reason: str


@dataclass(frozen=True, slots=True)
class Verdict:
    a: int  # places in the group, a < b
    b: int
    verdict: AliasVerdict
    certain: bool
    reason: str


class _Attempt(Exception):
    """The group's request failed this time (English reason)."""


def answer_schema(size: int) -> dict[str, Any]:
    """The JSON schema of an answer about a group of this many persons."""
    return {
        "type": "object",
        "properties": {
            "persons": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "members": {
                            "type": "array",
                            "items": {"type": "string", "enum": list(LETTERS[:size])},
                        },
                        "sure": {"type": "boolean"},
                        "reason": {"type": "string"},
                    },
                    "required": ["members", "sure", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["persons"],
        "additionalProperties": False,
    }


def read_answer(answer: str, size: int) -> list[Seen]:
    """The persons of an answer about a group of this many (module docstring); raises
    AnswerError."""
    found = answer_object(answer)
    if found is None:
        raise AnswerError(f"no JSON object in the answer: {shown(answer)}")
    entries = found.get("persons")
    if not isinstance(entries, list):
        raise AnswerError(f"the answer has no list under persons: {shown(answer)}")
    seen: list[Seen] = []
    placed: set[int] = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("members"), list):
            raise AnswerError(f"an entry has no list under members: {shown(answer)}")
        members, sure, reason = entry["members"], entry.get("sure"), entry.get("reason")
        if not isinstance(sure, bool):
            raise AnswerError(f"an entry has no true or false under sure: {shown(answer)}")
        places: set[int] = set()
        for letter in members:
            place = LETTERS.find(letter) if isinstance(letter, str) and len(letter) == 1 else -1
            if not 0 <= place < size or place in placed | places:
                raise AnswerError(f"the letter {letter!r} is unknown or twice: {shown(answer)}")
            places.add(place)
        if not places:
            continue
        placed |= places
        seen.append(Seen(tuple(sorted(places)), sure, _tidy(reason)))
    seen += [Seen((place,), False, "") for place in range(size) if place not in placed]
    return sorted(seen, key=lambda person: person.members)


def verdicts(seen: Sequence[Seen]) -> list[Verdict]:
    """Every pair of the group with its verdict (module docstring)."""
    person = {place: entry for entry in seen for place in entry.members}
    found = []
    for a, b in combinations(sorted(person), 2):
        first, second = person[a], person[b]
        if first is second:
            found.append(Verdict(a, b, AliasVerdict.SAME, first.sure, first.reason))
            continue
        verdict = AliasVerdict.DIFFERENT if first.sure and second.sure else AliasVerdict.UNCLEAR
        reasons = [
            f"{LETTERS[a] if entry is first else LETTERS[b]}: {entry.reason}"
            for entry in (first, second)
            if entry.reason
        ]
        found.append(Verdict(a, b, verdict, False, _tidy(" ".join(reasons))))
    return found


def _tidy(reason: Any) -> str:
    tidied = " ".join(reason.split()) if isinstance(reason, str) else ""
    if len(tidied) > ALIAS_REASON_MAX_CHARS:
        tidied = tidied[: ALIAS_REASON_MAX_CHARS - 1].rstrip() + "…"
    return tidied


class AliasStep:
    """The step aliases of a run with --aliases: its groups, the text service it uses, and
    the work on each group (module docstring). ai.run checks the service and runs the step."""

    def __init__(self, run: "_Run") -> None:
        self.run = run
        self.groups: list[Group] = []
        self.service: Service | None = None
        self.protocol: Protocol | None = None
        self._prompts: AliasPrompts = load_prompts().aliases

    async def read(self) -> int:
        """The groups to ask about now."""
        async with self.run.sessionmaker() as session:
            self.groups = await read_groups(session, self._prompts.version)
        self.run.summary.aliases_queued = len(self.groups)
        return len(self.groups)

    def use(self, service: Service, protocol: Protocol) -> None:
        self.service, self.protocol = service, protocol
        self.run.summary.text = service.display_url
        log.info("text: %s, model %s (local)", service.display_url, service.model)

    async def work(self, counter: Step) -> None:
        """Every group in order, options.concurrency at once (D327), until the run is asked to
        stop."""
        waiting = iter(self.groups)

        async def worker() -> None:
            for group in waiting:
                if self.run.job.stop.is_set():
                    return
                await self._check(group)
                counter.advance()

        await self.run._together(worker)

    def _limit(self) -> int:
        """The characters the material may take: the context without prompt and answer."""
        context = self.run.options.context_tokens
        prompt = len(self._prompts.system) // CHARS_PER_TOKEN
        return max(0, (context - prompt - ALIAS_ANSWER_TOKENS) * CHARS_PER_TOKEN)

    async def _check(self, group: Group) -> None:
        run = self.run
        async with run.sessionmaker() as session:
            facts = await read_group(session, group.members)
        if facts is None:
            log.info("persons %s: fewer than two persons left", group.members)
            return
        user = f"{MATERIAL_START}\n{material(facts, self._limit())}\n{MATERIAL_END}"
        for _ in range(AI_TASK_ATTEMPTS):
            try:
                seen, found, seconds = await self._ask(user, len(facts.roots))
                break
            except _Attempt as attempt:
                log.warning("persons %s: %s", facts.roots, attempt)
        else:
            run.summary.aliases_failed += 1
            return
        assert self.service is not None
        pairs = verdicts(seen)
        roots = facts.roots
        async with run.sessionmaker.begin() as session:
            await session.execute(
                _STORE,
                {
                    "a": [roots[pair.a] for pair in pairs],
                    "b": [roots[pair.b] for pair in pairs],
                    "verdict": [pair.verdict.value for pair in pairs],
                    "certain": [pair.certain for pair in pairs],
                    "reason": [pair.reason for pair in pairs],
                    "model": self.service.model,
                    "service_url": self.service.display_url,
                    "prompt_version": self._prompts.version,
                    "seconds": seconds,
                    "tokens_in": found.tokens_in,
                    "tokens_out": found.tokens_out,
                    "job_id": run.job.job_id,
                },
            )
        same = sum(pair.verdict is AliasVerdict.SAME for pair in pairs)
        sure = sum(pair.verdict is AliasVerdict.SAME and pair.certain for pair in pairs)
        for figures in (run.summary, run.progress):
            figures.aliases += 1
            figures.aliases_same += same
            figures.aliases_sure += sure
        log.info("persons %s: %s", roots, [[roots[i] for i in s.members] for s in seen])

    async def _ask(self, user: str, size: int) -> tuple[list[Seen], ChatAnswer, float]:
        """One request with this material; _Attempt for an answer that is no valid one."""
        service, protocol, run, prompts = self.service, self.protocol, self.run, self._prompts
        assert service is not None and protocol is not None

        def request() -> tuple[ChatAnswer, float]:
            started = time.monotonic()
            found = chat_text(
                service,
                protocol,
                system=prompts.system,
                user=user,
                schema=answer_schema(size),
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
            seen = read_answer(found.text, size)
        except AnswerError as error:
            raise _Attempt(str(error)) from None
        return seen, found, seconds
