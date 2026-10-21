"""`mailrobbe bench`: the response times of a running server's API, measured the way one person
clicks through the screens (D51).

It first picks its samples through the API itself: the newest mails and words of their
subjects, the person with the most mails and one from the middle of the person list, that
person's strongest contact and busiest year, the top sender domains, thresholds at which the
map's excerpts stay below 2,000 nodes, the document carried by the most mails and words of the
busiest document with text. So it needs nothing but the server's URL and runs on the
host or in the container (`docker compose exec backend mailrobbe bench`) against any archive.
Then it requests every scenario `--rounds` times, one request after the other over one
keep-alive connection, and prints the median, the 95th percentile and the maximum of each,
from sending the request to reading the last byte of the response. Any answer other than 200
is listed at the end and makes the exit status 1.

Standard library only, so it needs nothing beyond the server's own installation.
"""

import argparse
import base64
import http.client
import json
import math
import os
import re
import sys
import time
import urllib.parse
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_URL = "http://127.0.0.1:8000"
TIMEOUT = 600.0  # seconds per request; the CSV export of every mail takes a while
KEEP = 300  # bytes of a failed response's body kept for the error list
WORDS = 3  # subject words the full-text scenarios use in turn
MIN_WORD = 5  # letters of a subject word
MIDDLE_PAGES = 25  # person pages of 200 walked at most to reach the middle of the list
MAX_THRESHOLD = 1 << 15  # the map's threshold is doubled up to this until an excerpt fits
_WORD = re.compile(rf"[^\W\d_]{{{MIN_WORD},}}")

Params = Sequence[tuple[str, object]]


class BenchError(Exception):
    """The server cannot be reached, or a request needed for the samples failed."""


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    size: int  # bytes of the body
    seconds: float  # from sending the request to reading its last byte
    body: bytes  # the whole body, or its first KEEP bytes


class Client:
    """GET requests over one keep-alive connection, opened again when the server closed it."""

    def __init__(self, url: str, user: str = "", password: str = "") -> None:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise BenchError(f"not an http or https URL: {url}")
        self.url = url.rstrip("/")
        self._secure = parts.scheme == "https"
        self._host, self._port = parts.hostname, parts.port
        self._prefix = parts.path.rstrip("/")
        self._headers = {"Accept": "application/json"}
        if user or password:
            token = base64.b64encode(f"{user}:{password}".encode()).decode()
            self._headers["Authorization"] = f"Basic {token}"
        self._connection: http.client.HTTPConnection | None = None

    def get(self, path: str, keep: int | None = KEEP) -> Response:
        """One request; keep None keeps the whole body."""
        for attempt in (1, 2):
            if self._connection is None:
                kind = http.client.HTTPSConnection if self._secure else http.client.HTTPConnection
                self._connection = kind(self._host, self._port, timeout=TIMEOUT)
            started = time.perf_counter()
            try:
                self._connection.request("GET", self._prefix + path, headers=self._headers)
                response = self._connection.getresponse()
                body, size = bytearray(), 0
                while chunk := response.read(64 * 1024):
                    size += len(chunk)
                    if keep is None or len(body) < keep:
                        body += chunk
                seconds = time.perf_counter() - started
            except (http.client.RemoteDisconnected, ConnectionResetError, BrokenPipeError):
                self.close()
                if attempt == 2:
                    raise BenchError(f"{self.url} closed the connection") from None
                continue  # an idle keep-alive connection the server closed meanwhile
            except OSError as error:
                self.close()
                raise BenchError(f"cannot reach {self.url}: {error}") from error
            if response.will_close:
                self.close()
            return Response(response.status, size, seconds, bytes(body[:keep]))
        raise AssertionError("unreachable")

    def json(self, path: str, params: Params = ()) -> Any:
        """The JSON answer; BenchError unless the status is 200."""
        target = with_query(path, params)
        response = self.get(target, keep=None)
        if response.status != 200:
            raise BenchError(f"HTTP {response.status} for {target}: {_excerpt(response.body)}")
        return json.loads(response.body)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def with_query(path: str, params: Params) -> str:
    return f"{path}?{urllib.parse.urlencode(list(params))}" if params else path


def _excerpt(body: bytes) -> str:
    return body[:KEEP].decode("utf-8", "replace").replace("\n", " ")


# Samples ---------------------------------------------------------------------------------------


@dataclass(slots=True)
class Samples:
    """What the scenarios request, picked through the API; None or empty: the archive has none."""

    mails: int = 0
    persons: int = 0
    mail_id: int | None = None  # the newest mail
    next_cursor: str | None = None  # of the first page of the mail list
    words: list[str] = field(default_factory=list)  # most common subject words, newest mails
    neighbours: tuple[str, str, int] | None = None  # filter, value, a mail matching it
    sender_domains: list[str] = field(default_factory=list)  # the two with the most mails
    year: int | None = None  # the top person's busiest year
    top_person: int | None = None
    top_email: str | None = None
    contact: int | None = None  # the top person's strongest contact
    middle_person: int | None = None
    middle_rank: int | None = None  # 1-based, in the person list by mails
    ego_thresholds: dict[int, int] = field(default_factory=dict)  # depth -> min_edge
    domains_threshold: int | None = None
    documents: int = 0
    document_id: int | None = None  # the document carried by the most mails
    text_document_id: int | None = None  # the one with text carried by the most mails
    document_words: list[str] = field(default_factory=list)  # most common words of its text


def pick_samples(client: Client) -> Samples:
    stats = client.json("/api/stats")
    samples = Samples(mails=stats["mails"], persons=stats["persons"])
    samples.sender_domains = [entry["domain"] for entry in stats["sender_domains"][:2]]
    if stats["date_max"]:
        samples.year = datetime.fromisoformat(stats["date_max"]).year
    if samples.mails:
        first = client.json("/api/mails")
        if first["items"]:
            samples.mail_id = first["items"][0]["id"]
        samples.next_cursor = first["next_cursor"]
        subjects = [item["subject"] or "" for item in first["items"]]
        words = Counter(word.lower() for subject in subjects for word in _WORD.findall(subject))
        samples.words = [word for word, _ in words.most_common(WORDS)]
        filtered: tuple[str, str] | None = None
        if stats["dkim"]["pass"]:
            filtered = ("dkim", "pass")
        elif samples.sender_domains:
            filtered = ("sender_domain", samples.sender_domains[0])
        if filtered is not None:
            items = client.json("/api/mails", [filtered])["items"]
            if items:
                samples.neighbours = (*filtered, items[len(items) // 2]["id"])
    if samples.persons:
        _pick_persons(client, samples)
    samples.documents = sum(client.json("/api/import/summary")["documents"].values())
    if samples.documents:
        _pick_documents(client, samples)
    return samples


def _pick_persons(client: Client, samples: Samples) -> None:
    page = client.json("/api/persons", [("limit", 1)])
    if not page["items"]:
        return
    top = page["items"][0]
    samples.top_person, samples.top_email = top["id"], top["email"]
    profile = client.json(f"/api/persons/{top['id']}")
    if profile["years"]:
        busiest = max(profile["years"], key=lambda year: year["sent"] + year["received"])
        samples.year = busiest["year"]
    if profile["top_contacts"]:
        samples.contact = profile["top_contacts"][0]["person"]["person_id"]

    target, seen, cursor = page["total"] // 2, 0, None
    for _ in range(MIDDLE_PAGES):
        params: list[tuple[str, object]] = [("limit", 200)]
        if cursor:
            params.append(("cursor", cursor))
        found = client.json("/api/persons", params)
        items, cursor = found["items"], found["next_cursor"]
        if not items:
            break
        index = min(target - seen, len(items) - 1)
        samples.middle_person, samples.middle_rank = items[index]["id"], seen + index + 1
        seen += len(items)
        if seen > target or not cursor:
            break

    center = [("mode", "ego"), ("center", top["id"])]
    for depth in (1, 2):
        samples.ego_thresholds[depth] = fit_threshold(client, [*center, ("depth", depth)])
    if len(samples.sender_domains) == 2:
        domains = [("mode", "domains"), *(("domain", d) for d in samples.sender_domains)]
        samples.domains_threshold = fit_threshold(client, domains)


def _pick_documents(client: Client, samples: Samples) -> None:
    busiest = [("sort", "mails"), ("limit", 1)]
    items = client.json("/api/documents", busiest)["items"]
    if items:
        samples.document_id = items[0]["id"]
    items = client.json("/api/documents", [*busiest, ("text_status", "text")])["items"]
    if items:
        samples.text_document_id = items[0]["id"]
        text = client.json(f"/api/documents/{samples.text_document_id}/text")["text"]
        words = Counter(word.lower() for word in _WORD.findall(text))
        samples.document_words = [word for word, _ in words.most_common(WORDS)]


def fit_threshold(client: Client, params: Params) -> int:
    """The smallest power of two as min_edge at which the excerpt has at most 2,000 nodes, as
    someone would raise the threshold until the map draws."""
    threshold = 1
    while threshold < MAX_THRESHOLD:
        size = client.json("/api/graph/size", [*params, ("min_edge", threshold)])
        if not size["too_large"]:
            break
        threshold *= 2
    return threshold


# Scenarios -------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    paths: tuple[str, ...]  # round n requests paths[n % len(paths)]


def scenarios(samples: Samples, with_export: bool = False) -> tuple[list[Scenario], list[str]]:
    """Every scenario the samples allow, in the order of the screens; and those skipped."""
    found: list[Scenario] = []
    skipped: list[str] = []

    def add(name: str, *paths: object) -> None:
        """paths without a sample are None (or another false value) and left out."""
        usable = tuple(path for path in paths if isinstance(path, str) and path)
        if usable:
            found.append(Scenario(name, usable))
        else:
            skipped.append(name)

    def mails(*params: tuple[str, object]) -> str:
        return with_query("/api/mails", params)

    def summary(*params: tuple[str, object]) -> str:
        return with_query("/api/mails/summary", params)

    s = samples
    domain = s.sender_domains[0] if s.sender_domains else None
    year = (
        [] if s.year is None else [("date_from", f"{s.year}-01-01"), ("date_to", f"{s.year}-12-31")]
    )
    words: list[str | None] = list(s.words) or [None]  # None: skipped
    mail = None if s.mail_id is None else f"/api/mails/{s.mail_id}"
    top = None if s.top_person is None else f"/api/persons/{s.top_person}"

    add("stats", "/api/stats")
    add("mail list, first page", "/api/mails")
    add("mail list, next page", s.next_cursor and mails(("cursor", s.next_cursor)))
    add("mail list, oldest first", mails(("sort", "date_asc")))
    add("filter dkim=pass", mails(("dkim", "pass")))
    add("filter dkim=no_key", mails(("dkim", "no_key")))
    add("filter has_attachment", mails(("has_attachment", "true")))
    add("filter sender_domain", domain and mails(("sender_domain", domain)))
    add("filter one year", year and mails(*year))
    add("filter full text word", *(word and mails(("q", word)) for word in words))
    add("filter from:<address>", s.top_email and mails(("q", f"from:{s.top_email}")))
    add("filter subject:<word>", *(word and mails(("q", f"subject:{word}")) for word in words))
    add(
        "filter dkim, domain and year",
        domain and year and mails(("dkim", "pass"), ("sender_domain", domain), *year),
    )
    add("summary, unfiltered", "/api/mails/summary")
    add("summary, dkim=pass", summary(("dkim", "pass")))
    add("summary, full text word", *(word and summary(("q", word)) for word in words))
    if s.neighbours is not None:
        key, value, mail_id = s.neighbours
        add(
            "neighbours in a filtered list",
            with_query(f"/api/mails/{mail_id}/neighbors", [(key, value)]),
        )
    else:
        add("neighbours in a filtered list")
    add("mail detail", mail)
    add("body text", mail and f"{mail}/body?format=text")
    add("body headers", mail and f"{mail}/body?format=headers")
    add("body raw", mail and f"{mail}/body?format=raw")

    persons = s.persons and "/api/persons"
    add("persons by mails", persons)
    add("persons by name", persons and "/api/persons?sort=name")
    add("persons by latest mail", persons and "/api/persons?sort=recent")
    search = s.top_email.split("@")[0][:4] if s.top_email else None
    add("person search", search and with_query("/api/persons", [("q", search)]))
    add("profile, top person", top)
    add("profile, middle person", s.middle_person and f"/api/persons/{s.middle_person}")
    add("contacts, top person", top and f"{top}/contacts")
    add("mail counts, top person, one year", top and s.year and f"{top}/mail-counts?year={s.year}")
    add("alias suggestions", persons and "/api/persons/suggestions")
    add(
        "mails of the top person, sent",
        top and mails(("person", s.top_person), ("person_role", "sent")),
    )
    add(
        "mails between top person and contact",
        top and s.contact and mails(("between", s.top_person), ("between", s.contact)),
    )

    ego = [("mode", "ego"), ("center", s.top_person)]
    add("map, top 50", persons and "/api/graph?mode=top&limit=50")
    add("map, top 200", persons and "/api/graph?mode=top&limit=200")
    for depth in (1, 2):
        threshold = s.ego_thresholds.get(depth)
        params = [*ego, ("depth", depth), ("min_edge", threshold)]
        add(f"map, ego depth {depth}", threshold and with_query("/api/graph", params))
    domains = [("domain", domain) for domain in s.sender_domains]
    params = [("mode", "domains"), *domains, ("min_edge", s.domains_threshold)]
    add("map, two domains", s.domains_threshold and with_query("/api/graph", params))
    add("map size, ego depth 2", top and with_query("/api/graph/size", [*ego, ("depth", 2)]))
    add("GraphML, top 50", persons and "/api/graph/export.graphml?mode=top&limit=50")

    listed = s.documents and "/api/documents"
    document = None if s.document_id is None else f"/api/documents/{s.document_id}"
    document_words: list[str | None] = list(s.document_words) or [None]
    add("documents, newest first", listed)
    add("documents, oldest first", listed and "/api/documents?sort=oldest")
    add("documents by mails", listed and "/api/documents?sort=mails")
    add("documents by size", listed and "/api/documents?sort=size")
    add(
        "documents, full text word",
        *(word and with_query("/api/documents", [("q", word)]) for word in document_words),
    )
    add("documents summary, unfiltered", listed and "/api/documents/summary")
    add(
        "documents summary, full text word",
        *(word and with_query("/api/documents/summary", [("q", word)]) for word in document_words),
    )
    add("document page", document)
    add("document text", document and f"{document}/text")
    add(
        "mails of a document, oldest first",
        document and mails(("document", s.document_id), ("sort", "date_asc")),
    )
    add(
        "mail search through attachments",
        *(word and mails(("q", word)) for word in document_words),
    )

    add("import status", "/api/import/status")
    add("import summary", "/api/import/summary")
    add("import errors", "/api/import/errors")
    if with_export:
        add("CSV export, every mail", "/api/mails/export.csv")
    return found, skipped


# Measuring -------------------------------------------------------------------------------------


@dataclass(slots=True)
class Result:
    name: str
    paths: tuple[str, ...]
    seconds: list[float] = field(default_factory=list)
    size: int = 0  # bytes of the last body
    errors: list[str] = field(default_factory=list)

    def summary(self, slow_ms: float) -> dict[str, Any]:
        p95 = percentile(self.seconds, 0.95) * 1000
        return {
            "name": self.name,
            "paths": list(self.paths),
            "p50_ms": round(percentile(self.seconds, 0.5) * 1000, 1),
            "p95_ms": round(p95, 1),
            "max_ms": round(max(self.seconds) * 1000, 1),
            "size_bytes": self.size,
            "slow": p95 > slow_ms,
            "errors": self.errors,
        }


def percentile(values: Sequence[float], fraction: float) -> float:
    """The value below which `fraction` of values lie, interpolated linearly between the two
    nearest ranks (as statistics.quantiles with method="inclusive"); values must not be empty."""
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def measure(client: Client, scenario: Scenario, rounds: int) -> Result:
    result = Result(scenario.name, scenario.paths)
    for round_ in range(rounds):
        path = scenario.paths[round_ % len(scenario.paths)]
        response = client.get(path)
        result.seconds.append(response.seconds)
        result.size = response.size
        if response.status != 200:
            result.errors.append(f"HTTP {response.status} for {path}: {_excerpt(response.body)}")
    return result


# Output ----------------------------------------------------------------------------------------

NAME_WIDTH = 40
HEADER = f"{'scenario':<{NAME_WIDTH}} {'p50 ms':>8} {'p95 ms':>8} {'max ms':>8} {'size':>10}"


def table_row(row: dict[str, Any]) -> str:
    mark = "  SLOW" if row["slow"] else ""
    mark += "  ERROR" if row["errors"] else ""
    return (
        f"{row['name']:<{NAME_WIDTH}} {row['p50_ms']:>8.1f} {row['p95_ms']:>8.1f} "
        f"{row['max_ms']:>8.1f} {format_size(row['size_bytes']):>10}{mark}"
    )


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024**2:
        return f"{size / 1024:.1f} KiB"
    return f"{size / 1024**2:.1f} MiB"


def describe(samples: Samples) -> list[str]:
    """The samples, for the reader of the output."""
    s = samples
    lines = [f"  archive         {s.mails:,} mails, {s.persons:,} persons"]
    if s.mail_id is not None:
        lines.append(f"  mail            #{s.mail_id}, the newest")
    if s.words:
        lines.append(f"  words           {', '.join(s.words)} (from the newest subjects)")
    if s.sender_domains:
        lines.append(f"  sender domains  {', '.join(s.sender_domains)} (most mails)")
    if s.year is not None:
        lines.append(f"  year            {s.year}")
    if s.top_person is not None:
        contact = "" if s.contact is None else f", strongest contact #{s.contact}"
        lines.append(f"  top person      #{s.top_person} {s.top_email}{contact}")
    if s.middle_person is not None:
        lines.append(
            f"  middle person   #{s.middle_person}, rank {s.middle_rank:,} of {s.persons:,}"
        )
    if s.ego_thresholds:
        parts = [f"{t} for ego depth {d}" for d, t in s.ego_thresholds.items()]
        if s.domains_threshold is not None:
            parts.append(f"{s.domains_threshold} for two domains")
        lines.append(f"  map min_edge    {', '.join(parts)}, so they have at most 2,000 nodes")
    if s.document_id is not None:
        lines.append(f"  document        #{s.document_id} of {s.documents:,}, in the most mails")
    if s.document_words:
        lines.append(
            f"  document words  {', '.join(s.document_words)} "
            f"(from the text of #{s.text_document_id})"
        )
    return lines


# Command ---------------------------------------------------------------------------------------


def _positive(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError(f"not a positive integer: {value!r}")
    return int(value)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--url", default=DEFAULT_URL, help=f"the server (default: {DEFAULT_URL})")
    parser.add_argument(
        "--rounds", type=_positive, default=5, help="requests per scenario (default: 5)"
    )
    parser.add_argument(
        "--user",
        default=os.environ.get("MAILROBBE_BASIC_AUTH_USER", ""),
        help="Basic Auth user (default: MAILROBBE_BASIC_AUTH_USER)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("MAILROBBE_BASIC_AUTH_PASSWORD", ""),
        help="Basic Auth password (default: MAILROBBE_BASIC_AUTH_PASSWORD)",
    )
    parser.add_argument("--only", metavar="TEXT", help="only scenarios whose name contains TEXT")
    parser.add_argument(
        "--with-export", action="store_true", help="also the CSV export of every mail"
    )
    parser.add_argument(
        "--slow-ms",
        type=float,
        default=1000.0,
        metavar="MS",
        help="mark scenarios whose p95 is above this (default: 1000)",
    )
    parser.add_argument("--json", type=Path, metavar="PATH", help="also write the results here")


def run(args: argparse.Namespace) -> int:
    try:
        return _bench(args)
    except BenchError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


def _bench(args: argparse.Namespace) -> int:
    started_at = datetime.now(UTC)
    client = Client(args.url, args.user, args.password)
    print(
        f"mailrobbe bench: {client.url}, {args.rounds} rounds per scenario, one request at a time"
    )
    print("Samples, picked through the API:")
    samples = pick_samples(client)
    print("\n".join(describe(samples)))
    chosen, skipped = scenarios(samples, args.with_export)
    if args.only:
        chosen = [scenario for scenario in chosen if args.only.lower() in scenario.name.lower()]
        skipped = [name for name in skipped if args.only.lower() in name.lower()]
        if not chosen:
            print(f"error: no scenario name contains {args.only!r}", file=sys.stderr)
            return 2

    print(f"\n{HEADER}")
    began = time.perf_counter()
    rows = []
    for scenario in chosen:
        row = measure(client, scenario, args.rounds).summary(args.slow_ms)
        print(table_row(row), flush=True)
        rows.append(row)
    elapsed = time.perf_counter() - began
    client.close()

    errors = [f"  {row['name']}: {error}" for row in rows for error in row["errors"]]
    requests = len(rows) * args.rounds
    print(
        f"\np50, p95, max: response times over {args.rounds} rounds, from sending the request to "
        "reading the last byte.\nsize: body of the last response. "
        f"SLOW: p95 above {args.slow_ms:g} ms (--slow-ms)."
    )
    for name in skipped:
        print(f"skipped, no sample in this archive: {name}")
    if errors:
        print(f"{len(errors)} of {requests} requests failed:")
        print("\n".join(errors))
    else:
        print(f"All {requests} requests succeeded in {elapsed:.1f} s.")
    if args.json is not None:
        report = {
            "url": client.url,
            "started_at": started_at.isoformat(),
            "rounds": args.rounds,
            "slow_ms": args.slow_ms,
            "samples": asdict(samples),
            "scenarios": rows,
            "skipped": skipped,
            "requests": requests,
            "failed": len(errors),
            "seconds": round(elapsed, 3),
        }
        args.json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Results written to {args.json}")
    return 1 if errors else 0
