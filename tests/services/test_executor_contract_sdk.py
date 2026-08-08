"""Independent package contract tests for the isolated Executor."""

from __future__ import annotations

import ast
import tomllib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from fdai_service_contracts.executor import (
    Action,
    ActionStopCondition,
    BlastRadius,
    BlastRadiusScope,
    ExecutionPath,
    ExecutorCommand,
    ExecutorShadowReceipt,
    ExecutorShadowReceiptStatus,
    Mode,
    Operation,
    RollbackKind,
    RollbackRef,
    StopConditionKind,
    resolve_azure_operation_target,
)
from fdai_service_contracts.schema import (
    JsonSchemaContractValidator,
    PackageResourceSchemaRegistry,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_SOURCE = REPO_ROOT / "packages" / "service-contracts" / "src" / "fdai_service_contracts"
EXECUTOR_SOURCE = REPO_ROOT / "services" / "isolated-executor" / "src" / "fdai_executor_service"


def _fdai_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return {name for name in imports if name == "fdai" or name.startswith("fdai.")}


def _action() -> Action:
    now = datetime(2026, 8, 8, tzinfo=UTC)
    return Action(
        schema_version="1.0.0",
        action_id=UUID(int=1),
        idempotency_key="executor-contract-test",
        event_id=UUID(int=2),
        action_type="ops.restart-service",
        target_resource_ref="resource/example",
        operation=Operation.RESTART,
        stop_condition=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS.value,
        stop_conditions=[
            ActionStopCondition(
                kind=StopConditionKind.TIME_BOX_EXCEEDED_SECONDS,
                seconds=60,
            )
        ],
        rollback_ref=RollbackRef(kind=RollbackKind.SCRIPTED, reference="rollback/example"),
        blast_radius=BlastRadius(scope=BlastRadiusScope.RESOURCE, count=1),
        mode=Mode.SHADOW,
        citing_rules=["rule.example"],
        created_at=now,
    )


def test_executor_and_contract_packages_import_no_fdai_module() -> None:
    offenders = {
        path.relative_to(REPO_ROOT): _fdai_imports(path)
        for source in (CONTRACT_SOURCE, EXECUTOR_SOURCE)
        for path in source.rglob("*.py")
        if _fdai_imports(path)
    }

    assert offenders == {}


def test_executor_distribution_has_no_fdai_dependency_or_source() -> None:
    project = tomllib.loads(
        (REPO_ROOT / "services" / "isolated-executor" / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    dependencies = project["project"]["dependencies"]
    sources = project.get("tool", {}).get("uv", {}).get("sources", {})

    assert "fdai-service-contracts==0.1.0" in dependencies
    assert not any(
        dependency == "fdai" or dependency.startswith(("fdai[", "fdai==", "fdai>=", "fdai<"))
        for dependency in dependencies
    )
    assert "fdai" not in sources


def test_executor_command_and_receipt_validate_with_packaged_schemas() -> None:
    action = _action()
    command = ExecutorCommand.from_action(
        command_id=UUID(int=3),
        action=action,
        execution_path=ExecutionPath.DIRECT_API,
        attempt=1,
        issued_at=action.created_at,
        deadline_at=action.created_at + timedelta(minutes=5),
    )
    receipt = ExecutorShadowReceipt(
        receipt_id=UUID(int=4),
        command_id=command.command_id,
        action_id=command.action_id,
        idempotency_key=command.idempotency_key,
        attempt=command.attempt,
        action_payload_digest=command.action_payload_digest,
        requested_mode=command.requested_mode,
        status=ExecutorShadowReceiptStatus.SHADOWED,
        reason="shadow command recorded without dispatch",
        executor_instance_id="executor-test",
        received_at=action.created_at,
        completed_at=action.created_at,
        effect_applied=False,
    )
    validator = JsonSchemaContractValidator(PackageResourceSchemaRegistry())

    validator.validate(
        "action",
        action.model_dump(mode="json", exclude_none=True),
        version="1.0.0",
    )
    validator.validate(
        "executor-command",
        command.model_dump(mode="json"),
        version=command.schema_version,
    )
    validator.validate(
        "executor-receipt",
        receipt.model_dump(mode="json"),
        version=receipt.schema_version,
    )


def test_upgrade_receipt_schema_is_registered_with_the_contract_sdk() -> None:
    registry = PackageResourceSchemaRegistry()

    schema = registry.get("service-upgrade-receipt", "1.0.0")

    assert "service-upgrade-receipt" in registry.names()
    assert schema["$id"].endswith("/service-upgrade-receipt/1.0.0")


def test_executor_contract_canonicalizes_azure_operation_targets() -> None:
    vm = resolve_azure_operation_target(
        "ops.start-vm",
        {"resource_group": "Example", "vm_name": "VM-App"},
    )
    rule = resolve_azure_operation_target(
        "ops.delete-network-rule",
        {
            "resource_group": "Example",
            "nsg_name": "NSG-App",
            "rule_name": "Allow-HTTPS",
        },
    )

    assert vm.operation_id == "azure.compute.vm.start"
    assert vm.resource_ref == (
        "/resourcegroups/example/providers/microsoft.compute/virtualmachines/vm-app"
    )
    assert rule.resource_ref == (
        "/resourcegroups/example/providers/microsoft.network/"
        "networksecuritygroups/nsg-app/securityrules/allow-https"
    )
