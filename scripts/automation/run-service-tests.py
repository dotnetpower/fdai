#!/usr/bin/env python3
"""Run the pytest suite owned by one deployable FDAI service."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "tests" / "service-suites.json"


def _load_services() -> dict[str, dict[str, Any]]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    services = manifest.get("services")
    if manifest.get("schema_version") != 1 or not isinstance(services, list):
        raise ValueError("service test suite manifest MUST use schema version 1")
    return {str(service["id"]): service for service in services}


def _test_paths(service: dict[str, Any]) -> tuple[str, ...]:
    groups = service.get("test_groups")
    if not isinstance(groups, dict):
        raise ValueError("service test suite MUST declare test_groups")
    paths: list[str] = []
    for group in ("unit", "contract", "integration", "smoke"):
        values = groups.get(group)
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise ValueError(f"service test group {group} MUST be a string array")
        paths.extend(values)
    return tuple(paths)


def _parser(service_ids: Sequence[str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=service_ids)
    parser.add_argument("--list", action="store_true", help="print owned test paths and exit")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    services = _load_services()
    args, pytest_args = _parser(tuple(services)).parse_known_args(argv)
    paths = _test_paths(services[args.service])
    if args.list:
        print("\n".join(paths))
        return 0
    pytest_args = list(pytest_args)
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    command = [sys.executable, "-m", "pytest", *pytest_args, *paths]
    return subprocess.run(command, cwd=REPO_ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
