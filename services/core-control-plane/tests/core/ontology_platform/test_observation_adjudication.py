"""Deterministic adjudication of repeated observations of one target."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.observation_adjudication import (
    CONFLICT_TRUNCATED,
    MAX_OBSERVATION_CONFLICTS,
    ObservationIdentityConflictError,
    ObservedClaim,
    adjudicate_independent_observations,
    adjudicate_observations,
)

OBSERVED_AT = datetime(2026, 8, 8, 12, tzinfo=UTC)


def _claim(
    *,
    properties: dict[str, object] | None = None,
    provider_ref: str | None = "provider-ref-1",
    offset_seconds: int = 0,
    type_id: str = "compute.vm",
    target_id: str | None = "resource-1",
    generation_id: str | None = "generation-1",
    provider_identity_verified: bool = True,
) -> ObservedClaim:
    return ObservedClaim(
        type=type_id,
        properties=properties if properties is not None else {"status": "running"},
        provider_ref=provider_ref,
        observed_at=OBSERVED_AT + timedelta(seconds=offset_seconds),
        target_id=target_id,
        generation_id=generation_id,
        provider_identity_verified=provider_identity_verified,
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
    assert verdict.target_id == "resource-1"
    assert verdict.generation_id == "generation-1"


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
            "verified canonical providers",
        ),
        (
            (_claim(provider_ref=" "), _claim(provider_ref="provider-ref-2")),
            "verified canonical providers",
        ),
        (
            (_claim(provider_ref="provider-ref-1"), _claim(provider_ref="provider-ref-1")),
            "verified canonical providers",
        ),
        (
            (
                _claim(provider_ref="provider-ref-1", target_id="resource-1"),
                _claim(provider_ref="provider-ref-2", target_id="resource-2"),
            ),
            "one target generation",
        ),
        (
            (
                _claim(provider_ref="provider-ref-1", provider_identity_verified=False),
                _claim(provider_ref="provider-ref-2"),
            ),
            "verified canonical providers",
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
