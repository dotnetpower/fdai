"""Single-invocation Genesis supervisor regressions."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = ROOT / "scripts/deployment/azure"
sys.path.insert(0, str(SCRIPT_DIR))

import genesis_supervisor  # noqa: E402
from genesis_prepare import PreparedGenesis  # noqa: E402

SOURCE = "a" * 40


def test_supervisor_composes_foundation_images_repository_and_application(
    tmp_path: Path, monkeypatch
) -> None:
    tmp_path.chmod(0o700)
    prepared = PreparedGenesis(
        root=tmp_path,
        stage=tmp_path / "stage",
        profile=tmp_path / "profile.json",
        variables=tmp_path / "variables.json",
        ssh_private_key=tmp_path / "runner_ed25519",
        source_commit=SOURCE,
        target_binding="b" * 64,
        run_binding="c" * 64,
        kit_manifest_digest="d" * 64,
    )
    calls = []
    monkeypatch.setattr(
        genesis_supervisor,
        "_preflight",
        lambda **_: (SOURCE, "subscription", "tenant"),
    )
    monkeypatch.setattr(genesis_supervisor, "prepare_genesis", lambda **_: prepared)
    monkeypatch.setattr(genesis_supervisor, "current_actor_digest", lambda _: "e" * 64)
    monkeypatch.setattr(
        genesis_supervisor,
        "_run_foundation_loop",
        lambda **_: {"run_id": "run-1", "state": "waiting"},
    )
    monkeypatch.setattr(
        genesis_supervisor,
        "_configure_entra",
        lambda **_: {"ENTRA_CONSOLE_API_SCOPE": "api://example/access"},
    )

    def supply_chain(**kwargs):
        calls.append(("supply-chain", kwargs))

    monkeypatch.setattr(genesis_supervisor, "ensure_container_supply_chain", supply_chain)
    monkeypatch.setattr(
        genesis_supervisor,
        "resolve_exact_images",
        lambda *_: {"fdai-core-control-plane": "exact"},
    )

    def configure(**kwargs):
        calls.append(("repository-config", kwargs))
        return {"receipt_digest": "f" * 64}

    monkeypatch.setattr(genesis_supervisor, "_configure_repository", configure)
    monkeypatch.setattr(
        genesis_supervisor,
        "run_application",
        lambda _: {"receipt_digest": "1" * 64},
    )

    receipt = genesis_supervisor.supervise(
        repository_root=ROOT,
        repository="example/fdai",
        region="koreacentral",
        monthly_cost_ceiling=1000,
        work_dir=tmp_path,
        timeout_seconds=1800,
    )

    assert [item[0] for item in calls] == ["supply-chain", "repository-config"]
    assert receipt["application_converged"] is True
    assert receipt["active_inventory_generation_verified"] is False
    assert receipt["subscription_ready"] is False
    assert (tmp_path / "terminal-receipt.json").stat().st_mode & 0o777 == 0o600


def test_foundation_checkpoint_reducer_accepts_only_current_exact_evidence() -> None:
    status = {
        "current_stage": "foundation-state",
        "foundation_report": {
            "foundation_apply": {"receipt_digest": "a" * 64},
            "runner_enrollment": {"receipt_digest": "b" * 64},
        },
    }

    stage, evidence = genesis_supervisor._approval_from_status(status)

    assert stage == "foundation-state"
    assert evidence == {
        "foundation_receipt_digest": "a" * 64,
        "enrollment_receipt_digest": "b" * 64,
    }
