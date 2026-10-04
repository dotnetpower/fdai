from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai_deployment_cli.lifecycle_plan import (
    ArtifactRequirement,
    DataResidencyRequirement,
    LifecycleConstraintContext,
    LifecycleEffectEnvelope,
    LifecyclePlan,
    MaintenanceWindow,
    PlanAdmissionState,
    SuppressionWindow,
    evaluate_lifecycle_constraints,
    evaluate_plan_admission,
)
from fdai_deployment_cli.runtime_release import RecallRecord, RuntimeRelease, SchemaRange


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _release(
    *,
    version: str = "1.5.0",
    schema_target: int = 15,
    schema_range: SchemaRange | None = None,
    capabilities: Mapping[str, str] | None = None,
) -> RuntimeRelease:
    resolved_schema_range = schema_range or SchemaRange(minimum=12, maximum=16)
    return RuntimeRelease(
        source_commit=_digest("source")[:40],
        platform_tag="linux-x86_64",
        deployment_bundle_sha256=_digest("bundle"),
        digest=_digest(f"release-{version}"),
        artifact_paths=(),
        _catalog=b"{}",
        schema_version="fdai.runtime-release.v3",
        schema_target=schema_target,
        schema_range=resolved_schema_range,
        capability_maximums=dict(capabilities or {"action:scale-service": "enforce"}),
    )


class _Verifier:
    def __init__(self, *, allowed: bool = True, fail: bool = False) -> None:
        self.allowed = allowed
        self.fail = fail
        self.calls: list[tuple[str, bytes, bytes]] = []

    def __call__(self, key_id: str, payload: bytes, signature: bytes) -> bool:
        self.calls.append((key_id, payload, signature))
        if self.fail:
            raise ValueError("synthetic verifier failure")
        return self.allowed


def _envelope(**overrides: object) -> LifecycleEffectEnvelope:
    base = LifecycleEffectEnvelope(
        entity_ids=frozenset({"core", "operator-api"}),
        regions=frozenset({"korea-central"}),
        capability_modes={"action:scale-service": "enforce"},
        destructive_allowed=False,
        max_duration_minutes=30,
    )
    return replace(base, **overrides)


def _plan(**overrides: object) -> LifecyclePlan:
    base = LifecyclePlan(
        plan_id="plan-upgrade",
        audience="installation-alpha",
        hub_key_epoch=3,
        hub_key_id="hub-key-active",
        source_state_digest=_digest("state"),
        sequence=8,
        fencing_generation=4,
        envelope=_envelope(entity_ids=frozenset({"core"}), max_duration_minutes=20),
        signed_payload=b"canonical-plan-payload",
        signature=b"synthetic-signature",
    )
    return replace(base, **overrides)


def _state() -> PlanAdmissionState:
    return PlanAdmissionState(
        expected_audience="installation-alpha",
        expected_source_state_digest=_digest("state"),
        last_accepted_sequence=7,
        current_fencing_generation=4,
        active_hub_key_ids=frozenset({"hub-key-active"}),
        revoked_hub_key_ids=frozenset({"hub-key-revoked"}),
    )


def test_plan_admission_allows_narrow_signed_plan() -> None:
    verifier = _Verifier()

    decision = evaluate_plan_admission(
        _plan(),
        local_state=_state(),
        locally_derived_maximum=_envelope(),
        verify_signature=verifier,
    )

    assert decision.allowed is True
    assert decision.reason_code == "allowed"
    assert verifier.calls == [("hub-key-active", b"canonical-plan-payload", b"synthetic-signature")]


def test_plan_admission_rejects_required_safety_boundaries_before_signature() -> None:
    cases = (
        (
            _plan(sequence=7),
            _state(),
            _envelope(),
            "plan_sequence_stale",
        ),
        (
            _plan(audience="other-installation"),
            _state(),
            _envelope(),
            "plan_audience_mismatch",
        ),
        (
            _plan(hub_key_id="hub-key-revoked"),
            _state(),
            _envelope(),
            "hub_key_revoked",
        ),
        (
            _plan(envelope=_envelope(destructive_allowed=True)),
            _state(),
            _envelope(),
            "plan_envelope_exceeds_local_maximum",
        ),
    )

    for plan, state, maximum, reason_code in cases:
        verifier = _Verifier()
        decision = evaluate_plan_admission(
            plan,
            local_state=state,
            locally_derived_maximum=maximum,
            verify_signature=verifier,
        )
        assert decision.allowed is False
        assert decision.reason_code == reason_code
        assert verifier.calls == []


def test_plan_admission_fails_closed_when_signature_cannot_be_verified() -> None:
    invalid_signature = evaluate_plan_admission(
        _plan(),
        local_state=_state(),
        locally_derived_maximum=_envelope(),
        verify_signature=_Verifier(allowed=False),
    )
    verifier_error = evaluate_plan_admission(
        _plan(),
        local_state=_state(),
        locally_derived_maximum=_envelope(),
        verify_signature=_Verifier(fail=True),
    )

    assert invalid_signature.allowed is False
    assert invalid_signature.reason_code == "plan_signature_invalid"
    assert verifier_error.allowed is False
    assert verifier_error.reason_code == "plan_signature_invalid"


def test_constraint_evaluator_reports_every_blocking_constraint() -> None:
    now = datetime(2026, 10, 5, 12, tzinfo=UTC)
    context = LifecycleConstraintContext(
        now=now,
        plan_type="upgrade",
        declared_duration_minutes=45,
        requires_downtime=True,
        target_release_version="1.5.0",
        candidate_release=_release(),
        current_schema_revision=17,
        schema_direction="upgrade",
        version_range=">=1.4.0 <1.5.0",
        release_defaults={"replicas": 1},
        environment_config={"replicas": 2},
        entity_overrides=(),
        required_artifacts=(
            ArtifactRequirement(name="core", digest=_digest("image-core")),
            ArtifactRequirement(name="operator-api", digest=_digest("image-operator")),
        ),
        available_artifact_digests=frozenset({_digest("image-core")}),
        data_residency=DataResidencyRequirement(
            allowed_regions=frozenset({"korea-central"}),
            release_regions=frozenset({"east-us"}),
        ),
        maintenance_windows=(
            MaintenanceWindow(
                starts_at=now - timedelta(minutes=10),
                ends_at=now + timedelta(minutes=20),
                allows_downtime=False,
            ),
        ),
        suppression_windows=(
            SuppressionWindow(
                scope="entity:core",
                starts_at=now - timedelta(minutes=5),
                ends_at=now + timedelta(minutes=30),
            ),
        ),
        entity_ids=frozenset({"core"}),
        capability_ids=("action:scale-service",),
        recall_records=(
            RecallRecord(
                scope="release",
                target="1.5.0",
                sequence=1,
                notice_digest=_digest("recall"),
            ),
        ),
    )

    blocks = evaluate_lifecycle_constraints(context)

    assert {block.reason_code for block in blocks} == {
        "maintenance_window_unavailable",
        "suppression_window_active",
        "release_version_outside_range",
        "schema_revision_outside_tolerated_range",
        "artifact_unavailable",
        "override_coverage_missing",
        "data_residency_mismatch",
        "release_recalled",
    }


def test_constraint_evaluator_allows_candidate_when_every_constraint_passes() -> None:
    now = datetime(2026, 10, 5, 12, tzinfo=UTC)
    digest = _digest("image-core")
    context = LifecycleConstraintContext(
        now=now,
        plan_type="upgrade",
        declared_duration_minutes=15,
        requires_downtime=False,
        target_release_version="1.5.0",
        candidate_release=_release(),
        current_schema_revision=12,
        schema_direction="upgrade",
        version_range=">=1.4.0 <1.6.0",
        release_defaults={"replicas": 1},
        environment_config={"region": "korea-central"},
        entity_overrides=(
            {
                "version_range": ">=1.5.0 <1.6.0",
                "values": {"replicas": 2},
            },
        ),
        required_artifacts=(ArtifactRequirement(name="core", digest=digest),),
        available_artifact_digests=frozenset({digest}),
        data_residency=DataResidencyRequirement(
            allowed_regions=frozenset({"korea-central"}),
            release_regions=frozenset({"korea-central"}),
        ),
        maintenance_windows=(
            MaintenanceWindow(
                starts_at=now - timedelta(minutes=5),
                ends_at=now + timedelta(minutes=20),
                allows_downtime=False,
            ),
        ),
        suppression_windows=(),
        entity_ids=frozenset({"core"}),
        capability_ids=("action:scale-service",),
        recall_records=(),
    )

    assert evaluate_lifecycle_constraints(context) == ()
