"""Publish one protected OHL scale-out proposal into the normal control-loop ingress."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

import httpx

from fdai.delivery.azure.event_bus import EventHubsKafkaBus, EventHubsKafkaBusConfig
from fdai.delivery.azure.workload_identity import ManagedIdentityWorkloadIdentity
from fdai.shared.providers.event_bus import EventBus, PublishReceipt

_LOGGER = logging.getLogger("fdai.ohl_scale_out_evidence")
_TARGET_PATTERN = re.compile(
    r"^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/"
    r"Microsoft\.Compute/virtualMachineScaleSets/[^/]+$",
    re.IGNORECASE,
)
_CAMPAIGN_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_REASON = "OHL Lane F protected scale-out evidence campaign."


@dataclass(frozen=True, slots=True)
class OhlScaleOutProposalConfig:
    """Validated deployment-owned inputs for one retry-stable proposal."""

    bootstrap_servers: str
    topic: str
    target_resource_id: str
    initiator_principal: str
    campaign_id: str
    baseline_capacity: int = 1

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> OhlScaleOutProposalConfig:
        """Load the bounded proposal coordinates without reading secrets."""
        values = os.environ if environ is None else environ
        raw_capacity = values.get("FDAI_OHL_BASELINE_CAPACITY", "1").strip()
        try:
            baseline_capacity = int(raw_capacity)
        except ValueError as exc:
            raise ValueError("FDAI_OHL_BASELINE_CAPACITY MUST be an integer") from exc
        return cls(
            bootstrap_servers=values.get("KAFKA_BOOTSTRAP_SERVERS", "").strip(),
            topic=values.get("KAFKA_TOPIC_EVENTS", "").strip(),
            target_resource_id=values.get("FDAI_OHL_TARGET_RESOURCE_ID", "").strip(),
            initiator_principal=values.get("FDAI_OHL_INITIATOR_PRINCIPAL_ID", "").strip(),
            campaign_id=values.get("FDAI_OHL_CAMPAIGN_ID", "").strip(),
            baseline_capacity=baseline_capacity,
        )

    def __post_init__(self) -> None:
        if not self.bootstrap_servers or len(self.bootstrap_servers) > 512:
            raise ValueError("KAFKA_BOOTSTRAP_SERVERS MUST be a bounded non-empty value")
        if not self.topic or len(self.topic) > 256:
            raise ValueError("KAFKA_TOPIC_EVENTS MUST be a bounded non-empty value")
        if _TARGET_PATTERN.fullmatch(self.target_resource_id) is None:
            raise ValueError("FDAI_OHL_TARGET_RESOURCE_ID MUST identify one Azure VM Scale Set")
        try:
            UUID(self.initiator_principal)
        except ValueError as exc:
            raise ValueError("FDAI_OHL_INITIATOR_PRINCIPAL_ID MUST be a UUID") from exc
        if _CAMPAIGN_PATTERN.fullmatch(self.campaign_id) is None:
            raise ValueError("FDAI_OHL_CAMPAIGN_ID MUST use 1 to 128 safe characters")
        if not 0 <= self.baseline_capacity < 1000:
            raise ValueError("FDAI_OHL_BASELINE_CAPACITY MUST be in [0, 999]")


def build_scale_out_proposal(config: OhlScaleOutProposalConfig) -> dict[str, object]:
    """Build the exact raw operator request consumed by ``EventIngest``."""
    idempotency_key = f"ohl-scale-out:{config.campaign_id}"
    return {
        "idempotency_key": idempotency_key,
        "correlation_id": idempotency_key,
        "initiator_principal": config.initiator_principal,
        "operator_initiated": True,
        "action_type": "ops.scale-out",
        "resource_id": config.target_resource_id,
        "resource_type": "Microsoft.Compute/virtualMachineScaleSets",
        "event_type": "operator_request",
        "params": {
            "target_resource_ref": config.target_resource_id,
            "replica_count": config.baseline_capacity + 1,
            "reason": _REASON,
        },
    }


async def publish_scale_out_proposal(
    config: OhlScaleOutProposalConfig,
    event_bus: EventBus,
) -> PublishReceipt:
    """Publish one proposal with target-scoped partition ordering."""
    return await event_bus.publish(
        config.topic,
        config.target_resource_id,
        build_scale_out_proposal(config),
    )


async def _run() -> int:
    config = OhlScaleOutProposalConfig.from_env()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=15.0, write=15.0, pool=5.0)
    ) as http_client:
        identity = ManagedIdentityWorkloadIdentity.from_env(http_client=http_client)
        bus = EventHubsKafkaBus(
            identity=identity,
            config=EventHubsKafkaBusConfig(
                bootstrap_servers=config.bootstrap_servers,
                client_id="fdai-ohl-scale-out-evidence",
            ),
        )
        try:
            await publish_scale_out_proposal(config, bus)
        finally:
            await bus.close()
    _LOGGER.info(
        "ohl_scale_out_proposal_published",
        extra={
            "campaign_id": config.campaign_id,
            "target_digest": hashlib.sha256(config.target_resource_id.encode()).hexdigest(),
        },
    )
    return 0


def main() -> int:
    """Publish one proposal and map validation or provider failures to job failure."""
    logging.basicConfig(level=logging.INFO)
    try:
        return asyncio.run(_run())
    except Exception:
        _LOGGER.exception("ohl_scale_out_proposal_failed")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "OhlScaleOutProposalConfig",
    "build_scale_out_proposal",
    "main",
    "publish_scale_out_proposal",
]
