"""Read exact, authoritative inventory records without treating deltas as observations."""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from fdai.core.investigation.resource_availability_evidence import (
    AvailabilityUnavailableReason,
    ResourceAvailabilityEvidence,
    ResourceOperationalState,
)
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.state_evidence import STATE_FACT_METADATA_PROPERTY, StateFactMetadata


class AvailabilityInventoryReader(Protocol):
    async def read_active_resources(
        self, *, resource_ids: tuple[str, ...]
    ) -> tuple[str | None, Mapping[str, ResourceRecord]]: ...


@dataclass(frozen=True, slots=True)
class ResourceAvailabilityBinding:
    resource_ref: str
    resource_type: str
    provider_ref: str
    scope_ref: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.resource_ref,
                self.resource_type,
                self.provider_ref,
                self.scope_ref,
            )
        ):
            raise ValueError("availability binding MUST have exact identity, type and scope")


class InventoryResourceAvailabilitySource:
    """Use retained full/current records and their own last_seen, never read time.

    ``reader`` must read the authoritative active snapshot, not change hints.
    The existing PostgresInventorySnapshotStore.read_active_resources does so.
    A revision fence can bind the source to the target-resolution generation.
    """

    def __init__(
        self,
        reader: AvailabilityInventoryReader,
        *,
        bindings: Sequence[ResourceAvailabilityBinding],
        state_reader: Callable[[ResourceRecord], ResourceOperationalState],
        supported_resource_types: frozenset[str],
        expected_snapshot_id: str | None = None,
        timeout_seconds: float = 10.0,
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("availability source timeout MUST be finite and positive")
        self._bindings = {item.resource_ref: item for item in bindings}
        if len(self._bindings) != len(bindings) or len(
            {item.provider_ref.casefold() for item in bindings}
        ) != len(bindings):
            raise ValueError("availability bindings MUST have unambiguous exact identities")
        self._reader = reader
        self._state_reader = state_reader
        self._supported = supported_resource_types
        self._revision = expected_snapshot_id
        self._timeout = timeout_seconds
        self._clock = wall_clock or (lambda: datetime.now(UTC))

    async def observe(
        self, *, resource_ref: str, since: datetime, until: datetime
    ) -> ResourceAvailabilityEvidence:
        del since, until
        binding = self._bindings.get(resource_ref)
        if binding is None:
            raise ValueError("availability target MUST have an inventory identity binding")
        reason: AvailabilityUnavailableReason | None = None
        state_metadata: StateFactMetadata | None = None
        revision: str | None = None
        record: ResourceRecord | None = None
        if binding.resource_type not in self._supported:
            reason = AvailabilityUnavailableReason.UNSUPPORTED_RESOURCE_TYPE
        else:
            try:
                async with asyncio.timeout(self._timeout):
                    revision, resources = await self._reader.read_active_resources(
                        resource_ids=(resource_ref,)
                    )
                record = resources.get(resource_ref)
                if revision is None:
                    reason = AvailabilityUnavailableReason.SOURCE_UNAVAILABLE
                elif self._revision is not None and revision != self._revision:
                    reason = AvailabilityUnavailableReason.GENERATION_CHANGED
                elif record is None:
                    reason = AvailabilityUnavailableReason.RESOURCE_MISSING
                elif (
                    record.resource_id != binding.resource_ref
                    or record.type != binding.resource_type
                    or record.provider_ref is None
                    or record.provider_ref.casefold() != binding.provider_ref.casefold()
                    or set(resources) != {resource_ref}
                ):
                    reason = AvailabilityUnavailableReason.IDENTITY_MISMATCH
                elif record.props.get("_truncated") is True:
                    reason = AvailabilityUnavailableReason.OBSERVATION_INCOMPLETE
                else:
                    metadata = record.props.get(STATE_FACT_METADATA_PROPERTY)
                    if metadata is not None:
                        if not isinstance(metadata, Mapping):
                            raise ValueError("state fact metadata MUST be a mapping")
                        raw = (
                            metadata
                            if "lane" in metadata
                            else metadata.get("state", metadata.get("status"))
                        )
                        if raw is not None:
                            if not isinstance(raw, Mapping):
                                raise ValueError("state fact metadata MUST be a mapping")
                            state_metadata = StateFactMetadata.from_mapping(raw)
            except PermissionError:
                reason = AvailabilityUnavailableReason.AUTHORIZATION_DENIED
            except (TypeError, ValueError):
                reason = AvailabilityUnavailableReason.OBSERVATION_INCOMPLETE
            except Exception:  # noqa: BLE001 - unavailable never means healthy
                reason = AvailabilityUnavailableReason.SOURCE_UNAVAILABLE
        valid = record is not None and reason is None
        observed_at = (
            datetime.fromisoformat(record.last_seen.replace("Z", "+00:00"))
            if valid and record is not None and record.last_seen is not None
            else None
        )
        if valid and state_metadata is not None:
            observed_at = state_metadata.effective_at
        identity = hashlib.sha256(resource_ref.encode()).hexdigest()
        return ResourceAvailabilityEvidence(
            resource_ref=resource_ref,
            resource_type=binding.resource_type,
            scope_ref=binding.scope_ref,
            state=(
                self._state_reader(record)
                if valid and record is not None
                else ResourceOperationalState.UNKNOWN
            ),
            observed_at=observed_at,
            recorded_at=self._clock(),
            source_revision=revision,
            evidence_ref=f"inventory:{revision}:resource:{identity}" if valid else None,
            unavailable_reason=reason,
            state_metadata=state_metadata if valid else None,
        )
