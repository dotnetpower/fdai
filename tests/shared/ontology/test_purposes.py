"""Tests for :mod:`fdai.shared.ontology.purposes` and the ACL audit path."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from textwrap import dedent

import pytest

from fdai.rule_catalog.schema.object_type import load_object_type_from_mapping
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.acl import (
    ProjectionRequest,
    build_projection_audit_event,
    redact_properties,
    redactions_for_audit,
)
from fdai.shared.ontology.purposes import (
    PurposeRegistry,
    PurposeRegistryError,
    UnknownPurposeError,
    concatenate_registries,
    load_purpose_registry,
    load_purpose_registry_from_mapping,
    validate_declared_purposes,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
UPSTREAM_REGISTRY = REPO_ROOT / "rule-catalog" / "vocabulary" / "purposes.yaml"


def test_shipped_purpose_registry_loads() -> None:
    registry = load_purpose_registry(UPSTREAM_REGISTRY)
    ids = registry.ids()
    assert {
        "audit-review",
        "incident-response",
        "compliance-report",
        "capacity-planning",
        "cost-analysis",
    } <= ids


def test_load_from_mapping_rejects_empty_purposes() -> None:
    with pytest.raises(PurposeRegistryError):
        load_purpose_registry_from_mapping({"purposes": []})


def test_load_from_mapping_rejects_bad_id() -> None:
    raw = {
        "purposes": [
            {"id": "BadCase", "description": "camel"},
        ]
    }
    with pytest.raises(PurposeRegistryError) as exc:
        load_purpose_registry_from_mapping(raw)
    joined = " ".join(i.message for i in exc.value.issues).lower()
    assert "kebab" in joined or "pattern" in joined


def test_load_from_mapping_rejects_duplicate_id() -> None:
    raw = {
        "purposes": [
            {"id": "audit-review", "description": "one"},
            {"id": "audit-review", "description": "two"},
        ]
    }
    with pytest.raises(PurposeRegistryError) as exc:
        load_purpose_registry_from_mapping(raw)
    joined = " ".join(i.message for i in exc.value.issues).lower()
    assert "duplicate" in joined


def test_concatenate_registries_dedupes_identical_entries() -> None:
    reg_a = load_purpose_registry_from_mapping(
        {"purposes": [{"id": "audit-review", "description": "d"}]}
    )
    reg_b = load_purpose_registry_from_mapping(
        {"purposes": [{"id": "audit-review", "description": "d"}]}
    )
    merged = concatenate_registries(reg_a, reg_b)
    assert merged.ids() == {"audit-review"}


def test_concatenate_registries_rejects_conflicting_duplicate() -> None:
    reg_a = load_purpose_registry_from_mapping(
        {"purposes": [{"id": "audit-review", "description": "first"}]}
    )
    reg_b = load_purpose_registry_from_mapping(
        {"purposes": [{"id": "audit-review", "description": "second"}]}
    )
    with pytest.raises(PurposeRegistryError):
        concatenate_registries(reg_a, reg_b)


def test_validate_declared_purposes_rejects_unknown() -> None:
    registry = load_purpose_registry(UPSTREAM_REGISTRY)
    with pytest.raises(UnknownPurposeError) as exc:
        validate_declared_purposes(["not-a-real-purpose"], registry)
    assert exc.value.unknown == {"not-a-real-purpose"}


def test_validate_declared_purposes_normalises_whitespace_and_empties() -> None:
    registry = load_purpose_registry(UPSTREAM_REGISTRY)
    got = validate_declared_purposes([" audit-review ", "", "incident-response"], registry)
    assert got == frozenset({"audit-review", "incident-response"})


def _object_type() -> object:
    return load_object_type_from_mapping(
        {
            "schema_version": "1.0.0",
            "name": "AuditTarget",
            "version": "1.0.0",
            "key": "id",
            "properties": {
                "id": {"type": "string", "required": True},
                "public": {"type": "string"},
                "owner_only": {"type": "string", "access_scope": "owner"},
                "audit_only": {
                    "type": "string",
                    "purpose_binding": ["audit-review"],
                },
            },
        },
        schema_registry=PackageResourceSchemaRegistry(),
    )


def test_audit_event_captures_declared_purposes_and_redactions() -> None:
    ot = _object_type()
    request = ProjectionRequest(
        caller_role=CeilingRole.CONTRIBUTOR,
        declared_purposes=frozenset(),
    )
    projected = redact_properties(
        ot,
        {"id": "x", "public": "hi", "owner_only": "s", "audit_only": "a"},
        request,
    )
    event = build_projection_audit_event(
        audit_id="00000000-0000-0000-0000-000000000ac1",
        request=request,
        caller_id="user@example.com",
        surface="operator-api:/panels/example",
        object_type="AuditTarget",
        projected=projected,
        instance_key="x",
        correlation_id="req-1",
    )

    # Deterministic sorting so order-of-redaction-iteration bugs surface.
    reasons = {r.property: r.reason for r in event.redactions}
    assert reasons == {"owner_only": "access_scope", "audit_only": "purpose_binding"}
    assert event.caller_role is CeilingRole.CONTRIBUTOR
    assert event.declared_purposes == ()
    assert event.surface == "operator-api:/panels/example"
    assert event.object_type == "AuditTarget"
    assert event.instance_key == "x"
    assert event.correlation_id == "req-1"
    assert isinstance(event.observed_at, datetime)
    assert event.observed_at.tzinfo is UTC


def test_redactions_for_audit_returns_empty_when_nothing_redacted() -> None:
    ot = _object_type()
    projected = redact_properties(
        ot,
        {"id": "x", "public": "hi"},
        ProjectionRequest(caller_role=CeilingRole.READER),
    )
    assert redactions_for_audit(projected) == ()


def test_audit_event_never_carries_underlying_values(tmp_path: Path) -> None:
    """Regression: the audit dataclass MUST NOT carry the raw property value."""
    ot = _object_type()
    request = ProjectionRequest(caller_role=CeilingRole.READER)
    secret_value = "SUPER-SECRET-STRING"
    projected = redact_properties(
        ot,
        {"id": "x", "owner_only": secret_value},
        request,
    )
    event = build_projection_audit_event(
        audit_id="00000000-0000-0000-0000-000000000ac2",
        request=request,
        caller_id="user@example.com",
        surface="operator-api:/panels/x",
        object_type="AuditTarget",
        projected=projected,
    )
    # The audit event is dataclass-serialisable; walk every field to
    # prove the secret is nowhere in the record.
    assert secret_value not in repr(event)
    for record in event.redactions:
        assert secret_value not in repr(record)


def test_purpose_yaml_survives_disk_roundtrip(tmp_path: Path) -> None:
    text = dedent(
        """
        purposes:
          - id: fork-only
            description: A fork-owned purpose.
            audit_required: false
        """
    ).lstrip()
    path = tmp_path / "purposes.yaml"
    path.write_text(text)
    reg = load_purpose_registry(path)
    assert reg.ids() == {"fork-only"}
    entry = reg.get("fork-only")
    assert entry.audit_required is False


def test_purpose_yaml_rejects_missing_description(tmp_path: Path) -> None:
    text = dedent(
        """
        purposes:
          - id: no-description
        """
    ).lstrip()
    path = tmp_path / "purposes.yaml"
    path.write_text(text)
    with pytest.raises(PurposeRegistryError):
        load_purpose_registry(path)


def test_purpose_registry_get_raises_on_unknown() -> None:
    registry: PurposeRegistry = load_purpose_registry(UPSTREAM_REGISTRY)
    with pytest.raises(KeyError):
        registry.get("does-not-exist")
