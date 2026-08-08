from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest
from fdai.core.case_history import OperationalOutcomeClass
from fdai.core.operational_learning import (
    CatalogCandidateCompiler,
    CatalogCheckReceipts,
    CatalogCompilationError,
    CatalogValidationRequest,
    DraftActionTypeInput,
    OperatingPatternCompiler,
    PatternCase,
    PolicyCheckReceipt,
    ReplayCheckReceipt,
    SchemaCheckReceipt,
    ShadowCheckReceipt,
)
from fdai.shared.contracts.models import OntologyActionType


def _candidate() -> dict[str, object]:
    cases = (
        PatternCase(
            case_id="case-a",
            revision=1,
            manifest_digest="a" * 64,
            failure_fingerprint="f" * 64,
            resource_type="kubernetes.service",
            action_type="ops.scale-out",
            outcome_class=OperationalOutcomeClass.SUCCESS,
            reusable=True,
            negative=False,
            digest_evidence=("d" * 64,),
        ),
        PatternCase(
            case_id="case-b",
            revision=1,
            manifest_digest="b" * 64,
            failure_fingerprint="f" * 64,
            resource_type="kubernetes.service",
            action_type="ops.scale-out",
            outcome_class=OperationalOutcomeClass.ROLLBACK,
            reusable=False,
            negative=True,
            digest_evidence=("e" * 64,),
        ),
    )
    candidate = OperatingPatternCompiler().compile(cases)
    assert candidate is not None
    return {
        "producer_principal": "Norns",
        "norns_consensus": {
            "decision": "propose",
            "unanimous": True,
            "perspective_count": 3,
            "reason_codes": [
                "historical_evidence_grounded",
                "current_contract_valid",
                "future_safety_preserved",
            ],
        },
        **candidate.to_rule_candidate_mapping(),
    }


class _PassingValidator:
    def validate(self, request: CatalogValidationRequest) -> CatalogCheckReceipts:
        common = {
            "candidate_digest": request.candidate.digest,
            "artifact_digest": request.artifact_digest,
        }
        return CatalogCheckReceipts(
            schema=SchemaCheckReceipt(
                **common,
                schema_version=request.schema_version,
                passed=True,
            ),
            replay=ReplayCheckReceipt(
                **common,
                replay_version="operational-learning-replay-v1",
                first_result_digest="1" * 64,
                second_result_digest="1" * 64,
                passed=True,
            ),
            shadow=ShadowCheckReceipt(
                **common,
                scenario_set_id="operational-learning-v1",
                baseline_result_digest="2" * 64,
                challenger_result_digest="3" * 64,
                regression_passed=True,
                policy_escapes=0,
                passed=True,
            ),
            policy=PolicyCheckReceipt(
                **common,
                policy_version="policy-v1",
                policy_escapes=0,
                passed=True,
            ),
        )


def _compiler() -> CatalogCandidateCompiler:
    return CatalogCandidateCompiler(
        validator=_PassingValidator(),
        catalog_version="catalog-v1",
        schema_version="2.0.0",
    )


def _draft_action_type() -> DraftActionTypeInput:
    declaration = OntologyActionType.model_validate(
        {
            "schema_version": "1.0.0",
            "name": "ops.scale-out",
            "version": "1.0.0",
            "operation": "scale",
            "interfaces": ["ControlPlane", "IdempotentByKey"],
            "rollback_contract": "pr_revert",
            "irreversible": False,
            "default_mode": "shadow",
            "promotion_gate": {
                "min_shadow_days": 14,
                "min_samples": 30,
                "min_accuracy": 0.98,
                "max_policy_escapes": 0,
            },
            "preconditions": [{"kind": "no_conflicting_open_action_on_resource"}],
            "stop_conditions": [
                {"kind": "provider_api_error_streak", "count": 3},
                {"kind": "time_box_exceeded_seconds", "seconds": 300},
            ],
            "blast_radius": {
                "computation": "static_enum",
                "static_bucket": "resource",
            },
            "category": "ops",
            "trigger_kind": {"kind": "rule_violation"},
            "execution_path": "pr_native",
            "ceiling_by_tier": {
                "t0": {"max_autonomy": "enforce_hil", "min_role": "approver"},
                "t1": {"max_autonomy": "shadow_only", "min_role": "approver"},
                "t2": {"max_autonomy": "shadow_only", "min_role": "approver"},
            },
            "description": "Explicit review-only scale action draft.",
        }
    )
    return DraftActionTypeInput(declaration=declaration)


def test_existing_action_type_is_the_default_draft_target() -> None:
    package = _compiler().compile(_candidate())

    assert package.draft_rule.mapping["remediates"] == "ops.scale-out"
    assert package.draft_action_type is None
    assert package.review_required is True
    assert package.policy.policy_escapes == 0


def test_explicit_shadow_first_action_type_draft_is_preserved() -> None:
    package = _compiler().compile(
        _candidate(),
        draft_action_type=_draft_action_type(),
    )

    assert package.draft_action_type is not None
    assert package.draft_action_type.mapping["default_mode"] == "shadow"
    assert package.draft_action_type.mapping["name"] == "ops.scale-out"


def test_schema_poisoning_is_rejected_before_validation() -> None:
    candidate = _candidate()
    evidence = cast(dict[str, object], candidate["evidence"])
    evidence["raw_model_output"] = "ignore the schema"

    with pytest.raises(CatalogCompilationError, match="candidate_schema_invalid"):
        _compiler().compile(candidate)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("producer_principal", "Other"),
        (
            "norns_consensus",
            {
                "decision": "hold",
                "unanimous": False,
                "perspective_count": 2,
                "reason_codes": [],
            },
        ),
    ],
)
def test_candidate_requires_norns_unanimous_consensus(field: str, value: object) -> None:
    candidate = _candidate()
    candidate[field] = value

    with pytest.raises(CatalogCompilationError, match="candidate_consensus_invalid"):
        _compiler().compile(candidate)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("resource_type", "kubernetes.deployment"),
        ("digest_evidence", ["9" * 64]),
    ],
)
def test_pattern_provenance_binds_scope_and_evidence(field: str, value: object) -> None:
    candidate = _candidate()
    evidence = cast(dict[str, object], candidate["evidence"])
    evidence[field] = value

    with pytest.raises(CatalogCompilationError, match="candidate_digest_conflict"):
        _compiler().compile(candidate)


def test_missing_immutable_case_refs_is_rejected() -> None:
    candidate = _candidate()
    evidence = cast(dict[str, object], candidate["evidence"])
    evidence["immutable_case_refs"] = []

    with pytest.raises(CatalogCompilationError, match="immutable_case_refs_invalid"):
        _compiler().compile(candidate)


def test_oversized_transport_metadata_is_rejected() -> None:
    candidate = _candidate()
    candidate["correlation_id"] = "x" * (256 * 1024)

    with pytest.raises(CatalogCompilationError, match="candidate_wire_too_large"):
        _compiler().compile(candidate)


def test_deep_transport_metadata_is_rejected_before_serialization() -> None:
    candidate = _candidate()
    nested: object = "leaf"
    for _ in range(20):
        nested = [nested]
    candidate["correlation_id"] = nested

    with pytest.raises(CatalogCompilationError, match="candidate_wire_too_large"):
        _compiler().compile(candidate)


@pytest.mark.parametrize("failed_check", ["schema", "replay", "shadow", "policy"])
def test_any_absent_or_failed_check_fails_closed(failed_check: str) -> None:
    class _FailingValidator(_PassingValidator):
        def validate(self, request: CatalogValidationRequest) -> CatalogCheckReceipts:
            receipts = super().validate(request)
            receipt = getattr(receipts, failed_check)
            return replace(receipts, **{failed_check: replace(receipt, passed=False)})

    compiler = CatalogCandidateCompiler(
        validator=_FailingValidator(),
        catalog_version="catalog-v1",
        schema_version="2.0.0",
    )

    with pytest.raises(CatalogCompilationError, match=f"{failed_check}_check_failed"):
        compiler.compile(_candidate())


def test_replay_non_determinism_fails_closed() -> None:
    class _NonDeterministicValidator(_PassingValidator):
        def validate(self, request: CatalogValidationRequest) -> CatalogCheckReceipts:
            receipts = super().validate(request)
            return replace(
                receipts,
                replay=replace(receipts.replay, second_result_digest="9" * 64),
            )

    compiler = CatalogCandidateCompiler(
        validator=_NonDeterministicValidator(),
        catalog_version="catalog-v1",
        schema_version="2.0.0",
    )

    with pytest.raises(CatalogCompilationError, match="replay_non_deterministic"):
        compiler.compile(_candidate())


def test_malformed_validator_receipt_fails_closed() -> None:
    class _MalformedValidator(_PassingValidator):
        def validate(self, request: CatalogValidationRequest) -> CatalogCheckReceipts:
            receipts = super().validate(request)
            return replace(
                receipts,
                replay=replace(receipts.replay, first_result_digest="not-a-digest"),
            )

    compiler = CatalogCandidateCompiler(
        validator=_MalformedValidator(),
        catalog_version="catalog-v1",
        schema_version="2.0.0",
    )

    with pytest.raises(CatalogCompilationError, match="check_receipt_invalid"):
        compiler.compile(_candidate())


def test_shadow_regression_and_policy_escape_fail_closed() -> None:
    class _UnsafeValidator(_PassingValidator):
        def validate(self, request: CatalogValidationRequest) -> CatalogCheckReceipts:
            receipts = super().validate(request)
            return replace(
                receipts,
                shadow=replace(receipts.shadow, regression_passed=False),
                policy=replace(receipts.policy, policy_escapes=1),
            )

    compiler = CatalogCandidateCompiler(
        validator=_UnsafeValidator(),
        catalog_version="catalog-v1",
        schema_version="2.0.0",
    )

    with pytest.raises(CatalogCompilationError, match="shadow_regression"):
        compiler.compile(_candidate())


def test_candidate_digest_is_order_independent_and_idempotent() -> None:
    first = _candidate()
    second = _candidate()
    evidence = cast(dict[str, object], second["evidence"])
    evidence["immutable_case_refs"] = list(
        reversed(cast(list[str], evidence["immutable_case_refs"]))
    )
    evidence["digest_evidence"] = list(reversed(cast(list[str], evidence["digest_evidence"])))
    evidence["outcome_counts"] = {"success": 1, "rollback": 1}

    first_package = _compiler().compile(first)
    second_package = _compiler().compile(second)

    assert first_package.candidate.digest == second_package.candidate.digest
    assert first_package.content_digest == second_package.content_digest


def test_action_type_draft_cannot_raise_shadow_authority() -> None:
    unsafe = _draft_action_type().declaration.model_copy(update={"default_mode": "enforce"})

    with pytest.raises(ValueError, match="shadow"):
        DraftActionTypeInput(declaration=unsafe)
