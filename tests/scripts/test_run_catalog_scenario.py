"""Regression tests for scripts/catalog/run-catalog-scenario.py."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from fdai.core.chaos.promotion_evidence import (
    ScenarioEvidenceKey,
    ScenarioPromotionEvidence,
    ScenarioPromotionState,
)
from fdai.core.chaos.scenario_catalog import CatalogEntry, catalog_fingerprint
from fdai.delivery.chaos.factories import default_factory

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "catalog" / "run-catalog-scenario.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_catalog_scenario", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_dry_run_builds_every_executable_catalog_entry(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()

    result = asyncio.run(module._dry_run(default_factory()))

    assert result == 0
    output = capsys.readouterr().out
    assert "dry-run: 93/93 entries dispatchable" in output


def test_dry_run_writes_sanitized_fingerprint_bound_summary(tmp_path: Path) -> None:
    module = _load_script()
    summary_path = tmp_path / "summary.json"

    result = asyncio.run(module._dry_run(default_factory(), summary_path))

    assert result == 0
    payload = json.loads(summary_path.read_text())
    outcomes = [entry["outcome"] for entry in payload["entries"]]
    assert payload["evidence_level"] == "dispatchability"
    assert payload["catalog_entry_count"] == 135
    assert outcomes.count("dispatchable") == 93
    assert outcomes.count("skipped_non_executable") == 42


def test_enforce_requires_explicit_confirmation() -> None:
    module = _load_script()

    with pytest.raises(SystemExit, match="requires explicit --confirm-enforce"):
        module.main(["--run", "chaos.chaos-mesh.pod-failure"])


def test_substrate_context_requires_and_returns_approval_ref(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    values = {
        "FDAI_ENFORCE_SUB_ID": "00000000-0000-0000-0000-000000000000",
        "FDAI_ENFORCE_RG": "rg-test",
        "FDAI_ENFORCE_AKS_CONTEXT": "ctx-test",
        "FDAI_ENFORCE_NS": "workloads",
        "FDAI_ENFORCE_CHAOS_NS": "chaos",
        "FDAI_ENFORCE_BACKEND_DEPLOY": "backend",
        "FDAI_ENFORCE_BACKEND_SVC": "backend",
        "FDAI_ENFORCE_BACKEND_LABEL": "app=backend",
        "FDAI_ENFORCE_VM": "vm-test",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("FDAI_ENFORCE_PROMOTION_EVIDENCE", raising=False)

    with pytest.raises(SystemExit, match="FDAI_ENFORCE_PROMOTION_EVIDENCE"):
        module._substrate_context()

    monkeypatch.setenv("FDAI_ENFORCE_PROMOTION_EVIDENCE", "evidence.jsonl")
    assert module._substrate_context()["promotion_evidence_path"] == "evidence.jsonl"


def test_promotion_approval_requires_current_enforce_eligible_record(tmp_path: Path) -> None:
    module = _load_script()
    entry = CatalogEntry(
        id="chaos.test.approved",
        source_path=tmp_path / "scenario.yaml",
        spec={"id": "chaos.test.approved", "version": 1},
    )
    key = ScenarioEvidenceKey(entry.id, 1, catalog_fingerprint([entry]))
    records = [
        ScenarioPromotionEvidence(
            evidence_id="shadow",
            key=key,
            from_state=ScenarioPromotionState.COLLECTED,
            to_state=ScenarioPromotionState.SHADOW_VALIDATED,
            actor_principal="Saga",
            audit_ref="audit:shadow",
            observed_at=module.datetime(2026, 7, 17, tzinfo=module.UTC),
            runner_version="runner/1",
            stop_condition_observed=True,
            rollback_succeeded=True,
            blast_radius_compliant=True,
            detection_latency_ms=100,
            latency_budget_ms=500,
        ),
        ScenarioPromotionEvidence(
            evidence_id="pending",
            key=key,
            from_state=ScenarioPromotionState.SHADOW_VALIDATED,
            to_state=ScenarioPromotionState.APPROVAL_PENDING,
            actor_principal="Mimir",
            audit_ref="audit:pending",
            observed_at=module.datetime(2026, 7, 17, tzinfo=module.UTC),
            runner_version="runner/1",
        ),
        ScenarioPromotionEvidence(
            evidence_id="approved",
            key=key,
            from_state=ScenarioPromotionState.APPROVAL_PENDING,
            to_state=ScenarioPromotionState.ENFORCE_ELIGIBLE,
            actor_principal="Mimir",
            audit_ref="audit:approved",
            observed_at=module.datetime(2026, 7, 17, tzinfo=module.UTC),
            runner_version="runner/1",
            approval_ref="approval:test-run",
            approval_principal="Var",
        ),
    ]
    path = tmp_path / "evidence.jsonl"
    path.write_text("\n".join(json.dumps(record.to_dict()) for record in records) + "\n")

    context = module._with_promotion_approval(
        entry,
        {"promotion_evidence_path": str(path)},
        [entry],
    )

    assert context == {"approval_ref": "approval:test-run"}


def test_build_error_report_retains_approval_ref(tmp_path: Path) -> None:
    module = _load_script()
    entry = CatalogEntry(
        id="chaos.test.build-error",
        source_path=tmp_path / "scenario.yaml",
        spec={
            "id": "chaos.test.build-error",
            "category": "compute",
            "expected_signal": "pod_restart",
            "injector": "test:broken",
        },
    )

    class BrokenFactory:
        def build(self, entry: CatalogEntry, context: dict[str, object]) -> None:
            raise RuntimeError("builder failed")

    payload = asyncio.run(
        module._run_one(
            entry,
            BrokenFactory(),
            {"approval_ref": "approval:test-run"},
            tmp_path,
            1.0,
        )
    )

    assert payload["outcome"] == "build_error"
    assert payload["approval_ref"] == "approval:test-run"
