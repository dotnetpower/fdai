"""Publish verified bounded live evidence through canonical inventory ingress."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from fdai.core.ontology_platform.models import ObjectSetDefinition
from fdai.core.ontology_platform.query_gateway import SecuredObjectSetQueryResult
from fdai.delivery.persistence.postgres_inventory_delta import (
    InventoryDeltaApplyOutcome,
    InventoryDeltaApplyResult,
)
from fdai.shared.providers.read_investigation import (
    EvidenceFreshness,
    EvidenceStatus,
    ReadEvidenceEnvelope,
    ReadInvestigationProvider,
    ReadToolLimits,
    ResolvedResource,
)


class InventoryObservationIngress(Protocol):
    """Accept one canonical inventory observation payload."""

    async def __call__(self, payload: dict[str, Any]) -> InventoryDeltaApplyResult: ...


@dataclass(frozen=True, slots=True)
class LiveEvidenceWriteThroughReceipt:
    """Record a bounded write-through without granting graph or action authority."""

    event_id: str
    idempotency_key: str
    published: bool
    projector_outcome: InventoryDeltaApplyOutcome | None
    reason_code: str
    digest: str
    observation_authority: bool = False
    mutation_authority: bool = False
    execution_authority: bool = False


class InventoryLiveEvidenceWriter:
    """Convert verified live evidence to a partial overlay upsert."""

    def __init__(self, *, ingress: InventoryObservationIngress) -> None:
        self._ingress = ingress

    async def publish(
        self,
        *,
        resource: ResolvedResource,
        evidence: ReadEvidenceEnvelope,
        ontology_release_digest: str,
    ) -> LiveEvidenceWriteThroughReceipt:
        """Publish matched live evidence and reject every weaker posture."""

        _digest(ontology_release_digest, "ontology_release_digest")
        if evidence.resource_ref != resource.resource_ref:
            return _receipt("resource_mismatch")
        if (
            evidence.status is not EvidenceStatus.MATCHED
            or evidence.freshness is not EvidenceFreshness.LIVE
            or evidence.truncated
        ):
            return _receipt("live_evidence_unverified")
        latest = max(evidence.records, key=lambda item: item.occurred_at)
        live_values: dict[str, object] = {
            "authority": evidence.authority,
            "observed_at": evidence.observed_at.isoformat(),
            "recorded_fact_at": latest.occurred_at.isoformat(),
            "ontology_release_digest": ontology_release_digest,
            "evidence_refs": evidence.evidence_refs,
            "limitations": tuple(item.value for item in evidence.limitations),
            "complete": not evidence.limitations,
        }
        if latest.state is not None:
            live_values["state"] = latest.state
        if latest.health_kind is not None:
            live_values["health_kind"] = latest.health_kind
        if latest.details:
            live_values["details"] = dict(latest.details)
        identity = {
            "resource_ref": resource.resource_ref,
            "resource_type": resource.resource_type,
            "observed_at": evidence.observed_at.isoformat(),
            "authority": evidence.authority,
            "evidence_refs": evidence.evidence_refs,
            "ontology_release_digest": ontology_release_digest,
            "live_values": live_values,
        }
        digest = _sha256(identity)
        event_id = f"inventory-live:{digest[7:]}"
        idempotency_key = f"inventory-live:{digest}"
        result = await self._ingress(
            {
                "event_type": "inventory.resource_changed",
                "event_id": event_id,
                "idempotency_key": idempotency_key,
                "inventory_change": {
                    "kind": "upsert",
                    "properties_complete": False,
                    "resource": {
                        "resource_id": resource.resource_ref,
                        "type": resource.resource_type,
                        "props": {"live_evidence": live_values},
                        "provider_ref": None,
                        "last_seen": evidence.observed_at.isoformat(),
                    },
                    "links_complete": False,
                    "links": [],
                },
            }
        )
        return _receipt(
            "published",
            event_id=event_id,
            idempotency_key=idempotency_key,
            published=True,
            projector_outcome=result.outcome,
        )


class InventoryGraphLiveRefreshProvider:
    """Refresh one exact secured Resource through the canonical observation ingress."""

    def __init__(
        self,
        *,
        provider: ReadInvestigationProvider,
        writer: InventoryLiveEvidenceWriter,
        scope_ref: str,
    ) -> None:
        if not scope_ref.strip():
            raise ValueError("inventory graph refresh scope_ref MUST be non-empty")
        self._provider = provider
        self._writer = writer
        self._scope_ref = scope_ref
        self._limits = ReadToolLimits(
            timeout_seconds=3.0,
            max_results=10,
            max_output_bytes=65_536,
        )

    async def refresh(
        self,
        *,
        definition: ObjectSetDefinition,
        secured: SecuredObjectSetQueryResult,
    ) -> bool:
        """Publish one verified exact-resource observation; decline every wider query."""

        del definition
        resources = tuple(
            item for item in secured.materialization.graph.objects if item.object_type == "Resource"
        )
        if len(resources) != 1:
            return False
        record = resources[0]
        name = record.properties.get("name")
        resource_type = record.properties.get("type")
        if not isinstance(name, str) or not name.strip():
            return False
        if not isinstance(resource_type, str) or not resource_type.strip():
            return False
        resource = ResolvedResource(
            resource_ref=record.id,
            scope_ref=self._scope_ref,
            name=name,
            resource_type=resource_type,
        )
        attempt = await self._provider.get_resource_state(resource, limits=self._limits)
        receipt = await self._writer.publish(
            resource=resource,
            evidence=attempt.evidence,
            ontology_release_digest=secured.receipt.ontology_release.digest,
        )
        return receipt.published


def _receipt(
    reason_code: str,
    *,
    event_id: str = "none",
    idempotency_key: str = "none",
    published: bool = False,
    projector_outcome: InventoryDeltaApplyOutcome | None = None,
) -> LiveEvidenceWriteThroughReceipt:
    body = {
        "event_id": event_id,
        "idempotency_key": idempotency_key,
        "published": published,
        "projector_outcome": (projector_outcome.value if projector_outcome is not None else None),
        "reason_code": reason_code,
        "observation_authority": False,
        "mutation_authority": False,
        "execution_authority": False,
    }
    return LiveEvidenceWriteThroughReceipt(
        event_id=event_id,
        idempotency_key=idempotency_key,
        published=published,
        projector_outcome=projector_outcome,
        reason_code=reason_code,
        digest=_sha256(body),
    )


def _sha256(value: object) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
    )


def _digest(value: str, name: str) -> None:
    if (
        len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"inventory live evidence {name} MUST be a canonical digest")


__all__ = [
    "InventoryGraphLiveRefreshProvider",
    "InventoryLiveEvidenceWriter",
    "InventoryObservationIngress",
    "LiveEvidenceWriteThroughReceipt",
]
