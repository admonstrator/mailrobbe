import itertools
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mailspider.generator.config import GeneratorConfig
from mailspider.generator.model import MailKind, PlannedMail, derive_seed, stage_rng
from mailspider.generator.planner import (
    MAX_OPEN_THREADS,
    MAX_REFERENCES,
    Planner,
    plan,
    reply_subject,
    subject_core,
)
from mailspider.generator.population import Population, build_population
from tests.generator.conftest import small_config

_PREFIX = re.compile(r"^(?:(?:Re|RE|AW|Aw|WG|FW|Fwd|Fw|\[[^\]]+\]):\s*)+")


def test_stream_positions_and_seeds(
    gen_config: GeneratorConfig, gen_plan: list[PlannedMail]
) -> None:
    assert len(gen_plan) == gen_config.mails
    assert [mail.index for mail in gen_plan] == list(range(gen_config.mails))
    assert all(mail.seed == derive_seed(gen_config.seed, mail.index) for mail in gen_plan)
    assert len({mail.message_id for mail in gen_plan}) == len(gen_plan)
    assert all(re.fullmatch(r"<[^<>@\s]+@[^<>@\s]+>", mail.message_id) for mail in gen_plan)


def test_roughly_chronological_within_range(
    gen_config: GeneratorConfig, gen_plan: list[PlannedMail]
) -> None:
    start = datetime.combine(gen_config.date_from, datetime.min.time(), UTC)
    end = datetime.combine(gen_config.date_to + timedelta(days=1), datetime.min.time(), UTC)
    for mail in gen_plan:
        assert mail.date.tzinfo is not None
        assert start <= mail.date < end
    inversions = sum(b.date < a.date for a, b in itertools.pairwise(gen_plan))
    assert inversions / len(gen_plan) < 0.02
    years = Counter(mail.date.year for mail in gen_plan)
    assert set(years) == set(range(gen_config.date_from.year, gen_config.date_to.year + 1))


def test_working_rhythm_and_zones(gen_plan: list[PlannedMail]) -> None:
    people = [mail for mail in gen_plan if not mail.automated]
    weekdays = sum(mail.date.weekday() < 5 for mail in people)
    assert weekdays / len(people) > 0.85
    office = sum(7 <= mail.date.hour < 19 for mail in people)
    assert office / len(people) > 0.75
    offsets = Counter(mail.date.utcoffset() for mail in gen_plan)
    central = offsets[timedelta(hours=1)] + offsets[timedelta(hours=2)]
    assert central / len(gen_plan) > 0.6
    assert len(offsets) >= 4


def test_replies_reference_earlier_mails(gen_plan: list[PlannedMail]) -> None:
    by_id: dict[str, PlannedMail] = {}
    replies = 0
    for mail in gen_plan:
        if mail.in_reply_to is not None:
            replies += 1
            parent = by_id[mail.in_reply_to]  # planned before this one
            assert mail.references[-1] == mail.in_reply_to
            assert len(mail.references) <= MAX_REFERENCES
            assert all(ref in by_id for ref in mail.references)
            assert mail.thread_index == parent.thread_index
            assert mail.date > parent.date
            assert subject_core(mail.subject) == subject_core(parent.subject)
            assert mail.kind is MailKind.REPLY
            assert mail.quoted is not None and mail.quoted.message_id == parent.message_id
            assert mail.quoted.quoted is None  # quotes are one level deep
        by_id[mail.message_id] = mail
    assert replies / len(gen_plan) > 0.2


def test_thread_index_is_the_first_mail(gen_plan: list[PlannedMail]) -> None:
    for mail in gen_plan:
        if mail.thread_index is None:
            continue
        root = gen_plan[mail.thread_index]
        assert root.thread_index == root.index
        assert mail.index >= root.index
    threads = Counter(mail.thread_index for mail in gen_plan if mail.thread_index is not None)
    assert all(size >= 2 for size in threads.values())  # no thread of one
    assert max(threads.values()) >= 6


def test_subject_prefixes(gen_plan: list[PlannedMail]) -> None:
    replies = [mail.subject for mail in gen_plan if mail.kind is MailKind.REPLY]
    forwards = [mail.subject for mail in gen_plan if mail.kind is MailKind.FORWARD]
    assert all(re.match(r"(?:Re|RE|AW|Aw): ", subject) for subject in replies)
    assert all(re.match(r"(?:WG|Fwd|FW|Fw): ", subject) for subject in forwards)
    prefixes = Counter(subject.split(":")[0] for subject in replies)
    assert prefixes["AW"] and prefixes["Re"]
    stacked = [s for s in replies if len(_PREFIX.match(s).group(0).split(":")) > 2]  # type: ignore[union-attr]
    assert stacked  # AW: Re: ...
    assert any(s.startswith("AW: Re:") or s.startswith("RE: AW:") for s in stacked)  # mixed


def test_reply_subject_helper() -> None:
    rng = stage_rng(1, "test")
    assert reply_subject("Angebot", "outlook", "de", rng).startswith("AW: ")
    assert reply_subject("Offer", "thunderbird", "en", rng).startswith("Re: ")
    for deep in ("AW: Re: AW: Angebot", "WG: AW: Re: Angebot"):
        for _ in range(50):
            subject = reply_subject(deep, "outlook", "de", rng)
            assert subject.startswith("AW: ")
            assert subject.count(":") <= 4


def test_lists_and_automated_mails(gen_plan: list[PlannedMail], gen_population: Population) -> None:
    lists = {lst.list_id: lst for lst in gen_population.lists}
    posts = [m for m in gen_plan if m.list_id and not m.automated]
    assert posts
    for mail in posts:
        assert lists[mail.list_id].address.email in {a.email for a in mail.to}  # type: ignore[index]
        assert mail.sender.email != lists[mail.list_id].address.email  # type: ignore[index]
    automated = [m for m in gen_plan if m.automated]
    kinds = Counter(m.kind for m in automated)
    assert set(kinds) == {MailKind.NEWSLETTER, MailKind.NOTIFICATION, MailKind.INVOICE}
    assert all(m.list_id for m in automated if m.kind is MailKind.NEWSLETTER)
    services = {d.name for d in gen_population.domains if not d.internal}
    noreply = {p.email for p in gen_population.persons if p.internal and p.service}
    for mail in automated:
        assert mail.sender.domain in services or mail.sender.email in noreply
    assert 0.08 < len(automated) / len(gen_plan) < 0.4


def test_cc_chains_grow_and_bcc_only_from_insiders(
    gen_plan: list[PlannedMail], gen_population: Population
) -> None:
    internal = {d.name for d in gen_population.domains if d.internal}
    grown = 0
    for mail in gen_plan:
        if mail.bcc:
            assert mail.sender.domain in internal
        if mail.quoted is not None and mail.kind is MailKind.REPLY:
            before = {a.email for a in (*mail.quoted.to, *mail.quoted.cc)}
            after = {a.email for a in (*mail.to, *mail.cc)}
            grown += bool(after - before - {mail.quoted.sender.email})
    assert grown > 0
    with_bcc = sum(bool(mail.bcc) for mail in gen_plan)
    assert 0 < with_bcc / len(gen_plan) < 0.05


def test_languages(gen_plan: list[PlannedMail]) -> None:
    languages = Counter(mail.language for mail in gen_plan)
    assert set(languages) == {"de", "en"}
    assert languages["de"] > languages["en"]


def test_attachments(gen_config: GeneratorConfig, gen_plan: list[PlannedMail]) -> None:
    with_files = [mail for mail in gen_plan if mail.attachments]
    share = len(with_files) / len(gen_plan)
    assert abs(share - gen_config.attachment_share) < 0.06
    sizes = sorted(a.size for mail in with_files for a in mail.attachments if not a.inline)
    assert sizes[len(sizes) // 2] < 2 * 1024**2  # most a few KB to a few MB
    assert sizes[-1] >= gen_config.large_attachment_size
    names = {a.filename for mail in with_files for a in mail.attachments}
    assert any(re.fullmatch(r"Rechnung_\d{4}-\d\d\.pdf", name) for name in names)
    assert any(name.endswith(".docx") for name in names)
    assert any(re.fullmatch(r"IMG_\d+\.jpg", name) for name in names)
    for mail in with_files:
        assert len({a.filename for a in mail.attachments}) == len(mail.attachments)


def test_exact_number_of_large_attachments(tmp_path: Path) -> None:
    size = 5 * 1024**2 + 7
    config = small_config(tmp_path, mails=600, large_attachments=4, large_attachment_size=size)
    population = build_population(config, stage_rng(config.seed, "population"))
    mails = list(plan(config, population))
    large = [mail for mail in mails if mail.large_attachment]
    assert len(large) == 4
    for mail in large:
        assert mail.attachments[-1].size == size
    assert sum(a.size == size for mail in mails for a in mail.attachments) == 4
    indexes = [mail.index for mail in large]
    assert indexes[0] < 300 < indexes[-1]  # spread over the stream


def test_state_stays_bounded(tmp_path: Path) -> None:
    config = small_config(tmp_path, mails=12_000, persons=600, domains=40)
    population = build_population(config, stage_rng(config.seed, "population"))
    planner = Planner(config, population)
    peak = 0
    for mail in planner:
        peak = max(peak, planner.open_threads)
        assert mail.quoted is None or mail.quoted.quoted is None
    assert planner.max_open_threads <= MAX_OPEN_THREADS
    assert peak <= MAX_OPEN_THREADS


def test_plan_is_deterministic(gen_config: GeneratorConfig, gen_population: Population) -> None:
    first = [(m.message_id, m.date, m.subject) for m in plan(gen_config, gen_population)]
    again = build_population(gen_config, stage_rng(gen_config.seed, "population"))
    second = [(m.message_id, m.date, m.subject) for m in plan(gen_config, again)]
    assert first == second
