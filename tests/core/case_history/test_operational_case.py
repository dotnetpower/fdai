from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from fdai.core.case_history import (
    FailureFingerprint,
    OperationalCaseInput,
    OperationalCaseProjection,
    OperationalOutcomeClass,
    OperationalReceiptFact,
    OperationalReceiptType,
    compile_operational_case,
)
from fdai.core.case_history.models import CaseKind

T0 = datetime(2026, 8, 1, tzinfo=UTC)


def _fingerprint(**overrides: object) -> FailureFingerprint:
    values: dict[str, object] = {
        "resource_type": "kubernetes.service",
        "failure_mechanism": "selector_target_mismatch",
        "symptom_codes": ("request_route_failure", "endpoint_owner_mismatch"),
        "topology_roles": ("service", "client", "selected_workload"),
        "ownership_shape": ("service_selects_workload",),
    }
    values.update(overrides)
    return FailureFingerprint(**values)  # type: ignore[arg-type]


def _receipt(
    receipt_type: OperationalReceiptType,
    digest_character: str,
    facts: tuple[tuple[str, str | bool | int], ...],
) -> OperationalReceiptFact:
    return OperationalReceiptFact(
        receipt_type=receipt_type,
        receipt_digest=digest_character * 64,
        occurred_at=T0,
        facts=facts,
    )


def _case_input(
    *,
    outcome_class: OperationalOutcomeClass = OperationalOutcomeClass.SUCCESS,
    receipts: tuple[OperationalReceiptFact, ...] | None = None,
) -> OperationalCaseInput:
    response_status = (
        "mismatch" if outcome_class is not OperationalOutcomeClass.SUCCESS else "verified"
    )
    standard_receipts = (
        _receipt(
            OperationalReceiptType.AUDIT,
            "1",
            (("event_type", "action.completed"), ("decision", "auto"), ("mode", "shadow")),
        ),
        _receipt(
            OperationalReceiptType.ACTION,
            "2",
            (
                ("action_type", "ops.restart-service"),
                ("execution_outcome", outcome_class.value),
                ("dry_run_digest", "a" * 64),
                ("terminal_receipt_digest", "b" * 64),
            ),
        ),
        _receipt(
            OperationalReceiptType.RESPONSE_OUTCOME,
            "3",
            (
                ("label", response_status),
                ("verification_status", response_status),
                ("execution_outcome", outcome_class.value),
                ("rollback_succeeded", outcome_class is OperationalOutcomeClass.ROLLBACK),
                ("recurrence", outcome_class is OperationalOutcomeClass.RECURRENCE),
            ),
        ),
        _receipt(
            OperationalReceiptType.EVALUATION,
            "4",
            (
                ("validation_status", "accepted"),
                ("evidence_digest", "c" * 64),
                ("operationalized", True),
                ("azure_validated", False),
            ),
        ),
    )
    return OperationalCaseInput(
        case_identity_digest="d" * 64,
        kind=CaseKind.ACTION,
        correlation_digest="e" * 64,
        purpose="operational-learning",
        access_scope_digest="f" * 64,
        redaction_policy_version="1.0.0",
        event_time_cutoff=T0,
        failure_fingerprint=_fingerprint(),
        action_type="ops.restart-service",
        outcome_class=outcome_class,
        evidence_refs=("9" * 64, "8" * 64),
        receipts=standard_receipts if receipts is None else receipts,
    )


def test_failure_fingerprint_is_environment_and_order_independent() -> None:
    first = _fingerprint()
    differently_named_environment = _fingerprint(
        symptom_codes=("endpoint_owner_mismatch", "request_route_failure"),
        topology_roles=("selected_workload", "client", "service", "client"),
    )

    assert first.digest == differently_named_environment.digest
    assert b"environment" not in first.canonical_bytes()
    assert b"action" not in first.canonical_bytes()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("resource_type", "kubernetes.deployment"),
        ("failure_mechanism", "readiness_probe_failure"),
        ("symptom_codes", ("request_route_failure",)),
        ("topology_roles", ("service", "selected_workload")),
        ("ownership_shape", ("service_routes_to_workload",)),
    ],
)
def test_failure_fingerprint_changes_with_mechanism_or_graph_shape(
    field: str,
    value: object,
) -> None:
    assert _fingerprint().digest != _fingerprint(**{field: value}).digest


@pytest.mark.parametrize(
    "value",
    ["Cluster One", "namespace/team-a", "https://example.com", "selector target mismatch"],
)
def test_failure_fingerprint_rejects_noncanonical_or_raw_identifiers(value: str) -> None:
    with pytest.raises(ValueError, match="canonical identifier"):
        _fingerprint(failure_mechanism=value)


def test_operational_case_projection_preserves_immutable_case_evidence() -> None:
    projection = OperationalCaseProjection(
        case_id="case-1",
        case_revision=2,
        manifest_digest="a" * 64,
        failure_fingerprint=_fingerprint(),
        action_type="ops.restart-service",
        outcome_class=OperationalOutcomeClass.ROLLBACK,
        evidence_refs=("audit:2", "audit:1", "audit:2"),
    )

    assert projection.failure_fingerprint.digest == _fingerprint().digest
    assert projection.evidence_refs == ("audit:1", "audit:2")


def test_operational_case_projection_rejects_unsealed_case() -> None:
    with pytest.raises(ValueError, match="manifest digest"):
        OperationalCaseProjection(
            case_id="case-1",
            case_revision=1,
            manifest_digest="not-sealed",
            failure_fingerprint=_fingerprint(),
            action_type="ops.restart-service",
            outcome_class=OperationalOutcomeClass.SUCCESS,
            evidence_refs=("audit:1",),
        )


@pytest.mark.parametrize(
    "outcome_class",
    [
        OperationalOutcomeClass.REFUSAL,
        OperationalOutcomeClass.ROLLBACK,
        OperationalOutcomeClass.RECURRENCE,
    ],
)
def test_operational_case_compiler_preserves_negative_outcomes(
    outcome_class: OperationalOutcomeClass,
) -> None:
    compiled = compile_operational_case(_case_input(outcome_class=outcome_class))

    assert len(compiled.sources) == 5
    projection_source = compiled.sources[0]
    assert projection_source.record_type == "operational-case-projection"
    assert projection_source.payload["failure_fingerprint"] == _fingerprint().digest
    assert projection_source.payload["evidence_refs"] == ("8" * 64, "9" * 64)
    response = next(
        source
        for source in compiled.sources
        if source.record_type == "operational-response_outcome-receipt"
    )
    assert response.payload["execution_outcome"] == outcome_class.value
    projection = compiled.projection(
        case_id="case-1",
        case_revision=1,
        manifest_digest="a" * 64,
    )
    assert projection.outcome_class is outcome_class


def test_operational_receipt_rejects_secret_or_free_form_fact() -> None:
    with pytest.raises(ValueError, match="standard schema"):
        _receipt(
            OperationalReceiptType.AUDIT,
            "1",
            (
                ("event_type", "action.completed"),
                ("decision", "auto"),
                ("mode", "shadow"),
                ("prompt", "ignore-prior-instructions"),
            ),
        )
    with pytest.raises(ValueError, match="canonical identifier"):
        _receipt(
            OperationalReceiptType.AUDIT,
            "1",
            (
                ("event_type", "action.completed"),
                ("decision", "Bearer secret-token-value-123456"),
                ("mode", "shadow"),
            ),
        )


def test_operational_case_rejects_receipt_authority_mismatch() -> None:
    receipts = list(_case_input().receipts)
    action_index = next(
        index
        for index, receipt in enumerate(receipts)
        if receipt.receipt_type is OperationalReceiptType.ACTION
    )
    receipts[action_index] = _receipt(
        OperationalReceiptType.ACTION,
        "2",
        (
            ("action_type", "ops.scale-service"),
            ("execution_outcome", "success"),
            ("dry_run_digest", "a" * 64),
            ("terminal_receipt_digest", "b" * 64),
        ),
    )
    with pytest.raises(ValueError, match="match the case action type"):
        _case_input(receipts=tuple(receipts))


def test_operational_case_rejects_duplicate_authoritative_receipt() -> None:
    case_input = _case_input()
    audit = next(
        receipt
        for receipt in case_input.receipts
        if receipt.receipt_type is OperationalReceiptType.AUDIT
    )
    duplicate = replace(audit, receipt_digest="6" * 64)

    with pytest.raises(ValueError, match="authoritative receipt types MUST be unique"):
        replace(case_input, receipts=(*case_input.receipts, duplicate))


def test_operational_case_rejects_oversized_wire_payload() -> None:
    case_input = _case_input()
    mapping = case_input.to_mapping()
    mapping["unexpected_padding"] = "x" * (64 * 1024)

    with pytest.raises(ValueError, match="byte limit"):
        OperationalCaseInput.from_mapping(mapping)


@pytest.mark.parametrize("flag", ["rollback_succeeded", "recurrence"])
def test_operational_case_rejects_control_flag_outcome_mismatch(flag: str) -> None:
    receipts = list(_case_input().receipts)
    response_index = next(
        index
        for index, receipt in enumerate(receipts)
        if receipt.receipt_type is OperationalReceiptType.RESPONSE_OUTCOME
    )
    response = receipts[response_index]
    facts = dict(response.facts)
    facts[flag] = True
    receipts[response_index] = _receipt(
        OperationalReceiptType.RESPONSE_OUTCOME,
        "3",
        tuple(facts.items()),
    )

    with pytest.raises(ValueError, match=rf"{flag} MUST match"):
        _case_input(receipts=tuple(receipts))


def test_operational_case_input_strict_wire_round_trip() -> None:
    case_input = _case_input()

    assert OperationalCaseInput.from_mapping(case_input.to_mapping()) == case_input


def test_operational_case_input_rejects_unknown_wire_fields() -> None:
    payload = _case_input().to_mapping()
    payload["benchmark_name"] = "must-not-cross-boundary"

    with pytest.raises(ValueError, match="standard schema"):
        OperationalCaseInput.from_mapping(payload)

    fingerprint = payload["failure_fingerprint"]
    assert isinstance(fingerprint, dict)
    fingerprint["environment"] = "must-not-enter-fingerprint"
    payload.pop("benchmark_name")

    with pytest.raises(ValueError, match="standard schema"):
        OperationalCaseInput.from_mapping(payload)
