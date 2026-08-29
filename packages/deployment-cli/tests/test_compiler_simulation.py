from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fdai_deployment_cli.compiler import compile_manifest
from fdai_deployment_cli.contracts import ApprovalClass, ProvisionProfile
from fdai_deployment_cli.simulation import rehearse
from fdai_deployment_cli.state import RunState


def _profile() -> ProvisionProfile:
    return ProvisionProfile(
        environment="dev",
        region="koreacentral",
        connectivity="online",
        host="managed-vm",
        transport="github-actions",
        access_method="github_actions",
        shadow_only=True,
        approval_quorum=2,
        monthly_cost_ceiling=500,
    )


def test_compiler_emits_finite_ordered_manifest() -> None:
    manifest = compile_manifest(_profile(), source_commit="a" * 40)

    assert len(manifest.entries) == 11
    assert manifest.entries[0].prerequisites == ()
    assert manifest.entries[-1].prerequisites == ("initial-inventory",)
    assert any(entry.approval_class is ApprovalClass.HIGH_IMPACT for entry in manifest.entries)
    assert len({entry.idempotency_key for entry in manifest.entries}) == len(manifest.entries)


def test_simulation_interrupts_and_resumes_without_duplicate_stage(tmp_path: Path) -> None:
    manifest = compile_manifest(_profile(), source_commit="a" * 40)
    journal = tmp_path / "runs" / "run.jsonl"
    start = datetime(2026, 8, 29, tzinfo=UTC)

    first = rehearse(
        manifest,
        run_id="run.simulation",
        journal=journal,
        interrupt_after="database",
        started_at=start,
    )
    assert first[-1].stage == "database"
    assert first[-1].state is RunState.VERIFYING

    final = rehearse(
        manifest,
        run_id="run.simulation",
        journal=journal,
        started_at=start,
    )
    assert final[-1].state is RunState.READY
    assert [event.stage for event in final].count("database") == 1


def test_ready_simulation_is_idempotent(tmp_path: Path) -> None:
    manifest = compile_manifest(_profile(), source_commit="a" * 40)
    journal = tmp_path / "runs" / "run.jsonl"
    events = rehearse(
        manifest,
        run_id="run.simulation",
        journal=journal,
        started_at=datetime(2026, 8, 29, tzinfo=UTC),
    )

    assert rehearse(manifest, run_id="run.simulation", journal=journal) == events
