from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts/deployment/service/manual_operator_update.py"
)
_SUBSCRIPTION = "00000000-0000-0000-0000-000000000001"
_TENANT = "00000000-0000-0000-0000-000000000002"
_CLIENT = "00000000-0000-0000-0000-000000000003"
_PRINCIPAL = "00000000-0000-0000-0000-000000000004"


@pytest.fixture
def update(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    service_dir = str(_SCRIPT.parent)
    monkeypatch.syspath_prepend(service_dir)
    spec = importlib.util.spec_from_file_location("manual_operator_update", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_approval_binds_exact_review_to_active_human(
    tmp_path: Path, update: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target.json"
    review = tmp_path / "review.json"
    output = tmp_path / "approval.json"
    _private_json(target, _target())
    review_value = _review(update, _target())
    _private_json(review, review_value)

    def identity(command: tuple[str, ...], **_kwargs: object) -> dict[str, str]:
        if command[:3] == ("az", "account", "show"):
            return {
                "subscription_id": _SUBSCRIPTION,
                "tenant_id": _TENANT,
                "user_type": "user",
            }
        return {"object_id": "00000000-0000-0000-0000-000000000005"}

    monkeypatch.setattr(update, "_json_command", identity)

    result = update.approve(target_path=target, review_path=review, output=output)

    assert result["review_digest"] == review_value["review_digest"]
    assert result["plan_digest"] == "b" * 64
    assert result["actor_digest"] != update._executor_digest(_target())
    assert output.stat().st_mode & 0o777 == 0o600


def test_approval_rejects_service_principal(
    tmp_path: Path, update: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target.json"
    review = tmp_path / "review.json"
    _private_json(target, _target())
    _private_json(review, _review(update, _target()))
    monkeypatch.setattr(
        update,
        "_json_command",
        lambda *_args, **_kwargs: {
            "subscription_id": _SUBSCRIPTION,
            "tenant_id": _TENANT,
            "user_name": _CLIENT,
            "user_type": "servicePrincipal",
        },
    )

    with pytest.raises(update.ManualOperatorUpdateError, match="active Azure human"):
        update.approve(target_path=target, review_path=review, output=tmp_path / "approval.json")


def test_review_rejects_content_changed_after_digest(tmp_path: Path, update: ModuleType) -> None:
    review = _review(update, _target())
    review["image_ref"] = "ghcr.io/dotnetpower/fdai/fdai-operator-service@sha256:" + "f" * 64
    path = tmp_path / "review.json"
    _private_json(path, review)

    with pytest.raises(update.ManualOperatorUpdateError, match="review digest"):
        update._review(path)


def test_planned_target_rejects_unrelated_resource(update: ModuleType) -> None:
    plan = {"resource_changes": [{"address": "azurerm_resource_group.unrelated", "change": {}}]}

    with pytest.raises(update.ManualOperatorUpdateError, match="exactly one target"):
        update._planned_target(plan, "candidate", _SUBSCRIPTION)


def test_maps_shared_platform_outputs_to_service_contract(update: ModuleType) -> None:
    outputs = {
        "resource_group_name": "rg-example",
        "container_app_environment_id": "environment-id",
        "container_registry_login_server": "example.azurecr.io",
        "event_bus_kafka_bootstrap": "example.servicebus.windows.net:9093",
        "cost_pseudonym_key_secret_id": "secret-id",
    }

    assert update._platform_binding(outputs) == {
        "resource_group_name": "rg-example",
        "container_app_environment_id": "environment-id",
        "acr_login_server": "example.azurecr.io",
        "kafka_bootstrap_servers": "example.servicebus.windows.net:9093",
        "cost_pseudonym_key_secret_id": "secret-id",
    }


def test_normalizes_exact_cost_pseudonym_adoption(update: ModuleType) -> None:
    plan, secret_id = _cost_adoption_plan()

    normalized = update._normalize_cost_pseudonym_adoption(plan, expected_secret_id=secret_id)

    after = normalized["resource_changes"][0]["change"]["after"]
    assert [item["name"] for item in after["secret"]] == ["database-dsn"]
    assert [item["name"] for item in after["template"][0]["container"][0]["env"]] == [
        "FDAI_DATABASE_URL"
    ]


def test_rejects_unreviewed_cost_secret_binding(update: ModuleType) -> None:
    plan, _secret_id = _cost_adoption_plan()

    with pytest.raises(update.ManualOperatorUpdateError, match="secret binding is invalid"):
        update._normalize_cost_pseudonym_adoption(
            plan,
            expected_secret_id="https://kv-example.vault.azure.net/secrets/another-key",
        )


def test_rejects_extra_environment_with_cost_adoption(update: ModuleType) -> None:
    plan, secret_id = _cost_adoption_plan()
    after = plan["resource_changes"][0]["change"]["after"]
    after["template"][0]["container"][0]["env"].append({"name": "UNRELATED", "value": "drift"})

    with pytest.raises(update.ManualOperatorUpdateError, match="environment adoption is invalid"):
        update._normalize_cost_pseudonym_adoption(plan, expected_secret_id=secret_id)


def test_image_attestation_rejects_another_candidate(tmp_path: Path, update: ModuleType) -> None:
    image = "ghcr.io/dotnetpower/fdai/fdai-operator-service@sha256:" + "d" * 64
    receipt: dict[str, object] = {
        "schema_version": "fdai.manual-operator-image-attestation.v1",
        "repository": "dotnetpower/fdai",
        "image_ref": image,
        "source_commit": "c" * 40,
        "predicate_type": "https://slsa.dev/provenance/v1",
        "signer_workflow": "dotnetpower/fdai/.github/workflows/container-supply-chain.yml",
        "verified_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - Python 3.10 host
        "mutation_performed": False,
    }
    receipt["attestation_digest"] = update._canonical_digest(receipt)
    path = tmp_path / "attestation.json"
    _private_json(path, receipt)

    with pytest.raises(update.ManualOperatorUpdateError, match="attestation is invalid"):
        update._image_attestation(path, image[:-1] + "e", "c" * 40)


def test_manual_identity_login_rejects_github_actions(
    tmp_path: Path, update: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    with pytest.raises(update.ManualOperatorUpdateError, match="cannot run inside GitHub Actions"):
        update._login_identity(tmp_path, _target())


def test_apply_writes_claim_before_saved_plan(
    tmp_path: Path, update: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, work, approval, review = _apply_files(tmp_path, update)
    calls: list[str] = []
    _mock_apply_preconditions(monkeypatch, update, review)

    def run(command: tuple[str, ...], **_kwargs: object) -> None:
        if "apply" in command:
            assert (work / "claim.json").is_file()
            calls.append("apply")

    monkeypatch.setattr(update, "_run", run)
    monkeypatch.setattr(
        update,
        "_wait_for_image",
        lambda *_args, **_kwargs: _app(
            image=str(review["image_ref"]),
            revision="ca-example-operator-api--candidate",
        ),
    )

    result = update.apply(
        source_root=source,
        work_dir=work,
        approval_path=approval,
    )

    assert calls == ["apply"]
    assert result["state"] == "applied"
    assert result["effect_readback_verified"] is True


def test_apply_failure_restores_reviewed_revision(
    tmp_path: Path, update: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, work, approval, review = _apply_files(tmp_path, update)
    restored: list[str] = []
    _mock_apply_preconditions(monkeypatch, update, review)

    def run(command: tuple[str, ...], **_kwargs: object) -> None:
        if "apply" in command:
            assert (work / "claim.json").is_file()
            raise update.ManualOperatorUpdateError("apply failed")

    def restore(value: dict[str, object], **_kwargs: object) -> None:
        assert (work / "claim.json").is_file()
        restored.append(str(value["previous_revision"]))

    monkeypatch.setattr(update, "_run", run)
    monkeypatch.setattr(update, "_restore_revision", restore)

    with pytest.raises(update.ManualOperatorUpdateError, match="previous revision was restored"):
        update.apply(
            source_root=source,
            work_dir=work,
            approval_path=approval,
        )

    assert restored == [review["previous_revision"]]
    failure = json.loads((work / "failure.json").read_text(encoding="utf-8"))
    assert failure["rollback_verified"] is True


def test_rollback_copies_and_verifies_exact_previous_revision(
    update: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    review = _review(update, _target())
    commands: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        update,
        "_run",
        lambda command, **_kwargs: commands.append(command),
    )
    monkeypatch.setattr(
        update,
        "_read_app",
        lambda _resource_id: _app(
            image=str(review["previous_image"]),
            revision="ca-example-operator-api--rollback",
        ),
    )
    monkeypatch.setattr(
        update,
        "_json_command",
        lambda *_args, **_kwargs: {
            "properties": {
                "template": {"containers": [{"image": review["previous_image"]}]},
                "provisioningState": "Provisioned",
                "healthState": "Healthy",
                "active": True,
            }
        },
    )

    update._restore_revision(review, timeout_seconds=1)

    assert commands[0][:5] == ("az", "containerapp", "revision", "copy", "--resource-group")
    assert commands[0][commands[0].index("--from-revision") + 1] == review["previous_revision"]


def _target() -> dict[str, str]:
    return {
        "schema_version": "fdai.manual-operator-target.v1",
        "environment": "dev",
        "repository": "dotnetpower/fdai",
        "tenant_id": _TENANT,
        "subscription_id": _SUBSCRIPTION,
        "state_resource_group": "rg-example-state",
        "state_storage_account": "exampletfstate",
        "state_container": "tfstate",
        "deploy_identity_client_id": _CLIENT,
        "deploy_identity_principal_id": _PRINCIPAL,
    }


def _review(update: ModuleType, target: dict[str, str]) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "fdai.manual-operator-update-review.v1",
        "source_commit": "a" * 40,
        "image_source_commit": "c" * 40,
        "image_ref": "ghcr.io/dotnetpower/fdai/fdai-operator-service@sha256:" + "d" * 64,
        "target_binding": update._target_binding(target),
        "target": {
            "service_resource_id": (
                f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-example/providers/"
                "Microsoft.App/containerApps/ca-example-operator-api"
            ),
            "resource_group": "rg-example",
            "service_name": "ca-example-operator-api",
        },
        "plan_digest": "b" * 64,
        "plan_json_digest": "e" * 64,
        "previous_revision": "ca-example-operator-api--old",
        "previous_image": "ghcr.io/dotnetpower/fdai/fdai-operator-service@sha256:" + "1" * 64,
        "action": "terraform_apply_saved_operator_plan",
        "stop_condition": "plan_or_target_drift_or_unhealthy_revision",
        "rollback_action": "copy_verified_previous_revision",
        "blast_radius": "one_existing_operator_container_app",
        "idempotency_key": "f" * 64,
        "created_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - Python 3.10 host
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),  # noqa: UP017 - Python 3.10 host
        "mutation_performed": False,
    }
    value["review_digest"] = update._canonical_digest(value)
    return value


def _apply_files(tmp_path: Path, update: ModuleType) -> tuple[Path, Path, Path, dict[str, object]]:
    source = tmp_path / "source"
    source.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    target = _target()
    review = _review(update, target)
    approval_value: dict[str, object] = {
        "schema_version": "fdai.manual-operator-update-approval.v1",
        "review_digest": review["review_digest"],
        "plan_digest": review["plan_digest"],
        "target_binding": review["target_binding"],
        "actor_digest": "9" * 64,
        "approved_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - Python 3.10 host
        "expires_at": review["expires_at"],
    }
    approval_value["approval_digest"] = update._canonical_digest(approval_value)
    approval = tmp_path / "approval.json"
    _private_json(work / "review.json", review)
    _private_json(work / "target.json", target)
    _private_json(
        work / "operator.tfvars.json",
        {
            "cost_pseudonym_key_secret_id": (
                "https://kv-example.vault.azure.net/secrets/fdai-cost-pseudonym-key"
            )
        },
    )
    _private_json(approval, approval_value)
    (work / "operator.tfplan").write_bytes(b"plan")
    (work / "operator-plan.json").write_text("{}", encoding="utf-8")
    return source, work, approval, review


def _mock_apply_preconditions(
    monkeypatch: pytest.MonkeyPatch,
    update: ModuleType,
    review: dict[str, object],
) -> None:
    monkeypatch.setattr(update, "_review", lambda _path: review)
    monkeypatch.setattr(update, "_target", lambda _path: _target())
    monkeypatch.setattr(
        update,
        "_approval",
        lambda _path, _review_value: {
            "actor_digest": "9" * 64,
            "approval_digest": "8" * 64,
        },
    )
    monkeypatch.setattr(update, "_verified_source", lambda _path: review["source_commit"])
    monkeypatch.setattr(update, "_login_identity", lambda *_args: None)
    monkeypatch.setattr(update, "_executor_digest", lambda _target_value: "7" * 64)
    monkeypatch.setattr(
        update,
        "_file_digest",
        lambda path: (
            review["plan_json_digest"] if path.name.endswith(".json") else review["plan_digest"]
        ),
    )
    monkeypatch.setattr(update, "_guard", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(update, "_terraform_init", lambda *_args: None)
    monkeypatch.setattr(
        update,
        "_read_app",
        lambda _resource_id: _app(
            image=str(review["previous_image"]),
            revision=str(review["previous_revision"]),
        ),
    )


def _app(*, image: str, revision: str) -> dict[str, object]:
    return {
        "properties": {
            "latestReadyRevisionName": revision,
            "provisioningState": "Succeeded",
            "template": {"containers": [{"image": image}]},
        }
    }


def _cost_adoption_plan() -> tuple[dict[str, object], str]:
    identity = (
        f"/subscriptions/{_SUBSCRIPTION}/resourceGroups/rg-example/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/id-runtime"
    )
    secret_id = "https://kv-example.vault.azure.net/secrets/fdai-cost-pseudonym-key"
    before = {
        "identity": [{"identity_ids": [identity]}],
        "secret": [{"name": "database-dsn", "identity": identity}],
        "template": [
            {
                "container": [
                    {
                        "env": [
                            {
                                "name": "FDAI_DATABASE_URL",
                                "secret_name": "database-dsn",
                            }
                        ]
                    }
                ]
            }
        ],
    }
    after = json.loads(json.dumps(before))
    after["secret"].append(
        {
            "name": "cost-pseudonym-key",
            "identity": identity,
            "key_vault_secret_id": secret_id,
        }
    )
    after["template"][0]["container"][0]["env"].append(
        {"name": "FDAI_COST_PSEUDONYM_KEY", "secret_name": "cost-pseudonym-key"}
    )
    return (
        {
            "resource_changes": [
                {
                    "address": (
                        "module.operator_service.module.container_app.azurerm_container_app.service"
                    ),
                    "change": {"before": before, "after": after},
                }
            ]
        },
        secret_id,
    )


def _private_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)
