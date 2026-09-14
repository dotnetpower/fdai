"""Bounded conditional source collection; failed observations never renew freshness."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Protocol

from fdai_service_contracts.cloud_knowledge import (
    CloudKnowledgeSource,
    CloudSourceEvidence,
    KnowledgeContract,
    SourceCheckReceipt,
    content_digest,
)
from fdai_service_contracts.cloud_knowledge_release import CloudKnowledgeDocument

from fdai_ingestion_api_service.cloud_knowledge.normalization import normalize_source


@dataclass(frozen=True, slots=True)
class SourceResponse:
    """One bounded response from the approved network adapter."""

    status: int
    content: bytes = b""
    media_type: str = "text/plain"
    etag: str | None = None
    last_modified: str | None = None
    retry_after_seconds: int = 0


class SourceTransport(Protocol):
    async def fetch(self, source: CloudKnowledgeSource, *, etag: str | None) -> SourceResponse:
        """Fetch only the exact registered source with bounded bytes and no redirects."""
        ...


class SourceState(KnowledgeContract):
    """Checkpoint cache; document source times never derive from local row timestamps."""

    document: CloudKnowledgeDocument | None = None
    last_attempt: SourceCheckReceipt | None = None
    last_full_fetch_at: datetime | None = None
    retry_after: datetime | None = None
    consecutive_failures: int = 0


def source_due(source: CloudKnowledgeSource, state: SourceState, now: datetime) -> bool:
    """Select enabled authorized online sources without making a network request."""
    if now.utcoffset() is None:
        raise ValueError("collector clock MUST be timezone-aware")
    if not source.enabled or not source.storage_allowed or source.mode != "online":
        return False
    if state.consecutive_failures >= 5 or state.retry_after is not None and now < state.retry_after:
        return False
    return state.document is None or now >= state.document.evidence.check.checked_at + timedelta(
        seconds=source.policy.check_interval_seconds
    )


class CloudDocumentCollector:
    """Collect one source per bounded attempt; persistence and scheduling remain injected."""

    def __init__(
        self,
        transport: SourceTransport,
        *,
        collector_id: str,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        if not 0 < request_timeout_seconds <= 30:
            raise ValueError("source request timeout MUST be in (0, 30]")
        self._transport = transport
        self._collector_id = collector_id
        self._timeout = request_timeout_seconds

    async def collect(
        self,
        source: CloudKnowledgeSource,
        previous: SourceState,
        *,
        now: datetime,
    ) -> SourceState:
        """Fetch once, with one full-body fallback only for an unusable conditional result."""
        if not source_due(source, previous, now):
            return previous
        etag = None
        old = previous.document
        if (
            old is not None
            and previous.last_full_fetch_at is not None
            and now - previous.last_full_fetch_at
            < timedelta(
                seconds=source.policy.full_fetch_interval_seconds,
            )
        ):
            candidate = old.evidence.check.etag
            if candidate is not None and re.fullmatch(r'"[\x21\x23-\x7e]{1,500}"', candidate):
                etag = candidate
        try:
            async with asyncio.timeout(self._timeout):
                response = await self._transport.fetch(source, etag=etag)
                if response.status == 304 and (
                    old is None or etag is None or response.etag != etag
                ):
                    etag = None
                    response = await self._transport.fetch(source, etag=None)
            if (
                response.status == 304
                and old is not None
                and etag is not None
                and response.etag == etag
            ):
                check = self._receipt(
                    source,
                    now,
                    outcome="unchanged",
                    digest=old.evidence.source_sha256,
                    equivalence="strong_etag",
                    response=response,
                )
                updated = CloudKnowledgeDocument.model_validate(
                    old.model_dump()
                    | {
                        "evidence": old.evidence.model_dump() | {"check": check.model_dump()},
                    },
                )
                return SourceState(
                    document=updated,
                    last_attempt=check,
                    last_full_fetch_at=previous.last_full_fetch_at,
                )
            if response.status != 200:
                return self._failed(
                    source,
                    previous,
                    now,
                    f"http_{response.status}",
                    withdrawal=response.status in {404, 410},
                    retry_after=response.retry_after_seconds,
                )
            original, text = normalize_source(
                response.content,
                response.media_type,
                max_bytes=source.max_bytes,
            )
            digest = content_digest(response.content)
            same = old is not None and old.evidence.source_sha256 == digest
            check = self._receipt(
                source,
                now,
                outcome="unchanged" if same else "changed" if old else "fetched",
                digest=digest,
                equivalence="body_hash",
                response=response,
            )
            updated_at = None
            if response.last_modified:
                try:
                    updated_at = parsedate_to_datetime(response.last_modified)
                except (TypeError, ValueError, OverflowError):
                    pass  # Publisher date is optional, never substituted for collection time.
            evidence = CloudSourceEvidence(
                source_id=source.source_id,
                source_url=source.url,
                source_sha256=digest,
                normalized_sha256=content_digest(text.encode()),
                collected_at=old.evidence.collected_at if same and old else now,
                source_updated_at=updated_at,
                check=check,
                applicability=source.applicability,
                policy=source.policy,
                license_ref=source.license_ref,
            )
            return SourceState(
                document=CloudKnowledgeDocument(
                    evidence=evidence,
                    title=source.title,
                    original_text=original,
                    text=text,
                ),
                last_attempt=check,
                last_full_fetch_at=now,
            )
        except (TimeoutError, OSError, ValueError):
            return self._failed(source, previous, now, "source_unavailable")

    def _receipt(
        self,
        source: CloudKnowledgeSource,
        now: datetime,
        *,
        outcome: str,
        digest: str,
        equivalence: str,
        response: SourceResponse,
    ) -> SourceCheckReceipt:
        return SourceCheckReceipt.model_validate(
            {
                "source_id": source.source_id,
                "source_url": source.url,
                "checked_at": now,
                "outcome": outcome,
                "content_sha256": digest,
                "equivalence": equivalence,
                "etag": response.etag,
                "last_modified": response.last_modified,
                "collector_id": self._collector_id,
            },
        )

    def _failed(
        self,
        source: CloudKnowledgeSource,
        previous: SourceState,
        now: datetime,
        reason: str,
        *,
        withdrawal: bool = False,
        retry_after: int = 0,
    ) -> SourceState:
        failures = previous.consecutive_failures + 1
        delay = min(7 * 86400, max(3600 * 2 ** min(failures - 1, 5), retry_after))
        # Stable source-specific jitter prevents all sources retrying simultaneously.
        jitter = int(content_digest(source.source_id.encode())[:4], 16) % 300
        return SourceState(
            document=previous.document,
            last_full_fetch_at=previous.last_full_fetch_at,
            consecutive_failures=failures,
            retry_after=now + timedelta(seconds=delay + jitter),
            last_attempt=SourceCheckReceipt(
                source_id=source.source_id,
                source_url=source.url,
                checked_at=now,
                outcome="withdrawal_pending" if withdrawal else "failed",
                collector_id=self._collector_id,
                reason=reason,
            ),
        )
