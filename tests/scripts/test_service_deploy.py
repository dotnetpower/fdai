"""Protected independent-service deployment contract tests."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts" / "deployment" / "service"
sys.path.insert(0, str(_SCRIPTS))


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def contract() -> ModuleType:
    return _load("service_contract")


@pytest.fixture(scope="module")
def guard() -> ModuleType:
    return _load("guard_plan")


@pytest.fixture(scope="module")
def bundle() -> ModuleType:
    return _load("plan_bundle")


@pytest.fixture(scope="module")
def tfvars() -> ModuleType:
    return _load("materialize_tfvars")


@pytest.fixture(scope="module")
def migration() -> ModuleType:
    return _load("state_migration")


@pytest.fixture(scope="module")
def recovery() -> ModuleType:
    return _load("deployment_recovery")


def _image(service_image: str) -> str:
    return f"ghcr.io/example/fdai/{service_image}@sha256:{'a' * 64}"


def _resource(*, image: str = "old-image") -> dict[str, object]:
    return {
        "id": (
            "/subscriptions/example-subscription/resourceGroups/example/providers/"
            "Microsoft.App/containerApps/example"
        ),
        "name": "example",
        "resource_group_name": "example",
        "container_app_environment_id": (
            "/subscriptions/example-subscription/resourceGroups/example/providers/Microsoft.App/"
            "managedEnvironments/example"
        ),
        "identity": [
            {
                "type": "UserAssigned",
                "identity_ids": [
                    "/subscriptions/example-subscription/resourceGroups/example/providers/"
                    "Microsoft.ManagedIdentity/userAssignedIdentities/runtime"
                ],
            }
        ],
        "registry": [
            {
                "server": "example.azurecr.io",
                "identity": (
                    "/subscriptions/example-subscription/resourceGroups/example/providers/"
                    "Microsoft.ManagedIdentity/userAssignedIdentities/runtime"
                ),
            }
        ],
        "secret": [
            {
                "name": "database-dsn",
                "identity": (
                    "/subscriptions/example-subscription/resourceGroups/example/providers/"
                    "Microsoft.ManagedIdentity/userAssignedIdentities/runtime"
                ),
                "key_vault_secret_id": (
                    "/subscriptions/example/resourceGroups/example/providers/"
                    "Microsoft.KeyVault/vaults/example/secrets/database"
                ),
            }
        ],
        "template": [
            {
                "container": [
                    {
                        "name": "operator-service",
                        "image": image,
                        "command": ["fdai-operator-service"],
                        "args": [],
                        "env": [
                            {"name": "FDAI_DATABASE_URL", "secret_name": "database-dsn"},
                            {"name": "FDAI_DATABASE_ROLE", "value": "fdai_operator"},
                            {"name": "RUNTIME_ENV", "value": "dev"},
                            {"name": "FDAI_MI_CLIENT_ID", "value": "runtime"},
                            {"name": "FDAI_COMMAND_MI_CLIENT_ID", "value": "command"},
                            {"name": "FDAI_KAFKA_BOOTSTRAP_SERVERS", "value": "example"},
                            {"name": "KAFKA_TOPIC_EVENTS", "value": "events"},
                            {"name": "FDAI_ENTRA_TENANT_ID", "value": "tenant"},
                            {"name": "FDAI_API_AUDIENCE", "value": "audience"},
                            {"name": "FDAI_RBAC_READERS_GROUP_ID", "value": "reader"},
                            {
                                "name": "FDAI_RBAC_CONTRIBUTORS_GROUP_ID",
                                "value": "contributor",
                            },
                            {"name": "FDAI_RBAC_APPROVERS_GROUP_ID", "value": "approver"},
                            {"name": "FDAI_RBAC_OWNERS_GROUP_ID", "value": "owner"},
                            {
                                "name": "FDAI_RBAC_BREAK_GLASS_GROUP_ID",
                                "value": "break-glass",
                            },
                            {
                                "name": "FDAI_OPERATOR_API_CORS_ALLOW_ORIGINS",
                                "value": "https://example.com",
                            },
                            {"name": "FDAI_OPERATOR_SERVICE_PORT", "value": "8000"},
                        ],
                    }
                ]
            }
        ],
        "tags": {"fdai:component": "operator-service"},
    }


def _plan(address: str, actions: list[str], *, image: str = "image") -> dict[str, object]:
    before = _resource()
    after = copy.deepcopy(before)
    after["template"][0]["container"][0]["image"] = image  # type: ignore[index]
    return {
        "resource_changes": [
            {
                "address": address,
                "change": {
                    "actions": actions,
                    "before": before,
                    "after": after,
                },
            }
        ]
    }


def _bundle_coordinates() -> dict[str, str]:
    return {
        "tenant_id": "example-tenant",
        "subscription_id": "example-subscription",
        "backend_resource_group": "example-state-rg",
        "backend_storage_account": "examplestate",
        "backend_container": "tfstate",
        "workflow_run_attempt": "2",
        "controls_commit_sha": "d" * 40,
        "attestation_signer_workflow": "example/fdai/.github/workflows/container-supply-chain.yml",
    }


def _write_plan_json(path: Path, *, image: str) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    path.write_text(json.dumps(_plan(address, ["update"], image=image)) + "\n", encoding="utf-8")


def _state(*addresses: str) -> dict[str, object]:
    return {
        "values": {
            "root_module": {
                "resources": [{"address": address} for address in addresses],
                "child_modules": [],
            }
        }
    }


def _health_evidence() -> tuple[dict[str, object], ...]:
    image = _image("fdai-operator-service")
    resource_id = (
        "/subscriptions/example-subscription/resourceGroups/example/providers/"
        "Microsoft.App/containerApps/example"
    )
    context = {
        "subscription_id": "example-subscription",
        "target": {
            "service_resource_id": resource_id.lower(),
            "service_name": "example",
            "resource_group": "example",
            "component_tag": "operator-service",
            "image_ref": image,
        },
    }
    service_output = {
        "id": resource_id,
        "name": "example",
        "latest_revision_name": "example--new",
    }
    account = {"id": "example-subscription"}
    app = {
        "id": resource_id,
        "name": "example",
        "tags": {"fdai:component": "operator-service"},
        "properties": {"latestRevisionName": "example--new"},
    }
    revision = {
        "name": "example--new",
        "properties": {
            "provisioningState": "Provisioned",
            "healthState": "Healthy",
            "active": True,
            "template": {"containers": [{"image": image}]},
        },
    }
    return context, service_output, account, app, revision


def test_matrix_resolves_exact_five_services_and_state_keys(contract: ModuleType) -> None:
    matrix = contract.load_matrix()
    assert set(matrix["services"]) == {
        "core-control-plane",
        "operator-service",
        "document-ingestion-api",
        "document-processing-worker",
        "isolated-executor",
    }
    for service in matrix["services"]:
        resolved = contract.resolve_service(service, "staging")
        assert resolved.backend_key == f"services/{service}/staging.tfstate"
        assert resolved.terraform_root == f"infra/services/{service}"


def test_unknown_service_and_environment_fail_closed(contract: ModuleType) -> None:
    with pytest.raises(contract.ServiceContractError, match="five independent"):
        contract.resolve_service("platform", "dev")
    with pytest.raises(contract.ServiceContractError, match="environment"):
        contract.resolve_service("core-control-plane", "preview")


def test_image_reference_is_service_specific_and_digest_pinned(contract: ModuleType) -> None:
    resolved = contract.resolve_service("operator-service", "dev")
    image = _image("fdai-operator-service")
    digest = contract.validate_image_reference(resolved, "example/fdai", image)
    assert digest == f"sha256:{'a' * 64}"
    with pytest.raises(contract.ServiceContractError, match="selected service"):
        contract.validate_image_reference(
            resolved,
            "example/fdai",
            _image("fdai-core-control-plane"),
        )
    with pytest.raises(contract.ServiceContractError, match="sha256"):
        contract.validate_image_reference(
            resolved,
            "example/fdai",
            image.rsplit("@", 1)[0] + "@latest",
        )


def test_plan_guard_allows_only_selected_service_create_or_update(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    for action in ("create", "update", "no-op"):
        guard.validate_plan(
            _plan(address, [action]),
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


@pytest.mark.parametrize("actions", [["delete"], ["delete", "create"], ["create", "delete"]])
def test_plan_guard_rejects_delete_and_replacement(guard: ModuleType, actions: list[str]) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    with pytest.raises(guard.PlanGuardError, match="delete or replacement"):
        guard.validate_plan(
            _plan(address, actions),
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_rejects_platform_and_other_service_actions(guard: ModuleType) -> None:
    for address in (
        "azurerm_resource_group.platform",
        "module.core_control_plane.module.container_app.azurerm_container_app.service",
    ):
        with pytest.raises(guard.PlanGuardError, match="cross-service or platform"):
            guard.validate_plan(
                _plan(address, ["update"]),
                service="operator-service",
                environment="dev",
                image_ref="image",
            )


def test_plan_guard_rejects_image_substitution(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    with pytest.raises(guard.PlanGuardError, match="attested image"):
        guard.validate_plan(
            _plan(address, ["update"], image="mutable:latest"),
            service="operator-service",
            environment="dev",
            image_ref="ghcr.io/example/fdai/fdai-operator-service@sha256:" + "a" * 64,
        )


def test_plan_guard_rejects_untrusted_runtime_on_first_create(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["create"])
    container = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]
    container["command"] = ["python"]
    container["env"] = [{"name": "RUNTIME_ENV", "value": "dev"}]
    with pytest.raises(guard.PlanGuardError, match="service entrypoint.*missing required"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("name", "peer-service", "target resource identity"),
        ("resource_group_name", "peer-platform", "target resource identity"),
        (
            "container_app_environment_id",
            "/subscriptions/example/resourceGroups/example/providers/Microsoft.App/"
            "managedEnvironments/peer",
            "platform or peer resource identity",
        ),
    ],
)
def test_plan_guard_rejects_target_or_platform_identity_drift(
    guard: ModuleType,
    field: str,
    replacement: str,
    message: str,
) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    plan["resource_changes"][0]["change"]["after"][field] = replacement  # type: ignore[index]
    with pytest.raises(guard.PlanGuardError, match=message):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_rejects_identity_expansion(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    identity_ids = plan["resource_changes"][0]["change"]["after"]["identity"][0][  # type: ignore[index]
        "identity_ids"
    ]
    identity_ids.append(
        "/subscriptions/example/resourceGroups/example/providers/"
        "Microsoft.ManagedIdentity/userAssignedIdentities/executor"
    )
    with pytest.raises(guard.PlanGuardError, match="identity expansion"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


@pytest.mark.parametrize(
    ("runtime_field", "message"),
    [("command", "command"), ("args", "command"), ("env", "environment")],
)
def test_plan_guard_rejects_command_and_environment_drift(
    guard: ModuleType,
    runtime_field: str,
    message: str,
) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    container = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]
    container[runtime_field] = ["unexpected"]
    with pytest.raises(guard.PlanGuardError, match=message):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_rejects_authority_cutover_change(guard: ModuleType) -> None:
    address = "module.isolated_executor.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    before_container = plan["resource_changes"][0]["change"]["before"]["template"][0][  # type: ignore[index]
        "container"
    ][0]
    after_container = plan["resource_changes"][0]["change"]["after"]["template"][0][  # type: ignore[index]
        "container"
    ][0]
    before_container["env"].append(  # type: ignore[union-attr]
        {"name": "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER", "value": "0"}
    )
    after_container["env"].append(  # type: ignore[union-attr]
        {"name": "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER", "value": "1"}
    )
    with pytest.raises(guard.PlanGuardError, match="authority cutover"):
        guard.validate_plan(
            plan,
            service="isolated-executor",
            environment="dev",
            image_ref="image",
        )


def test_plan_guard_rejects_refreshed_platform_or_peer_drift(guard: ModuleType) -> None:
    address = "module.operator_service.module.container_app.azurerm_container_app.service"
    plan = _plan(address, ["update"])
    plan["resource_drift"] = [
        {
            "address": "module.platform.azurerm_container_app_environment.shared",
            "change": {"actions": ["update"]},
        }
    ]
    with pytest.raises(guard.PlanGuardError, match="platform or peer resource drift"):
        guard.validate_plan(
            plan,
            service="operator-service",
            environment="dev",
            image_ref="image",
        )


def test_tfvars_selects_one_service_and_reserves_image(tfvars: ModuleType, tmp_path: Path) -> None:
    payload = {"environments": {"dev": {"operator-service": {"name": "example"}}}}
    selected = tfvars.select_tfvars(payload, service="operator-service", environment="dev")
    output = tmp_path / "service.tfvars.json"
    tfvars.write_tfvars(output, selected)
    assert json.loads(output.read_text(encoding="utf-8")) == {"name": "example"}
    assert output.stat().st_mode & 0o777 == 0o600
    payload["environments"]["dev"]["operator-service"]["image"] = "mutable"
    with pytest.raises(tfvars.TfvarsError, match="must not set image"):
        tfvars.select_tfvars(payload, service="operator-service", environment="dev")


def test_state_migration_resolves_exact_source_and_destination(
    migration: ModuleType,
) -> None:
    source_key, destination_key, source, destination = migration.migration_coordinates(
        "operator-service", "staging"
    )
    assert source_key == "fdai-staging.tfstate"
    assert destination_key == "services/operator-service/staging.tfstate"
    assert source == "module.operator_api[0].azurerm_container_app.operator_api"
    assert destination == (
        "module.operator_service.module.container_app.azurerm_container_app.service"
    )


def test_state_cutover_requires_source_zero_and_destination_exactly_once(
    migration: ModuleType,
) -> None:
    source = "legacy.service"
    destination = "independent.service"
    migration.verify_state_pair(
        _state(source),
        _state(),
        source_address=source,
        destination_address=destination,
        phase="pre",
    )
    migration.verify_state_pair(
        _state(),
        _state(destination),
        source_address=source,
        destination_address=destination,
        phase="post",
    )
    with pytest.raises(migration.StateMigrationError, match="source=0 and destination=1"):
        migration.verify_state_pair(
            _state(source),
            _state(destination),
            source_address=source,
            destination_address=destination,
            phase="post",
        )
    with pytest.raises(migration.StateMigrationError, match="destination=1"):
        migration.verify_state_pair(
            _state(),
            _state(destination, destination),
            source_address=source,
            destination_address=destination,
            phase="post",
        )


def test_cutover_fence_rejects_legacy_runtime_recreation(migration: ModuleType) -> None:
    source = "module.operator_api[0].azurerm_container_app.operator_api"
    migration.guard_legacy_plan(
        {"resource_changes": [{"address": source, "change": {"actions": ["no-op"]}}]}
    )
    for actions in (["create"], ["update"], ["delete", "create"]):
        with pytest.raises(migration.StateMigrationError, match="legacy deploy cannot recreate"):
            migration.guard_legacy_plan(
                {"resource_changes": [{"address": source, "change": {"actions": actions}}]}
            )


def test_health_verification_binds_exact_resource_revision_component_and_image(
    recovery: ModuleType,
) -> None:
    context, service_output, account, app, revision = _health_evidence()
    recovery.validate_health(
        context=context,
        service_output=service_output,
        account=account,
        app=app,
        revision=revision,
        previous_revision="example--old",
    )


@pytest.mark.parametrize(
    ("evidence_index", "path", "value", "message"),
    [
        (2, ("id",), "peer-subscription", "subscription"),
        (3, ("id",), "/subscriptions/peer/resourceGroups/peer", "identity"),
        (3, ("name",), "peer", "identity"),
        (3, ("tags", "fdai:component"), "isolated-executor", "component tag"),
        (4, ("properties", "healthState"), "Unhealthy", "healthy and active"),
        (
            4,
            ("properties", "template", "containers", 0, "image"),
            _image("fdai-core-control-plane"),
            "image digest",
        ),
    ],
)
def test_health_verification_rejects_identity_and_health_drift(
    recovery: ModuleType,
    evidence_index: int,
    path: tuple[str | int, ...],
    value: object,
    message: str,
) -> None:
    evidence = [copy.deepcopy(item) for item in _health_evidence()]
    target: object = evidence[evidence_index]
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]
    with pytest.raises(recovery.DeploymentRecoveryError, match=message):
        recovery.validate_health(
            context=evidence[0],
            service_output=evidence[1],
            account=evidence[2],
            app=evidence[3],
            revision=evidence[4],
            previous_revision="example--old",
        )


def test_health_verification_rejects_stale_revision(recovery: ModuleType) -> None:
    context, service_output, account, app, revision = _health_evidence()
    with pytest.raises(recovery.DeploymentRecoveryError, match="new revision"):
        recovery.validate_health(
            context=context,
            service_output=service_output,
            account=account,
            app=app,
            revision=revision,
            previous_revision="example--new",
        )


def test_executor_rollback_uses_previous_revision_image_and_authority_fallback(
    recovery: ModuleType,
) -> None:
    snapshot = {
        "resource_group": "example",
        "service_name": "executor",
        "previous_revision": "executor--previous",
        "previous_image": _image("fdai-isolated-executor"),
        "authority_fallback": "core-in-process",
    }
    command = recovery.rollback_command(snapshot, revision_suffix="rollback-123-1")
    assert command[0:4] == ["az", "containerapp", "revision", "copy"]
    assert command[command.index("--from-revision") + 1] == "executor--previous"
    assert command[command.index("--image") + 1] == snapshot["previous_image"]
    assert command[command.index("--set-env-vars") + 1] == (
        "FDAI_ISOLATED_EXECUTOR_AUTHORITY_CUTOVER=0"
    )


def test_plan_bundle_round_trip_and_tamper_rejection(bundle: ModuleType, tmp_path: Path) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary plan")
    plan_json = tmp_path / "service-plan.json"
    context = tmp_path / "context.json"
    metadata = tmp_path / "metadata.json"
    now = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
    image = _image("fdai-operator-service")
    _write_plan_json(plan_json, image=image)
    coordinates = _bundle_coordinates()
    created = bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        workflow_run_id="123",
        now=now,
        **coordinates,
    )
    verified = bundle.verify_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        plan_digest=created["plan_digest"],
        context_digest=created["context_digest"],
        plan_run_id="123",
        now=now + timedelta(minutes=5),
        **coordinates,
    )
    assert verified == created
    sealed_context = json.loads(context.read_text(encoding="utf-8"))
    assert sealed_context["tenant_id"] == "example-tenant"
    assert sealed_context["subscription_id"] == "example-subscription"
    assert sealed_context["backend"] == {
        "resource_group": "example-state-rg",
        "storage_account": "examplestate",
        "container": "tfstate",
        "key": "services/operator-service/dev.tfstate",
    }
    assert sealed_context["target"]["service_resource_id"].endswith(
        "/providers/microsoft.app/containerapps/example"
    )
    assert sealed_context["target"]["service_name"] == "example"
    assert sealed_context["target"]["identity_resource_ids"]
    assert sealed_context["target"]["referenced_resource_ids"]
    assert sealed_context["attestation"] == {
        "signer_workflow": coordinates["attestation_signer_workflow"],
        "source_digest": "b" * 40,
        "subject_digest": f"sha256:{'a' * 64}",
    }
    assert sealed_context["trusted_controls"] == {
        "commit_sha": "d" * 40,
    }
    plan.write_bytes(b"tampered")
    with pytest.raises(bundle.PlanBundleError, match="binary plan digest"):
        bundle.verify_bundle(
            plan=plan,
            plan_json=plan_json,
            context_path=context,
            metadata_path=metadata,
            service="operator-service",
            environment="dev",
            repository="example/fdai",
            commit_sha="b" * 40,
            image_ref=image,
            plan_digest=created["plan_digest"],
            context_digest=created["context_digest"],
            plan_run_id="123",
            now=now + timedelta(minutes=5),
            **coordinates,
        )


@pytest.mark.parametrize(
    "coordinate",
    [
        "tenant_id",
        "subscription_id",
        "backend_resource_group",
        "backend_storage_account",
        "backend_container",
        "workflow_run_attempt",
        "controls_commit_sha",
        "attestation_signer_workflow",
    ],
)
def test_plan_bundle_rejects_apply_context_drift(
    bundle: ModuleType,
    tmp_path: Path,
    coordinate: str,
) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary plan")
    plan_json = tmp_path / "service-plan.json"
    image = _image("fdai-operator-service")
    _write_plan_json(plan_json, image=image)
    context = tmp_path / "context.json"
    metadata = tmp_path / "metadata.json"
    now = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
    coordinates = _bundle_coordinates()
    created = bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="b" * 40,
        image_ref=image,
        workflow_run_id="123",
        now=now,
        **coordinates,
    )
    changed = dict(coordinates)
    changed[coordinate] = "3" if coordinate == "workflow_run_attempt" else "changed"
    with pytest.raises(bundle.PlanBundleError, match="exact apply input"):
        bundle.verify_bundle(
            plan=plan,
            plan_json=plan_json,
            context_path=context,
            metadata_path=metadata,
            service="operator-service",
            environment="dev",
            repository="example/fdai",
            commit_sha="b" * 40,
            image_ref=image,
            plan_digest=created["plan_digest"],
            context_digest=created["context_digest"],
            plan_run_id="123",
            now=now + timedelta(minutes=5),
            **changed,
        )


def test_expired_plan_bundle_is_rejected(bundle: ModuleType, tmp_path: Path) -> None:
    plan = tmp_path / "service.plan"
    plan.write_bytes(b"binary plan")
    plan_json = tmp_path / "service-plan.json"
    context = tmp_path / "context.json"
    metadata = tmp_path / "metadata.json"
    now = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
    image = _image("fdai-operator-service")
    _write_plan_json(plan_json, image=image)
    coordinates = _bundle_coordinates()
    created = bundle.create_bundle(
        plan=plan,
        plan_json=plan_json,
        context_path=context,
        metadata_path=metadata,
        service="operator-service",
        environment="dev",
        repository="example/fdai",
        commit_sha="c" * 40,
        image_ref=image,
        workflow_run_id="456",
        now=now,
        **coordinates,
    )
    with pytest.raises(bundle.PlanBundleError, match="expired"):
        bundle.verify_bundle(
            plan=plan,
            plan_json=plan_json,
            context_path=context,
            metadata_path=metadata,
            service="operator-service",
            environment="dev",
            repository="example/fdai",
            commit_sha="c" * 40,
            image_ref=image,
            plan_digest=created["plan_digest"],
            context_digest=created["context_digest"],
            plan_run_id="456",
            now=now + timedelta(hours=25),
            **coordinates,
        )
