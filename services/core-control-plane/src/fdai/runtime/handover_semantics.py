"""Source-owned Norns compilation and independent Mimir verification in every Core venue.

Responsibility: Bind normalized documents, exact catalog compilers, and private packages.
Boundary: No startup provider call, inter-service implementation import, or active graph write.
Authority and state: Norns owns extraction; Mimir independently verifies; Saga seals inert receipts.
Dependencies: Current Core identity reads, restricted SQL, and same-venue document artifacts.
Deployment: Missing prerequisites keep extraction unavailable without a fake fallback.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import (
    Mapping,
    Sequence,
)
from dataclasses import (
    asdict,
    replace,
)
from datetime import (
    UTC,
    datetime,
)
from pathlib import Path

import httpx
import yaml
from fdai_service_contracts import DocumentEnvelope

from fdai.agents import AssignmentWorkflowBindings
from fdai.composition import Container
from fdai.core.human_assignment.knowledge_source import HandoverKnowledgeSourceCheck
from fdai.delivery.identity.handover_envelopes import HandoverEnvelopeReader
from fdai.delivery.identity.handover_semantic_sources import CurrentAcceptedHandoverSources
from fdai.delivery.persistence.postgres_handover_semantics import PostgresHandoverSemanticPackages
from fdai.rule_catalog.pipeline.distill.handover_rules import HandoverRuleCompiler
from fdai.rule_catalog.pipeline.distill.handover_semantics import (
    HandoverSemanticCompilation,
    HandoverSemanticReview,
    HandoverSemanticVerification,
)
from fdai.rule_catalog.pipeline.distill.ontology_models import AuthorityClass
from fdai.rule_catalog.pipeline.distill.ontology_verify import (
    LinkDeclaration,
    SourceAuthorityPolicy,
    TypePropertyDeclaration,
    VerificationContext,
)
from fdai.rule_catalog.schema.resource_type import load_resource_type_registry_from_mapping
from fdai.runtime.core_handover import (
    CoreHandoverServices,
    CurrentCoreHandoverSource,
)
from fdai.shared.contracts.models import (
    OntologyActionType,
    OntologyRelease,
)
from fdai.shared.providers.distiller import describe_distiller
from fdai.shared.providers.workload_identity import WorkloadIdentity


def bind_handover_semantics(
    *,
    workflow: AssignmentWorkflowBindings,
    core: CoreHandoverServices | None,
    container: Container,
    catalog_root: Path,
    ontology_release: OntologyRelease | None,
    action_types: Sequence[OntologyActionType],
    environment: Mapping[str, str],
    http_client: httpx.AsyncClient | None,
    identity: WorkloadIdentity | None,
) -> AssignmentWorkflowBindings:
    """Bind both roles with complete source prerequisites, without raising authority."""
    if core is None or ontology_release is None:
        return workflow
    local = environment.get("FDAI_LOCAL_DOCUMENT_STORE_DIR", "").strip()
    remote = environment.get("FDAI_ADLS_ACCOUNT_URL", "").strip()
    venue = environment.get("FDAI_EXECUTION_VENUE", "").strip()
    if venue == "local":
        if not local:
            return workflow
        envelopes = HandoverEnvelopeReader(local_root=Path(local))
    elif venue == "deployed":
        if not remote or http_client is None or identity is None:
            return workflow
        envelopes = HandoverEnvelopeReader(
            account_url=remote,
            file_system=environment.get("FDAI_ADLS_DERIVED_FILE_SYSTEM", "derived"),
            http_client=http_client,
            identity=identity,
        )
    else:
        return workflow
    resources = load_resource_type_registry_from_mapping(
        yaml.safe_load(
            (catalog_root / "vocabulary/resource-types.yaml").read_text(encoding="utf-8")
        )
    )
    rules = HandoverRuleCompiler(
        container.schema_registry,
        frozenset(item.name for item in action_types),
        frozenset(resources.ids()),
        catalog_root.parent / "policies",
        catalog_root / "remediation",
    )
    base = VerificationContext(
        ontology_release=ontology_release.digest.removeprefix("sha256:"),
        current_graph_revision="unobserved:handover-review-only",
        object_types=frozenset(item.name for item in container.ontology_object_types),
        links=tuple(
            LinkDeclaration(item.name, item.from_type, item.to_type)
            for item in container.ontology_link_types
        ),
        entities=(),
        source_policies=(),
        claim_text=(),
        object_properties=tuple(
            TypePropertyDeclaration(item.name, tuple(sorted(item.properties)))
            for item in container.ontology_object_types
        ),
    )

    def context(envelope: DocumentEnvelope) -> VerificationContext:
        return replace(
            base,
            source_policies=(
                SourceAuthorityPolicy(
                    source_ref=(
                        f"document://{envelope.document_id}/versions/{envelope.version_id}"
                    ),
                    allowed=frozenset({AuthorityClass.DECLARED_INTENT, AuthorityClass.PROCEDURE}),
                    priority=10,
                ),
            ),
        )

    fingerprint = {
        "version": "handover-semantics.v1",
        "release": ontology_release.digest,
        "distiller": asdict(describe_distiller(container.distiller)),
        "actions": sorted(rules.action_type_names),
        "resources": sorted(rules.resource_type_ids),
        "source_authority": ["declared_intent", "procedure"],
        "graph_revision": base.current_graph_revision,
    }
    compiler_digest = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    verifier = HandoverSemanticVerification(rules, context, compiler_digest)
    packages = PostgresHandoverSemanticPackages(core.source.config)

    def source() -> CurrentAcceptedHandoverSources:
        return CurrentAcceptedHandoverSources(
            HandoverKnowledgeSourceCheck(CurrentCoreHandoverSource(core.source, core)),
            core.admission,
            envelopes,
            lambda: datetime.now(UTC),
        )

    return replace(
        workflow,
        semantic_compiler=HandoverSemanticCompilation(
            source(), packages, container.distiller, verifier
        ),
        semantic_reviewer=HandoverSemanticReview(source(), packages, verifier),
    )


__all__ = ["bind_handover_semantics"]
