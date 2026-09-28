"""Tests for the isolated inventory network Terraform plan gate."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[3]
_PATH = (
    _ROOT / "scripts" / "deployment" / "azure" / "verify_inventory_network_certification_plan.py"
)
_SPEC = importlib.util.spec_from_file_location("verify_inventory_network_certification_plan", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_MIGRATION_PATH = (
    _ROOT / "scripts" / "deployment" / "azure" / "run_inventory_network_certification_migrations.py"
)
_MIGRATION_SPEC = importlib.util.spec_from_file_location(
    "run_inventory_network_certification_migrations",
    _MIGRATION_PATH,
)
assert _MIGRATION_SPEC is not None and _MIGRATION_SPEC.loader is not None
_MIGRATION_MODULE = importlib.util.module_from_spec(_MIGRATION_SPEC)
_MIGRATION_SPEC.loader.exec_module(_MIGRATION_MODULE)


def _plan(action: str) -> dict[str, object]:
    return {
        "resource_changes": [
            {"address": address, "change": {"actions": [action]}}
            for address in sorted(_MODULE.EXPECTED_ADDRESSES)
        ]
    }


@pytest.mark.parametrize(("mode", "action"), [("create", "create"), ("cleanup", "delete")])
def test_exact_plan_is_accepted(mode: str, action: str) -> None:
    _MODULE.verify_plan(_plan(action), mode=mode)


def test_exact_extension_recovery_is_accepted() -> None:
    plan = {
        "resource_changes": [
            {
                "address": "azurerm_postgresql_flexible_server_configuration.extensions",
                "change": {"actions": ["create"]},
            }
        ]
    }

    _MODULE.verify_plan(plan, mode="extension-recovery")


def test_exact_migration_recovery_is_accepted() -> None:
    plan = {
        "resource_changes": [
            {
                "address": "azurerm_container_app_job.migrate",
                "change": {"actions": ["update"]},
            }
        ]
    }

    _MODULE.verify_plan(plan, mode="migration-recovery")


def test_migration_recovery_accepts_reviewed_ownership_tag_updates() -> None:
    plan = {
        "resource_changes": [
            {"address": address, "change": {"actions": ["update"]}}
            for address in (
                "azurerm_container_app_job.migrate",
                "azurerm_container_app_environment.certification",
                "azurerm_virtual_network.certification",
            )
        ]
    }

    _MODULE.verify_plan(plan, mode="migration-recovery")


def test_migration_recovery_rejects_a_plan_without_the_migration_job() -> None:
    plan = {
        "resource_changes": [
            {
                "address": "azurerm_virtual_network.certification",
                "change": {"actions": ["update"]},
            }
        ]
    }

    with pytest.raises(_MODULE.PlanVerificationError, match="complete reviewed"):
        _MODULE.verify_plan(plan, mode="migration-recovery")


def test_migration_recovery_rejects_a_destructive_action() -> None:
    plan = {
        "resource_changes": [
            {
                "address": "azurerm_container_app_job.migrate",
                "change": {"actions": ["delete", "create"]},
            }
        ]
    }

    with pytest.raises(_MODULE.PlanVerificationError, match="non-update"):
        _MODULE.verify_plan(plan, mode="migration-recovery")


def test_migration_recovery_rejects_an_unreviewed_address() -> None:
    plan = {
        "resource_changes": [
            {
                "address": "azurerm_container_app_job.migrate",
                "change": {"actions": ["update"]},
            },
            {
                "address": "azurerm_virtual_network.shared",
                "change": {"actions": ["update"]},
            },
        ]
    }

    with pytest.raises(_MODULE.PlanVerificationError, match="unreviewed"):
        _MODULE.verify_plan(plan, mode="migration-recovery")


def test_certification_migration_runs_legacy_then_every_service_branch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    migration_entry = root / "service-migrations" / "migrate.py"
    migration_entry.parent.mkdir(parents=True)
    migration_entry.write_text("", encoding="utf-8")
    (root / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    services = ("document-ingestion-api", "core-control-plane", "operator-service")
    calls: list[tuple[str, tuple[str, ...]]] = []

    def _run(
        label: str,
        arguments: tuple[str, ...],
        *,
        repository_root: Path,
        environment: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        assert repository_root == root
        assert environment["FDAI_DATABASE_URL"] == "******"
        calls.append((label, arguments))
        if arguments[-2:] == ("all", "order"):
            return subprocess.CompletedProcess(arguments, 0, stdout="\n".join(services), stderr="")
        if "bootstrap" in arguments:
            evidence = Path(arguments[arguments.index("--evidence-output") + 1])
            schema = Path(arguments[arguments.index("--schema-output") + 1])
            evidence.write_text("{}", encoding="utf-8")
            schema.write_text("{}", encoding="utf-8")
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    monkeypatch.setattr(_MIGRATION_MODULE, "_run_command", _run)

    receipt = _MIGRATION_MODULE.run_inventory_network_migrations(
        {
            "FDAI_DATABASE_URL": "******",
            "FDAI_NETWORK_CERT_SOURCE_REVISION": "a" * 40,
        },
        repository_root=root,
        python_executable="/python",
    )

    assert calls[0][1] == ("/python", "-m", "alembic", "upgrade", "head")
    assert calls[1][1] == ("/python", str(migration_entry), "all", "order")
    assert [call[0] for call in calls[2:]] == [
        "document-ingestion-api migration",
        "core-control-plane migration",
        "operator-service migration",
    ]
    assert receipt["services"] == list(services)
    assert set(receipt["service_evidence_digests"]) == set(services)
    assert set(receipt["schema_evidence_digests"]) == set(services)
    assert receipt["mutation_authority"] is False
    assert receipt["execution_authority"] is False


def test_certification_migration_assets_are_shipped_and_bound() -> None:
    dockerfile = (_ROOT / "services/core-control-plane/docker/Dockerfile").read_text(
        encoding="utf-8"
    )
    terraform = (_ROOT / "infra/inventory-network-certification/main.tf").read_text(
        encoding="utf-8"
    )

    assert "service-migrations/ /app/service-migrations/" in dockerfile
    assert (
        "run_inventory_network_certification_migrations.py "
        "/app/scripts/deployment/azure/run_inventory_network_certification_migrations.py"
        in dockerfile
    )
    assert (
        '"/app/scripts/deployment/azure/run_inventory_network_certification_migrations.py"'
        in terraform
    )
    assert 'name  = "FDAI_NETWORK_CERT_SOURCE_REVISION"' in terraform
    assert "replica_timeout_in_seconds   = 1800" in terraform


def test_partial_cleanup_accepts_a_preserved_failed_sandbox_subset() -> None:
    plan = {
        "resource_changes": [
            {"address": address, "change": {"actions": ["delete"]}}
            for address in (
                "azurerm_virtual_network.certification",
                "azurerm_storage_account.receipts",
                "azurerm_user_assigned_identity.campaign",
            )
        ]
    }

    _MODULE.verify_plan(plan, mode="partial-cleanup")


def test_partial_cleanup_rejects_an_empty_plan() -> None:
    with pytest.raises(_MODULE.PlanVerificationError, match="removes nothing"):
        _MODULE.verify_plan({"resource_changes": []}, mode="partial-cleanup")


def test_partial_cleanup_rejects_a_non_delete_action() -> None:
    plan = {
        "resource_changes": [
            {
                "address": "azurerm_virtual_network.certification",
                "change": {"actions": ["update"]},
            }
        ]
    }

    with pytest.raises(_MODULE.PlanVerificationError, match="non-delete"):
        _MODULE.verify_plan(plan, mode="partial-cleanup")


def test_partial_cleanup_rejects_an_unreviewed_address() -> None:
    plan = {
        "resource_changes": [
            {
                "address": "azurerm_virtual_network.shared",
                "change": {"actions": ["delete"]},
            }
        ]
    }

    with pytest.raises(_MODULE.PlanVerificationError, match="unreviewed"):
        _MODULE.verify_plan(plan, mode="partial-cleanup")


def test_unreviewed_address_is_rejected() -> None:
    plan = _plan("create")
    plan["resource_changes"].append(
        {"address": "azurerm_virtual_network.shared", "change": {"actions": ["create"]}}
    )

    with pytest.raises(_MODULE.PlanVerificationError, match="unreviewed"):
        _MODULE.verify_plan(plan, mode="create")


def test_replacement_is_rejected() -> None:
    plan = _plan("create")
    plan["resource_changes"][0]["change"]["actions"] = ["delete", "create"]

    with pytest.raises(_MODULE.PlanVerificationError, match="non-create"):
        _MODULE.verify_plan(plan, mode="create")


def test_incomplete_cleanup_is_rejected() -> None:
    plan = _plan("delete")
    plan["resource_changes"].pop()

    with pytest.raises(_MODULE.PlanVerificationError, match="complete reviewed"):
        _MODULE.verify_plan(plan, mode="cleanup")
