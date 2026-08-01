#!/usr/bin/env python3
"""Check FDAI DNS, resolved IP policy, and TCP destination ports."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from network_connectivity import (
    DEFAULT_TIMEOUT_SECONDS,
    PROFILES,
    ConnectivityInputError,
    EndpointCheck,
    add_input_issues,
    build_checks,
    exit_code,
    load_env_file,
    parse_manifest,
    redact_report,
    run_checks,
)


def render_summary(report: Mapping[str, object]) -> str:
    """Render operator-readable results and exact next actions."""
    summary = cast(dict[str, int], report["summary"])
    lines = [
        f"FDAI network connectivity: {str(report['status']).upper()} "
        f"(pass={summary['pass']} warn={summary['warn']} fail={summary['fail']})"
    ]
    checks = cast(list[dict[str, object]], report["checks"])
    for result in checks:
        endpoint = result.get("host", result.get("host_ref", "configuration"))
        port = f":{result['port']}" if "port" in result else ""
        addresses = cast(list[str], result.get("addresses", []))
        address_text = ",".join(addresses) or "none"
        lines.append(
            f"{str(result['status']).upper():4} {result['id']} "
            f"{endpoint}{port} dns={address_text} reason={result['reason']}"
        )
    actions = cast(list[dict[str, str]], report["actions_required"])
    if actions:
        lines.append("Actions required:")
        lines.extend(f"- {item['id']}: {item['action']}" for item in actions)
    else:
        lines.append("Actions required: none")
    return "\n".join(lines)


def _load_manifest_checks(paths: list[Path]) -> tuple[EndpointCheck, ...]:
    checks: list[EndpointCheck] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        checks.extend(parse_manifest(payload))
    return tuple(checks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=PROFILES, default="runtime-private")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--manifest", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--redact", action="store_true")
    args = parser.parse_args(argv)
    try:
        env_file = args.env_file
        if env_file is None and Path(".fdai/local-runtime.env").is_file():
            env_file = Path(".fdai/local-runtime.env")
        env = load_env_file(env_file) if env_file is not None else {}
        env.update(os.environ)
        checks, issues = build_checks(
            args.profile,
            env,
            _load_manifest_checks(args.manifest),
        )
        if not checks:
            raise ConnectivityInputError("profile and manifests produced no checks")
        report = run_checks(
            checks,
            timeout_seconds=args.timeout_seconds,
            workers=args.workers,
        )
        report["profile"] = args.profile
        report = add_input_issues(report, issues)
        visible_report = redact_report(report) if args.redact else report
        print(render_summary(visible_report))
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(visible_report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return exit_code(report)
    except (ConnectivityInputError, json.JSONDecodeError, OSError) as exc:
        print(f"network connectivity check failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
