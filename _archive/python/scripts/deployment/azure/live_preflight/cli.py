"""Command adapter for the runner-owned Azure live preflight."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .runner import mapping, run_preflight
from .transport import AzureCliReader, PreflightError

_OUTPUT_SCHEMA = "fdai.deployment-cli.preflight.v1"
_GUID = re.compile(r"^[0-9a-fA-F-]{36}$")


def _load_json(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PreflightError("preflight input is invalid or unreadable") from exc
    return mapping(payload, path.name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--terraform-plan", type=Path, required=True)
    parser.add_argument("--environment-config", type=Path, required=True)
    parser.add_argument("--output", choices=("json",), default="json")
    args = parser.parse_args(argv)
    try:
        profile = _load_json(args.input)
        plan = _load_json(args.terraform_plan)
        environment = _load_json(args.environment_config)
        azure = mapping(environment.get("azure"), "environment.azure")
        subscription_id = azure.get("subscription_id")
        if not isinstance(subscription_id, str) or _GUID.fullmatch(subscription_id) is None:
            raise PreflightError("subscription_id is invalid")
        result = run_preflight(
            profile,
            plan,
            environment,
            AzureCliReader(subscription_id=subscription_id),
        )
    except PreflightError as exc:
        print(
            json.dumps(
                {"error": str(exc), "schema_version": _OUTPUT_SCHEMA},
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 4
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    report = result["report"]
    if report["blocks_deploy"]:
        return 3
    if report["findings"]:
        return 2
    return 0
