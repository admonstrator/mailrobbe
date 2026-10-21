"""`mailrobbe graph`: recompute the edges, or export the whole edge table as GraphML (D36, D38).

refresh is the full refresh_edges that every import and DKIM recheck also runs. export writes one
node per root person with an edge and one edge per row of edge, streamed from the database in
pieces, so the 400,000-mail archive never sits in memory as a whole document.

Exit status: 0 on success, 1 when the database fails, 2 when the export file exists already
(--force overwrites it).
"""

import argparse
import asyncio
import logging
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from mailrobbe.config import get_settings
from mailrobbe.db.session import create_engine
from mailrobbe.graph.edges import EdgeRefresh, refresh_edges
from mailrobbe.graph.graphml import GraphmlEdge, GraphmlNode, graphml_chunks

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_EXISTS = 2
_PARTITION = 10_000  # rows fetched at a time

_KINDS = text("SELECT kind::text, count(*) FROM person WHERE kind IS NOT NULL GROUP BY 1")
# Every person at an end of a kept edge; mails is the weight of its kept edges (D37, D38).
_NODES = text("""
    WITH kept AS (SELECT person_a, person_b, mails_total FROM edge WHERE mails_total >= :min_mails),
    ends AS (
        SELECT person_a AS id, mails_total FROM kept
        UNION ALL SELECT person_b, mails_total FROM kept
    )
    SELECT p.id, coalesce(p.display_name, p.canonical_email), p.canonical_email, p.domain,
        p.kind::text, sum(e.mails_total)::bigint
    FROM ends e JOIN person p ON p.id = e.id
    GROUP BY p.id ORDER BY p.id
""").execution_options(yield_per=_PARTITION)
_EDGES = text("""
    SELECT person_a, person_b, mails_total, mails_a_to_b, mails_b_to_a, mails_cc,
        first_date, last_date
    FROM edge WHERE mails_total >= :min_mails ORDER BY person_a, person_b
""").execution_options(yield_per=_PARTITION)


def _positive(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError(f"not a positive integer: {value!r}")
    return int(value)


def add_arguments(parser: argparse.ArgumentParser) -> None:
    actions = parser.add_subparsers(dest="action", required=True, metavar="ACTION")
    actions.add_parser(
        "refresh", help="recompute edge, edge_year and person kinds from the imported mails"
    )
    export = actions.add_parser("export", help="write the whole edge table as GraphML for Gephi")
    export.add_argument("file", metavar="FILE", help="output file, - for standard output")
    export.add_argument(
        "--min-mails",
        type=_positive,
        default=1,
        metavar="N",
        help="leave out edges with fewer mails and then persons without edges (default: 1)",
    )
    export.add_argument("--force", action="store_true", help="overwrite an existing file")


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    database_url = get_settings().database_url
    try:
        if args.action == "refresh":
            return asyncio.run(_refresh(database_url))
        return asyncio.run(_export(database_url, args.file, args.min_mails, args.force))
    except (SQLAlchemyError, OSError) as error:
        log.error("database error: %s", _message(error))
        return EXIT_FAILED


async def _refresh(database_url: str) -> int:
    engine = create_engine(database_url)
    try:
        async with engine.begin() as connection:
            result = await refresh_edges(connection)
            kinds = {kind: count for kind, count in await connection.execute(_KINDS)}
    finally:
        await engine.dispose()
    print(_summary(result, kinds))
    return EXIT_OK


def _summary(result: EdgeRefresh, kinds: dict[str, int]) -> str:
    return "\n".join(
        (
            f"edges:         {result.pairs} pairs ({result.inserted} inserted, "
            f"{result.updated} updated, {result.deleted} deleted)",
            f"edge years:    {result.years} rows changed",
            f"person kinds:  {result.kinds} changed ({kinds.get('list', 0)} lists, "
            f"{kinds.get('automated', 0)} automated)",
            f"elapsed:       {result.seconds:.1f} s",
        )
    )


async def _export(database_url: str, file: str, min_mails: int, force: bool) -> int:
    if file == "-":
        return await _stream(database_url, sys.stdout, min_mails, "standard output")
    path = Path(file)
    try:
        out = path.open("w" if force else "x", encoding="utf-8")
    except FileExistsError:
        log.error("%s exists; --force overwrites it", file)
        return EXIT_EXISTS
    except OSError as error:
        log.error("cannot write %s: %s", file, error.strerror or error)
        return EXIT_FAILED
    try:
        with out:
            return await _stream(database_url, out, min_mails, file)
    except BaseException:
        path.unlink(missing_ok=True)  # no half document left behind
        raise


async def _stream(database_url: str, out: TextIO, min_mails: int, name: str) -> int:
    engine = create_engine(database_url)
    try:
        async with engine.connect() as connection:
            nodes, edges = await connection.run_sync(_write, out, min_mails)
    finally:
        await engine.dispose()
    out.flush()
    log.info("%d persons and %d edges written to %s", nodes, edges, name)
    return EXIT_OK


def _write(connection: Connection, out: TextIO, min_mails: int) -> tuple[int, int]:
    """Stream the document into out; returns the numbers of nodes and edges written."""
    counts = [0, 0]
    params = {"min_mails": min_mails}

    def nodes() -> Iterator[GraphmlNode]:
        for row in connection.execute(_NODES, params):
            counts[0] += 1
            yield GraphmlNode(*row)

    def edges() -> Iterator[GraphmlEdge]:
        for row in connection.execute(_EDGES, params):
            counts[1] += 1
            yield GraphmlEdge(*row)

    for chunk in graphml_chunks(nodes(), edges()):
        out.write(chunk)
    return counts[0], counts[1]


def _message(error: Exception) -> str:
    """The first line of the error, without SQLAlchemy's wrapping."""
    cause: BaseException = error.orig if isinstance(error, DBAPIError) and error.orig else error
    message = str(cause).strip()
    return message.splitlines()[0] if message else type(cause).__name__
