from __future__ import annotations

import json
from pathlib import Path

import pytest

from fdai_deployment_cli.contracts import canonical_digest
from fdai_deployment_cli.runtime_profile import RuntimeDeploymentProfile
from fdai_deployment_cli.source_teardown import apply_source_teardown, plan_source_teardown

SOURCE_COMMIT = "c" * 40
TARGET = "a" * 64
RUN = "b" * 64
SNAPSHOT = "d" * 64
SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"


class FakeGroups:
    def __init__(self, *, absent: bool = True) -> None:
        self.absent = absent
        self.deleted: list[str] = []

    def delete_group(self, *, subscription_id: str, name: str) -> None:
        assert subscription_id == SUBSCRIPTION
        self.deleted.append(name)

    def group_absent(self, *, subscription_id: str, name: str) -> bool:
        assert subscription_id == SUBSCRIPTION
        return self.absent


@pytest.fixture
def source_run(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    profile = RuntimeDeploymentProfile.create(
        runtime_platform="aks", database_placement="postgres-flex"
    )
    _write_signed(
        tmp_path / "source-intent.json",
        {
            "schema_version": "fdai.source-deployment-intent.v1",
            "source": {
                "schema_version": "fdai.source-deployment-input.v1",
                "provenance": "operator-selected-source",
                "source_commit": SOURCE_COMMIT,
                "source_tree": SOURCE_COMMIT,
                "content_digest": "e" * 64,
                "file_count": 1,
                "release_signature_verified": False,
            },
            "source_input_digest": "f" * 64,
            "runtime_profile": profile.to_mapping(),
            "environment": "dev",
            "region": "eastus",
            "monthly_cost_ceiling": 1000,
        },
    )
    intent = json.loads((tmp_path / "source-intent.json").read_text())
    _write_signed(
        tmp_path / "source-preparation.json",
        {
            "schema_version": "fdai.source-deployment-preparation.v1",
            "state": "prepared",
            "provenance": "operator-selected-source",
            "source_commit": SOURCE_COMMIT,
            "source_input_digest": "f" * 64,
            "source_snapshot_digest": SNAPSHOT,
            "intent_digest": intent["receipt_digest"],
            "runtime_profile_digest": profile.digest,
            "release_signature_verified": False,
            "apply_authorized": False,
            "mutation_performed": False,
            "deployment_ready": False,
            "subscription_ready": False,
        },
    )
    foundation = tmp_path / "foundation"
    plan = foundation / "foundation-plan-attempt-1"
    plan.mkdir(parents=True)
    foundation.chmod(0o700)
    plan.chmod(0o700)
    _write_signed(
        foundation / "source-genesis.json",
        {
            "schema_version": "fdai.source-genesis-preparation.v1",
            "state": "prepared",
            "source_commit": SOURCE_COMMIT,
            "source_input_digest": "f" * 64,
            "target_binding": TARGET,
            "run_binding": RUN,
            "mutation_performed": False,
            "deployment_ready": False,
        },
    )
    _write_signed(
        plan / "foundation-state-handoff-receipt.json",
        {
            "schema_version": "fdai.genesis-foundation-state-handoff-receipt.v1",
            "state": "verified",
            "source_commit": SOURCE_COMMIT,
            "target_binding": TARGET,
            "run_digest": RUN,
            "subscription_id": SUBSCRIPTION,
            "effect_verified": True,
            "runner_attested": True,
            "remote_backend_authority_verified": True,
            "zero_change_verified": True,
            "remote_transient_deleted": True,
            "app_resource_group": {"name": "rg-fdai-dev-eus"},
            "ops": {"resource_group_name": "rg-fdai-ops-eus"},
        },
    )
    handoff = json.loads((plan / "foundation-state-handoff-receipt.json").read_text())
    status = {
        "foundation_report": {
            "foundation_plan": {"plan_ref": "foundation-plan-attempt-1"},
            "state_handoff": {"receipt_digest": handoff["receipt_digest"]},
        }
    }
    status_path = foundation / "status.json"
    status_path.write_text(json.dumps(status), encoding="utf-8")
    status_path.chmod(0o600)
    return tmp_path


def test_teardown_plans_only_proven_owned_groups(source_run: Path) -> None:
    plan = plan_source_teardown(
        work_dir=source_run,
        runtime_profile=RuntimeDeploymentProfile.create(
            runtime_platform="aks", database_placement="postgres-flex"
        ),
        region="eastus",
        monthly_cost_ceiling=1000,
    )

    assert plan.resource_groups == ("rg-fdai-dev-eus", "rg-fdai-ops-eus")
    assert plan.confirmation.startswith("delete ")


def test_teardown_refuses_unproven_foreign_resource_before_delete(source_run: Path) -> None:
    handoff = (
        source_run / "foundation/foundation-plan-attempt-1/foundation-state-handoff-receipt.json"
    )
    data = json.loads(handoff.read_text())
    data["app_resource_group"]["name"] = "foreign"
    data["receipt_digest"] = canonical_digest(
        {k: v for k, v in data.items() if k != "receipt_digest"}
    )
    handoff.write_text(json.dumps(data), encoding="utf-8")
    handoff.chmod(0o600)
    status = source_run / "foundation/status.json"
    status_data = json.loads(status.read_text())
    status_data["foundation_report"]["state_handoff"]["receipt_digest"] = data["receipt_digest"]
    status.write_text(json.dumps(status_data), encoding="utf-8")
    status.chmod(0o600)
    client = FakeGroups()

    with pytest.raises(ValueError, match="name is invalid"):
        apply_source_teardown(
            work_dir=source_run,
            runtime_profile=RuntimeDeploymentProfile.create(
                runtime_platform="aks", database_placement="postgres-flex"
            ),
            region="eastus",
            monthly_cost_ceiling=1000,
            confirmation="delete anything",
            client=client,
        )

    assert client.deleted == []


def test_teardown_requires_typed_confirmation(source_run: Path) -> None:
    client = FakeGroups()

    result = apply_source_teardown(
        work_dir=source_run,
        runtime_profile=RuntimeDeploymentProfile.create(
            runtime_platform="aks", database_placement="postgres-flex"
        ),
        region="eastus",
        monthly_cost_ceiling=1000,
        confirmation=None,
        client=client,
    )

    assert result["state"] == "review"
    assert result["reason_code"] == "source_teardown_confirmation_required"
    assert client.deleted == []


def test_teardown_reads_back_partial_failure(source_run: Path) -> None:
    plan = plan_source_teardown(
        work_dir=source_run,
        runtime_profile=RuntimeDeploymentProfile.create(
            runtime_platform="aks", database_placement="postgres-flex"
        ),
        region="eastus",
        monthly_cost_ceiling=1000,
    )
    client = FakeGroups(absent=False)

    result = apply_source_teardown(
        work_dir=source_run,
        runtime_profile=RuntimeDeploymentProfile.create(
            runtime_platform="aks", database_placement="postgres-flex"
        ),
        region="eastus",
        monthly_cost_ceiling=1000,
        confirmation=plan.confirmation,
        client=client,
    )

    assert result["state"] == "partial-failure"
    assert client.deleted == ["rg-fdai-dev-eus", "rg-fdai-ops-eus"]
    assert result["absent"] == {"rg-fdai-dev-eus": False, "rg-fdai-ops-eus": False}


def test_teardown_writes_verified_receipt_after_absence(source_run: Path) -> None:
    plan = plan_source_teardown(
        work_dir=source_run,
        runtime_profile=RuntimeDeploymentProfile.create(
            runtime_platform="aks", database_placement="postgres-flex"
        ),
        region="eastus",
        monthly_cost_ceiling=1000,
    )
    result = apply_source_teardown(
        work_dir=source_run,
        runtime_profile=RuntimeDeploymentProfile.create(
            runtime_platform="aks", database_placement="postgres-flex"
        ),
        region="eastus",
        monthly_cost_ceiling=1000,
        confirmation=plan.confirmation,
        client=FakeGroups(),
    )

    assert result["state"] == "torn-down"
    assert (source_run / "source-teardown-receipt.json").is_file()


def _write_signed(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["receipt_digest"] = canonical_digest(payload)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)
