"""Principal-safe PostgreSQL role evidence projection tests."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

import pytest
from fdai.core.ontology_platform.postgres_role_evidence import (
    PostgresRoleObservation,
    PostgresRoleProjectionReason,
    project_postgres_role_evidence,
)

NOW = datetime(2026, 8, 24, 5, 0, tzinfo=UTC)
SCOPE_REF = "scope:operations-review"
SERVICE_REF = "service:core-runtime"


def _observation() -> PostgresRoleObservation:
    return PostgresRoleObservation(
        observation_id="postgres-role:core-runtime",
        role_name="fdai_core",
        service_ref=SERVICE_REF,
        scope_ref=SCOPE_REF,
        can_login=False,
        superuser=False,
        create_database=False,
        create_role=False,
        inherit=False,
        replication=False,
        bypass_row_level_security=False,
        observed_at=NOW - timedelta(minutes=2),
        evidence_cutoff=NOW - timedelta(minutes=1),
        recorded_at=NOW,
        freshness_ceiling_seconds=300,
        source_identity="postgres.catalog",
        source_revision="pg_roles@1.0.0",
        evidence_ref="sha256:" + "2" * 64,
        authentication_ref="sha256:" + "1" * 64,
    )


def _project(observation: PostgresRoleObservation, **changes: object):  # type: ignore[no-untyped-def]
    values: dict[str, object] = {
        "principal_scope_ref": SCOPE_REF,
        "readable_service_refs": {SERVICE_REF},
        "evaluation_time": NOW + timedelta(seconds=1),
    }
    values.update(changes)
    return project_postgres_role_evidence(observation, **values)  # type: ignore[arg-type]


def test_role_projection_exposes_only_principal_safe_attributes() -> None:
    result = _project(_observation())

    assert result.reason is PostgresRoleProjectionReason.PROJECTED
    assert result.evidence is not None
    projected = asdict(result.evidence)
    assert "role_name" not in projected
    assert "fdai_core" not in str(projected)
    assert projected["service_ref"] == SERVICE_REF
    assert str(projected["principal_handle"]).startswith("sha256:")
    assert projected["superuser"] is False
    assert projected["create_database"] is False
    assert projected["create_role"] is False
    assert result.execution_authority is False
    assert result.mutation_authority is False


def test_wrong_scope_or_unreadable_service_discloses_no_role_evidence() -> None:
    wrong_scope = _project(_observation(), principal_scope_ref="scope:other")
    unreadable = _project(_observation(), readable_service_refs=set())

    assert wrong_scope.reason is PostgresRoleProjectionReason.WRONG_SCOPE
    assert unreadable.reason is PostgresRoleProjectionReason.WRONG_SCOPE
    assert wrong_scope.evidence is None
    assert unreadable.evidence is None
    assert "fdai_core" not in wrong_scope.digest
    assert "fdai_core" not in unreadable.digest


def test_stale_role_evidence_remains_unavailable() -> None:
    result = _project(
        replace(
            _observation(),
            observed_at=NOW - timedelta(minutes=12),
            evidence_cutoff=NOW - timedelta(minutes=10),
            recorded_at=NOW - timedelta(minutes=9),
        )
    )

    assert result.reason is PostgresRoleProjectionReason.STALE
    assert result.evidence is None


def test_postgres_role_projection_has_no_resource_relationship_shape() -> None:
    evidence = _project(_observation()).evidence

    assert evidence is not None
    assert not hasattr(evidence, "from_id")
    assert not hasattr(evidence, "to_id")
    assert not hasattr(evidence, "link_type")


def test_role_references_must_be_content_addressed() -> None:
    for field_name in ("evidence_ref", "authentication_ref"):
        with pytest.raises(ValueError, match=f"{field_name} MUST be canonical SHA-256"):
            replace(_observation(), **{field_name: "postgres-role:fdai_core"})


def test_principal_handle_is_scoped_to_the_database_service() -> None:
    first = _project(_observation()).evidence
    second_service = "service:document-worker"
    second = _project(
        replace(_observation(), service_ref=second_service),
        readable_service_refs={second_service},
    ).evidence

    assert first is not None
    assert second is not None
    assert first.principal_handle != second.principal_handle
