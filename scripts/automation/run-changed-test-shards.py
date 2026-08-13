#!/usr/bin/env python3
"""Run changed pytest targets in checkpointed deterministic file shards."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ShardResult:
    """One deterministic pytest shard result."""

    index: int
    status: int
    duration_seconds: float
    cached: bool


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name in {"RUNTIME_ENV", "DATABASE_URL", "POSTGRES_URL", "AZURE_CONFIG_DIR"}:
            environment.pop(name, None)
        elif name.startswith("FDAI_"):
            environment.pop(name, None)
    return environment


def _command_digest(command: list[str], environment: dict[str, str]) -> str:
    digest = hashlib.sha256()
    digest.update(json.dumps(command, separators=(",", ":")).encode())
    for name in ("PYTHONPATH", "FDAI_PYTEST_SHARD_COUNT", "FDAI_PYTEST_SHARD_INDEX"):
        digest.update(name.encode())
        digest.update(environment.get(name, "").encode())
    return digest.hexdigest()


def _run_shard(
    *,
    index: int,
    count: int,
    tests: list[str],
    cache_root: Path,
    result_root: Path,
    environment: dict[str, str],
) -> tuple[ShardResult, str]:
    cache_dir = cache_root / f"shard-{index}"
    command = [
        "uv",
        "run",
        "pytest",
        "-q",
        "-m",
        "not integration",
        "--no-cov",
        "--durations=25",
        "-o",
        f"cache_dir={cache_dir}",
    ]
    shard_environment = environment.copy()
    if count > 1:
        command.extend(("-p", "scripts.quality.ci.pytest_shard"))
        shard_environment["FDAI_PYTEST_SHARD_COUNT"] = str(count)
        shard_environment["FDAI_PYTEST_SHARD_INDEX"] = str(index)
    command.extend(tests)
    command_digest = _command_digest(command, shard_environment)
    marker = result_root / f"shard-{index}.pass"
    try:
        if marker.read_text(encoding="utf-8").strip() == command_digest:
            return ShardResult(index, 0, 0.0, True), ""
    except OSError:
        pass

    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=Path.cwd(),
        env=shard_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    duration = round(time.monotonic() - started, 3)
    if completed.returncode in {0, 5}:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(command_digest + "\n", encoding="utf-8")
    output = completed.stdout + completed.stderr
    return ShardResult(index, completed.returncode, duration, False), output


def _run_integration(
    *,
    tests: list[str],
    cache_root: Path,
    environment: dict[str, str],
    database_url: str,
) -> tuple[int, str]:
    if not database_url:
        return 2, "changed-test-shards: FDAI_DATABASE_URL is required for integration tests\n"
    integration_environment = environment | {"FDAI_DATABASE_URL": database_url}
    completed = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "-q",
            "-m",
            "integration",
            "--no-cov",
            "--durations=25",
            "-o",
            f"cache_dir={cache_root / 'integration'}",
            *tests,
        ],
        cwd=Path.cwd(),
        env=integration_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout + completed.stderr


def _collect_integration(
    *, tests: list[str], cache_root: Path, environment: dict[str, str]
) -> tuple[int, str]:
    completed = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "--collect-only",
            "-q",
            "-m",
            "integration",
            "--no-cov",
            "-o",
            f"cache_dir={cache_root / 'integration-collect'}",
            *tests,
        ],
        cwd=Path.cwd(),
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout + completed.stderr


def run(
    *,
    tests: list[str],
    shard_count: int,
    cache_root: Path,
    result_root: Path,
    integration: bool,
) -> int:
    """Run all non-integration shards and optional integration tests."""
    environment = _clean_environment()
    database_url = os.environ.get("FDAI_DATABASE_URL", "")
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=shard_count) as executor:
        futures = [
            executor.submit(
                _run_shard,
                index=index,
                count=shard_count,
                tests=tests,
                cache_root=cache_root,
                result_root=result_root,
                environment=environment,
            )
            for index in range(1, shard_count + 1)
        ]
        completed = [future.result() for future in futures]
    results = [item[0] for item in completed]
    for result, output in completed:
        print(
            "changed-test-shards: "
            f"shard={result.index}/{shard_count} status={result.status} "
            f"duration={result.duration_seconds:.3f}s cached={str(result.cached).lower()}"
        )
        if output:
            print(output, end="" if output.endswith("\n") else "\n")

    failed = next((result.status for result in results if result.status not in {0, 5}), 0)
    integration_status: int | None = None
    if failed == 0 and integration:
        integration_status, output = _run_integration(
            tests=tests,
            cache_root=cache_root,
            environment=environment,
            database_url=database_url,
        )
        if output:
            print(output, end="" if output.endswith("\n") else "\n")
        if integration_status not in {0, 5}:
            failed = integration_status
    elif failed == 0 and all(result.status == 5 for result in results):
        integration_status, output = _collect_integration(
            tests=tests,
            cache_root=cache_root,
            environment=environment,
        )
        if output:
            print(output, end="" if output.endswith("\n") else "\n")
        if integration_status == 5:
            failed = 5
        elif integration_status != 0:
            failed = integration_status

    summary = {
        "duration_seconds": round(time.monotonic() - started, 3),
        "integration_status": integration_status,
        "shard_count": shard_count,
        "shards": [asdict(result) for result in results],
        "status": failed,
    }
    _atomic_json(result_root / "summary.json", summary)
    if failed == 0 and not integration:
        print(
            "changed-test-shards: integration tests skipped; set "
            "FDAI_CHANGED_TEST_INTEGRATION=1 with a dedicated validation "
            "FDAI_DATABASE_URL to run them",
            file=sys.stderr,
        )
    return failed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--integration", choices=("0", "1"), required=True)
    parser.add_argument("tests", nargs="+")
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    if arguments.shard_count < 1 or arguments.shard_count > 4:
        print("changed-test-shards: shard count must be between 1 and 4", file=sys.stderr)
        return 2
    return run(
        tests=arguments.tests,
        shard_count=arguments.shard_count,
        cache_root=arguments.cache_root,
        result_root=arguments.result_root,
        integration=arguments.integration == "1",
    )


if __name__ == "__main__":
    raise SystemExit(main())
