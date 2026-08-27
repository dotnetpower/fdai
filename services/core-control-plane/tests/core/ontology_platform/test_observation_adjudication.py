"""Deterministic adjudication of repeated observations of one target."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.observation_adjudication import (
    CONFLICT_TRUNCATED,
    MAX_OBSERVATION_CONFLICTS,
    CrossSourceReadConfidence,
    CrossSourceStateStatus,
    ObservationIdentityConflictError,
    ObservedClaim,
    StateEvidenceSnapshot,
    adjudicate_independent_observations,
    adjudicate_observations,
    adjudicate_projected_state,
)
from fdai.shared.providers.state_evidence import (
    StateFactAuthority,
    StateFactLane,
    StateFactMetadata,
)

OBSERVED_AT = datetime(2026, 8, 8, 12, tzinfo=UTC)


def _claim(
    *,
    properties: dict[str, object] | None = None,
    provider_ref: str | None = "provider-ref-1",
    offset_seconds: int = 0,
    type_id: str = "compute.vm",
) -> ObservedClaim:
    return ObservedClaim(
        type=type_id,
        properties=properties if properties is not None else {"status": "running"},
        provider_ref=provider_ref,
        observed_at=OBSERVED_AT + timedelta(seconds=offset_seconds),
    )


def _metadata(
    *,
    authority: StateFactAuthority,
    age_seconds: int = 30,
    completeness: float = 1.0,
    conflicts: tuple[str, ...] = (),
) -> StateFactMetadata:
    cutoff = OBSERVED_AT - timedelta(seconds=age_seconds)
    return StateFactMetadata(
        lane=StateFactLane.OBSERVED,
        authority=authority,
        source_identity=f"{authority.value}-source",
        source_revision=f"{authority.value}-revision",
        effective_at=cutoff,
        evidence_cutoff=cutoff,
        recorded_at=cutoff,
        freshness_ceiling_seconds=300,
        completeness=completeness,
        synthetic=False,
        conflicts=conflicts,
        evidence_refs=(f"{authority.value}-evidence",),
    )


def _snapshot(
    *,
    authority: StateFactAuthority,
    state: dict[str, object] | None = None,
    age_seconds: int = 30,
    target_id: str = "resource-example",
    scope_ref: str = "scope-example",
    censoring_refs: tuple[str, ...] = (),
    conflicts: tuple[str, ...] = (),
) -> StateEvidenceSnapshot:
    return StateEvidenceSnapshot(
        target_id=target_id,
        scope_ref=scope_ref,
        state=state if state is not None else {"status": "running", "replicas": 2},
        metadata=_metadata(
            authority=authority,
            age_seconds=age_seconds,
            conflicts=conflicts,
        ),
        censoring_refs=censoring_refs,
    )


def _adjudicate(
    *,
    projection: StateEvidenceSnapshot | None = None,
    telemetry: StateEvidenceSnapshot | None = None,
):
    return adjudicate_projected_state(
        projection=projection or _snapshot(authority=StateFactAuthority.PROVIDER),
        telemetry=telemetry,
        evaluated_at=OBSERVED_AT,
    )


def test_single_claim_agrees_with_itself() -> None:
    verdict = adjudicate_observations((_claim(),))

    assert verdict.conflicts == ()
    assert verdict.contested is False
    assert verdict.agreed_properties == {"status": "running"}
    assert verdict.observed_at == OBSERVED_AT


def test_equal_content_with_different_observation_times_is_not_a_conflict() -> None:
    verdict = adjudicate_observations(
        (_claim(offset_seconds=30), _claim(offset_seconds=0)),
    )

    assert verdict.conflicts == ()
    assert verdict.agreed_properties == {"status": "running"}


def test_earliest_observation_time_is_kept_so_freshness_is_never_inflated() -> None:
    verdict = adjudicate_observations(
        (_claim(offset_seconds=600), _claim(offset_seconds=5), _claim(offset_seconds=90)),
    )

    assert verdict.observed_at == OBSERVED_AT + timedelta(seconds=5)


def test_disagreeing_value_becomes_an_explicit_conflict_and_is_withheld() -> None:
    verdict = adjudicate_observations(
        (
            _claim(properties={"status": "running", "region": "koreacentral"}),
            _claim(properties={"status": "deallocated", "region": "koreacentral"}),
        ),
    )

    assert verdict.conflicts == ("observed_property_conflict:status",)
    assert verdict.agreed_properties == {"region": "koreacentral"}


def test_absent_property_on_one_side_is_a_conflict_not_a_merge() -> None:
    verdict = adjudicate_observations(
        (
            _claim(properties={"status": "running", "sku": "Standard_D2s_v5"}),
            _claim(properties={"status": "running"}),
        ),
    )

    assert verdict.conflicts == ("observed_property_conflict:sku",)
    assert verdict.agreed_properties == {"status": "running"}


def test_numeric_disagreement_is_never_averaged() -> None:
    verdict = adjudicate_observations(
        (
            _claim(properties={"replicas": 2}),
            _claim(properties={"replicas": 4}),
        ),
    )

    assert verdict.conflicts == ("observed_property_conflict:replicas",)
    assert "replicas" not in verdict.agreed_properties


def test_latest_observation_never_wins_a_disagreement() -> None:
    verdict = adjudicate_observations(
        (
            _claim(properties={"status": "running"}, offset_seconds=0),
            _claim(properties={"status": "deallocated"}, offset_seconds=600),
        ),
    )

    assert verdict.contested is True
    assert "status" not in verdict.agreed_properties


def test_nested_mapping_equality_is_order_independent() -> None:
    verdict = adjudicate_observations(
        (
            _claim(properties={"tags": {"env": "dev", "owner": "sre"}}),
            _claim(properties={"tags": {"owner": "sre", "env": "dev"}}),
        ),
    )

    assert verdict.conflicts == ()


def test_disagreeing_provider_ref_is_an_explicit_conflict() -> None:
    verdict = adjudicate_observations(
        (
            _claim(provider_ref="provider-ref-1"),
            _claim(provider_ref="provider-ref-2"),
        ),
    )

    assert "observed_provider_ref_conflict" in verdict.conflicts


def test_independent_providers_agree_without_increasing_authority() -> None:
    verdict = adjudicate_independent_observations(
        (
            _claim(provider_ref="provider-ref-1"),
            _claim(provider_ref="provider-ref-2"),
        )
    )

    assert verdict.conflicts == ()
    assert verdict.agreed_properties == {"status": "running"}


def test_independent_provider_disagreement_withholds_only_contested_values() -> None:
    verdict = adjudicate_independent_observations(
        (
            _claim(
                provider_ref="provider-ref-1",
                properties={"status": "running", "region": "one"},
            ),
            _claim(
                provider_ref="provider-ref-2",
                properties={"status": "deallocated", "region": "one"},
            ),
        )
    )

    assert verdict.conflicts == ("observed_property_conflict:status",)
    assert verdict.agreed_properties == {"region": "one"}


@pytest.mark.parametrize(
    ("claims", "message"),
    (
        ((_claim(provider_ref="provider-ref-1"),), "at least two"),
        (
            (_claim(provider_ref=None), _claim(provider_ref="provider-ref-2")),
            "distinct provider",
        ),
        (
            (_claim(provider_ref=" "), _claim(provider_ref="provider-ref-2")),
            "distinct provider",
        ),
        (
            (_claim(provider_ref="provider-ref-1"), _claim(provider_ref="provider-ref-1")),
            "distinct provider",
        ),
    ),
)
def test_independent_adjudication_requires_distinct_provider_identity(
    claims: tuple[ObservedClaim, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        adjudicate_independent_observations(claims)


def test_conflicting_type_is_an_identity_contradiction() -> None:
    with pytest.raises(ObservationIdentityConflictError):
        adjudicate_observations((_claim(), _claim(type_id="network.nic")))


def test_empty_claim_sequence_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least one claim"):
        adjudicate_observations(())


def test_conflict_evidence_is_bounded() -> None:
    wide = MAX_OBSERVATION_CONFLICTS + 10
    verdict = adjudicate_observations(
        (
            _claim(properties={f"field-{index:03d}": index for index in range(wide)}),
            _claim(properties={f"field-{index:03d}": index + 1 for index in range(wide)}),
        ),
    )

    assert len(verdict.conflicts) == MAX_OBSERVATION_CONFLICTS
    assert verdict.conflicts[-1] == CONFLICT_TRUNCATED


def test_conflict_entries_name_keys_and_never_values() -> None:
    verdict = adjudicate_observations(
        (
            _claim(properties={"connectionString": "secret-one"}),
            _claim(properties={"connectionString": "secret-two"}),
        ),
    )

    assert verdict.conflicts == ("observed_property_conflict:connectionString",)
    assert all("secret" not in item for item in verdict.conflicts)


def test_oversized_property_key_is_truncated_in_conflict_evidence() -> None:
    key = "k" * 400
    verdict = adjudicate_observations(
        (_claim(properties={key: "one"}), _claim(properties={key: "two"})),
    )

    assert verdict.conflicts == ("observed_property_conflict:" + "k" * 96,)


def test_projected_state_agrees_with_fresh_telemetry() -> None:
    telemetry = _snapshot(authority=StateFactAuthority.TELEMETRY)

    result = _adjudicate(telemetry=telemetry)

    assert result.status is CrossSourceStateStatus.AGREED
    assert result.read_confidence is CrossSourceReadConfidence.CORROBORATED
    assert result.agreed_state == {"replicas": 2, "status": "running"}
    assert result.projection.metadata.authority is StateFactAuthority.PROVIDER
    assert result.projection.scope_ref == "scope-example"
    assert result.projection.metadata.evidence_cutoff == OBSERVED_AT - timedelta(seconds=30)
    assert result.projection.metadata.completeness == 1.0
    assert result.projection.metadata.evidence_refs == ("provider-evidence",)
    assert result.telemetry is telemetry
    assert result.telemetry.metadata.source_identity == "telemetry-source"
    assert result.execution_authority is result.mutation_authority is False


def test_missing_telemetry_preserves_only_degraded_projection_state() -> None:
    result = _adjudicate(telemetry=None)

    assert result.status is CrossSourceStateStatus.TELEMETRY_MISSING
    assert result.read_confidence is CrossSourceReadConfidence.DEGRADED
    assert result.agreed_state == {"replicas": 2, "status": "running"}
    assert result.telemetry_fresh is None


def test_stale_projection_and_stale_telemetry_remain_distinct() -> None:
    stale_projection = _adjudicate(
        projection=_snapshot(authority=StateFactAuthority.PROVIDER, age_seconds=301),
        telemetry=_snapshot(authority=StateFactAuthority.TELEMETRY),
    )
    stale_telemetry = _adjudicate(
        telemetry=_snapshot(authority=StateFactAuthority.TELEMETRY, age_seconds=301),
    )

    assert stale_projection.status is CrossSourceStateStatus.PROJECTION_STALE
    assert stale_projection.projection_fresh is False
    assert stale_telemetry.status is CrossSourceStateStatus.TELEMETRY_STALE
    assert stale_telemetry.telemetry_fresh is False


def test_cross_source_conflict_withholds_value_without_averaging() -> None:
    telemetry = _snapshot(
        authority=StateFactAuthority.TELEMETRY,
        state={"status": "running", "replicas": 4},
    )

    result = _adjudicate(telemetry=telemetry)

    assert result.status is CrossSourceStateStatus.CONFLICTING
    assert result.read_confidence is CrossSourceReadConfidence.DEGRADED
    assert result.agreed_state == {"status": "running"}
    assert result.conflicting_fields == ("replicas",)


def test_scope_mismatch_is_an_explicit_conflict_with_no_agreed_state() -> None:
    telemetry = _snapshot(
        authority=StateFactAuthority.TELEMETRY,
        scope_ref="other-scope",
    )

    result = _adjudicate(telemetry=telemetry)

    assert result.status is CrossSourceStateStatus.CONFLICTING
    assert result.conflicting_fields == ("scope_ref",)
    assert result.agreed_state == {}


def test_censored_evidence_is_unavailable_and_retains_both_sources() -> None:
    projection = _snapshot(
        authority=StateFactAuthority.PROVIDER,
        censoring_refs=("policy-redaction:one",),
    )
    telemetry = _snapshot(authority=StateFactAuthority.TELEMETRY)

    result = _adjudicate(projection=projection, telemetry=telemetry)

    assert result.status is CrossSourceStateStatus.CENSORED
    assert result.read_confidence is CrossSourceReadConfidence.UNAVAILABLE
    assert result.agreed_state == {}
    assert result.projection.censoring_refs == ("policy-redaction:one",)
    assert result.telemetry is telemetry


def test_existing_source_conflicts_remain_explicit() -> None:
    telemetry = _snapshot(
        authority=StateFactAuthority.TELEMETRY,
        conflicts=("telemetry-source-conflict",),
    )

    result = _adjudicate(telemetry=telemetry)

    assert result.status is CrossSourceStateStatus.CONFLICTING
    assert result.conflicting_fields == ("telemetry:telemetry-source-conflict",)


def test_cross_source_roles_and_evaluation_time_fail_closed() -> None:
    with pytest.raises(ValueError, match="projected state MUST carry provider authority"):
        _adjudicate(
            projection=_snapshot(authority=StateFactAuthority.TELEMETRY),
            telemetry=_snapshot(authority=StateFactAuthority.TELEMETRY),
        )

    with pytest.raises(ValueError, match="telemetry state MUST carry telemetry authority"):
        _adjudicate(telemetry=_snapshot(authority=StateFactAuthority.PROVIDER))

    with pytest.raises(ValueError, match="evaluated_at MUST be timezone-aware"):
        adjudicate_projected_state(
            projection=_snapshot(authority=StateFactAuthority.PROVIDER),
            telemetry=_snapshot(authority=StateFactAuthority.TELEMETRY),
            evaluated_at=OBSERVED_AT.replace(tzinfo=None),
        )


def test_cross_source_state_rejects_non_json_values() -> None:
    with pytest.raises(ValueError, match="MUST contain JSON values"):
        _snapshot(
            authority=StateFactAuthority.PROVIDER,
            state={"status": object()},
        )
