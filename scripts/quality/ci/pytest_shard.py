"""Partition files before collection and record complete CI timing evidence.

All shards use the same versioned weights and candidate paths. Selection never
depends on worker-local timing data or on which tests have already been imported.
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

import pytest

_DURATION_WEIGHTS_PATH = Path(__file__).with_name("pytest-shard-durations.json")
_STATE = pytest.StashKey["_ShardState"]()


@dataclass(frozen=True)
class _ShardState:
    count: int
    index: int
    assignments: Mapping[Path, int]


def _positive_int(name: str) -> int:
    raw = os.environ.get(name, "")
    try:
        value = int(raw)
    except ValueError as exc:
        raise pytest.UsageError(f"{name} must be an integer") from exc
    if value < 1:
        raise pytest.UsageError(f"{name} must be >= 1")
    return value


def _load_duration_weights(path: Path) -> tuple[float, dict[Path, float]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise pytest.UsageError(f"cannot load pytest shard durations: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 2:
        raise pytest.UsageError("pytest shard durations must use schema_version 2")

    default = payload.get("default_seconds_per_file")
    files = payload.get("files")
    if (
        not isinstance(default, (int, float))
        or isinstance(default, bool)
        or not math.isfinite(default)
        or default <= 0
    ):
        raise pytest.UsageError("default_seconds_per_file must be a positive finite number")
    if not isinstance(files, dict):
        raise pytest.UsageError("pytest shard duration files must be an object")

    weights: dict[Path, float] = {}
    for raw_path, raw_weight in files.items():
        candidate = Path(raw_path) if isinstance(raw_path, str) else Path()
        if (
            not isinstance(raw_path, str)
            or candidate.is_absolute()
            or ".." in candidate.parts
            or candidate.suffix != ".py"
        ):
            raise pytest.UsageError(f"invalid pytest shard duration path: {raw_path!r}")
        if (
            not isinstance(raw_weight, (int, float))
            or isinstance(raw_weight, bool)
            or not math.isfinite(raw_weight)
            or raw_weight <= 0
        ):
            raise pytest.UsageError(f"invalid pytest shard duration weight: {raw_path}")
        weights[candidate] = float(raw_weight)
    return float(default), weights


def _assign_shards(file_weights: Mapping[Path, float], count: int) -> dict[Path, int]:
    if count < 1:
        raise ValueError("count must be >= 1")
    if any(not math.isfinite(weight) or weight <= 0 for weight in file_weights.values()):
        raise ValueError("file weights must be positive finite numbers")

    loads = [0.0] * count
    assignments: dict[Path, int] = {}
    for path, weight in sorted(
        file_weights.items(),
        key=lambda item: (-item[1], item[0].as_posix()),
    ):
        shard = min(range(count), key=lambda candidate: (loads[candidate], candidate))
        assignments[path] = shard
        loads[shard] += weight
    return assignments


def _candidate_files(
    root: Path,
    arguments: Sequence[str],
    patterns: Sequence[str],
    ignored: Sequence[Path],
    norecursedirs: Sequence[str],
) -> set[Path]:
    files: set[Path] = set()

    def excluded(path: Path) -> bool:
        return any(path == ignore or path.is_relative_to(ignore) for ignore in ignored)

    def fail_discovery(error: OSError) -> None:
        raise error

    for argument in arguments:
        candidate = (root / argument.split("::", 1)[0]).resolve()
        if candidate.is_file():
            files.add(candidate.relative_to(root))
            continue
        if excluded(candidate):
            continue
        for directory, names, filenames in os.walk(candidate, onerror=fail_discovery):
            parent = Path(directory)
            names[:] = [
                name
                for name in names
                if not any(fnmatch(name, pattern) for pattern in norecursedirs)
                and not excluded(parent / name)
            ]
            for name in filenames:
                path = parent / name
                if any(fnmatch(name, pattern) for pattern in patterns) and not excluded(path):
                    files.add(path.resolve().relative_to(root))
    return files


def pytest_configure(config: pytest.Config) -> None:
    count = _positive_int("FDAI_PYTEST_SHARD_COUNT")
    index = _positive_int("FDAI_PYTEST_SHARD_INDEX") - 1
    if index >= count:
        raise pytest.UsageError("FDAI_PYTEST_SHARD_INDEX must not exceed shard count")
    if config.getoption("pyargs"):
        raise pytest.UsageError("pytest file sharding requires filesystem paths, not --pyargs")

    root = config.rootpath.resolve()
    invocation = config.invocation_params.dir
    ignored = [(invocation / path).resolve() for path in config.getoption("ignore") or []]
    arguments = [
        str((invocation / argument.split("::", 1)[0]).resolve()) for argument in config.args
    ]
    candidates = _candidate_files(
        root,
        arguments,
        config.getini("python_files"),
        ignored,
        config.getini("norecursedirs"),
    )
    default_seconds, historical_weights = _load_duration_weights(_DURATION_WEIGHTS_PATH)
    file_weights = {path: historical_weights.get(path, default_seconds) for path in candidates}
    assignments = _assign_shards(file_weights, count)
    config.stash[_STATE] = _ShardState(count, index, assignments)
    report = os.environ.get("FDAI_PYTEST_DURATION_REPORT")
    if report and not hasattr(config, "workerinput"):
        config.pluginmanager.register(_DurationRecorder(Path(report), index + 1, count))


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    if not collection_path.is_file():
        return None
    state = config.stash[_STATE]
    resolved = collection_path.resolve()
    root = config.rootpath.resolve()
    if not resolved.is_relative_to(root):
        return None
    relative = resolved.relative_to(root)
    shard = state.assignments.get(relative)
    return True if shard is not None and shard != state.index else None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    state = config.stash[_STATE]
    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    root = config.rootpath.resolve()
    for item in items:
        path = item.path.resolve().relative_to(root)
        if path not in state.assignments:
            raise pytest.UsageError(f"collected file is missing from the shard inventory: {path}")
        # Pytest deliberately bypasses ignore hooks for explicitly named files.
        target = selected if state.assignments[path] == state.index else deselected
        target.append(item)
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected


class _DurationRecorder:
    def __init__(self, output: Path, index: int, count: int) -> None:
        self.output = output
        self.index = index
        self.count = count
        self.files: dict[str, float] = defaultdict(float)

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        path = report.nodeid.split("::", 1)[0]
        self.files[path] += report.duration

    def pytest_sessionfinish(self, exitstatus: int) -> None:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "mode": os.environ.get("FDAI_PYTEST_MODE", "all"),
                    "shard_index": self.index,
                    "shard_count": self.count,
                    "source_revision": os.environ.get("GITHUB_SHA"),
                    "exit_status": int(exitstatus),
                    "files": {path: round(value, 6) for path, value in sorted(self.files.items())},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
