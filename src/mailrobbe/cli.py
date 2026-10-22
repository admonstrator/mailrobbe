import argparse
import sys
from collections.abc import Sequence

from mailrobbe import bench
from mailrobbe.dkim import cli as dkim_cli
from mailrobbe.dkim.keys import cli as keys_cli
from mailrobbe.generator import cli as generator_cli
from mailrobbe.graph import cli as graph_cli
from mailrobbe.importer import cli as importer_cli
from mailrobbe.places import cli as map_cli


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from mailrobbe.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "mailrobbe.api.app:create_app",
        factory=True,
        host=args.host or settings.host,
        port=args.port or settings.port,
    )
    return 0


def _migrate(args: argparse.Namespace) -> int:
    from mailrobbe import migrate

    migrate.upgrade(args.revision)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mailrobbe")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the web server")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.set_defaults(handler=_serve)

    migrate = commands.add_parser("migrate", help="upgrade the database schema")
    migrate.add_argument("--revision", default="head")
    migrate.set_defaults(handler=_migrate)

    generate = commands.add_parser("generate", help="write synthetic MBOX test data")
    generator_cli.add_arguments(generate)
    generate.set_defaults(handler=generator_cli.run)

    importer = commands.add_parser("import", help="import MBOX files into the database")
    importer_cli.add_arguments(importer)
    importer.set_defaults(handler=importer_cli.run)

    check = commands.add_parser("dkim", help="check the DKIM signatures of imported mails")
    dkim_cli.add_arguments(check)
    check.set_defaults(handler=dkim_cli.run)

    keys = commands.add_parser("dkim-keys", help="find the keys of deleted DKIM selectors")
    keys_cli.add_arguments(keys)
    keys.set_defaults(handler=keys_cli.run)

    graph = commands.add_parser("graph", help="recompute or export the relationship map's edges")
    graph_cli.add_arguments(graph)
    graph.set_defaults(handler=graph_cli.run)

    detail_map = commands.add_parser("map", help="download or delete the detail map")
    map_cli.add_arguments(detail_map)
    detail_map.set_defaults(handler=map_cli.run)

    measure = commands.add_parser(
        "bench", help="measure the API's response times against a running server"
    )
    bench.add_arguments(measure)
    measure.set_defaults(handler=bench.run)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.handler(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
