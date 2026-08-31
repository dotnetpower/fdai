from __future__ import annotations

from dataclasses import replace

import pytest

from fdai_deployment_cli.progress import InventoryClosure
from fdai_deployment_cli.readiness import (
    DatabaseSemanticReadback,
    REQUIRED_READINESS_EVIDENCE,
    REQUIRED_TERRAFORM_ROOTS,
    GenesisReadinessReceipt,
    NoChangeReadback,
)


def _inventory() -> InventoryClosure:
    return InventoryClosure(
        subscription_root=True,
        resource_type_filter=False,
        final_fence=True,
        provider_coverage_complete=True,
        truncated=False,
        active_generation_matches=True,
        overlay_open=False,
        child_sources_complete=True,
        observer_distinct=True,
    )


def _receipt() -> GenesisReadinessReceipt:
    return GenesisReadinessReceipt(
        source_commit="a" * 40,
        manifest_digest="b" * 64,
        target_binding="c" * 64,
        generated_at="2026-08-30T12:00:00+00:00",
        evidence_digests={
            name: f"{index:064x}"
            for index, name in enumerate(sorted(REQUIRED_READINESS_EVIDENCE), start=1)
        },
        database_semantic=DatabaseSemanticReadback(
            expected_legacy_head="20260829_0088",
            legacy_head="20260829_0088",
            expected_service_heads={
                "core-control-plane": "core_head",
                "document-ingestion-api": "ingestion_head",
                "document-processing-worker": "worker_head",
                "isolated-executor": "executor_head",
                "operator-service": "operator_head",
            },
            service_heads={
                "core-control-plane": "core_head",
                "document-ingestion-api": "ingestion_head",
                "document-processing-worker": "worker_head",
                "isolated-executor": "executor_head",
                "operator-service": "operator_head",
            },
            extensions=("pg_trgm", "plpgsql", "vector"),
            expected_runtime_role_checks=(
                "core_runtime_no_ddl",
                "operator_read_only",
            ),
            runtime_role_checks={
                "core_runtime_no_ddl": True,
                "operator_read_only": True,
            },
            ontology_release_digest="1" * 64,
            catalog_digest="2" * 64,
            defaults_digest="3" * 64,
            role_manifest_digest="4" * 64,
            expected_ontology_release_digest="1" * 64,
            expected_catalog_digest="2" * 64,
            expected_defaults_digest="3" * 64,
            expected_role_manifest_digest="4" * 64,
            shadow_only=True,
            observer_distinct=True,
        ),
        inventory_closure=_inventory(),
        second_run=NoChangeReadback(
            root_changes={root: (0, 0, 0) for root in REQUIRED_TERRAFORM_ROOTS},
        ),
    )


def test_readiness_receipt_requires_complete_inventory_and_no_change() -> None:
    receipt = _receipt()

    assert receipt.to_mapping()["status"] == "verified"
    assert len(receipt.digest) == 64
    assert set(receipt.to_mapping()["evidence_digests"]) == REQUIRED_READINESS_EVIDENCE

    with pytest.raises(ValueError, match="child_source_incomplete"):
        replace(receipt, inventory_closure=replace(_inventory(), child_sources_complete=False))
    with pytest.raises(ValueError, match="MUST be no-change"):
        changed = dict(receipt.second_run.root_changes)
        changed["platform"] = (0, 1, 0)
        replace(receipt, second_run=NoChangeReadback(root_changes=changed))


def test_readiness_receipt_requires_every_evidence_family() -> None:
    receipt = _receipt()
    incomplete = dict(receipt.evidence_digests)
    incomplete.pop("migration_readback")

    with pytest.raises(ValueError, match="evidence set is incomplete"):
        replace(receipt, evidence_digests=incomplete)


def test_readiness_receipt_copies_evidence_and_requires_utc() -> None:
    evidence = dict(_receipt().evidence_digests)
    receipt = replace(_receipt(), evidence_digests=evidence)
    evidence["foundation_plan"] = "f" * 64

    assert receipt.evidence_digests["foundation_plan"] != "f" * 64
    with pytest.raises(TypeError):
        receipt.evidence_digests["foundation_plan"] = "e" * 64  # type: ignore[index]
    with pytest.raises(ValueError, match="MUST use UTC"):
        replace(receipt, generated_at="2026-08-30T21:00:00+09:00")


@pytest.mark.parametrize("value", [True, 0.0, -1])
def test_second_run_counts_require_non_negative_integers(value: object) -> None:
    changes = {root: (0, 0, 0) for root in REQUIRED_TERRAFORM_ROOTS}
    changes["platform"] = (value, 0, 0)  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="non-negative integer"):
        NoChangeReadback(root_changes=changes)


def test_second_run_requires_the_exact_root_set() -> None:
    changes = {root: (0, 0, 0) for root in REQUIRED_TERRAFORM_ROOTS}
    changes.pop("service.operator-service")

    with pytest.raises(ValueError, match="every Terraform root"):
        NoChangeReadback(root_changes=changes)


def test_database_semantic_readback_rejects_missing_or_self_certified_evidence() -> None:
    readback = _receipt().database_semantic
    heads = dict(readback.service_heads)
    heads.pop("operator-service")
    with pytest.raises(ValueError, match="every service"):
        replace(readback, service_heads=heads)
    with pytest.raises(ValueError, match="legacy migration head"):
        replace(readback, legacy_head="fabricated_head")
    with pytest.raises(ValueError, match="sealed manifest"):
        replace(readback, catalog_digest="f" * 64)
    with pytest.raises(ValueError, match="extensions"):
        replace(readback, extensions=("plpgsql", "vector"))
    with pytest.raises(ValueError, match="passing checks"):
        replace(readback, runtime_role_checks={"runtime_no_ddl": False})
    with pytest.raises(ValueError, match="passing checks"):
        replace(readback, runtime_role_checks={"unrelated_check": True})
    with pytest.raises(ValueError, match="shadow-only"):
        replace(readback, shadow_only=False)
    with pytest.raises(ValueError, match="independent"):
        replace(readback, observer_distinct=False)
