"""Register changed-source CLI commands without growing the top-level parser."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from pathlib import Path


def register(
    provision_commands: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    command: Callable[..., argparse.ArgumentParser],
    handlers: Mapping[str, Callable[[argparse.Namespace], int]],
) -> None:
    plan = command(
        provision_commands,
        "source-change-plan",
        "Classify one exact Git diff into the narrowest safe deployment lane",
    )
    plan.add_argument("--source", type=Path, required=True, help="Clean Git checkout to inspect")
    plan.add_argument("--base", required=True, help="Base Git revision for the exact diff")
    plan.add_argument(
        "--head",
        default="HEAD",
        help="Head Git revision for the exact diff (default: %(default)s)",
    )
    plan.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format (default: %(default)s)",
    )
    plan.set_defaults(handler=handlers["provision_source_change_plan"])

    update = command(
        provision_commands,
        "source-changed-update",
        "Deploy every affected baseline service from one exact Git diff",
    )
    update.add_argument(
        "--source",
        type=Path,
        required=True,
        help="Clean checkout whose HEAD supplies the update",
    )
    update.add_argument("--base", required=True, help="Base Git revision for affected services")
    update.add_argument(
        "--application-work-dir",
        type=Path,
        required=True,
        help="Retained existing-development application work directory",
    )
    update.add_argument(
        "--work-dir",
        type=Path,
        required=True,
        help="Fresh or retained private changed-update work directory",
    )
    update.add_argument(
        "--timeout-seconds",
        type=int,
        default=14400,
        help="Total update deadline in seconds (default: %(default)s)",
    )
    update.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="Output format (default: %(default)s)",
    )
    update.set_defaults(handler=handlers["provision_source_changed_update"])


__all__ = ["register"]
