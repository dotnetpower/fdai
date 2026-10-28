"""Select a deterministic file-level pytest shard for CI."""

from __future__ import annotations

import json
import math
import os
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

import pytest

_DURATION_WEIGHTS_PATH = Path(__file__).with_name("pytest-shard-durations.json")


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
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise pytest.UsageError("pytest shard durations must use schema_version 1")

    default = payload.get("default_seconds_per_test")
    files = payload.get("files")
    if (
        not isinstance(default, (int, float))
        or isinstance(default, bool)
        or not math.isfinite(default)
        or default <= 0
    ):
        raise pytest.UsageError("default_seconds_per_test must be a positive finite number")
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


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    count = _positive_int("FDAI_PYTEST_SHARD_COUNT")
    index = _positive_int("FDAI_PYTEST_SHARD_INDEX") - 1
    if index >= count:
        raise pytest.UsageError("FDAI_PYTEST_SHARD_INDEX must not exceed shard count")

    selected: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    root = Path(str(config.rootpath))
    item_paths = [Path(str(item.path)).resolve().relative_to(root.resolve()) for item in items]
    item_counts = Counter(item_paths)
    default_seconds, historical_weights = _load_duration_weights(_DURATION_WEIGHTS_PATH)
    file_weights = {
        path: historical_weights.get(path, item_count * default_seconds)
        for path, item_count in item_counts.items()
    }
    assignments = _assign_shards(file_weights, count)
    for item, path in zip(items, item_paths, strict=True):
        target = selected if assignments[path] == index else deselected
        target.append(item)
    config.hook.pytest_deselected(items=deselected)
    items[:] = selected
