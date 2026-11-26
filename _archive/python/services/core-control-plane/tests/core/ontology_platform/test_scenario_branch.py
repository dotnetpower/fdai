from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fdai.core.ontology_platform import (
    OntologyScenarioBranch,
    OntologyScenarioChangeSet,
)
from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.query_receipt_authority import SecuredQueryReceiptAuthority
from fdai.core.operational_context import (
    AuthenticatedPrincipalContext,
    OperationalEvidenceMaterial,
    OperationalEvidenceReadRequest,
    OperationalEvidenceReadService,
)
from fdai.shared.contracts.models import (
    LinkCardinality,
    OntologyLinkType,
    OntologyObjectType,
    PropertyDecl,
    PropertyType,
)
from fdai.shared.providers.ontology_instance import (
    OntologyGraphSnapshot,
    OntologyInstanceValidationError,
    OntologyLinkRecord,
    OntologyObjectRecord,
)

NOW = datetime(2026, 8, 24, tzinfo=UTC)
RELEASE = "sha256:" + "a" * 64
PRINCIPAL = "principal-example"
PRINCIPAL_SCOPE = "sha256:" + "c" * 64


class _EvidenceSource:
    async def collect(self, request: OperationalEvidenceReadRequest) -> OperationalEvidenceMaterial:
        return OperationalEvidenceMaterial(
            ontology_release_digest=request.ontology_release_digest,
            catalog_revision=request.catalog_revision,
            purpose=request.purpose,
            scope=request.scope,
            cutoff=request.cutoff,
        )


async def _bundle():
    authority = SecuredQueryReceiptAuthority()
    result = await OperationalEvidenceReadService(
        source=_EvidenceSource(),
        clock=lambda: NOW,
    ).read(
        OperationalEvidenceReadRequest(
            ontology_release_digest=RELEASE,
            catalog_revision="catalog-r1",
            purpose="scenario-review",
            scope=("resource-base",),
            cutoff=NOW,
        ),
        authenticated_context=AuthenticatedPrincipalContext(
            principal_ref=PRINCIPAL,
            principal_scope_digest=PRINCIPAL_SCOPE,
            purpose="scenario-review",
            receipt_authority=authority,
            invocation_context=FunctionInvocationContext(
                caller_agent="Bragi",
                caller_role="reader",
                purposes=("scenario-review",),
            ),
            verification_context=authority.verification_context,
        ),
    )
    return result.bundle


def _types() -> tuple[tuple[OntologyObjectType, ...], tuple[OntologyLinkType, ...]]:
    resource = OntologyObjectType(
        schema_version="1.0.0",
        name="Resource",
        version="1.0.0",
        key="id",
        properties={
            "id": PropertyDecl(type=PropertyType.STRING, required=True),
            "state": PropertyDecl(type=PropertyType.STRING, required=True),
        },
    )
    depends_on = OntologyLinkType(
        schema_version="1.0.0",
        name="depends_on",
        version="1.0.0",
        from_type="Resource",
        to_type="Resource",
        cardinality=LinkCardinality.MANY_TO_MANY,
    )
    return (resource,), (depends_on,)


def _object(identifier: str, state: str) -> OntologyObjectRecord:
    return OntologyObjectRecord(
        id=identifier,
        object_type="Resource",
        properties={"id": identifier, "state": state},
    )


async def test_scenario_branch_is_copy_on_write_evidence_only() -> None:
    base_object = _object("resource-base", "ready")
    base = OntologyGraphSnapshot(objects=(base_object,))
    object_types, link_types = _types()
    branch = OntologyScenarioBranch(
        branch_id="capacity-review",
        evidence_bundle=await _bundle(),
        base=base,
        object_types=object_types,
        link_types=link_types,
    )

    result = await branch.materialize(
        OntologyScenarioChangeSet(
            upsert_objects=(
                _object("resource-base", "scaled"),
                _object("resource-new", "planned"),
            ),
            upsert_links=(
                OntologyLinkRecord(
                    link_type="depends_on",
                    from_id="resource-new",
                    to_id="resource-base",
                ),
            ),
        )
    )

    assert base.objects == (base_object,)
    assert {item.properties["state"] for item in result.graph.objects} == {"scaled", "planned"}
    assert result.production_write is False
    assert result.mutation_authority is False
    assert result.execution_authority is False
    assert result.promotion_required is True
    assert result.evidence_bundle_digest == (await _bundle()).digest


async def test_scenario_branch_rejects_dangling_overlay_without_touching_base() -> None:
    base = OntologyGraphSnapshot(objects=(_object("resource-base", "ready"),))
    object_types, link_types = _types()
    branch = OntologyScenarioBranch(
        branch_id="invalid-review",
        evidence_bundle=await _bundle(),
        base=base,
        object_types=object_types,
        link_types=link_types,
    )

    with pytest.raises(OntologyInstanceValidationError, match="link endpoints do not exist"):
        await branch.materialize(
            OntologyScenarioChangeSet(
                upsert_links=(
                    OntologyLinkRecord(
                        link_type="depends_on",
                        from_id="resource-base",
                        to_id="resource-missing",
                    ),
                )
            )
        )

    assert base.objects[0].properties["state"] == "ready"
