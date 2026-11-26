"""Exact-target Azure semantic ingress projection tests."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.models import (
    ObjectSelector,
    ObjectSelectorKind,
    ObjectSetDefinition,
    ObjectSetMaterialization,
)
from fdai.core.ontology_platform.query_gateway import (
    ObjectSetRedactionSummary,
    SecuredObjectSetQueryReceipt,
    SecuredObjectSetQueryResult,
    _projected_result_digest,
)
from fdai.core.ontology_platform.resource_ingress_queries import (
    RESOURCE_INGRESS_FUNCTION_NAME,
    resource_ingress_function_type,
)
from fdai.delivery.azure.semantic_resource_ingress import semantic_resource_ingress_function
from fdai.shared.contracts.models import CeilingRole
from fdai.shared.ontology.release import build_ontology_release
from fdai.shared.providers.ontology_instance import OntologyGraphSnapshot, OntologyObjectRecord

NOW = datetime(2026, 8, 22, 1, 0, tzinfo=UTC)


def _query_result(
    *,
    ingress_enabled: bool = True,
    resource_type: str = "compute.container-app",
    truncated_properties: bool = False,
) -> SecuredObjectSetQueryResult:
    definition = ObjectSetDefinition(
        selector=ObjectSelector(kind=ObjectSelectorKind.OBJECT_TYPE, name="Resource"),
        as_of=NOW,
        purpose="operations-review",
        limit=2,
    )
    provider: dict[str, object] = {
        "properties": {
            "configuration": {
                "activeRevisionsMode": "Single",
                "ingress": {
                    "external": True,
                    "fqdn": "app.example.com",
                    "targetPort": 8080,
                    "exposedPort": 0,
                    "transport": "Auto",
                    "allowInsecure": False,
                    "clientCertificateMode": "Ignore",
                    "traffic": [{"weight": 100, "latestRevision": True}],
                    "customDomains": [{"name": "redacted.example.com"}],
                    "ipSecurityRestrictions": [{"action": "Allow"}],
                }
                if ingress_enabled
                else None,
            }
        },
        "_state_fact": {"effective_at": "2026-08-22T00:59:00+00:00"},
    }
    if truncated_properties:
        provider = {"_truncated": True}
    materialization = ObjectSetMaterialization(
        definition=definition,
        graph=OntologyGraphSnapshot(
            objects=(
                OntologyObjectRecord(
                    id="scope-example/resource-group/example-rg/app-example",
                    object_type="Resource",
                    properties={
                        "id": "resource-example",
                        "name": "app-example",
                        "type": resource_type,
                        "properties": provider,
                    },
                ),
            ),
            links=(),
            truncated=False,
        ),
        concrete_types=("Resource",),
        truncated=False,
        truncation_reason=None,
    )
    release = build_ontology_release(function_types=(resource_ingress_function_type(),))
    return SecuredObjectSetQueryResult(
        materialization=materialization,
        receipt=SecuredObjectSetQueryReceipt(
            ontology_release=release.ref(),
            projected_result_digest=_projected_result_digest(materialization),
            purpose="operations-review",
            caller_role="reader",
            observation_cutoff=NOW,
            as_of_skew_seconds=0,
            returned_object_count=1,
            returned_link_count=0,
            complete=True,
            truncated=False,
            truncation_reason=None,
            redactions=ObjectSetRedactionSummary(
                objects_with_redactions=0,
                redacted_identity_count=0,
                access_scope_count=0,
                purpose_binding_count=0,
                undeclared_property_count=0,
                links_with_redactions=0,
                redacted_link_property_count=0,
                removed_link_count=0,
            ),
        ),
    )


async def _invoke(query_result: SecuredObjectSetQueryResult) -> dict[str, object]:
    declaration = resource_ingress_function_type()
    release = build_ontology_release(function_types=(declaration,))
    registry = OntologyFunctionRegistry(release=release)
    registry.register_contextual(declaration, semantic_resource_ingress_function(release))
    result = await registry.invoke(
        RESOURCE_INGRESS_FUNCTION_NAME,
        {"query_result": query_result.model_dump(mode="json")},
        context=FunctionInvocationContext(
            caller_agent="Bragi",
            caller_role=CeilingRole.READER,
            purposes=("operations-review",),
        ),
    )
    assert isinstance(result, dict)
    return result


async def test_ingress_projection_returns_only_typed_configuration_fields() -> None:
    result = await _invoke(_query_result())

    assert result["complete"] is True
    rows = result["rows"]
    assert isinstance(rows, list)
    values = rows[0]["values"]
    assert values["ingress_enabled"] is True
    assert values["external"] is True
    assert values["fqdn"] == "app.example.com"
    assert values["target_port"] == 8080
    assert values["transport"] == "Auto"
    assert values["allow_insecure"] is False
    assert values["traffic_rules"] == [
        {
            "label": None,
            "latest_revision": True,
            "revision_name": None,
            "weight": 100,
        }
    ]
    assert values["custom_domain_count"] == 1
    assert values["ip_security_restriction_count"] == 1
    assert values["source_observed_at"] == "2026-08-22T00:59:00+00:00"
    assert values["inventory_read_at"] == NOW.isoformat()
    assert values["execution_authority"] is False
    assert "configuration" not in values


async def test_ingress_projection_does_not_treat_truncated_properties_as_disabled() -> None:
    result = await _invoke(_query_result(truncated_properties=True))

    assert result["complete"] is False
    assert result["truncation_reason"] == (
        "provider_properties_truncated+source_observed_at_unavailable+"
        "container_app_configuration_unavailable"
    )
    rows = result["rows"]
    assert isinstance(rows, list)
    assert rows[0]["values"]["ingress_enabled"] is None
    assert rows[0]["values"]["execution_authority"] is False


async def test_ingress_projection_preserves_verified_disabled_state() -> None:
    result = await _invoke(_query_result(ingress_enabled=False))

    assert result["complete"] is True
    assert result["truncation_reason"] is None
    rows = result["rows"]
    assert isinstance(rows, list)
    assert rows[0]["values"]["ingress_enabled"] is False
    assert rows[0]["values"]["external"] is None


async def test_ingress_projection_rejects_a_non_container_app_target() -> None:
    result = await _invoke(_query_result(resource_type="compute.vm"))

    assert result["complete"] is False
    assert result["rows"] == []
    assert result["truncation_reason"] == "target_type_not_container_app"
