"""Tests for deterministic OHL evidence bundle assembly."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/quality/repository/build-ohl-scale-out-evidence-bundle.py"
CONTRACT = json.loads((ROOT / "config/ohl-scale-out-evidence.json").read_text())


@pytest.fixture(scope="module")
def builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_ohl_scale_out_bundle", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _receipts() -> list[dict[str, str]]:
    return [
        {"kind": kind, "provenance_digest": _digest(kind)}
        for kind in CONTRACT["evidence"]["required_receipts"]
    ]


def _build(builder: ModuleType, receipts: list[dict[str, str]]) -> dict[str, object]:
    return builder.build_bundle(
        CONTRACT,
        receipts,
        [{"sample_id": "sample-001"}],
        campaign_id="campaign-1",
        correlation_id="correlation-1",
        target_revision="revision-1",
        started_at="2026-01-01T00:00:00Z",
        recurrence_observed_at="2026-01-15T00:00:00Z",
    )


def test_builds_exact_condition_receipt_mapping(builder: ModuleType) -> None:
    bundle = _build(builder, _receipts())

    expected = {
        condition: _digest(kind)
        for condition, kind in CONTRACT["evidence"]["condition_receipt_kinds"].items()
    }
    assert bundle["condition_receipts"] == expected
    assert [receipt["kind"] for receipt in bundle["receipts"]] == sorted(
        CONTRACT["evidence"]["required_receipts"]
    )


def test_rejects_missing_receipt_kind(builder: ModuleType) -> None:
    with pytest.raises(ValueError, match="missing: approval"):
        _build(
            builder,
            [receipt for receipt in _receipts() if receipt["kind"] != "approval"],
        )


def test_rejects_duplicate_receipt_kind(builder: ModuleType) -> None:
    receipts = _receipts()
    receipts.append(receipts[0])

    with pytest.raises(ValueError, match="duplicate kind"):
        _build(builder, receipts)


def test_rejects_unknown_condition_receipt_kind(builder: ModuleType) -> None:
    manifest = deepcopy(CONTRACT)
    manifest["evidence"]["condition_receipt_kinds"]["cleanup_verified"] = "unknown-receipt"

    with pytest.raises(ValueError, match="MUST reference required receipt kinds"):
        builder.build_bundle(
            manifest,
            _receipts(),
            [],
            campaign_id="campaign-1",
            correlation_id="correlation-1",
            target_revision="revision-1",
            started_at="2026-01-01T00:00:00Z",
            recurrence_observed_at="2026-01-15T00:00:00Z",
        )


def test_cli_writes_canonical_bundle_once(builder: ModuleType, tmp_path: Path) -> None:
    receipts_directory = tmp_path / "receipts"
    receipts_directory.mkdir()
    for receipt in _receipts():
        (receipts_directory / f"{receipt['kind']}.json").write_text(json.dumps(receipt))
    samples = tmp_path / "samples.json"
    samples.write_text('[{"sample_id":"sample-001"}]')
    output = tmp_path / "bundle.json"
    argv = [
        str(ROOT / "config/ohl-scale-out-evidence.json"),
        str(receipts_directory),
        str(samples),
        str(output),
        "--campaign-id",
        "campaign-1",
        "--correlation-id",
        "correlation-1",
        "--target-revision",
        "revision-1",
        "--started-at",
        "2026-01-01T00:00:00Z",
        "--recurrence-observed-at",
        "2026-01-15T00:00:00Z",
    ]

    assert builder.main(argv) == 0
    assert output.read_bytes().endswith(b"\n")
    assert builder.main(argv) == 1
