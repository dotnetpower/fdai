"""Read-only chat projection for an integrity-pinned configuration baseline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Final

from fdai.core.detection.configuration_drift import KnowledgeGroundingStatus
from fdai.core.detection.configuration_drift_service import (
    ConfigurationBaselineSource,
    ConfigurationDriftService,
)
from fdai.delivery.operator_api.routes.chat_system_health import ChatToolResolver

_BASELINE_DOCUMENT_REF: Final = "sre-s13-workload-infrastructure-baseline.docx"


def needs_configuration_drift_context(prompt: str) -> bool:
    """Return whether a turn names the server-pinned frozen baseline document."""

    return _BASELINE_DOCUMENT_REF in prompt.casefold()


@dataclass(frozen=True, slots=True)
class ConfigurationDriftChatTools:
    """Project the exact frozen baseline and its Knowledge citation."""

    baseline_source: ConfigurationBaselineSource
    service: ConfigurationDriftService
    document_name: str
    fallback: ChatToolResolver | None = None

    def with_fallback(self, fallback: ChatToolResolver) -> ConfigurationDriftChatTools:
        """Return a new resolver that preserves the existing tool chain."""

        return replace(self, fallback=fallback)

    async def resolve(self, prompt: str, *, principal_id: str) -> dict[str, Any] | None:
        if not needs_configuration_drift_context(prompt):
            if self.fallback is None:
                return None
            return await self.fallback.resolve(prompt, principal_id=principal_id)
        try:
            baseline = await self.baseline_source.load()
            report = await self.service.run()
        except Exception as exc:  # noqa: BLE001 - evidence failure stays bounded and read-only
            return _response(
                "unavailable",
                reason=f"configuration_baseline_unavailable:{type(exc).__name__}",
            )
        if report.knowledge_status is not KnowledgeGroundingStatus.CITED:
            return _response(
                "unavailable",
                reason=f"configuration_baseline_knowledge_{report.knowledge_status.value}",
                evidence_refs=report.knowledge_citations,
            )
        return _response(
            "matched",
            evidence_refs=report.knowledge_citations,
            data={
                "version": baseline.version,
                "created_at": baseline.created_at.isoformat(),
                "document_name": self.document_name,
                "resources": [
                    {
                        "name": resource.local_name,
                        "resource_type": resource.resource_type,
                        "sku_or_tier": _sku_or_tier(resource.attributes),
                    }
                    for resource in baseline.resources[:3]
                ],
                "topology": [
                    {
                        "source": link.source,
                        "relation": link.relation,
                        "target": link.target,
                    }
                    for link in baseline.links[:3]
                ],
                "topology_complete": bool(baseline.links),
                "drift_verdict": report.verdict.value,
                "mutation_count": report.mutation_count,
                "approval_request_count": report.approval_request_count,
                "mitigation_execution_count": report.mitigation_execution_count,
                "unsupported_claim_count": report.unsupported_claim_count,
            },
        )

    async def resolve_with_context(
        self,
        prompt: str,
        *,
        principal_id: str,
        context: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        del context
        return await self.resolve(prompt, principal_id=principal_id)


def _sku_or_tier(attributes: Mapping[str, object]) -> str:
    values = tuple(
        str(attributes[key])
        for key in ("sku_name", "sku_tier", "sku", "tier")
        if key in attributes and str(attributes[key]).strip()
    )
    return " / ".join(dict.fromkeys(values)) if values else "unknown"


def _response(
    status: str,
    *,
    reason: str | None = None,
    evidence_refs: tuple[str, ...] = (),
    data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "tool": "query_knowledge_context",
        "authority": "server_knowledge_context",
        "status": "ok" if status == "matched" else "abstain",
        "result": {
            "intent": "configuration_baseline",
            "status": status,
            "reason": reason,
            "evidence_refs": list(dict.fromkeys(evidence_refs)),
            "data": dict(data or {}),
        },
    }


__all__ = ["ConfigurationDriftChatTools", "needs_configuration_drift_context"]
