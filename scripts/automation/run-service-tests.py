#!/usr/bin/env python3
"""Run the pytest suites owned by one or all deployable FDAI services."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = REPO_ROOT / "tests" / "service-suites.json"
SERVICE_PLAN_PATH = REPO_ROOT / "config" / "service-decomposition.json"
GROUPS = ("unit", "contract", "integration", "smoke")
_SERVICE_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_PYTEST_FLAGS = frozenset(
    {
        "-q",
        "-v",
        "-vv",
        "-x",
        "-s",
        "--cache-clear",
        "--disable-warnings",
        "--exitfirst",
        "--ff",
        "--lf",
        "--nf",
        "--no-cov",
        "--showlocals",
        "--stepwise",
        "--stepwise-skip",
        "--strict-config",
        "--strict-markers",
    }
)
_PYTEST_VALUE_OPTIONS = frozenset(
    {
        "-k",
        "-m",
        "-n",
        "--color",
        "--dist",
        "--durations",
        "--log-cli-level",
        "--maxfail",
        "--tb",
    }
)
_PYTEST_VALUE_PREFIXES = tuple(f"{option}=" for option in _PYTEST_VALUE_OPTIONS)


def _load_services() -> dict[str, dict[str, Any]]:
    try:
        raw = MANIFEST_PATH.read_text(encoding="utf-8")
        manifest = json.loads(raw)
    except OSError as exc:
        raise ValueError(f"service test suite manifest is unreadable: {MANIFEST_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"service test suite manifest is invalid JSON: {MANIFEST_PATH}:{exc.lineno}"
        ) from exc
    if not isinstance(manifest, dict):
        raise ValueError("service test suite manifest MUST be an object")
    schema_version = manifest.get("schema_version")
    if schema_version != 1:
        raise ValueError(
            f"service test suite manifest schema_version MUST be 1; got {schema_version!r}"
        )
    services = manifest.get("services")
    if not isinstance(services, list):
        raise ValueError("service test suite manifest services MUST be an array")
    _validate_exact_keys(
        manifest,
        expected={"schema_version", "coverage", "services"},
        label="service test suite manifest",
    )
    if not services:
        raise ValueError("service test suite manifest MUST declare at least one service")
    loaded: dict[str, dict[str, Any]] = {}
    source_claims: list[tuple[Path, str]] = []
    test_claims: list[tuple[Path, str]] = []
    for entry in services:
        if not isinstance(entry, dict):
            raise ValueError("service entry MUST be an object")
        service = _validated_service(entry)
        service_id = service["id"]
        if service_id in loaded:
            raise ValueError(f"duplicate service test suite id: {service_id}")
        for source_root in service["source_roots"]:
            _claim_path(Path(source_root), service_id, source_claims, "source")
        for test_path in _test_paths(service):
            _claim_path(Path(test_path), service_id, test_claims, "test")
        loaded[service_id] = service
    canonical_ids = _canonical_service_ids()
    if tuple(loaded) != canonical_ids:
        raise ValueError(
            f"service test suites MUST match canonical service ids and order: {list(canonical_ids)}"
        )
    _validate_coverage(manifest.get("coverage"), source_claims, test_claims)
    return loaded


def _canonical_service_ids() -> tuple[str, ...]:
    try:
        plan = json.loads(SERVICE_PLAN_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"service decomposition plan is unreadable: {SERVICE_PLAN_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"service decomposition plan is invalid JSON: {SERVICE_PLAN_PATH}:{exc.lineno}"
        ) from exc
    if not isinstance(plan, dict) or not isinstance(plan.get("services"), list):
        raise ValueError("service decomposition plan services MUST be an array")
    service_ids: list[str] = []
    for service in plan["services"]:
        if not isinstance(service, dict) or not isinstance(service.get("id"), str):
            raise ValueError("service decomposition plan entries MUST declare string ids")
        service_ids.append(service["id"])
    if plan.get("target_service_count") != len(service_ids):
        raise ValueError("service decomposition target count MUST match its service entries")
    return tuple(service_ids)


def _validate_coverage(
    value: object,
    source_claims: list[tuple[Path, str]],
    test_claims: list[tuple[Path, str]],
) -> None:
    if not isinstance(value, dict) or set(value) != {"source_patterns", "test_patterns"}:
        raise ValueError(
            "service test suite coverage MUST declare source_patterns and test_patterns"
        )
    for label, patterns, allowed_root, claims in (
        ("source", value["source_patterns"], REPO_ROOT / "services", source_claims),
        ("test", value["test_patterns"], REPO_ROOT / "tests", test_claims),
    ):
        if (
            not isinstance(patterns, list)
            or not patterns
            or not all(isinstance(pattern, str) for pattern in patterns)
        ):
            raise ValueError(
                f"service test suite {label}_patterns MUST be a non-empty string array"
            )
        for pattern in patterns:
            _validate_coverage_pattern(
                pattern,
                label=label,
                allowed_root=allowed_root,
                claims=claims,
            )


def _validate_coverage_pattern(
    pattern: str,
    *,
    label: str,
    allowed_root: Path,
    claims: list[tuple[Path, str]],
) -> None:
    relative = Path(pattern)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"service {label} coverage pattern MUST stay within the repository")
    matches = tuple(path for path in REPO_ROOT.glob(pattern) if path.is_file())
    if not matches:
        raise ValueError(f"service {label} coverage pattern matched no files: {pattern}")
    for matched in matches:
        resolved = matched.resolve(strict=True)
        if not resolved.is_relative_to(allowed_root.resolve()):
            raise ValueError(f"service {label} coverage pattern escaped its root: {pattern}")
        relative_match = resolved.relative_to(REPO_ROOT)
        owners = {
            owner
            for claimed_path, owner in claims
            if relative_match == claimed_path or relative_match.is_relative_to(claimed_path)
        }
        if len(owners) != 1:
            raise ValueError(
                f"service {label} coverage requires one owner for "
                f"{relative_match.as_posix()}; got {sorted(owners)}"
            )


def _validated_service(entry: Mapping[str, object]) -> dict[str, Any]:
    _validate_exact_keys(
        entry,
        expected={"id", "source_roots", "test_groups"},
        label="service test suite entry",
    )
    service_id = entry.get("id")
    if not isinstance(service_id, str) or _SERVICE_ID.fullmatch(service_id) is None:
        raise ValueError("service id MUST use lowercase kebab-case")
    source_roots = _validated_paths(
        entry.get("source_roots"),
        allowed_root=REPO_ROOT / "services",
        label=f"service {service_id} source root",
    )
    groups = entry.get("test_groups")
    if not isinstance(groups, dict) or set(groups) != set(GROUPS):
        raise ValueError(f"service {service_id} test_groups MUST declare {', '.join(GROUPS)}")
    test_groups = {
        group: _validated_paths(
            groups[group],
            allowed_root=REPO_ROOT / "tests",
            label=f"service {service_id} {group} test path",
            allow_empty=True,
        )
        for group in GROUPS
    }
    service = {
        "id": service_id,
        "source_roots": source_roots,
        "test_groups": test_groups,
    }
    if not _test_paths(service):
        raise ValueError(f"service {service_id} MUST own at least one test path")
    return service


def _validate_exact_keys(
    value: Mapping[str, object],
    *,
    expected: set[str],
    label: str,
) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        raise ValueError(
            f"{label} has invalid keys; missing keys: {missing}; unexpected keys: {unexpected}"
        )


def _validated_paths(
    value: object,
    *,
    allowed_root: Path,
    label: str,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} MUST be a string array")
    if not value and not allow_empty:
        raise ValueError(f"{label} MUST not be empty")
    return [_validated_path(item, allowed_root=allowed_root, label=label) for item in value]


def _validated_path(value: str, *, allowed_root: Path, label: str) -> str:
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ValueError(f"{label} MUST stay within {allowed_root.relative_to(REPO_ROOT)}")
    candidate = REPO_ROOT / relative
    current = REPO_ROOT
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError(f"{label} MUST not traverse a symlink: {value}")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"{label} does not exist: {value}") from exc
    if not resolved.is_relative_to(allowed_root.resolve()):
        raise ValueError(f"{label} MUST stay within {allowed_root.relative_to(REPO_ROOT)}")
    return resolved.relative_to(REPO_ROOT).as_posix()


def _claim_path(
    path: Path,
    service_id: str,
    existing: list[tuple[Path, str]],
    kind: str,
) -> None:
    for owned_path, owner in existing:
        if path == owned_path or path.is_relative_to(owned_path) or owned_path.is_relative_to(path):
            raise ValueError(
                f"service {service_id} {kind} path {path.as_posix()} overlaps "
                f"service {owner} path {owned_path.as_posix()}"
            )
    existing.append((path, service_id))


def _test_paths(service: dict[str, Any]) -> tuple[str, ...]:
    groups = service.get("test_groups")
    if not isinstance(groups, dict):
        raise ValueError("service test suite MUST declare test_groups")
    paths: list[str] = []
    for group in GROUPS:
        values = groups.get(group)
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise ValueError(f"service test group {group} MUST be a string array")
        paths.extend(values)
    return tuple(paths)


def _python_path(service_ids: Sequence[str]) -> str:
    roots = [REPO_ROOT / "services" / service_id / "src" for service_id in service_ids]
    roots.append(REPO_ROOT / "packages" / "service-contracts" / "src")
    if "core-control-plane" in service_ids:
        roots.append(REPO_ROOT / "src")
    missing = [path for path in roots if not path.is_dir()]
    if missing:
        raise ValueError(f"service import root does not exist: {missing[0]}")
    return os.pathsep.join(str(path) for path in roots)


def _parser(service_ids: Sequence[str]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", nargs="?", choices=service_ids)
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_services",
        help="select every service in canonical topology order",
    )
    parser.add_argument("--list", action="store_true", help="print owned test paths and exit")
    return parser


def _validated_pytest_args(values: Sequence[str]) -> list[str]:
    args = list(values)
    if args[:1] == ["--"]:
        args = args[1:]
    validated: list[str] = []
    index = 0
    while index < len(args):
        value = args[index]
        if value in _PYTEST_FLAGS or value.startswith(_PYTEST_VALUE_PREFIXES):
            validated.append(value)
            index += 1
            continue
        if value in _PYTEST_VALUE_OPTIONS and index + 1 < len(args):
            validated.extend((value, args[index + 1]))
            index += 2
            continue
        raise ValueError(f"pytest argument is not allowed for a service suite: {value}")
    return validated


def main(argv: Sequence[str] | None = None) -> int:
    try:
        services = _load_services()
        args, pytest_args = _parser(tuple(services)).parse_known_args(argv)
        selection_count = int(args.service is not None) + int(args.all_services)
        if selection_count != 1:
            raise ValueError("select exactly one service or --all")
        if args.all_services:
            selected_ids = tuple(services)
            paths = tuple(path for service in services.values() for path in _test_paths(service))
        else:
            selected_ids = (args.service,)
            paths = _test_paths(services[args.service])
        pytest_args = _validated_pytest_args(pytest_args)
        if args.list:
            if pytest_args:
                raise ValueError("pytest arguments cannot be combined with --list")
            print("\n".join(paths))
            return 0
        environment = {**os.environ, "PYTHONPATH": _python_path(selected_ids)}
    except ValueError as exc:
        print(f"service-test: {exc}", file=sys.stderr)
        return 2
    command = [sys.executable, "-m", "pytest", *pytest_args, *paths]
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        env=environment,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
