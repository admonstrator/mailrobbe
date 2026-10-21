"""Streaming mail plan (SPEC 3.6): who writes to whom, when, about what and in which thread.

The planner yields PlannedMail objects in stream order with roughly chronological dates and keeps
only bounded state: the open threads (each with its next reply scheduled a few positions ahead)
and a short window of recent mails that may be forwarded. Nothing grows with the mail count.
"""

import bisect
import heapq
import math
import random
import re
from collections import deque
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta, timezone

from mailrobbe.generator import invitations
from mailrobbe.generator import vocabulary as vocab
from mailrobbe.generator.config import GeneratorConfig
from mailrobbe.generator.documents import DocumentPool
from mailrobbe.generator.model import (
    Address,
    AttachmentSpec,
    Invitation,
    MailKind,
    Meeting,
    PlannedMail,
    derive_seed,
    stage_rng,
)
from mailrobbe.generator.population import (
    ERAS,
    MailingList,
    Person,
    PersonKind,
    Population,
    utc_offset,
)

MAX_OPEN_THREADS = 400  # hard bound on the threads waiting for replies
RECENT_MAILS = 64  # forwards pick one of the last mails
MAX_REFERENCES = 20  # References keeps the root and the latest ancestors, like most clients
MAX_ATTACHMENT_SIZE = 20 * 1024**2  # normal attachments stay below common server limits

_PREFIXES = re.compile(r"^(?:(?:re|aw|antw|wg|fw|fwd|sv)(?:\[\d+\])?:\s*|\[[^\]]*\]\s*)+", re.I)
_REPLY_PREFIX = re.compile(r"^(?:re|aw|antw)(?:\[\d+\])?:\s*", re.I)


def subject_core(subject: str) -> str:
    """Subject without reply/forward prefixes and list tags: 'AW: [x] Re: Angebot' -> 'Angebot'."""
    return _PREFIXES.sub("", subject)


def reply_subject(subject: str, client: str, language: str, rng: random.Random) -> str:
    """Subject of a reply as the given program writes it; prefixes mix and stack like real ones."""
    own = ("AW" if language == "de" else "RE") if client == "outlook" else "Re"
    if subject.startswith(f"{own}: "):
        return f"{own}: {subject}" if rng.random() < 0.06 else subject
    prefixes = _PREFIXES.match(subject)
    if prefixes and prefixes.group().count(":") >= 3 and _REPLY_PREFIX.match(subject):
        return subject  # long chains stop growing once several prefixes have piled up
    if _REPLY_PREFIX.match(subject):
        if client == "outlook" or rng.random() < 0.5:
            return f"{own}: {subject}"  # "AW: Re: ..."
        return f"{own}: {_REPLY_PREFIX.sub('', subject, count=1)}"
    return f"{own}: {subject}"


def forward_subject(subject: str, client: str, language: str) -> str:
    own = ("WG" if language == "de" else "FW") if client == "outlook" else "Fwd"
    return f"{own}: {subject}"


def plan(config: GeneratorConfig, population: Population) -> Iterator[PlannedMail]:
    return iter(Planner(config, population))


class _Pool:
    """Persons with cumulative activity weights for fast weighted picks."""

    __slots__ = ("cum", "items")

    def __init__(self, items: Sequence[Person]) -> None:
        self.items = tuple(items)
        total = 0.0
        cum = []
        for person in self.items:
            total += person.weight
            cum.append(total)
        self.cum = tuple(cum)

    def __bool__(self) -> bool:
        return bool(self.items)

    def pick(self, rng: random.Random) -> Person:
        return self.items[bisect.bisect_right(self.cum, rng.random() * self.cum[-1])]


# Mails per local hour (Europe/Berlin) on working days and on weekends, relative.
_WORKDAY_HOURS = (
    0.02, 0.01, 0.01, 0.01, 0.02, 0.05, 0.15, 0.45, 0.95, 1.0, 1.0, 0.95,
    0.6, 0.8, 0.95, 0.9, 0.8, 0.6, 0.35, 0.22, 0.18, 0.15, 0.1, 0.05,
)  # fmt: skip
_WEEKEND_HOURS = (
    0.03, 0.02, 0.01, 0.01, 0.01, 0.02, 0.04, 0.08, 0.15, 0.25, 0.32, 0.35,
    0.33, 0.3, 0.3, 0.3, 0.32, 0.33, 0.33, 0.32, 0.3, 0.25, 0.15, 0.07,
)  # fmt: skip
_DAY_FACTORS = (1.0, 1.05, 1.05, 1.0, 0.85, 0.12, 0.08)  # Monday .. Sunday


def _normalised_cumulative(values: Sequence[float]) -> tuple[float, ...]:
    total = sum(values)
    running = 0.0
    out = []
    for value in values:
        running += value / total
        out.append(running)
    return tuple(out)


class _Clock:
    """Maps stream positions to UTC instants, increasing, with a working-week rhythm.

    Each day of the range gets a weight (weekday, slow growth over the years, quiet holidays,
    noise); mail `i` lands where the cumulative weight reaches (i + jitter) / mails of the total.
    """

    def __init__(self, config: GeneratorConfig, rng: random.Random) -> None:
        self._rng = rng
        self._first = config.date_from
        days = (config.date_to - config.date_from).days + 1
        self._weights = []
        for offset in range(days):
            day = config.date_from + timedelta(days=offset)
            weight = _DAY_FACTORS[day.weekday()] * (0.55 + 0.9 * offset / days)
            if (day.month == 12 and day.day >= 24) or (day.month == 1 and day.day == 1):
                weight *= 0.25
            self._weights.append(weight * (0.7 + 0.6 * rng.random()))
        self._step = sum(self._weights) / config.mails
        self._day = 0
        self._before = 0.0  # cumulative weight of the days before self._day
        self.start = datetime.combine(config.date_from, time(), tzinfo=UTC)
        self.end = datetime.combine(config.date_to + timedelta(days=1), time(), tzinfo=UTC)
        self._workday = _normalised_cumulative(_WORKDAY_HOURS)
        self._weekend = _normalised_cumulative(_WEEKEND_HOURS)

    def at(self, index: int) -> datetime:
        target = (index + self._rng.random()) * self._step
        last = len(self._weights) - 1
        while self._day < last and self._before + self._weights[self._day] < target:
            self._before += self._weights[self._day]
            self._day += 1
        fraction = min(max((target - self._before) / self._weights[self._day], 0.0), 0.999999)
        day = self._first + timedelta(days=self._day)
        hours = self._weekend if day.weekday() >= 5 else self._workday
        hour = bisect.bisect_right(hours, fraction)
        low = hours[hour - 1] if hour else 0.0
        within = (fraction - low) / (hours[hour] - low)
        local = datetime.combine(day, time(), tzinfo=UTC) + timedelta(hours=hour + within)
        instant = local - utc_offset("Europe/Berlin", local - timedelta(hours=1))
        instant = min(max(instant, self.start), self.end - timedelta(seconds=1))
        return instant.replace(microsecond=0)


@dataclass(slots=True)
class _Thread:
    root: int  # stream index of the first mail
    last: PlannedMail  # latest mail of the thread, stripped
    references: tuple[str, ...]  # References header of `last`
    remaining: int  # replies still to come
    entry: int = -1  # sequence number of the live heap entry
    meeting: Meeting | None = None  # the meeting the thread's first mail invited to, as of now
    cancelled: bool = False  # the organiser cancelled it: the thread goes on in plain mails


_REPLY_COUNTS = ((1, 0.45), (2, 0.25), (3, 0.12), (4, 0.05), (5, 0.04), (6, 0.03), (8, 0.03),
                 (11, 0.02), (15, 0.01))  # fmt: skip
_TO_COUNTS = ((1, 0.72), (2, 0.14), (3, 0.06), (4, 0.03), (5, 0.02), (6, 0.015), (8, 0.015))
_CC_COUNTS = ((0, 0.68), (1, 0.17), (2, 0.08), (3, 0.03), (4, 0.02), (6, 0.02))
_ATTACHMENT_COUNTS = ((1, 0.75), (2, 0.15), (3, 0.06), (4, 0.03), (5, 0.01))
_AUTOMATED_SHARE = 0.28
_AUTOMATED_KINDS = (
    (MailKind.NEWSLETTER, 0.45),
    (MailKind.NOTIFICATION, 0.37),
    (MailKind.INVOICE, 0.18),
)
_LIST_SHARE = 0.06
_FORWARD_SHARE = 0.03
_PERSONAL_THREAD_SHARE = 0.32
_FORWARD_THREAD_SHARE = 0.3
_LIST_THREAD_SHARE = 0.5
_BCC_SHARE = 0.04
_PRIVATE_SEND_SHARE = 0.07
_BACKDATE_SHARE = 0.01
_ATTACHMENT_TEMPLATES = tuple(
    ((name, mime, median, spread), weight)
    for name, mime, median, spread, weight in vocab.ATTACHMENT_TYPES
)
_AUTOMATED_ATTACHMENTS = (
    ("Katalog_{year}.pdf", "application/pdf", 2_500_000, 0.7),
    ("Lieferschein_{n}.pdf", "application/pdf", 45_000, 0.5),
    ("Export_{n}.csv", "text/csv", 12_000, 1.0),
    ("Termin.ics", "text/calendar", 1_500, 0.3),
)


def _weighted[T](rng: random.Random, options: Sequence[tuple[T, float]]) -> T:
    point = rng.random() * sum(weight for _, weight in options)
    for value, weight in options:
        point -= weight
        if point < 0:
            return value
    return options[-1][0]


def _strip(mail: PlannedMail) -> PlannedMail:
    """Copy kept in bounded state and attached as `quoted`: without its own quote (one level)."""
    return replace(mail, quoted=None)


def _unique(addresses: Iterable[Address], exclude: str = "") -> tuple[Address, ...]:
    """Addresses in order without repeats (by email) and without `exclude`."""
    seen = {exclude}
    out = []
    for address in addresses:
        if address.email not in seen:
            seen.add(address.email)
            out.append(address)
    return tuple(out)


class Planner:
    def __init__(self, config: GeneratorConfig, population: Population) -> None:
        self.config = config
        self.population = population
        self._rng = stage_rng(config.seed, "plan")
        self._clock = _Clock(config, stage_rng(config.seed, "plan-clock"))
        self._large_rng = stage_rng(config.seed, "plan-large")
        self._calendar_rng = stage_rng(config.seed, "plan-calendar")
        persons = population.persons
        people = [p for p in persons if p.kind is not PersonKind.SERVICE]
        self._staff = _Pool([p for p in people if p.internal])
        self._outsiders = _Pool([p for p in people if not p.internal])
        self._everyone = _Pool(people)
        self._humans_inside = _Pool([p for p in self._staff.items if p.kind is PersonKind.HUMAN])
        automated = [p for p in persons if p.kind is PersonKind.SERVICE]
        self._services = _Pool(automated)
        self._services_by_kind = {
            kind: _Pool([p for p in automated if p.service is kind]) for kind, _ in _AUTOMATED_KINDS
        }
        size = len(population.departments)
        self._community = [_Pool([p for p in people if p.community == c]) for c in range(size)]
        self._community_staff = [
            _Pool([p for p in self._staff.items if p.community == c]) for c in range(size)
        ]
        # email -> (person index, mailbox index); list addresses are not persons
        self._owners: dict[str, tuple[int, int]] = {}
        for person in persons:
            for number, variants in enumerate(person.mailboxes):
                self._owners[variants[0].email] = (person.index, number)
        self._list_by_id = {lst.list_id: lst for lst in population.lists}
        self._threads: dict[int, _Thread] = {}
        self._schedule: list[tuple[int, int, int]] = []  # (due index, sequence, thread root)
        self._unanswered: dict[int, None] = {}  # roots without a reply yet, oldest first
        self._sequence = 0
        self._recent: deque[PlannedMail] = deque(maxlen=RECENT_MAILS)
        self._tz: dict[timedelta, timezone] = {}
        self._large_now = False  # the mail being built gets the very large attachment
        self._documents = DocumentPool(config.seed)
        self.max_open_threads = 0  # largest number of open threads seen, for tests

    @property
    def open_threads(self) -> int:
        return len(self._threads)

    def __iter__(self) -> Iterator[PlannedMail]:
        large = self._large_targets()
        next_large = next(large, -1)
        for index in range(self.config.mails):
            self._large_now = index == next_large
            if self._large_now:
                next_large = next(large, -1)
            mail = self._next(index, self._clock.at(index))
            if not mail.automated:
                self._recent.append(_strip(mail))
            self.max_open_threads = max(self.max_open_threads, len(self._threads))
            yield mail

    # Choosing what comes next -----------------------------------------------------------

    def _large_targets(self) -> Iterator[int]:
        """One position per equal segment of the stream, so large mails are spread out."""
        count, mails = self.config.large_attachments, self.config.mails
        for k in range(count):
            low, high = k * mails // count, (k + 1) * mails // count
            yield low + self._large_rng.randrange(high - low)

    def _next(self, index: int, when: datetime) -> PlannedMail:
        rng = self._rng
        remaining = self.config.mails - index
        thread = self._forced_thread(remaining) or self._due_thread(index)
        if thread is not None:
            return self._reply(index, when, thread)
        if rng.random() < _AUTOMATED_SHARE and self._services and not self._large_now:
            return self._automated(index, self._backdate(when))
        draw = rng.random()
        if draw < _LIST_SHARE and self.population.lists:
            return self._list_post(index, self._backdate(when), remaining)
        if draw < _LIST_SHARE + _FORWARD_SHARE and self._recent:
            mail = self._forward(index, when, remaining)
            if mail is not None:
                return mail
        return self._personal(index, self._backdate(when), remaining)

    def _backdate(self, when: datetime) -> datetime:
        """A few mails arrive out of order, as in real exports; never before the range."""
        if self._rng.random() >= _BACKDATE_SHARE:
            return when
        earlier = when - timedelta(seconds=int(self._rng.uniform(600, 72 * 3600)))
        return max(earlier, self._clock.start)

    def _forced_thread(self, remaining: int) -> _Thread | None:
        """Near the end, answer every thread that has none yet, so no root stays alone."""
        if self._unanswered and remaining <= len(self._unanswered):
            return self._threads[next(iter(self._unanswered))]
        return None

    def _due_thread(self, index: int) -> _Thread | None:
        while self._schedule and self._schedule[0][0] <= index:
            _, sequence, root = heapq.heappop(self._schedule)
            thread = self._threads.get(root)
            if thread is not None and thread.entry == sequence:
                return thread
        return None

    def _open_thread(self, mail: PlannedMail, remaining: int, share: float) -> None:
        """Decide whether `mail` (not yet yielded) starts a thread and schedule its first reply."""
        rng = self._rng
        if (
            rng.random() >= share
            or len(self._threads) >= MAX_OPEN_THREADS
            or remaining - 1 <= len(self._unanswered)
        ):
            return
        mail.thread_index = mail.index
        replies = _weighted(rng, _REPLY_COUNTS)
        thread = _Thread(mail.index, _strip(mail), mail.references, replies)
        self._threads[mail.index] = thread
        self._unanswered[mail.index] = None
        self._schedule_reply(thread, mail.index)

    def _schedule_reply(self, thread: _Thread, index: int) -> None:
        gap = 1 + min(59, int(self._rng.expovariate(1 / 5)))
        self._sequence += 1
        thread.entry = self._sequence
        heapq.heappush(self._schedule, (index + gap, self._sequence, thread.root))

    # Building mails ---------------------------------------------------------------------

    def _client(self, person: Person, when: datetime) -> str:
        position = (when - self._clock.start) / (self._clock.end - self._clock.start)
        return person.clients[min(ERAS - 1, max(0, int(position * ERAS)))]

    def _local_date(self, person: Person, when: datetime) -> datetime:
        offset = utc_offset(person.zone, when)
        zone = self._tz.get(offset)
        if zone is None:
            zone = self._tz[offset] = timezone(offset)
        return when.astimezone(zone)

    def _sender(self, person: Person, when: datetime) -> tuple[Address, str]:
        """From address and mail program; insiders sometimes write from their private mailbox."""
        rng = self._rng
        if person.private is not None and rng.random() < _PRIVATE_SEND_SHARE:
            client = rng.choice(("webmail", "mobile", "apple"))
            return person.address(person.private, rng, sender=True), client
        return person.address(person.mailbox(when), rng, sender=True), self._client(person, when)

    def _recipient(self, person: Person, when: datetime, private_share: float) -> Address:
        rng = self._rng
        if person.private is not None and rng.random() < private_share:
            return person.address(person.private, rng)
        return person.address(person.mailbox(when), rng)

    def _pick_contacts(self, sender: Person, count: int, exclude: set[int]) -> list[Person]:
        """Recipients mostly from the sender's community, some from anywhere in the archive."""
        rng = self._rng
        chosen: list[Person] = []
        for slot in range(count):
            for _ in range(8):
                draw = rng.random()
                if slot == 0 and not sender.internal:
                    pool = self._community_staff[sender.community] or self._staff
                elif draw < 0.7:
                    pool = self._community[sender.community]
                elif draw < 0.85:
                    pool = self._staff
                else:
                    pool = self._outsiders
                if not pool:
                    pool = self._everyone
                person = pool.pick(rng)
                if person.index not in exclude:
                    exclude.add(person.index)
                    chosen.append(person)
                    break
        return chosen

    def _personal(self, index: int, when: datetime, remaining: int) -> PlannedMail:
        rng = self._rng
        if self._staff and (not self._outsiders or rng.random() < 0.55):
            sender = self._staff.pick(rng)
        else:
            sender = self._outsiders.pick(rng)
        exclude = {sender.index}
        to = self._pick_contacts(sender, _weighted(rng, _TO_COUNTS), exclude)
        cc = self._pick_contacts(sender, _weighted(rng, _CC_COUNTS), exclude)
        if not to:
            others = [p for p in self._everyone.items if p is not sender]
            to, cc = cc[:1] or others[:1], cc[1:]
        language = sender.language
        if language == "de" and to and to[0].language == "en":
            language = "en"
        from_address, client = self._sender(sender, when)
        # Mail from a private mailbox mostly goes to the private mailboxes of friends.
        private_share = 0.4 if from_address.domain != sender.domain.name else 0.03
        bcc: tuple[Address, ...] = ()
        if sender.internal and rng.random() < _BCC_SHARE:
            if sender.private is not None and rng.random() < 0.3:
                bcc = (sender.address(sender.private, rng),)
            else:
                hidden = self._pick_contacts(sender, rng.randint(1, 2), exclude)
                bcc = tuple(self._recipient(p, when, 0.0) for p in hidden)
        mail = PlannedMail(
            index=index,
            seed=derive_seed(self.config.seed, index),
            date=self._local_date(sender, when),
            sender=from_address,
            to=_unique(self._recipient(p, when, private_share) for p in to),
            cc=_unique(self._recipient(p, when, private_share) for p in cc),
            bcc=bcc,
            subject=self._topic_subject(language, when),
            message_id=self._message_id(client, from_address.domain, when),
            language=language,
            attachments=self._attachments(MailKind.PERSONAL, when, client),
            kind=MailKind.PERSONAL,
            client=client,
            large_attachment=self._large_now,
        )
        if self._large_now or self._calendar_rng.random() >= invitations.INVITATION_SHARE:
            self._open_thread(mail, remaining, _PERSONAL_THREAD_SHARE)
            return mail
        room = (
            sender.domain.name
            if sender.internal and from_address.domain == sender.domain.name
            else None
        )
        meeting = invitations.meeting(self._calendar_rng, mail, sender.index, sender.zone, room)
        mail.bcc = ()
        self._carry(mail, Invitation("REQUEST", meeting, invitations.style(client)))
        self._open_thread(mail, remaining, invitations.THREAD_SHARE)
        thread = self._threads.get(index)
        if thread is not None:
            thread.meeting = meeting
        return mail

    def _list_post(self, index: int, when: datetime, remaining: int) -> PlannedMail:
        rng = self._rng
        mailing_list = rng.choice(self.population.lists)
        sender = self.population.persons[mailing_list.pick_member(rng)]
        from_address, client = self._sender(sender, when)
        subject = self._topic_subject(sender.language, when)
        if mailing_list.tag:
            subject = f"{mailing_list.tag} {subject}"
        mail = PlannedMail(
            index=index,
            seed=derive_seed(self.config.seed, index),
            date=self._local_date(sender, when),
            sender=from_address,
            to=(mailing_list.address,),
            subject=subject,
            message_id=self._message_id(client, from_address.domain, when),
            list_id=mailing_list.list_id,
            language=sender.language,
            attachments=self._attachments(MailKind.PERSONAL, when, client),
            kind=MailKind.PERSONAL,
            client=client,
            large_attachment=self._large_now,
        )
        self._open_thread(mail, remaining, _LIST_THREAD_SHARE)
        return mail

    def _automated(self, index: int, when: datetime) -> PlannedMail:
        rng = self._rng
        pool = self._services_by_kind[_weighted(rng, _AUTOMATED_KINDS)] or self._services
        service = pool.pick(rng)
        kind = service.service or MailKind.NOTIFICATION
        recipient = (self._humans_inside or self._staff).pick(rng)
        private_share = 0.0 if service.internal else 0.3
        to: tuple[Address, ...] = (self._recipient(recipient, when, private_share),)
        if kind is MailKind.NEWSLETTER and rng.random() < 0.04:
            to = ()  # sent as Bcc, the header reads "To: undisclosed-recipients:;"
        sender = service.address(0, rng, sender=True)
        client = service.clients[0]
        local = sender.email.partition("@")[0]
        return PlannedMail(
            index=index,
            seed=derive_seed(self.config.seed, index),
            date=self._local_date(service, when),
            sender=sender,
            to=to,
            subject=self._automated_subject(kind, service, when),
            message_id=self._message_id(client, sender.domain, when),
            list_id=f"{local}.{sender.domain}" if kind is MailKind.NEWSLETTER else None,
            automated=True,
            language=service.language,
            attachments=self._attachments(kind, when, client, sender.email),
            kind=kind,
            client=client,
        )

    def _forward(self, index: int, when: datetime, remaining: int) -> PlannedMail | None:
        rng = self._rng
        source = self._recent[-1 - min(len(self._recent) - 1, int(rng.expovariate(0.15)))]
        involved = {
            self._owners[a.email]
            for a in (source.sender, *source.to, *source.cc)
            if a.email in self._owners
        }
        insiders = sorted(o for o in involved if self.population.persons[o[0]].internal)
        if not insiders:
            return None
        person_index, mailbox = rng.choice(insiders)
        forwarder = self.population.persons[person_index]
        targets = self._pick_contacts(forwarder, 1, {owner for owner, _ in involved})
        if not targets:
            return None
        client = self._client(forwarder, when)
        sender = forwarder.address(mailbox, rng, sender=True)
        carried = source.attachments[:-1] if source.large_attachment else source.attachments
        carried = tuple(a for a in carried if not a.inline and a.content is None)
        if self._large_now or not carried:
            carried = self._attachments(MailKind.FORWARD, when, client)
        mail = PlannedMail(
            index=index,
            seed=derive_seed(self.config.seed, index),
            date=self._local_date(forwarder, when),
            sender=sender,
            to=(self._recipient(targets[0], when, 0.0),),
            subject=forward_subject(source.subject, client, forwarder.language),
            message_id=self._message_id(client, sender.domain, when),
            language=source.language,
            attachments=carried,
            kind=MailKind.FORWARD,
            client=client,
            quoted=source,
            large_attachment=self._large_now,
        )
        self._open_thread(mail, remaining, _FORWARD_THREAD_SHARE)
        return mail

    def _reply(self, index: int, when: datetime, thread: _Thread) -> PlannedMail:
        rng = self._rng
        parent = thread.last
        mailing_list = self._list_by_id.get(parent.list_id or "")
        replier, mailbox = self._replier(parent, mailing_list, when)
        sender = replier.address(mailbox, rng, sender=True)
        to, cc = self._reply_recipients(parent, sender, replier, mailing_list, when)
        client = "webmail" if mailbox == replier.private else self._client(replier, when)
        # A reply is never older than its parent, even when the parent was back-dated.
        not_before = parent.date.astimezone(UTC) + timedelta(seconds=30)
        when = min(max(when, not_before), self._clock.end - timedelta(seconds=1))
        references = (*thread.references, parent.message_id)
        if len(references) > MAX_REFERENCES:
            references = (references[0], *references[-(MAX_REFERENCES - 1) :])
        # The main rng draws subject, Message-ID, then attachments, in this order.
        subject = reply_subject(parent.subject, client, replier.language, rng)
        message_id = self._message_id(client, sender.domain, when)
        attachments = self._attachments(MailKind.REPLY, when, client)
        if attachments and not self._large_now:
            attachments = self._documents.again(parent.attachments, attachments)
        mail = PlannedMail(
            index=index,
            seed=derive_seed(self.config.seed, index),
            date=self._local_date(replier, when),
            sender=sender,
            to=to,
            cc=cc,
            subject=subject,
            message_id=message_id,
            in_reply_to=parent.message_id,
            references=references,
            thread_index=thread.root,
            list_id=parent.list_id,
            language=parent.language,
            attachments=attachments,
            kind=MailKind.REPLY,
            client=client,
            quoted=parent,
            large_attachment=self._large_now,
        )
        if thread.meeting is not None and not thread.cancelled and not self._large_now:
            self._follow_up(mail, thread, replier)
        thread.last = _strip(mail)
        thread.references = references
        thread.remaining -= 1
        self._unanswered.pop(thread.root, None)
        if thread.remaining > 0:
            self._schedule_reply(thread, index)
        else:
            del self._threads[thread.root]
        return mail

    def _follow_up(self, mail: PlannedMail, thread: _Thread, replier: Person) -> None:
        """A mail in the thread of an invitation (D154): the organiser moves or cancels the
        meeting, an attendee answers, or it stays a plain reply."""
        meeting = thread.meeting
        assert meeting is not None
        rng = self._calendar_rng
        written_by = invitations.style(mail.client)
        if replier.index == meeting.organizer_person:
            draw = rng.random()
            if draw < invitations.UPDATE_SHARE:
                meeting = invitations.moved(rng, meeting)
                invitation = Invitation("REQUEST", meeting, written_by)
            elif draw < invitations.UPDATE_SHARE + invitations.CANCEL_SHARE:
                meeting = replace(meeting, sequence=meeting.sequence + 1)
                invitation = Invitation("CANCEL", meeting, written_by)
                thread.cancelled = True
            else:
                return
            thread.meeting = meeting
            mail.to = meeting.attendees
        else:
            if rng.random() >= invitations.ANSWER_SHARE:
                return
            partstat = _weighted(rng, invitations.PARTSTATS)
            invitation = Invitation("REPLY", meeting, written_by, mail.sender, partstat)
            mail.to = (meeting.organizer,)
        mail.cc = mail.bcc = ()
        self._carry(mail, invitation)

    def _carry(self, mail: PlannedMail, invitation: Invitation) -> None:
        """The mail carries the invitation: its subject and, by the program, an invite.ics."""
        mail.calendar = invitation
        mail.subject = invitations.subject(invitation, mail.language)
        mail.attachments = invitations.files(mail)

    def _replier(
        self, parent: PlannedMail, mailing_list: MailingList | None, when: datetime
    ) -> tuple[Person, int]:
        rng = self._rng
        persons = self.population.persons
        author = self._owners.get(parent.sender.email, (-1, 0))[0]
        if mailing_list is not None:
            member = mailing_list.pick_member(rng)
            for _ in range(8):
                if member != author:
                    break
                member = mailing_list.pick_member(rng)
            return persons[member], persons[member].mailbox(when)
        owners = [
            self._owners[a.email]
            for a in (*parent.to, *parent.cc)
            if a.email in self._owners and self._owners[a.email][0] != author
        ]
        if not owners:  # nobody else can answer: the author follows up on the own mail
            owners = [self._owners.get(parent.sender.email, (self._everyone.items[0].index, 0))]
        first = self._owners.get(parent.to[0].email) if parent.to else None
        if first is not None and first in owners and rng.random() < 0.6:
            person_index, mailbox = first
        else:
            person_index, mailbox = rng.choice(owners)
        return persons[person_index], mailbox

    def _reply_recipients(
        self,
        parent: PlannedMail,
        sender: Address,
        replier: Person,
        mailing_list: MailingList | None,
        when: datetime,
    ) -> tuple[tuple[Address, ...], tuple[Address, ...]]:
        rng = self._rng
        if mailing_list is not None:
            copied = (parent.sender,) if rng.random() < 0.15 else ()
            return (mailing_list.address,), _unique(copied, exclude=sender.email)
        author = self._owners.get(parent.sender.email)
        author_inside = author is not None and self.population.persons[author[0]].internal
        # Two outsiders only show up in the archive when an insider stays on the thread.
        reply_all = len(parent.to) + len(parent.cc) > 1 and (
            rng.random() < 0.5 or not (replier.internal or author_inside)
        )
        to = [parent.sender]
        cc: list[Address] = []
        if reply_all:
            to.extend(parent.to)
            cc.extend(parent.cc)
        if rng.random() < 0.15:  # the Cc chain grows: somebody new is copied in
            involved = {self._owners.get(a.email, (-1, 0))[0] for a in (*to, *cc, sender)}
            extra = self._pick_contacts(replier, 1, involved)
            cc.extend(self._recipient(p, when, 0.0) for p in extra)
        to_unique = _unique(to, exclude=sender.email)
        if not to_unique:  # following up on the own mail: write to its recipients again
            to_unique = _unique(parent.to, exclude=sender.email) or (parent.sender,)
        seen = {a.email for a in to_unique}
        return to_unique, _unique((a for a in cc if a.email not in seen), exclude=sender.email)

    # Content decisions ------------------------------------------------------------------

    def _topic_subject(self, language: str, when: datetime) -> str:
        topic = self._rng.choice(vocab.TOPICS_DE if language == "de" else vocab.TOPICS_EN)
        if "{}" not in topic.subject:
            return topic.subject
        return topic.subject.format(self._topic_arg(topic.arg, language, when))

    def _topic_arg(self, kind: str, language: str, when: datetime) -> str:
        rng = self._rng
        german = language == "de"
        match kind:
            case "project":
                return rng.choice(vocab.PROJECTS)
            case "weekday":
                return rng.choice((vocab.WEEKDAYS_DE if german else vocab.WEEKDAYS_EN)[:5])
            case "meeting":
                return rng.choice(vocab.MEETINGS_DE if german else vocab.MEETINGS_EN)
            case "invoice":
                return f"{when.year}-{rng.randint(1, 4999):04d}"
            case "week":
                return str((when.isocalendar().week + rng.randint(0, 2)) % 52 + 1)
            case "question":
                return rng.choice(vocab.QUESTIONS_DE if german else vocab.QUESTIONS_EN)
            case "event":
                return rng.choice(vocab.EVENTS_DE if german else vocab.EVENTS_EN)
            case "system":
                return rng.choice(vocab.SYSTEMS)
            case "month":
                months = vocab.MONTHS_DE if german else vocab.MONTHS_EN
                return months[(when.month + rng.randint(0, 3)) % 12]
            case "product":
                return rng.choice(vocab.PRODUCTS if german else vocab.PRODUCTS_EN)
        return ""

    def _automated_subject(self, kind: MailKind, service: Person, when: datetime) -> str:
        rng = self._rng
        german = service.language == "de"
        templates: tuple[str, ...]
        if kind is MailKind.NEWSLETTER:
            templates = vocab.NEWSLETTER_SUBJECTS_DE if german else vocab.NEWSLETTER_SUBJECTS_EN
        elif kind is MailKind.INVOICE:
            templates = vocab.INVOICE_SUBJECTS_DE if german else vocab.INVOICE_SUBJECTS_EN
        else:
            de, en = vocab.NOTIFICATION_SUBJECTS[service.theme or "account"]
            templates = de if german else en
        later = when + timedelta(days=rng.randint(1, 20))
        months = vocab.MONTHS_DE if german else vocab.MONTHS_EN
        return rng.choice(templates).format(
            month=months[when.month - 1],
            year=when.year,
            pct=rng.choice((10, 15, 20, 25, 30, 40, 50)),
            season=(vocab.SEASONS_DE if german else vocab.SEASONS_EN)[when.month % 12 // 3],
            week=when.isocalendar().week,
            n=rng.randint(10_000, 999_999),
            days=rng.randint(3, 14),
            room=rng.randint(101, 420),
            date=format_date(later.date(), german),
        )

    def _message_id(self, client: str, domain: str, when: datetime) -> str:
        """Message-ID in the style of the program that wrote the mail; at least 64 random bits."""
        bits = self._rng.getrandbits
        if client == "outlook" and when.year < 2016:
            return f"<{bits(40):012x}${bits(32):08x}${bits(32):08x}$@{domain}>"
        if client == "outlook":
            host = f"EX{bits(4) + 1:02d}MB{bits(12):04X}"
            return f"<{host}{bits(96):024X}@{host.lower()}.{domain}>"
        if client == "thunderbird" and when.year < 2019:
            return f"<{bits(40):010X}.{bits(32)}@{domain}>"
        if client == "thunderbird":
            return f"<{_uuid(bits(128))}@{domain}>"
        if client in ("apple", "mobile"):
            return f"<{_uuid(bits(128)).upper()}@{domain}>"
        if client == "bulk":
            return f"<{when:%Y%m%d%H%M%S}.{bits(64):016x}@{domain}>"
        if client == "system":
            return f"<{bits(64):016x}.{when:%Y%m%d%H%M%S}@{domain}>"
        return f"<{bits(128):032x}@{domain}>"  # webmail

    def _attachments(
        self, kind: MailKind, when: datetime, client: str, sender: str = ""
    ) -> tuple[AttachmentSpec, ...]:
        """Attachments of a new mail; documents (generator.documents) for the templates that
        have them. Automated mail sends its own documents, which do not circulate."""
        rng = self._rng
        documents = self._documents
        if self._large_now:
            name, mime = rng.choice(vocab.LARGE_ATTACHMENT_NAMES)
            filename = name.format(year=when.year, month2=f"{when.month:02d}")
            return (AttachmentSpec(filename, mime, self.config.large_attachment_size),)
        if rng.random() >= self.config.attachment_share:
            return ()
        if kind is MailKind.INVOICE:
            name = f"Rechnung_{when.year}-{when.month:02d}.pdf"
            spec = AttachmentSpec(name, "application/pdf", _size(rng, 60_000, 0.5))
            pattern = "Rechnung_{year}-{month2}.pdf"
            return (documents.attach(spec, pattern, when, circulate=False),)
        if kind in (MailKind.NEWSLETTER, MailKind.NOTIFICATION):
            name, mime, median, spread = rng.choice(_AUTOMATED_ATTACHMENTS)
            filename = name.format(year=when.year, n=rng.randint(10_000, 99_999))
            spec = AttachmentSpec(filename, mime, _size(rng, median, spread))
            shared = f"{sender}:{filename}" if name.startswith("Katalog") else None
            return (documents.attach(spec, name, when, circulate=False, shared=shared),)
        specs: list[AttachmentSpec] = []
        planned: set[str] = set()  # the drawn names: the pool may hand out others
        for _ in range(_weighted(rng, _ATTACHMENT_COUNTS)):
            name, mime, median, spread = _weighted(rng, _ATTACHMENT_TEMPLATES)
            filename = self._file_name(name, when)
            if filename not in planned:
                planned.add(filename)
                spec = AttachmentSpec(filename, mime, _size(rng, median, spread))
                specs.append(documents.attach(spec, name, when, specs))
        if client in ("outlook", "apple") and rng.random() < 0.25:
            name, mime = rng.choice(vocab.INLINE_IMAGE_NAMES)
            spec = AttachmentSpec(name, mime, _size(rng, 12_000, 0.6), inline=True)
            specs.insert(0, documents.inline(spec, when))
        return tuple(specs)

    def _file_name(self, pattern: str, when: datetime) -> str:
        rng = self._rng
        return pattern.format(
            year=when.year,
            month2=f"{when.month:02d}",
            day2=f"{when.day:02d}",
            n=rng.randint(1000, 9999),
            project=rng.choice(vocab.PROJECTS).replace(" ", "_"),
            word=rng.choice(vocab.SURNAMES_DE).replace(" ", "_"),
        )


def format_date(day: date, german: bool) -> str:
    if german:
        return f"{day.day:02d}.{day.month:02d}.{day.year}"
    return f"{vocab.MONTHS_EN[day.month - 1]} {day.day}, {day.year}"


def _size(rng: random.Random, median: int, spread: float) -> int:
    """Log-normal size: most files a few KB to a few MB, a long tail up to the cap."""
    return max(120, min(MAX_ATTACHMENT_SIZE, int(median * math.exp(spread * rng.gauss(0, 1)))))


def _uuid(value: int) -> str:
    text = f"{value:032x}"
    variant = "89ab"[value & 3]
    return f"{text[:8]}-{text[8:12]}-4{text[13:16]}-{variant}{text[17:20]}-{text[20:]}"
