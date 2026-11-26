"""Tests for ``fdai.shared.ontology.acl``.

Cover the property-level ACL projection contract used by every
read surface (Operator API panels, assurance twin, exported reports).
"""

from __future__ import annotations

from fdai.rule_catalog.schema.object_type import load_object_type_from_mapping
from fdai.shared.contracts.models import CeilingRole, OntologyObjectType
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.ontology.acl import (
    REDACTED_PLACEHOLDER,
    ProjectionRequest,
    RedactedField,
    RedactionReason,
    declared_purposes_from_iterable,
    project_graph_snapshot,
    redact_properties,
    serialize_projection,
)
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyLinkRecord,
    OntologyObjectRecord,
)


def _registry() -> PackageResourceSchemaRegistry:
    return PackageResourceSchemaRegistry()


def _object_type(props: dict[str, dict]) -> OntologyObjectType:
    return load_object_type_from_mapping(
        {
            "schema_version": "1.0.0",
            "name": "TestOT",
            "version": "1.0.0",
            "key": next(iter(props)),
            "properties": props,
        },
        schema_registry=_registry(),
    )


def test_reader_sees_public_properties() -> None:
    ot = _object_type(
        {
            "id": {"type": "string", "required": True},
            "note": {"type": "string"},
        }
    )
    projected = redact_properties(
        ot,
        {"id": "x", "note": "hello"},
        ProjectionRequest(caller_role=CeilingRole.READER),
    )
    assert projected == {"id": "x", "note": "hello"}


def test_access_scope_redacts_below_required_role() -> None:
    ot = _object_type(
        {
            "id": {"type": "string", "required": True},
            "secret_note": {"type": "string", "access_scope": "owner"},
        }
    )
    projected = redact_properties(
        ot,
        {"id": "x", "secret_note": "sensitive"},
        ProjectionRequest(caller_role=CeilingRole.CONTRIBUTOR),
    )
    assert projected["id"] == "x"
    assert isinstance(projected["secret_note"], RedactedField)
    assert projected["secret_note"].reason is RedactionReason.ACCESS_SCOPE
    assert projected["secret_note"].required_role is CeilingRole.OWNER


def test_access_scope_passes_at_or_above_required_role() -> None:
    ot = _object_type(
        {
            "id": {"type": "string", "required": True},
            "approver_note": {"type": "string", "access_scope": "approver"},
        }
    )
    for role in (CeilingRole.APPROVER, CeilingRole.OWNER):
        projected = redact_properties(
            ot,
            {"id": "x", "approver_note": "seen"},
            ProjectionRequest(caller_role=role),
        )
        assert projected["approver_note"] == "seen", f"role={role} MUST see the field"


def test_purpose_binding_requires_purpose_intersection() -> None:
    ot = _object_type(
        {
            "id": {"type": "string", "required": True},
            "audit_field": {
                "type": "string",
                "purpose_binding": ["audit-review", "incident-response"],
            },
        }
    )
    denied = redact_properties(
        ot,
        {"id": "x", "audit_field": "value"},
        ProjectionRequest(caller_role=CeilingRole.OWNER),
    )
    assert isinstance(denied["audit_field"], RedactedField)
    assert denied["audit_field"].reason is RedactionReason.PURPOSE_BINDING
    assert denied["audit_field"].required_purposes == ("audit-review", "incident-response")

    allowed = redact_properties(
        ot,
        {"id": "x", "audit_field": "value"},
        ProjectionRequest(
            caller_role=CeilingRole.OWNER,
            declared_purposes=frozenset({"audit-review"}),
        ),
    )
    assert allowed["audit_field"] == "value"


def test_access_scope_and_purpose_binding_are_both_enforced() -> None:
    ot = _object_type(
        {
            "id": {"type": "string", "required": True},
            "double_gated": {
                "type": "string",
                "access_scope": "approver",
                "purpose_binding": ["compliance-report"],
            },
        }
    )
    # Reader without purpose - fails access first (order is stable).
    reader = redact_properties(
        ot,
        {"id": "x", "double_gated": "v"},
        ProjectionRequest(caller_role=CeilingRole.READER),
    )
    assert isinstance(reader["double_gated"], RedactedField)
    assert reader["double_gated"].reason is RedactionReason.ACCESS_SCOPE

    # Approver without purpose - fails purpose gate.
    approver_no_purpose = redact_properties(
        ot,
        {"id": "x", "double_gated": "v"},
        ProjectionRequest(caller_role=CeilingRole.APPROVER),
    )
    assert isinstance(approver_no_purpose["double_gated"], RedactedField)
    assert approver_no_purpose["double_gated"].reason is RedactionReason.PURPOSE_BINDING

    # Approver with purpose - through.
    approver_with_purpose = redact_properties(
        ot,
        {"id": "x", "double_gated": "v"},
        ProjectionRequest(
            caller_role=CeilingRole.APPROVER,
            declared_purposes=frozenset({"compliance-report"}),
        ),
    )
    assert approver_with_purpose["double_gated"] == "v"


def test_undeclared_property_is_redacted_fail_closed() -> None:
    ot = _object_type({"id": {"type": "string", "required": True}})
    projected = redact_properties(
        ot,
        {"id": "x", "unknown_prop": "leaked?"},
        ProjectionRequest(caller_role=CeilingRole.OWNER),
    )
    assert isinstance(projected["unknown_prop"], RedactedField)
    assert projected["unknown_prop"].reason is RedactionReason.UNDECLARED_PROPERTY


def test_serialize_projection_replaces_sentinels_with_placeholder() -> None:
    ot = _object_type(
        {
            "id": {"type": "string", "required": True},
            "secret": {"type": "string", "access_scope": "owner"},
        }
    )
    projected = redact_properties(
        ot,
        {"id": "x", "secret": "sensitive"},
        ProjectionRequest(caller_role=CeilingRole.CONTRIBUTOR),
    )
    values, redactions = serialize_projection(projected)
    assert values["id"] == "x"
    assert values["secret"] == REDACTED_PLACEHOLDER
    assert redactions == {
        "secret": {
            "reason": "access_scope",
            "required_role": "owner",
            "required_purposes": [],
        }
    }
    # Serialiser MUST NOT leak the underlying value anywhere.
    assert "sensitive" not in str(values)
    assert "sensitive" not in str(redactions)


def test_declared_purposes_from_iterable_normalises_input() -> None:
    result = declared_purposes_from_iterable(
        ["audit-review", " audit-review ", "", "incident-response"]
    )
    assert result == frozenset({"audit-review", "incident-response"})


def test_graph_projection_remaps_restricted_keys_and_edges() -> None:
    object_type = _object_type(
        {
            "id": {
                "type": "string",
                "required": True,
                "access_scope": "owner",
                "purpose_binding": ["user_context"],
            },
            "label": {"type": "string"},
        }
    )
    snapshot = OntologyGraphSnapshot(
        objects=(
            OntologyObjectRecord(
                id="principal-secret",
                object_type="TestOT",
                properties={"id": "principal-secret", "label": "Principal"},
            ),
        ),
        links=(
            OntologyLinkRecord(
                link_type="self_link",
                from_id="principal-secret",
                to_id="principal-secret",
            ),
        ),
    )

    projected = project_graph_snapshot(
        snapshot,
        object_types={object_type.name: object_type},
        request=ProjectionRequest(caller_role=CeilingRole.READER),
    )

    assert projected.objects[0].id == "redacted-object-1"
    assert projected.objects[0].properties["id"] == REDACTED_PLACEHOLDER
    assert projected.links[0].from_id == "redacted-object-1"
    assert "principal-secret" not in str(projected)


def test_graph_projection_preserves_key_for_trusted_purpose() -> None:
    object_type = _object_type(
        {
            "id": {
                "type": "string",
                "required": True,
                "access_scope": "owner",
                "purpose_binding": ["user_context"],
            }
        }
    )
    snapshot = OntologyGraphSnapshot(
        objects=(
            OntologyObjectRecord(
                id="principal-1",
                object_type="TestOT",
                properties={"id": "principal-1"},
            ),
        )
    )

    projected = project_graph_snapshot(
        snapshot,
        object_types={object_type.name: object_type},
        request=ProjectionRequest(
            caller_role=CeilingRole.OWNER,
            declared_purposes=frozenset({"user_context"}),
        ),
    )

    assert projected.objects[0].id == "principal-1"
    assert projected.objects[0].properties["id"] == "principal-1"
