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


def _build_source_run(tmp_path: Path, *, app_group: str = "rg-fdai-dev-eus") -> Path:
    """Write the records exactly as the source producers do, including the unsigned intent."""
    tmp_path.chmod(0o700)
    profile = RuntimeDeploymentProfile.create(
        runtime_platform="aks", database_placement="postgres-flex"
    )
    intent = {
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
    }
    _write_plain(tmp_path / "source-intent.json", intent)
    _write_signed(
        tmp_path / "source-preparation.json",
        {
            "schema_version": "fdai.source-deployment-preparation.v1",
            "state": "prepared",
            "provenance": "operator-selected-source",
            "source_commit": SOURCE_COMMIT,
            "source_input_digest": "f" * 64,
            "source_snapshot_digest": SNAPSHOT,
            "intent_digest": canonical_digest(intent),
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
    located = {
        "terraform_root": "infra/genesis-foundation",
        "source_commit": SOURCE_COMMIT,
        "run_digest": RUN,
        "subscription_id": SUBSCRIPTION,
        "region": "eastus",
        "app_resource_group": {"name": app_group, "id": f"/x/{app_group}"},
        "ops": {"resource_group_name": "rg-fdai-ops-eus"},
    }
    _write_plain(plan / "foundation-private-handoff.json", located)
    apply = _write_signed(
        plan / "foundation-apply-receipt.json",
        {
            "schema_version": "fdai.genesis-foundation-apply-receipt.v1",
            "state": "applied",
            "source_commit": SOURCE_COMMIT,
            "target_binding": TARGET,
            "handoff_digest": canonical_digest(located),
            "mutation_performed": True,
        },
    )
    handoff = _write_signed(
        plan / "foundation-state-handoff-receipt.json",
        {
            "schema_version": "fdai.genesis-foundation-state-handoff-receipt.v1",
            "state": "verified",
            "source_commit": SOURCE_COMMIT,
            "target_binding": TARGET,
            "foundation_receipt_digest": apply,
            "effect_verified": True,
            "runner_attested": True,
            "remote_backend_authority_verified": True,
            "zero_change_verified": True,
            "remote_transient_deleted": True,
        },
    )
    _write_plain(
        foundation / "status.json",
        {
            "foundation_report": {
                "foundation_plan": {"plan_ref": "foundation-plan-attempt-1"},
                "state_handoff": {"receipt_digest": handoff},
            }
        },
    )
    return tmp_path


@pytest.fixture
def source_run(tmp_path: Path) -> Path:
    return _build_source_run(tmp_path)


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


def test_teardown_refuses_unproven_foreign_resource_before_delete(tmp_path: Path) -> None:
    source_run = _build_source_run(tmp_path, app_group="foreign")
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


@pytest.mark.parametrize(
    "record,field,value,message",
    [
        ("foundation-private-handoff.json", "run_digest", "9" * 64, "location proof"),
        ("foundation-private-handoff.json", "ops", {"resource_group_name": "rg-other"}, "location"),
        ("source-intent.json", "region", "westus3", "intent differs"),
    ],
)
def test_teardown_refuses_records_that_break_the_bound_chain(
    source_run: Path, record, field, value, message
) -> None:
    root = (
        source_run
        if record == "source-intent.json"
        else source_run / "foundation/foundation-plan-attempt-1"
    )
    path = root / record
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    client = FakeGroups()

    with pytest.raises(ValueError, match=message):
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


def _write_plain(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    path.chmod(0o600)


def _write_signed(path: Path, payload: dict[str, object]) -> str:
    payload = dict(payload)
    payload["receipt_digest"] = canonical_digest(payload)
    _write_plain(path, payload)
    return str(payload["receipt_digest"])


@pytest.mark.parametrize(
    "requested,expected", [([], 1000), (["--monthly-cost-ceiling", "1200"], 1200)]
)
def test_cli_teardown_keeps_the_retained_ceiling_by_default(
    tmp_path, monkeypatch, requested, expected
):
    """A run saved under an older default must stay removable without restating it."""
    from fdai_deployment_cli import cli

    work_dir = tmp_path / "work"
    work_dir.mkdir(mode=0o700)
    intent = work_dir / "source-intent.json"
    intent.write_text(json.dumps({"monthly_cost_ceiling": 1000}))
    intent.chmod(0o600)
    seen = []

    def teardown(**kwargs):
        seen.append(kwargs["monthly_cost_ceiling"])
        return {"state": "torn-down"}

    monkeypatch.setattr(cli, "apply_source_teardown", teardown)
    monkeypatch.setattr(cli, "AzureResourceGroupClient", lambda: None)
    code = cli.main(
        [
            "provision",
            "azure",
            "--source",
            str(tmp_path),
            "--teardown",
            "--work-dir",
            str(work_dir),
            "--output",
            "json",
            *requested,
        ]
    )
    assert code == 0
    assert seen == [expected]
