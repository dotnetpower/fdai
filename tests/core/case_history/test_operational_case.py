from __future__ import annotations

import pytest

from fdai.core.case_history import (
    FailureFingerprint,
    OperationalCaseProjection,
    OperationalOutcomeClass,
)


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
