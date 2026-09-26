"""Bounded, read-only broker reconciliation for uncertain analyzer publications."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from aiokafka import AIOKafkaConsumer, TopicPartition

from fdai.delivery.analyzer_tick import ANALYZER_EVENT_SOURCE
from fdai.delivery.azure.event_bus import (
    EventHubsKafkaBusConfig,
    _audience_from_bootstrap,
    _EntraTokenProvider,
    _transport_options,
)
from fdai.delivery.azure.event_bus_codec import decode_payload
from fdai.shared.providers.event_bus import PublishReceipt
from fdai.shared.providers.workload_identity import WorkloadIdentity

_MAX_RECORDS = 10_000
_LOOKUP_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class KafkaAnalyzerPublicationReconciler:
    """Find accepted event IDs without consuming, committing, or inferring absence.

    A retained broker record proves acceptance. A bounded scan with no match does
    not prove absence: retention, compaction, or a delayed ambiguous send could
    hide a record. In that case the durable claim remains uncertain.
    """

    config: EventHubsKafkaBusConfig
    identity: WorkloadIdentity | None

    async def reconcile(
        self, *, event_id: UUID, idempotency_key: str, topic: str
    ) -> PublishReceipt | None:
        token_provider = (
            _EntraTokenProvider(
                self.identity,
                self.config.audience or _audience_from_bootstrap(self.config.bootstrap_servers),
            )
            if self.identity is not None and self.config.security_protocol == "SASL_SSL"
            else None
        )
        consumer = AIOKafkaConsumer(
            bootstrap_servers=self.config.bootstrap_servers,
            client_id=f"{self.config.client_id}-analyzer-reconcile",
            group_id=None,
            enable_auto_commit=False,
            api_version="2.0.0",
            connections_max_idle_ms=self.config.connections_max_idle_ms,
            metadata_max_age_ms=self.config.metadata_max_age_ms,
            request_timeout_ms=self.config.request_timeout_ms,
            retry_backoff_ms=self.config.retry_backoff_ms,
            max_partition_fetch_bytes=256_000,
            fetch_max_bytes=1_000_000,
            **_transport_options(config=self.config, token_provider=token_provider),
        )
        try:
            async with asyncio.timeout(_LOOKUP_SECONDS):
                await consumer.start()
                partitions = await consumer.partitions_for_topic(topic)
                if not partitions:
                    raise RuntimeError("analyzer publication topic is unavailable")
                assigned = [TopicPartition(topic, partition) for partition in sorted(partitions)]
                consumer.assign(assigned)
                beginnings = await consumer.beginning_offsets(assigned)
                ends = await consumer.end_offsets(assigned)
                if set(beginnings) != set(assigned) or set(ends) != set(assigned):
                    raise RuntimeError("analyzer publication offsets are incomplete")
                positions: dict[TopicPartition, int] = {}
                for partition in assigned:
                    first = beginnings[partition]
                    end = ends[partition]
                    if first < 0 or end < first:
                        raise RuntimeError("analyzer publication offsets are invalid")
                    positions[partition] = max(first, end - _MAX_RECORDS)
                    consumer.seek(partition, positions[partition])
                scanned = 0
                while any(positions[partition] < ends[partition] for partition in assigned):
                    batch = await consumer.getmany(timeout_ms=500, max_records=200)
                    for partition, records in batch.items():
                        if partition not in positions:
                            raise RuntimeError("analyzer publication partition changed")
                        for record in records:
                            if record.offset < positions[partition]:
                                continue
                            if record.offset >= ends[partition]:
                                break
                            scanned += 1
                            if scanned > _MAX_RECORDS:
                                raise RuntimeError("analyzer publication lookup bound exceeded")
                            positions[partition] = record.offset + 1
                            payload = decode_payload(record.value, topic=topic)
                            if payload.get("event_id") != str(event_id):
                                continue
                            if (
                                payload.get("idempotency_key") != idempotency_key
                                or payload.get("source") != ANALYZER_EVENT_SOURCE
                            ):
                                raise RuntimeError("analyzer publication event identity conflicts")
                            return PublishReceipt(
                                topic=topic, partition=partition.partition, offset=record.offset
                            )
                raise RuntimeError("analyzer publication absence cannot be established")
        finally:
            await consumer.stop()


__all__ = ["KafkaAnalyzerPublicationReconciler"]
