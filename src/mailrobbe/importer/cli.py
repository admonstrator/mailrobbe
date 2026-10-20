"""The `mailrobbe import` command."""

import argparse
import sys


def add_arguments(parser: argparse.ArgumentParser) -> None:
    pass


def run(args: argparse.Namespace) -> int:
    print("The importer is not implemented yet (milestone 2).", file=sys.stderr)
    return 2
