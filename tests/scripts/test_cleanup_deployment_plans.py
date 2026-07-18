"""Bounded selection tests for private deployment-plan blob cleanup."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "deployment"
    / "azure"
    / "cleanup-deployment-plans.py"
)
_NOW = datetime(2026, 7, 17, 10, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def cleanup_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cleanup_deployment_plans", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _row(name: str, *, age_hours: int) -> dict[str, object]:
    modified = (_NOW - timedelta(hours=age_hours)).isoformat().replace("+00:00", "Z")
    return {"name": name, "properties": {"lastModified": modified}}


def test_selects_only_expired_allowlisted_plan_paths(cleanup_module: ModuleType) -> None:
    rows = [
        _row("dev/plan-123-1/terraform.plan", age_hours=25),
        _row("dev/plan-123-1/metadata.json", age_hours=25),
        _row("dev/plan-123-1/apply-claim.json", age_hours=25),
        _row("dev/plan-123-1/apply-receipt.json", age_hours=25),
        _row("dev/plan-123-1/preflight-evidence.json", age_hours=25),
        _row("dev/plan-124-1/terraform.plan", age_hours=1),
        _row("tfstate/fdai-dev.tfstate", age_hours=100),
        _row("dev/unexpected/terraform.plan", age_hours=100),
    ]

    selected = cleanup_module.select_expired_blobs(
        rows,
        now=_NOW,
        retention=timedelta(hours=24),
        max_scan=1001,
        max_delete=1000,
    )

    assert selected == (
        "dev/plan-123-1/apply-claim.json",
        "dev/plan-123-1/apply-receipt.json",
        "dev/plan-123-1/metadata.json",
        "dev/plan-123-1/preflight-evidence.json",
        "dev/plan-123-1/terraform.plan",
    )


def test_scan_cap_fails_closed(cleanup_module: ModuleType) -> None:
    rows = [_row(f"dev/plan-{index + 1}-1/metadata.json", age_hours=25) for index in range(3)]

    with pytest.raises(ValueError, match="max_scan"):
        cleanup_module.select_expired_blobs(
            rows,
            now=_NOW,
            retention=timedelta(hours=24),
            max_scan=3,
            max_delete=1000,
        )


def test_delete_cap_fails_closed(cleanup_module: ModuleType) -> None:
    rows = [_row(f"prod/plan-{index + 1}-1/metadata.json", age_hours=25) for index in range(2)]

    with pytest.raises(ValueError, match="max_delete"):
        cleanup_module.select_expired_blobs(
            rows,
            now=_NOW,
            retention=timedelta(hours=24),
            max_scan=1001,
            max_delete=1,
        )
