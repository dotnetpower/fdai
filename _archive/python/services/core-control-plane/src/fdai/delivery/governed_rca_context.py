"""Server-owned principal and access context for automated governed RCA reads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from fdai.core.ontology_platform.functions import FunctionInvocationContext
from fdai.core.ontology_platform.query_receipt_authority import SecuredQueryReceiptAuthority
from fdai.core.operational_context import (
    AuthenticatedPrincipalContext,
    OperationalEvidenceReadRequest,
)
from fdai.core.rca.governed_knowledge_evidence import (
    GovernedDocumentAccessContext,
    GovernedKnowledgeEvidenceContext,
)
from fdai.shared.contracts.models import CeilingRole

_PRINCIPAL_REF = "principal:fdai-rca"
_PURPOSE = "incident-review"


@dataclass(frozen=True, slots=True)
class GovernedRcaContextConfig:
    """Deployment-owned collection and exact access markers."""

    collection_id: str
    allowed_access_refs: frozenset[str]
    actor_groups: frozenset[str]

    def __post_init__(self) -> None:
        if not self.collection_id.strip() or len(self.collection_id) > 256:
            raise ValueError(
                "governed RCA collection_id MUST be non-empty and at most 256 characters"
            )
        for name, values in (
            ("allowed_access_refs", self.allowed_access_refs),
            ("actor_groups", self.actor_groups),
        ):
            if not values or any(not value.strip() or len(value) > 512 for value in values):
                raise ValueError(f"governed RCA {name} MUST contain bounded non-empty values")

    @classmethod
    def from_environ(
        cls,
        environment: Mapping[str, str],
    ) -> GovernedRcaContextConfig | None:
        """Return no binding when all settings are absent; reject partial settings."""

        collection_id = environment.get("FDAI_RCA_GOVERNED_COLLECTION_ID", "").strip()
        access_raw = environment.get("FDAI_RCA_GOVERNED_ACCESS_REFS_JSON", "").strip()
        groups_raw = environment.get("FDAI_RCA_GOVERNED_ACTOR_GROUPS_JSON", "").strip()
        if not collection_id and not access_raw and not groups_raw:
            return None
        if not collection_id or not access_raw or not groups_raw:
            raise ValueError(
                "governed RCA collection, access refs, and groups MUST be bound together"
            )
        return cls(
            collection_id=collection_id,
            allowed_access_refs=_json_string_set(
                access_raw,
                name="FDAI_RCA_GOVERNED_ACCESS_REFS_JSON",
            ),
            actor_groups=_json_string_set(
                groups_raw,
                name="FDAI_RCA_GOVERNED_ACTOR_GROUPS_JSON",
            ),
        )


class RuntimeGovernedRcaContextProvider:
    """Create an authority-free context for Forseti's automated RCA read."""

    def __init__(self, *, config: GovernedRcaContextConfig) -> None:
        self._config = config
        self._authority = SecuredQueryReceiptAuthority(now=lambda: datetime.now(tz=UTC))
        self._principal_scope_digest = _scope_digest(config)

    async def context_for(
        self,
        *,
        incident_ref: str,
        resource_ref: str,
        cutoff: datetime,
        ontology_release_digest: str,
        catalog_revision: str,
    ) -> GovernedKnowledgeEvidenceContext:
        """Bind one exact resource and evidence cutoff to the configured principal."""

        if (
            not incident_ref.strip()
            or len(incident_ref) > 1_024
            or not resource_ref.strip()
            or len(resource_ref) > 1_024
        ):
            raise ValueError("governed RCA incident and resource refs MUST be bounded")
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("governed RCA cutoff MUST be timezone-aware")
        if (
            len(ontology_release_digest) != 71
            or not ontology_release_digest.startswith("sha256:")
            or not catalog_revision.strip()
            or len(catalog_revision) > 256
        ):
            raise ValueError("governed RCA release and catalog identity are invalid")
        request = OperationalEvidenceReadRequest(
            ontology_release_digest=ontology_release_digest,
            catalog_revision=catalog_revision,
            purpose=_PURPOSE,
            scope=(incident_ref, resource_ref),
            cutoff=cutoff,
        )
        principal = AuthenticatedPrincipalContext(
            principal_ref=_PRINCIPAL_REF,
            principal_scope_digest=self._principal_scope_digest,
            purpose=_PURPOSE,
            receipt_authority=self._authority,
            invocation_context=FunctionInvocationContext(
                caller_agent="Forseti",
                caller_role=CeilingRole.READER,
                purposes=(_PURPOSE,),
            ),
            verification_context=self._authority.verification_context,
        )
        access_context_ref = (
            f"access-context:fdai-rca:{self._principal_scope_digest.removeprefix('sha256:')[:24]}"
        )
        return GovernedKnowledgeEvidenceContext(
            read_request=request,
            authenticated_context=principal,
            access_context=GovernedDocumentAccessContext(
                collection_id=self._config.collection_id,
                access_context_ref=access_context_ref,
                allowed_access_refs=self._config.allowed_access_refs,
                actor_groups=self._config.actor_groups,
            ),
        )


def _scope_digest(config: GovernedRcaContextConfig) -> str:
    material = json.dumps(
        {
            "actor_groups": sorted(config.actor_groups),
            "allowed_access_refs": sorted(config.allowed_access_refs),
            "collection_id": config.collection_id,
            "principal_ref": _PRINCIPAL_REF,
            "purpose": _PURPOSE,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(material.encode()).hexdigest()}"


def _json_string_set(raw: str, *, name: str) -> frozenset[str]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} MUST be a JSON string array") from exc
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= 64
        or any(not isinstance(item, str) or not item.strip() or len(item) > 512 for item in value)
    ):
        raise ValueError(f"{name} MUST contain 1-64 non-empty strings")
    normalized = tuple(item.strip() for item in value)
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{name} MUST contain unique values")
    return frozenset(normalized)


__all__ = [
    "GovernedRcaContextConfig",
    "RuntimeGovernedRcaContextProvider",
]
