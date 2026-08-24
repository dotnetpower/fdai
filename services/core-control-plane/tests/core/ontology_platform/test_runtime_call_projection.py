"""Exact endpoint and no-authority runtime-call projection tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.runtime_call_projection import (
    RUNTIME_CALL_LINK_TYPE,
    RUNTIME_CALL_LINK_TYPE_DECLARATION_DIGEST,
    RUNTIME_CALL_LINK_TYPE_VERSION,
    RuntimeCallObservation,
    RuntimeCallProjectionReason,
    project_runtime_call,
)
from fdai.shared.contracts.models import (
    OntologyDeclarationKind,
    OntologyDeclarationRef,
    OntologyRelease,
)
from fdai.shared.ontology.release import ontology_release_digest
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.state_evidence import (
    StateFactAuthority,
    StateFactLane,
)

NOW = datetime(2026, 8, 24, 2, 0, tzinfo=UTC)
CALLER_ID = "resource:caller"
TARGET_ID = "resource:target"
SCOPE_REF = "scope:operations-review"


def _observation(**changes: object) -> RuntimeCallObservation:
    values: dict[str, object] = {
        "observation_id": "runtime-call:one",
        "caller_resource_ids": (CALLER_ID,),
        "target_resource_ids": (TARGET_ID,),
        "scope_ref": SCOPE_REF,
        "observed_at": NOW - timedelta(minutes=2),
        "evidence_cutoff": NOW - timedelta(minutes=1),
        "recorded_at": NOW,
        "freshness_ceiling_seconds": 300,
        "source_identity": "telemetry.runtime-calls",
        "source_revision": "1.0.0",
        "evidence_ref": "telemetry:runtime-call:one",
        "authentication_ref": "sha256:" + "1" * 64,
        "execution_authority": False,
        "mutation_authority": False,
    }
    values.update(changes)
    return RuntimeCallObservation(**values)  # type: ignore[arg-type]


def _resources() -> tuple[ResourceRecord, ...]:
    return (
        ResourceRecord(resource_id=CALLER_ID, type="container-app"),
        ResourceRecord(resource_id=TARGET_ID, type="postgres-flexible"),
    )


def _release(
    *,
    declaration_digest: str = RUNTIME_CALL_LINK_TYPE_DECLARATION_DIGEST,
    include_runtime_calls: bool = True,
) -> OntologyRelease:
    declarations = (
        (
            OntologyDeclarationRef(
                kind=OntologyDeclarationKind.LINK,
                name=RUNTIME_CALL_LINK_TYPE,
                version=RUNTIME_CALL_LINK_TYPE_VERSION,
                declaration_digest=declaration_digest,
            ),
        )
        if include_runtime_calls
        else ()
    )
    return OntologyRelease(
        digest=ontology_release_digest(declarations),
        declarations=declarations,
    )


def _project(observation: RuntimeCallObservation, **changes: object):  # type: ignore[no-untyped-def]
    values: dict[str, object] = {
        "active_resources": _resources(),
        "readable_resource_ids": {
            CALLER_ID,
            TARGET_ID,
            "resource:caller-two",
            "resource:target-two",
        },
        "principal_scope_ref": SCOPE_REF,
        "ontology_release": _release(),
        "inventory_generation": "inventory:generation-one",
        "evaluation_time": NOW,
        "verifier_identity": "inventory.endpoint-verifier",
        "verifier_revision": "1.0.0",
    }
    values.update(changes)
    return project_runtime_call(observation, **values)  # type: ignore[arg-type]


def test_exact_fresh_endpoints_project_one_verified_authority_free_edge() -> None:
    result = _project(_observation())

    assert result.reason is RuntimeCallProjectionReason.PROJECTED
    assert result.execution_authority is False
    assert result.mutation_authority is False
    assert result.digest.startswith("sha256:")
    assert result.edge is not None
    assert (
        result.edge.from_id,
        result.edge.link_type,
        result.edge.to_id,
    ) == (CALLER_ID, RUNTIME_CALL_LINK_TYPE, TARGET_ID)
    metadata = result.edge.observation_metadata
    assert metadata is not None
    assert metadata.verified is True
    assert metadata.verification_method == "deterministic-cross-check"
    assert metadata.state_fact.lane is StateFactLane.OBSERVED
    assert metadata.state_fact.authority is StateFactAuthority.TELEMETRY
    assert metadata.state_fact.evidence_refs == (
        "sha256:" + "1" * 64,
        "telemetry:runtime-call:one",
    )
    assert metadata.inventory_generation == "inventory:generation-one"
    assert metadata.verification_receipt_ref is not None


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"caller_resource_ids": ()}, RuntimeCallProjectionReason.MISSING_CALLER),
        ({"target_resource_ids": ()}, RuntimeCallProjectionReason.MISSING_TARGET),
        (
            {"caller_resource_ids": (CALLER_ID, "resource:caller-two")},
            RuntimeCallProjectionReason.AMBIGUOUS_CALLER,
        ),
        (
            {"target_resource_ids": (TARGET_ID, "resource:target-two")},
            RuntimeCallProjectionReason.AMBIGUOUS_TARGET,
        ),
    ],
)
def test_missing_or_ambiguous_endpoints_never_project(
    changes: dict[str, object],
    reason: RuntimeCallProjectionReason,
) -> None:
    result = _project(_observation(**changes))

    assert result.reason is reason
    assert result.edge is None
    assert result.execution_authority is False
    assert result.mutation_authority is False


def test_stale_observation_never_projects() -> None:
    result = _project(
        _observation(
            observed_at=NOW - timedelta(minutes=12),
            evidence_cutoff=NOW - timedelta(minutes=10),
            recorded_at=NOW - timedelta(minutes=9),
        )
    )

    assert result.reason is RuntimeCallProjectionReason.STALE
    assert result.edge is None


def test_wrong_scope_or_redacted_endpoint_never_projects() -> None:
    wrong_scope = _project(
        _observation(scope_ref="scope:another"),
    )
    redacted_target = _project(
        _observation(),
        readable_resource_ids={CALLER_ID},
    )

    assert wrong_scope.reason is RuntimeCallProjectionReason.WRONG_SCOPE
    assert redacted_target.reason is RuntimeCallProjectionReason.WRONG_SCOPE
    assert wrong_scope.edge is None
    assert redacted_target.edge is None


def test_redacted_ambiguous_endpoint_does_not_disclose_cardinality() -> None:
    result = _project(
        _observation(target_resource_ids=(TARGET_ID, "resource:target-two")),
        readable_resource_ids={CALLER_ID},
    )

    assert result.reason is RuntimeCallProjectionReason.WRONG_SCOPE
    assert result.edge is None


def test_missing_active_link_type_never_projects() -> None:
    result = _project(_observation(), ontology_release=_release(include_runtime_calls=False))

    assert result.reason is RuntimeCallProjectionReason.LINK_TYPE_UNAVAILABLE
    assert result.edge is None


def test_mismatched_active_link_type_declaration_never_projects() -> None:
    result = _project(
        _observation(),
        ontology_release=_release(declaration_digest="sha256:" + "0" * 64),
    )

    assert result.reason is RuntimeCallProjectionReason.LINK_TYPE_MISMATCH
    assert result.edge is None


def test_endpoint_absent_from_active_generation_never_projects() -> None:
    caller_missing = _project(
        _observation(),
        active_resources=(ResourceRecord(resource_id=TARGET_ID, type="postgres-flexible"),),
    )
    target_missing = _project(
        _observation(),
        active_resources=(ResourceRecord(resource_id=CALLER_ID, type="container-app"),),
    )

    assert caller_missing.reason is RuntimeCallProjectionReason.CALLER_NOT_OBSERVED
    assert target_missing.reason is RuntimeCallProjectionReason.TARGET_NOT_OBSERVED
    assert caller_missing.edge is None
    assert target_missing.edge is None


def test_receipt_and_projection_are_replay_stable() -> None:
    first = _project(_observation())
    second = _project(replace(_observation(), execution_authority=False))

    assert first == second


def test_projection_digest_binds_observation_and_release_context() -> None:
    first = _project(_observation(scope_ref="scope:wrong-one"))
    second = _project(_observation(scope_ref="scope:wrong-two"))
    alternate_release = _release(declaration_digest="sha256:" + "0" * 64)
    third = _project(_observation(scope_ref="scope:wrong-one"), ontology_release=alternate_release)

    assert first.reason is RuntimeCallProjectionReason.WRONG_SCOPE
    assert second.reason is RuntimeCallProjectionReason.WRONG_SCOPE
    assert third.reason is RuntimeCallProjectionReason.WRONG_SCOPE
    assert len({first.digest, second.digest, third.digest}) == 3


def test_observation_recorded_after_evaluation_is_rejected() -> None:
    with pytest.raises(ValueError, match="MUST NOT precede recorded_at"):
        _project(_observation(recorded_at=NOW + timedelta(seconds=1)))


def test_unbounded_freshness_is_rejected() -> None:
    with pytest.raises(ValueError, match="MUST be between"):
        _observation(freshness_ceiling_seconds=31_536_001)


@pytest.mark.parametrize(
    "verifier_identity",
    (
        "telemetry.runtime-calls",
        "TELEMETRY.RUNTIME-CALLS",
        " telemetry.runtime-calls ",
    ),
)
def test_source_cannot_verify_its_own_observation(verifier_identity: str) -> None:
    with pytest.raises(ValueError, match="independent verifier"):
        _project(_observation(), verifier_identity=verifier_identity)
