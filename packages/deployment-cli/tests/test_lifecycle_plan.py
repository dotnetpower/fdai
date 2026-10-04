from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fdai_deployment_cli.contracts import canonical_bytes
from fdai_deployment_cli.lifecycle_plan import (
    DataResidencyRequirement,
    LifecycleConstraintContext,
    LifecycleEffectEnvelope,
    LifecyclePlan,
    MaintenanceWindow,
    PlanAdmissionState,
    SuppressionWindow,
    canonical_plan_payload,
    evaluate_lifecycle_constraints,
    evaluate_plan_admission,
)
from fdai_deployment_cli.runtime_release import RecallRecord, RuntimeRelease, SchemaRange

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _release(
    *,
    version: str = "1.5.0",
    schema_target: int = 15,
    schema_range: SchemaRange | None = None,
    capabilities: Mapping[str, str] | None = None,
    image_digests: Mapping[str, str] | None = None,
    downtime_entities: tuple[str, ...] = (),
) -> RuntimeRelease:
    resolved_schema_range = schema_range or SchemaRange(minimum=12, maximum=16)
    resolved_images = {"core": _digest("image-core")} if image_digests is None else image_digests
    catalog = {
        "services": {
            name: {"image_digest": digest} for name, digest in sorted(resolved_images.items())
        }
    }
    return RuntimeRelease(
        source_commit=_digest("source")[:40],
        platform_tag="linux-x86_64",
        deployment_bundle_sha256=_digest("bundle"),
        digest=_digest(f"release-{version}"),
        artifact_paths=(),
        _catalog=canonical_bytes(catalog),
        schema_version="fdai.runtime-release.v3",
        schema_target=schema_target,
        schema_range=resolved_schema_range,
        capability_maximums=dict(capabilities or {"action:scale-service": "enforce"}),
        downtime_entities=downtime_entities,
    )


class _Verifier:
    def __init__(self, *, allowed: object = True, fail: bool = False) -> None:
        self.allowed = allowed
        self.fail = fail
        self.calls: list[tuple[str, bytes, bytes]] = []

    def __call__(self, key_id: str, payload: bytes, signature: bytes) -> object:
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
        plan_type="upgrade",
        target_release_id="1.5.0",
        target_release_digest=_digest("release-1.5.0"),
        configuration_revision_digest=_digest("config"),
        entity_ids=frozenset({"core"}),
        rollback_target_plan_id=None,
        declared_duration_minutes=15,
        envelope=_envelope(entity_ids=frozenset({"core"}), max_duration_minutes=20),
        expires_at=NOW + timedelta(minutes=10),
        signed_payload=b"",
        signature=b"synthetic-signature",
    )
    plan = replace(base, **overrides)
    if "signed_payload" not in overrides:
        plan = replace(plan, signed_payload=canonical_plan_payload(plan))
    return plan


def _state() -> PlanAdmissionState:
    return PlanAdmissionState(
        expected_audience="installation-alpha",
        expected_source_state_digest=_digest("state"),
        last_accepted_sequence=7,
        current_hub_key_epoch=3,
        current_fencing_generation=4,
        active_hub_key_ids=frozenset({"hub-key-active"}),
        revoked_hub_key_ids=frozenset({"hub-key-revoked"}),
        hub_key_epochs={"hub-key-active": 3, "hub-key-revoked": 2},
    )


def _configuration_schema() -> dict[str, object]:
    return {
        "region": {
            "default": "korea-central",
            "x-fdai-axis": "Deployment environment",
            "x-fdai-owner": "customer",
        },
        "replicas": {
            "default": 1,
            "x-fdai-axis": "Release channel subscription",
            "x-fdai-owner": "customer",
        },
    }


def _passing_context(**overrides: object) -> LifecycleConstraintContext:
    digest = _digest("image-core")
    base = LifecycleConstraintContext(
        now=NOW,
        plan_id="plan-upgrade",
        plan_type="upgrade",
        rollback_target_plan_id=None,
        declared_duration_minutes=15,
        requires_downtime=False,
        target_release_version="1.5.0",
        candidate_release=_release(image_digests={"core": digest}),
        configuration_revision_digest=_digest("config"),
        current_schema_revision=12,
        version_range=">=1.4.0 <1.6.0",
        configuration_schema=_configuration_schema(),
        environment_config={"region": "korea-central"},
        entity_overrides=(
            {
                "versions": ">=1.5.0 <1.6.0",
                "values": {"replicas": 2},
            },
        ),
        available_artifact_digests=frozenset({digest}),
        data_residency=DataResidencyRequirement(
            allowed_regions=frozenset({"korea-central"}),
            release_regions=frozenset({"korea-central"}),
        ),
        maintenance_windows=(
            MaintenanceWindow(
                starts_at=NOW - timedelta(minutes=5),
                ends_at=NOW + timedelta(minutes=20),
                allows_downtime=False,
            ),
        ),
        suppression_windows=(),
        entity_ids=frozenset({"core"}),
        capability_ids=("action:scale-service",),
        recall_records=(),
    )
    return replace(base, **overrides)


def test_plan_admission_allows_narrow_signed_plan() -> None:
    verifier = _Verifier()

    decision = evaluate_plan_admission(
        _plan(),
        local_state=_state(),
        locally_derived_maximum=_envelope(),
        verify_signature=verifier,
        trusted_now=NOW,
    )

    assert decision.allowed is True
    assert decision.reason_code == "allowed"
    assert verifier.calls == [
        ("hub-key-active", canonical_plan_payload(_plan()), b"synthetic-signature")
    ]


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
            trusted_now=NOW,
        )
        assert decision.allowed is False
        assert decision.reason_code == reason_code


def test_plan_admission_rejects_replay_or_retarget_not_bound_to_payload() -> None:
    signed = _plan()
    replayed = replace(signed, sequence=9)
    retargeted = replace(signed, audience="installation-beta")

    for plan in (replayed, retargeted):
        decision = evaluate_plan_admission(
            plan,
            local_state=_state(),
            locally_derived_maximum=_envelope(),
            verify_signature=_Verifier(),
            trusted_now=NOW,
        )
        assert decision.allowed is False
        assert decision.reason_code == "plan_payload_mismatch"


def test_plan_admission_fails_closed_when_signature_cannot_be_verified() -> None:
    invalid_signature = evaluate_plan_admission(
        _plan(),
        local_state=_state(),
        locally_derived_maximum=_envelope(),
        verify_signature=_Verifier(allowed=False),
        trusted_now=NOW,
    )
    truthy_non_bool = evaluate_plan_admission(
        _plan(),
        local_state=_state(),
        locally_derived_maximum=_envelope(),
        verify_signature=_Verifier(allowed=1),
        trusted_now=NOW,
    )
    verifier_error = evaluate_plan_admission(
        _plan(),
        local_state=_state(),
        locally_derived_maximum=_envelope(),
        verify_signature=_Verifier(fail=True),
        trusted_now=NOW,
    )

    assert invalid_signature.allowed is False
    assert invalid_signature.reason_code == "plan_signature_invalid"
    assert truthy_non_bool.allowed is False
    assert truthy_non_bool.reason_code == "plan_signature_invalid"
    assert verifier_error.allowed is False
    assert verifier_error.reason_code == "plan_signature_invalid"


def test_plan_admission_rejects_key_epoch_and_expiry_failures() -> None:
    epoch_state = replace(_state(), current_hub_key_epoch=4)
    key_epoch_state = replace(_state(), hub_key_epochs={"hub-key-active": 4})
    expired = _plan(expires_at=NOW - timedelta(seconds=1))
    naive_expiry = _plan(expires_at=NOW.replace(tzinfo=None))

    cases = (
        (_plan(), epoch_state, NOW, "hub_key_epoch_mismatch"),
        (_plan(), key_epoch_state, NOW, "hub_key_epoch_mismatch"),
        (expired, _state(), NOW, "plan_expired"),
        (naive_expiry, _state(), NOW, "plan_expiry_timezone_missing"),
        (_plan(), _state(), NOW.replace(tzinfo=None), "trusted_clock_timezone_missing"),
    )

    for plan, state, trusted_now, reason_code in cases:
        decision = evaluate_plan_admission(
            plan,
            local_state=state,
            locally_derived_maximum=_envelope(),
            verify_signature=_Verifier(),
            trusted_now=trusted_now,
        )
        assert decision.allowed is False
        assert decision.reason_code == reason_code


def test_constraint_evaluator_reports_every_blocking_constraint() -> None:
    context = LifecycleConstraintContext(
        now=NOW,
        plan_id="plan-upgrade",
        plan_type="upgrade",
        rollback_target_plan_id=None,
        declared_duration_minutes=45,
        requires_downtime=True,
        target_release_version="1.5.0",
        candidate_release=_release(
            image_digests={
                "core": _digest("image-core"),
                "operator-api": _digest("image-operator"),
            }
        ),
        configuration_revision_digest=_digest("config"),
        current_schema_revision=17,
        version_range=">=1.4.0 <1.5.0",
        configuration_schema=_configuration_schema(),
        environment_config={"replicas": 2},
        entity_overrides=(),
        available_artifact_digests=frozenset({_digest("image-core")}),
        data_residency=DataResidencyRequirement(
            allowed_regions=frozenset({"korea-central"}),
            release_regions=frozenset({"east-us"}),
        ),
        maintenance_windows=(
            MaintenanceWindow(
                starts_at=NOW - timedelta(minutes=10),
                ends_at=NOW + timedelta(minutes=20),
                allows_downtime=False,
            ),
        ),
        suppression_windows=(
            SuppressionWindow(
                scope="entity:core",
                starts_at=NOW - timedelta(minutes=5),
                ends_at=NOW + timedelta(minutes=30),
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

    blocks = evaluate_lifecycle_constraints(
        context, admitted_plan=_plan(declared_duration_minutes=45)
    )

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
    assert evaluate_lifecycle_constraints(_passing_context(), admitted_plan=_plan()) == ()


def test_constraint_context_must_match_signed_plan_fields() -> None:
    plan_type_switch = evaluate_lifecycle_constraints(
        _passing_context(plan_type="recall-rolloff", current_schema_revision=16),
        admitted_plan=_plan(),
    )
    release_swap = evaluate_lifecycle_constraints(
        _passing_context(candidate_release=_release(version="1.5.1")),
        admitted_plan=_plan(),
    )

    assert {block.reason_code for block in plan_type_switch} == {"plan_context_mismatch"}
    assert {block.reason_code for block in release_swap} == {"target_release_digest_mismatch"}


def test_suppression_windows_fail_closed_for_malformed_or_unmatched_scope() -> None:
    scopes = (
        "Installation",
        "entity: core",
        "entity:Core",
        "plan:Upgrade",
        "entity:*",
        "*",
        "global",
    )

    for scope in scopes:
        blocks = evaluate_lifecycle_constraints(
            _passing_context(
                suppression_windows=(
                    SuppressionWindow(
                        scope=scope,
                        starts_at=NOW - timedelta(minutes=1),
                        ends_at=NOW + timedelta(minutes=1),
                    ),
                ),
            ),
            admitted_plan=_plan(),
        )
        assert [block.reason_code for block in blocks] == ["suppression_scope_invalid"]

    inverted = evaluate_lifecycle_constraints(
        _passing_context(
            suppression_windows=(
                SuppressionWindow(
                    scope="installation",
                    starts_at=NOW + timedelta(minutes=1),
                    ends_at=NOW - timedelta(minutes=1),
                ),
            ),
        ),
        admitted_plan=_plan(),
    )
    non_matching_active = evaluate_lifecycle_constraints(
        _passing_context(
            suppression_windows=(
                SuppressionWindow(
                    scope="entity:operator-api",
                    starts_at=NOW - timedelta(minutes=1),
                    ends_at=NOW + timedelta(minutes=1),
                ),
            ),
        ),
        admitted_plan=_plan(),
    )
    non_matching_expired = evaluate_lifecycle_constraints(
        _passing_context(
            suppression_windows=(
                SuppressionWindow(
                    scope="entity:operator-api",
                    starts_at=NOW - timedelta(minutes=3),
                    ends_at=NOW - timedelta(minutes=2),
                ),
            ),
        ),
        admitted_plan=_plan(),
    )
    assert [block.reason_code for block in inverted] == ["suppression_window_invalid"]
    assert non_matching_active == ()
    assert non_matching_expired == ()


def test_failure_suppression_exempts_only_matching_rollback_plan() -> None:
    window = SuppressionWindow(
        scope="installation",
        starts_at=NOW - timedelta(minutes=1),
        ends_at=NOW + timedelta(minutes=1),
        origin="failure",
        failed_plan_id="failed-plan",
    )

    exempt = evaluate_lifecycle_constraints(
        _passing_context(
            plan_type="rollback",
            rollback_target_plan_id="failed-plan",
            suppression_windows=(window,),
            current_schema_revision=16,
        ),
        admitted_plan=_plan(
            plan_type="rollback",
            rollback_target_plan_id="failed-plan",
            declared_duration_minutes=15,
        ),
    )
    different_rollback = evaluate_lifecycle_constraints(
        _passing_context(
            plan_type="rollback",
            rollback_target_plan_id="other-plan",
            suppression_windows=(window,),
            current_schema_revision=16,
        ),
        admitted_plan=_plan(
            plan_type="rollback",
            rollback_target_plan_id="other-plan",
            declared_duration_minutes=15,
        ),
    )
    manual_recall = evaluate_lifecycle_constraints(
        _passing_context(
            plan_type="recall-rolloff",
            suppression_windows=(
                SuppressionWindow(
                    scope="installation",
                    starts_at=NOW - timedelta(minutes=1),
                    ends_at=NOW + timedelta(minutes=1),
                    origin="manual",
                ),
            ),
            current_schema_revision=16,
        ),
        admitted_plan=_plan(plan_type="recall-rolloff", declared_duration_minutes=15),
    )

    assert {block.reason_code for block in exempt} == set()
    assert "suppression_window_active" in {block.reason_code for block in different_rollback}
    assert "suppression_window_active" in {block.reason_code for block in manual_recall}


def test_constraints_derive_downtime_artifacts_residency_and_schema_direction() -> None:
    derived_downtime = evaluate_lifecycle_constraints(
        _passing_context(
            candidate_release=_release(
                image_digests={"core": _digest("image-core")},
                downtime_entities=("core",),
            )
        ),
        admitted_plan=_plan(),
    )
    missing_artifacts = evaluate_lifecycle_constraints(
        _passing_context(candidate_release=_release(image_digests={})),
        admitted_plan=_plan(),
    )
    empty_residency = evaluate_lifecycle_constraints(
        _passing_context(
            data_residency=DataResidencyRequirement(
                allowed_regions=frozenset({"korea-central"}),
                release_regions=frozenset(),
            )
        ),
        admitted_plan=_plan(),
    )
    rollback_schema = evaluate_lifecycle_constraints(
        _passing_context(plan_type="rollback", current_schema_revision=16),
        admitted_plan=_plan(plan_type="rollback"),
    )

    assert "maintenance_window_unavailable" in {block.reason_code for block in derived_downtime}
    assert "artifact_requirements_missing" in {block.reason_code for block in missing_artifacts}
    assert "data_residency_missing" in {block.reason_code for block in empty_residency}
    assert "schema_target_not_forward" not in {block.reason_code for block in rollback_schema}
