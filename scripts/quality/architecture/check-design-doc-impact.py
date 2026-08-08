#!/usr/bin/env python3
"""Require route-owned design documentation in behavior-changing diffs."""

from __future__ import annotations

import fnmatch
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "scripts/lib/design-routes.json"


def _git_paths(args: list[str]) -> set[str]:
    completed = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMRT", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {line for line in completed.stdout.splitlines() if line}


def changed_paths(diff_range: str | None = None, *, cached: bool = False) -> set[str]:
    if cached:
        return _git_paths(["--cached", "HEAD"])
    if diff_range:
        return _git_paths([diff_range])
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return (
        _git_paths(["HEAD"])
        | _git_paths(["--cached", "HEAD"])
        | {line for line in untracked.stdout.splitlines() if line}
    )


def _matches(path: str, pattern: str) -> bool:
    return pattern == "**" or fnmatch.fnmatchcase(path, pattern)


def _route_paths(path: str) -> tuple[str, ...]:
    aliases = {
        "services/core-control-plane/src/fdai/": "services/core-control-plane/src/fdai/",
        "services/core-control-plane/tests/": "tests/",
        "services/operator-service/src/fdai_operator_service/": (
            "services/core-control-plane/src/fdai/delivery/operator_api/"
        ),
        "services/operator-service/tests/": (
            "services/core-control-plane/tests/delivery/operator_api/"
        ),
        "services/document-ingestion-api/src/fdai_ingestion_api_service/": (
            "services/core-control-plane/src/fdai/delivery/ingestion_gateway/"
        ),
        "services/document-ingestion-api/tests/": (
            "services/core-control-plane/tests/delivery/ingestion_gateway/"
        ),
        "services/document-processing-worker/src/fdai_document_worker_service/": (
            "services/core-control-plane/src/fdai/delivery/ingestion_gateway/"
        ),
        "services/document-processing-worker/tests/": (
            "services/core-control-plane/tests/delivery/ingestion_gateway/"
        ),
        "services/isolated-executor/src/fdai_executor_service/": (
            "services/core-control-plane/src/fdai/runtime/"
        ),
        "services/isolated-executor/tests/": ("services/core-control-plane/tests/runtime/"),
        "packages/service-contracts/src/fdai_service_contracts/": (
            "services/core-control-plane/src/fdai/shared/contracts/"
        ),
        "packages/service-contracts/tests/": (
            "services/core-control-plane/tests/shared/contracts/"
        ),
    }
    for prefix, replacement in aliases.items():
        if path.startswith(prefix):
            return path, replacement + path.removeprefix(prefix)
    return (path,)


def missing_doc_updates(
    paths: set[str], manifest: dict[str, Any]
) -> list[tuple[str, tuple[str, ...], tuple[str, ...]]]:
    failures: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    for route in manifest["routes"]:
        required_docs = tuple(str(path) for path in route.get("docs_update", ()))
        if not required_docs:
            continue
        patterns = tuple(route.get("paths", ())) + tuple(route.get("optional_paths", ()))
        impacted = tuple(
            sorted(
                path
                for path in paths
                if any(
                    _matches(candidate, pattern)
                    for candidate in _route_paths(path)
                    for pattern in patterns
                )
            )
        )
        if not impacted or any(doc in paths for doc in required_docs):
            continue
        failures.append((str(route["id"]), impacted, required_docs))
    return failures


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        print(
            "usage: check-design-doc-impact.py [--cached | <git-diff-range>]",
            file=sys.stderr,
        )
        return 2
    argument = argv[1] if len(argv) == 2 else None
    paths = changed_paths(
        argument if argument != "--cached" else None,
        cached=argument == "--cached",
    )
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    failures = missing_doc_updates(paths, manifest)
    if failures:
        for route_id, impacted, required_docs in failures:
            print(f"design-doc-impact: ERROR: route {route_id} changed:", file=sys.stderr)
            for path in impacted:
                print(f"  code: {path}", file=sys.stderr)
            print("  update at least one owning design doc:", file=sys.stderr)
            for path in required_docs:
                print(f"  doc:  {path}", file=sys.stderr)
        return 1
    print(f"design-doc-impact: OK ({len(paths)} changed path(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
