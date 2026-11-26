"""`python -m lifecycle.demo`: the prepare, publish, hub, and run commands."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from lifecycle.demo import catalog
from lifecycle.demo.scenario import Apply, DemoError, Scenario

from fdai_lifecycle_hub import cli as hub_cli

KUBE_CONTEXT_ENV = "FDAI_DEMO_KUBE_CONTEXT"
NAMESPACE_ENV = "FDAI_DEMO_NAMESPACE"
# The demo's test scope is one dedicated namespace, never a shared or system one.
_SHARED_NAMESPACES = frozenset({"default", "kube-system", "kube-public", "kube-node-lease"})


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    layout = catalog.Layout(args.work)
    try:
        match args.command:
            case "prepare":
                catalog.reset(layout.root)
                catalog.prepare(layout)
                print(json.dumps({"prepared": str(layout.root)}))
            case "publish":
                print(json.dumps({"channel": catalog.publish(layout, args.release_id)}))
            case "hub":
                os.environ[hub_cli.DATABASE_URL_ENV] = layout.database_url
                return hub_cli.main(args.hub_args)
            case "run":
                apply = _apply(parser, args)
                catalog.reset(layout.root)
                Scenario(layout=layout, port=args.port, apply=apply, pause=args.pause).run()
    except (DemoError, ValueError) as error:
        print(f"demo failed: {error}", file=sys.stderr)
        return 1
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m lifecycle.demo")
    parser.add_argument(
        "--work", type=Path, default=Path(tempfile.gettempdir()) / "fdai-lifecycle-demo"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare", help="write keys, the catalog, and the agent and Hub inputs")
    publish = commands.add_parser("publish", help="add one demo Release to the channel")
    publish.add_argument("release_id", choices=sorted(catalog.RELEASES_BY_ID))
    hub = commands.add_parser("hub", help="run an fdai-lifecycle-hub command on the demo database")
    hub.add_argument("hub_args", nargs=argparse.REMAINDER, metavar="...")

    run = commands.add_parser("run", help="run the whole scenario from a fresh work directory")
    run.add_argument("--port", type=int, default=8090, help="loopback port for the Hub API")
    run.add_argument("--pause", action="store_true", help="wait for Enter before each step")
    run.add_argument("--apply", action="store_true", help="let the agent change the workload")
    run.add_argument("--kube-context", default=os.environ.get(KUBE_CONTEXT_ENV))
    run.add_argument("--namespace", default=os.environ.get(NAMESPACE_ENV))
    run.add_argument("--health-timeout-seconds", type=int, default=60)
    return parser


def _apply(parser: argparse.ArgumentParser, args: argparse.Namespace) -> Apply | None:
    if not args.apply:
        return None
    if not args.kube_context or not args.namespace:
        parser.error(
            f"--apply needs --kube-context and --namespace ({KUBE_CONTEXT_ENV}, {NAMESPACE_ENV})"
        )
    if args.namespace in _SHARED_NAMESPACES:
        parser.error(f"--namespace must be a dedicated demo namespace, not {args.namespace}")
    if args.health_timeout_seconds < 1:
        parser.error("--health-timeout-seconds must be at least 1")
    return Apply(
        kube_context=args.kube_context,
        namespace=args.namespace,
        health_timeout_seconds=args.health_timeout_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())
