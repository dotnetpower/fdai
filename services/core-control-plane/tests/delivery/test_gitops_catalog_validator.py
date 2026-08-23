"""Deterministic O3 catalog validator tests."""

from __future__ import annotations

from typing import Any

from fdai.core.operational_learning import CatalogCandidateCompiler
from fdai.delivery.gitops_pr.catalog_validator import DeterministicCatalogValidator
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai_core_test_support.operational_catalog import operational_candidate_mapping


def _scenario() -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "id": "operational-review-1",
        "version": "operational-learning-v1",
        "domain": "sre",
        "tags": ["operational-learning"],
        "event": {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "idempotency_key": "operational-review-1",
            "source": "test",
            "event_type": "change_detected",
            "detected_at": "2026-08-23T00:00:00Z",
            "ingested_at": "2026-08-23T00:00:01Z",
            "mode": "shadow",
            "payload": {
                "resource": {
                    "type": "kubernetes.service",
                    "resource_id": "kubernetes.service::example",
                    "props": {},
                }
            },
        },
        "expected": {
            "tier": "t0",
            "decision": "auto",
            "citing_rule_ids": [],
            "guard": {
                "should_execute": False,
                "should_rollback": False,
                "should_trigger_policy_violation": False,
            },
        },
    }


def test_validator_seals_repeatable_schema_shadow_and_policy_receipts() -> None:
    validator = DeterministicCatalogValidator(
        schema_registry=PackageResourceSchemaRegistry(),
        action_type_names=frozenset({"ops.scale-out"}),
        resource_type_ids=frozenset({"kubernetes.service"}),
        baseline_rules=(),
        scenarios=(_scenario(),),
        scenario_set_id="operational-learning-v1",
        replay_version="shadow-replay-v1",
        policy_version="policy-v1",
    )
    compiler = CatalogCandidateCompiler(
        validator=validator,
        catalog_version="catalog-v1",
        schema_version="2.0.0",
    )

    package = compiler.compile(operational_candidate_mapping())

    assert package.schema.passed is True
    assert package.replay.passed is True
    assert package.replay.first_result_digest == package.replay.second_result_digest
    assert package.shadow.regression_passed is True
    assert package.policy.policy_escapes == 0
