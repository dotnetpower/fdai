#!/usr/bin/env python3
"""Run changed pytest targets in checkpointed deterministic file shards."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.automation.local_validation_inputs import (  # noqa: E402
    dependency_digest,
    digest,
    git,
    installed_digest,
)


@dataclass(frozen=True)
class ShardResult:
    """One deterministic pytest shard result."""

    index: int
    status: int
    duration_seconds: float
    cached: bool


def _workspace_file_digest(root: Path, relative: str) -> str:
    path = root / relative
    if not path.exists() and not path.is_symlink():
        raise ValueError(f"validation input is missing: {relative}")
    if path.is_symlink():
        value: object = {"kind": "symlink", "target": os.readlink(path)}
    elif path.is_file():
        value = {
            "kind": "file",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    else:
        raise ValueError(f"validation input is not a regular file: {relative}")
    return digest(value)


def _tracked_python_sources(root: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for raw_path in git(root, "ls-files", "-z", "--", "*.py").split(b"\0"):
        if not raw_path:
            continue
        relative = os.fsdecode(raw_path)
        files[relative] = _workspace_file_digest(root, relative)
    if not files:
        raise ValueError("tracked Python source tree is empty")
    return files


def _selected_test_files(root: Path, tests: list[str]) -> dict[str, str]:
    selected: dict[str, str] = {}
    for item in tests:
        relative = item.split("::", 1)[0]
        path = root / relative
        if path.is_dir():
            for raw_path in git(root, "ls-files", "-z", "--", relative).split(b"\0"):
                if raw_path:
                    nested = os.fsdecode(raw_path)
                    selected[nested] = _workspace_file_digest(root, nested)
        else:
            selected[relative] = _workspace_file_digest(root, relative)
    if not selected:
        raise ValueError("selected test inputs are empty")
    return selected


def _workspace_identity(root: Path, tests: list[str]) -> str:
    dependency_inputs = {
        relative: _workspace_file_digest(root, relative)
        for relative in ("pyproject.toml", "uv.lock")
    }
    return digest(
        {
            "schema_version": 1,
            "scope": "changed-test-shard-workspace",
            "selected_tests": _selected_test_files(root, tests),
            "python_sources": _tracked_python_sources(root),
            "dependency": dependency_digest(dependency_inputs),
            "installed": installed_digest(root / ".venv"),
        }
    )


def _try_workspace_identity(root: Path, tests: list[str]) -> str | None:
    try:
        return _workspace_identity(root, tests)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        detail = str(error).strip() or "no details"
        print(
            "changed-test-shards: cache=unavailable "
            f"reason={type(error).__name__}: {detail}; shard will run",
            file=sys.stderr,
        )
        return None


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
    return digest(
        {
            "command": command,
            "environment": {
                name: environment.get(name, "")
                for name in ("PYTHONPATH", "FDAI_PYTEST_SHARD_COUNT", "FDAI_PYTEST_SHARD_INDEX")
            },
        }
    )


def _shard_basetemp(cache_root: Path, index: int) -> Path:
    """Place one deterministic shard temp root outside the repository ancestry."""

    identity = hashlib.sha256(str(cache_root.resolve()).encode()).hexdigest()[:16]
    return Path(tempfile.gettempdir()) / "fdai-pytest-shards" / identity / f"shard-{index}"


def _run_shard(
    *,
    index: int,
    count: int,
    tests: list[str],
    cache_root: Path,
    result_root: Path,
    environment: dict[str, str],
    workspace_identity: str | None = None,
) -> tuple[ShardResult, str]:
    cache_dir = cache_root / f"shard-{index}"
    basetemp = _shard_basetemp(cache_root, index)
    command = [
        "uv",
        "run",
        "--extra",
        "dev",
        "pytest",
        "-q",
        "-m",
        "not integration",
        "--no-cov",
        "--durations=25",
        "-o",
        f"cache_dir={cache_dir}",
        f"--basetemp={basetemp}",
    ]
    shard_environment = environment.copy()
    if count > 1:
        command.extend(("-p", "scripts.quality.ci.pytest_shard"))
        shard_environment["FDAI_PYTEST_SHARD_COUNT"] = str(count)
        shard_environment["FDAI_PYTEST_SHARD_INDEX"] = str(index)
    command.extend(tests)
    command_digest = _command_digest(command, shard_environment)
    shard_identity = (
        digest(
            {
                "schema_version": 1,
                "scope": "changed-test-shard-pass",
                "workspace": workspace_identity,
                "command": command_digest,
                "shard_index": index,
                "shard_count": count,
            }
        )
        if workspace_identity is not None
        else None
    )
    marker = result_root / f"shard-{index}.pass"
    try:
        if (
            shard_identity is not None
            and marker.read_text(encoding="utf-8").strip() == shard_identity
        ):
            return ShardResult(index, 0, 0.0, True), ""
    except OSError:
        pass

    shutil.rmtree(basetemp, ignore_errors=True)
    basetemp.parent.mkdir(parents=True, exist_ok=True)
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
    if completed.returncode in {0, 5} and shard_identity is not None:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(shard_identity + "\n", encoding="utf-8")
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
            "--extra",
            "dev",
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
            "--extra",
            "dev",
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
    workspace_identity = _try_workspace_identity(Path.cwd(), tests)
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
                workspace_identity=workspace_identity,
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
