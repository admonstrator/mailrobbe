import argparse
import sys
from collections.abc import Sequence

from mailspider.generator import cli as generator_cli


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from mailspider.config import get_settings

    settings = get_settings()
    uvicorn.run(
        "mailspider.api.app:create_app",
        factory=True,
        host=args.host or settings.host,
        port=args.port or settings.port,
    )
    return 0


def _migrate(args: argparse.Namespace) -> int:
    from mailspider import migrate

    migrate.upgrade(args.revision)
    return 0


def _import(args: argparse.Namespace) -> int:
    print("The importer is not implemented yet (milestone 2).", file=sys.stderr)
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mailspider")
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

    importer = commands.add_parser("import", help="import MBOX files (milestone 2)")
    importer.set_defaults(handler=_import)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result: int = args.handler(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
