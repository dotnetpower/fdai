"""Explicit read-only status command; no source binding is selected by default."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from fdai_deployment_cli.private_output import read_private_bytes

from fdai_lifecycle_agent.reference_state import (
    CSIReference,
    ReferenceReadBudget,
    ReferenceStatusSource,
    observe_reference,
)
from fdai_lifecycle_agent.strict_json import load_json


def register_reference_command(
    commands: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    parser = commands.add_parser(
        "reference-status", help="Read CSI metadata only; never secret values."
    )
    parser.add_argument(
        "--references", type=Path, required=True, help="Private exact reference bindings."
    )
    parser.add_argument("--kube-context", required=True)
    parser.add_argument("--namespace", required=True)


def run_reference_command(
    arguments: argparse.Namespace,
    *,
    clock: Callable[[], datetime],
    connect: Callable[[str, str], ReferenceStatusSource],
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    """Return only bounded source-attributed states, not raw Kubernetes response content."""
    try:
        document = load_json(
            read_private_bytes(arguments.references, max_bytes=64 * 1024), label="CSI bindings"
        )
        if not isinstance(document, list) or not 1 <= len(document) <= 32:
            raise ValueError("CSI binding count is invalid")
        references: list[CSIReference] = []
        for item in document:
            if not isinstance(item, dict) or not all(
                isinstance(value, str) for value in item.values()
            ):
                raise ValueError("CSI binding is invalid")
            reference = CSIReference(**item)
            if reference.namespace != arguments.namespace:
                raise ValueError("CSI binding namespace does not match")
            references.append(reference)
        source = ReferenceReadBudget(
            connect(arguments.kube_context, arguments.namespace),
            deadline=monotonic() + 30.0,
            monotonic=monotonic,
        )
        results = [
            observe_reference(reference, source, now=clock()).to_json() for reference in references
        ]
    except (ValueError, TypeError, OSError):
        print(json.dumps({"state": "unavailable", "reason_code": "reference_source_unavailable"}))
        return 2
    print(json.dumps({"references": results}, sort_keys=True))
    return 0
