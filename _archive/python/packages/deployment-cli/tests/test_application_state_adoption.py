from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fdai_deployment_cli.application_state_adoption import stage_application_state_adoption

_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
_RESOURCE_GROUP = "rg-fdai-dev-wus2"


def _resource(
    module: str,
    resource_type: str,
    name: str,
    attributes: dict[str, object],
    *,
    index: int | None = None,
) -> dict[str, object]:
    instance: dict[str, object] = {"attributes": attributes, "schema_version": 0}
    if index is not None:
        instance["index_key"] = index
    return {
        "module": module,
        "mode": "managed",
        "type": resource_type,
        "name": name,
        "provider": 'provider["registry.terraform.io/hashicorp/example"]',
        "instances": [instance],
    }


def _inputs(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, object]]:
    tmp_path.chmod(0o700)
    state: dict[str, object] = {
        "version": 4,
        "terraform_version": "1.9.8",
        "serial": 7,
        "lineage": "00000000-0000-0000-0000-000000000002",
        "outputs": {},
        "resources": [
            _resource(
                "module.resource_group",
                "azurerm_resource_group",
                "primary",
                {"id": f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/{_RESOURCE_GROUP}"},
                index=0,
            ),
            _resource(
                "module.resource_group",
                "terraform_data",
                "ownership",
                {"id": "opaque", "input": {"value": "managed", "type": "string"}},
            ),
            _resource(
                "module.container_registry",
                "azurerm_container_registry",
                "primary",
                {"id": "opaque-registry", "name": "crfdaidevwus2ddcc51"},
            ),
            _resource(
                "module.identity",
                "azurerm_user_assigned_identity",
                "primary",
                {"id": "opaque-identity"},
            ),
            {
                "mode": "managed",
                "type": "azurerm_role_assignment",
                "name": "disabled",
                "provider": 'provider["registry.terraform.io/hashicorp/example"]',
                "instances": [],
            },
        ],
    }
    state_path = tmp_path / "terraform.tfstate"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    state_path.chmod(0o600)
    state_digest = hashlib.sha256(state_path.read_bytes()).hexdigest()
    recovery: dict[str, object] = {
        "schema_version": "fdai.contributor-recovery.v1",
        "state": "failed-apply-observed",
        "operational_verification": "observed",
        "state_sha256": state_digest,
        "plan_sha256": "a" * 64,
        "source_commit": "b" * 40,
        "verified_source_commit": "c" * 40,
        "tracked_resource_count": 4,
    }
    recovery_path = tmp_path / "recovery.json"
    recovery_path.write_text(json.dumps(recovery), encoding="utf-8")
    recovery_path.chmod(0o600)
    models_path = tmp_path / "resolved-models.json"
    models_path.write_text(
        json.dumps(
            {
                "capabilities": [
                    {"name": "t1.embedding", "status": "hil-only"},
                    {
                        "name": "t2.reasoner.secondary",
                        "publisher": "MistralAI",
                        "family": "Mistral-Large-3",
                        "version": "1",
                        "sku": "GlobalStandard",
                        "capacity_tpm": 1000,
                        "capacity_unit": "tpm",
                        "capacity_value": 0,
                        "status": "resolved",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    models_path.chmod(0o600)
    return state_path, recovery_path, models_path, state


def test_stages_split_state_and_preserves_original(tmp_path: Path) -> None:
    state_path, recovery_path, models_path, original = _inputs(tmp_path)

    result = stage_application_state_adoption(
        source_state=state_path,
        recovery_receipt=recovery_path,
        resolved_models=models_path,
        output_directory=tmp_path / "adoption",
        subscription_id=_SUBSCRIPTION,
        resource_group_name=_RESOURCE_GROUP,
        environment="dev",
        region_short="wus2",
    )

    assert json.loads(state_path.read_text(encoding="utf-8")) == original
    staged = json.loads(result.state.read_text(encoding="utf-8"))
    assert staged["serial"] == 8
    assert len(staged["resources"]) == 3
    assert result.resource_name_suffix == "ddcc51"
    assert result.managed_resource_count == 2
    descriptor = json.loads(result.descriptor.read_text(encoding="utf-8"))
    assert descriptor["removed_addresses"] == [
        "module.resource_group.terraform_data.ownership",
        "module.resource_group.azurerm_resource_group.primary[0]",
    ]
    assert descriptor["original_state_retained"] is True
    assert descriptor["remote_backend_authority_verified"] is False
    assert descriptor["resolved_capabilities"] == [
        {
            "capacity_tpm": 1000,
            "capacity_unit": "tpm",
            "capacity_value": 0,
            "family": "Mistral-Large-3",
            "name": "t2.reasoner.secondary",
            "publisher": "MistralAI",
            "sku": "GlobalStandard",
            "version": "1",
        }
    ]
    assert all(
        path.stat().st_mode & 0o777 == 0o600
        for path in (result.state, result.resolved_models, result.descriptor)
    )

    resumed = stage_application_state_adoption(
        source_state=state_path,
        recovery_receipt=recovery_path,
        resolved_models=models_path,
        output_directory=tmp_path / "adoption",
        subscription_id=_SUBSCRIPTION,
        resource_group_name=_RESOURCE_GROUP,
        environment="dev",
        region_short="wus2",
    )
    assert resumed == result


@pytest.mark.parametrize("changed_input", ["recovery", "staged-state"])
def test_resume_rejects_changed_input(tmp_path: Path, changed_input: str) -> None:
    state_path, recovery_path, models_path, _original = _inputs(tmp_path)
    output = tmp_path / "adoption"
    result = stage_application_state_adoption(
        source_state=state_path,
        recovery_receipt=recovery_path,
        resolved_models=models_path,
        output_directory=output,
        subscription_id=_SUBSCRIPTION,
        resource_group_name=_RESOURCE_GROUP,
        environment="dev",
        region_short="wus2",
    )
    if changed_input == "recovery":
        recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
        recovery["recorded_at"] = "2026-01-01T00:00:00+00:00"
        recovery_path.write_text(json.dumps(recovery), encoding="utf-8")
    else:
        result.state.write_text(result.state.read_text(encoding="utf-8") + " ", encoding="utf-8")

    with pytest.raises(ValueError, match="retained application state adoption differs"):
        stage_application_state_adoption(
            source_state=state_path,
            recovery_receipt=recovery_path,
            resolved_models=models_path,
            output_directory=output,
            subscription_id=_SUBSCRIPTION,
            resource_group_name=_RESOURCE_GROUP,
            environment="dev",
            region_short="wus2",
        )


def test_rejects_resource_group_region_mismatch(tmp_path: Path) -> None:
    state_path, recovery_path, models_path, _original = _inputs(tmp_path)

    with pytest.raises(ValueError, match="resource group"):
        stage_application_state_adoption(
            source_state=state_path,
            recovery_receipt=recovery_path,
            resolved_models=models_path,
            output_directory=tmp_path / "adoption",
            subscription_id=_SUBSCRIPTION,
            resource_group_name=_RESOURCE_GROUP,
            environment="dev",
            region_short="eus2",
        )


def test_rejects_invalid_resolved_capacity_before_staging(tmp_path: Path) -> None:
    state_path, recovery_path, models_path, _original = _inputs(tmp_path)
    models = json.loads(models_path.read_text(encoding="utf-8"))
    models["capabilities"][1]["capacity_tpm"] = 999
    models_path.write_text(json.dumps(models), encoding="utf-8")

    with pytest.raises(ValueError, match="capability capacity"):
        stage_application_state_adoption(
            source_state=state_path,
            recovery_receipt=recovery_path,
            resolved_models=models_path,
            output_directory=tmp_path / "adoption",
            subscription_id=_SUBSCRIPTION,
            resource_group_name=_RESOURCE_GROUP,
            environment="dev",
            region_short="wus2",
        )


def test_accepts_terraform_defaulted_capacity_fields(tmp_path: Path) -> None:
    state_path, recovery_path, models_path, _original = _inputs(tmp_path)
    models = json.loads(models_path.read_text(encoding="utf-8"))
    del models["capabilities"][1]["capacity_unit"]
    del models["capabilities"][1]["capacity_value"]
    models_path.write_text(json.dumps(models), encoding="utf-8")

    result = stage_application_state_adoption(
        source_state=state_path,
        recovery_receipt=recovery_path,
        resolved_models=models_path,
        output_directory=tmp_path / "adoption",
        subscription_id=_SUBSCRIPTION,
        resource_group_name=_RESOURCE_GROUP,
        environment="dev",
        region_short="wus2",
    )

    descriptor = json.loads(result.descriptor.read_text(encoding="utf-8"))
    assert descriptor["resolved_capabilities"][0]["capacity_tpm"] == 1000
    assert "capacity_unit" not in descriptor["resolved_capabilities"][0]
    assert "capacity_value" not in descriptor["resolved_capabilities"][0]


@pytest.mark.parametrize(
    "change",
    ["state", "group", "ownership", "registry", "receipt", "models", "existing-output"],
)
def test_rejects_unverified_adoption_input(tmp_path: Path, change: str) -> None:
    state_path, recovery_path, models_path, _original = _inputs(tmp_path)
    output = tmp_path / "adoption"
    if change == "state":
        state_path.write_text(state_path.read_text() + " ", encoding="utf-8")
    elif change == "group":
        payload = json.loads(state_path.read_text())
        payload["resources"][0]["instances"][0]["attributes"]["id"] += "-other"
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        receipt = json.loads(recovery_path.read_text())
        receipt["state_sha256"] = hashlib.sha256(state_path.read_bytes()).hexdigest()
        recovery_path.write_text(json.dumps(receipt), encoding="utf-8")
    elif change == "ownership":
        payload = json.loads(state_path.read_text())
        payload["resources"][1]["instances"][0]["attributes"]["input"] = {
            "value": "reference",
            "type": "string",
        }
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        receipt = json.loads(recovery_path.read_text())
        receipt["state_sha256"] = hashlib.sha256(state_path.read_bytes()).hexdigest()
        recovery_path.write_text(json.dumps(receipt), encoding="utf-8")
    elif change == "registry":
        payload = json.loads(state_path.read_text())
        payload["resources"][2]["instances"][0]["attributes"]["name"] = "other"
        state_path.write_text(json.dumps(payload), encoding="utf-8")
        receipt = json.loads(recovery_path.read_text())
        receipt["state_sha256"] = hashlib.sha256(state_path.read_bytes()).hexdigest()
        recovery_path.write_text(json.dumps(receipt), encoding="utf-8")
    elif change == "receipt":
        receipt = json.loads(recovery_path.read_text())
        receipt["operational_verification"] = "pending"
        recovery_path.write_text(json.dumps(receipt), encoding="utf-8")
    elif change == "models":
        models_path.write_text('{"capabilities":[]}', encoding="utf-8")
    else:
        output.mkdir()

    with pytest.raises((FileExistsError, PermissionError, ValueError)):
        stage_application_state_adoption(
            source_state=state_path,
            recovery_receipt=recovery_path,
            resolved_models=models_path,
            output_directory=output,
            subscription_id=_SUBSCRIPTION,
            resource_group_name=_RESOURCE_GROUP,
            environment="dev",
            region_short="wus2",
        )
