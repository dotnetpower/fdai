"""AKS standalone workloads receive the readiness and receipt bindings Core and Operator need."""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from fdai_deployment_cli import (
    aks_workload_jobs,
    standalone_host,
    standalone_license_installation,
    standalone_stage_targets,
)
from fdai_deployment_cli.standalone_host_values import (
    AKS_CORE_STARTUP_READINESS,
    aks_operator_request_receipts,
)

_INFRA = Path(__file__).resolve().parents[3] / "infra"
_BINDING = {
    "core_signing_seed_secret_id": (
        "https://kv-fdai-dev-wus3.vault.azure.net/secrets/fdai-operator-request-core-signing-seed"
    ),
    "operator_signing_seed_secret_id": (
        "https://kv-fdai-dev-wus3.vault.azure.net/secrets/"
        "fdai-operator-request-operator-signing-seed"
    ),
    "core_producer_id": "core-control-plane",
    "operator_producer_id": "operator-service",
}


def _block(source: str, header: str) -> str:
    start = source.index(header)
    depth = 0
    for index in range(source.index("{", start), len(source)):
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        if depth == 0:
            return source[start : index + 1]
    raise AssertionError(f"unterminated block: {header}")


def _variable_default(name: str) -> str:
    block = _block((_INFRA / "variables.tf").read_text(encoding="utf-8"), f'variable "{name}"')
    match = re.search(r"default\s*=\s*([0-9]+)", block)
    assert match is not None, name
    return match.group(1)


def test_core_startup_readiness_matches_the_shared_root_defaults() -> None:
    assert AKS_CORE_STARTUP_READINESS == {
        "FDAI_STARTUP_KAFKA_SETTLE_SECONDS": _variable_default("startup_kafka_settle_seconds"),
        "FDAI_STARTUP_PROBE_TIMEOUT_SECONDS": _variable_default("startup_probe_timeout_seconds"),
        "FDAI_STARTUP_PHASE_TIMEOUT_SECONDS": _variable_default("startup_phase_timeout_seconds"),
    }


def test_receipt_binding_renders_core_and_operator_configuration() -> None:
    core_env, core_secrets, operator_env, operator_secrets = aks_operator_request_receipts(_BINDING)

    assert core_env == {
        "FDAI_OPERATOR_REQUEST_CORE_PRODUCER_ID": "core-control-plane",
        "FDAI_OPERATOR_REQUEST_OPERATOR_PRODUCER_ID": "operator-service",
    }
    assert core_secrets == {
        "FDAI_OPERATOR_REQUEST_CORE_SIGNING_SEED": "fdai-operator-request-core-signing-seed",
        "FDAI_OPERATOR_REQUEST_OPERATOR_TRUST_SEED": "fdai-operator-request-operator-signing-seed",
    }
    assert operator_env == {"FDAI_OPERATOR_REQUEST_RECEIPT_PRODUCER_ID": "operator-service"}
    assert operator_secrets == {
        "FDAI_OPERATOR_REQUEST_OPERATOR_SIGNING_SEED": "fdai-operator-request-operator-signing-seed"
    }


@pytest.mark.parametrize(
    "change",
    [
        {"core_signing_seed_secret_id": ""},
        {"operator_signing_seed_secret_id": "fdai-operator-request-operator-signing-seed"},
        {"core_signing_seed_secret_id": "https://kv.vault.azure.net/secrets/a/version"},
        {"core_producer_id": "operator-service"},
        {"operator_producer_id": "core-control-plane"},
        {"operator_producer_id": ""},
        {"operator_signing_seed_secret_id": _BINDING["core_signing_seed_secret_id"]},
    ],
)
def test_receipt_binding_rejects_incomplete_or_ambiguous_references(
    change: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match="operator_request receipt"):
        aks_operator_request_receipts({**_BINDING, **change})


def test_receipt_binding_rejects_a_missing_binding() -> None:
    with pytest.raises(ValueError, match="operator_request receipt binding is invalid"):
        aks_operator_request_receipts(None)


@pytest.mark.parametrize("placement", ["postgres-flex", "postgres-aks"])
def test_substrate_creates_the_seeds_and_their_per_secret_readers(placement: str) -> None:
    targets = set(
        standalone_stage_targets.substrate_targets(
            {"runtime_profile": {"runtime_platform": "aks", "database_placement": placement}}
        )
    )

    assert {
        "azurerm_key_vault_secret.operator_request_core_signing_seed",
        "azurerm_key_vault_secret.operator_request_operator_signing_seed",
        "azurerm_role_assignment.core_operator_request_core_seed_reader",
        "azurerm_role_assignment.core_operator_request_operator_seed_reader",
        "azurerm_role_assignment.operator_api_operator_request_seed_reader",
    } <= targets


@pytest.mark.parametrize(
    ("name", "secret", "principal"),
    [
        (
            "core_operator_request_core_seed_reader",
            "operator_request_core_signing_seed",
            "module.identity.principal_id",
        ),
        (
            "core_operator_request_operator_seed_reader",
            "operator_request_operator_signing_seed",
            "module.identity.principal_id",
        ),
        (
            "operator_api_operator_request_seed_reader",
            "operator_request_operator_signing_seed",
            "module.operator_api_identity[0].principal_id",
        ),
    ],
)
def test_each_seed_reader_is_scoped_to_one_secret_and_one_identity(
    name: str, secret: str, principal: str
) -> None:
    block = _block(
        (_INFRA / "main.tf").read_text(encoding="utf-8"),
        f'resource "azurerm_role_assignment" "{name}"',
    )

    assert (
        f"scope                = azurerm_key_vault_secret.{secret}.resource_versionless_id" in block
    )
    assert 'role_definition_name = "Key Vault Secrets User"' in block
    assert f"principal_id         = {principal}" in block


_SECRET_REFERENCE = re.compile(r'"[A-Z][A-Z0-9_]+"\s*:\s*"(fdai-[a-z0-9-]+)"')
_SECRET_RESOURCE = re.compile(
    r'resource "azurerm_key_vault_secret" "([a-z0-9_]+)" \{[^}]*?\n\s+name\s*=\s*"([a-z0-9-]+)"'
)
# The managed host writes and reads back the license secret; Terraform never owns it.
_HOST_WRITTEN_SECRETS = frozenset({standalone_license_installation.LICENSE_SECRET_NAME})


def _secret_sources(root: Path) -> dict[str, str]:
    return {
        name: f"azurerm_key_vault_secret.{resource}"
        for path in sorted(root.glob("*.tf"))
        for resource, name in _SECRET_RESOURCE.findall(path.read_text(encoding="utf-8"))
    }


def test_every_aks_workload_secret_reference_has_a_targeted_or_host_written_source() -> None:
    rendered = "".join(
        inspect.getsource(item)
        for item in (
            standalone_host._prepare_aks_application,
            standalone_host._aks_document_workloads,
            aks_workload_jobs,
        )
    )
    referenced = set(_SECRET_REFERENCE.findall(rendered))
    assert {"fdai-state-store-dsn", "fdai-ingestion-api-dsn", "fdai-ingestion-worker-dsn"} <= (
        referenced
    )
    _license_environment, license_secrets = standalone_license_installation.aks_license_environment(
        {"license": {"token_secret_id": "id", "image_digest": "digest", "token_revision": "1"}}
    )
    assert set(license_secrets.values()) <= _HOST_WRITTEN_SECRETS
    shared = _secret_sources(_INFRA)
    database = _secret_sources(_INFRA / "runtimes" / "aks" / "database")

    for placement in ("postgres-flex", "postgres-aks"):
        targets = set(
            standalone_stage_targets.substrate_targets(
                {"runtime_profile": {"runtime_platform": "aks", "database_placement": placement}}
            )
        )
        for name in sorted(referenced - _HOST_WRITTEN_SECRETS):
            from_substrate = shared.get(name) in targets
            from_database = placement == "postgres-aks" and name in database
            assert from_substrate or from_database, (placement, name)
