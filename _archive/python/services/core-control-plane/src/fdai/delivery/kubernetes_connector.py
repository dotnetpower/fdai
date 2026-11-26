"""Atomic no-authority evidence admission for a cluster-initiated transport."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from fdai_service_contracts.cluster_connector import (
    ConnectorEvidence,
    ConnectorRegistration,
    connector_time,
)
from fdai_service_contracts.compatibility import canonical_digest

from fdai.shared.providers.state_store import StateStore

_PREFIX = "kubernetes-connector:evidence:v1:"


class ConnectorAdmissionError(ValueError):
    """Reject an inadmissible or conflicting stream without changing its checkpoint."""


class ConnectorAdmissionStatus(StrEnum):
    """Describe metadata persistence only, never artifact validation or promotion."""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class ConnectorAdmissionReceipt:
    """Return a stable checkpoint identity without claiming observed resource state."""

    status: ConnectorAdmissionStatus
    evidence_digest: str
    sequence: int


class ConnectorEvidenceInbox:
    """Serialize each registered evidence stream with the existing audited CAS store.

    The caller supplies a current server-owned registration and authenticated principal,
    not values copied from the request. Acceptance covers metadata only. A separate
    content validator and inventory writer remain required before resource promotion.
    """

    def __init__(self, store: StateStore, *, max_age_seconds: int = 300) -> None:
        if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 3600:
            raise ValueError("connector freshness limit must be in [1, 3600]")
        self._store = store
        self._max_age_seconds = max_age_seconds

    async def accept(
        self,
        packet: ConnectorEvidence,
        *,
        registration: ConnectorRegistration,
        principal_ref: str,
        now: datetime,
    ) -> ConnectorAdmissionReceipt:
        """Persist one contiguous envelope and audit atomically; reject conflicting replay."""
        packet = ConnectorEvidence.model_validate_json(packet.model_dump_json())
        registration = ConnectorRegistration.model_validate_json(registration.model_dump_json())
        current = connector_time(now)
        packet.admit(
            registration,
            principal_ref=principal_ref,
            now=current,
            max_age_seconds=self._max_age_seconds,
        )
        stream_digest = canonical_digest(
            {
                "scope": packet.scope.model_dump(mode="json"),
                "capability": packet.capability,
                "stream_id": packet.stream_id,
            }
        )
        key = _PREFIX + stream_digest
        previous = await self._store.read_state(key)
        prior_sequence = 0
        if previous is not None:
            if set(previous) != {"revision", "evidence", "evidence_digest", "received_at"}:
                raise ConnectorAdmissionError("connector checkpoint has an invalid shape")
            prior = ConnectorEvidence.model_validate(previous["evidence"])
            prior_sequence = prior.sequence
            if (
                type(previous["revision"]) is not int
                or previous["revision"] != prior_sequence
                or previous["evidence_digest"] != prior.digest
                or prior.scope != packet.scope
                or prior.capability != packet.capability
                or prior.stream_id != packet.stream_id
                or connector_time(previous["received_at"]) < prior.observed_at
                or connector_time(previous["received_at"]) > current
            ):
                raise ConnectorAdmissionError("connector checkpoint failed integrity validation")
            if prior.digest == packet.digest:
                return _receipt(packet, ConnectorAdmissionStatus.DUPLICATE)
            if packet.observed_at < prior.observed_at:
                raise ConnectorAdmissionError("connector observation cutoff moved backwards")
        if packet.sequence != prior_sequence + 1:
            raise ConnectorAdmissionError("connector sequence is not the next checkpoint")
        value = {
            "revision": packet.sequence,
            "evidence": packet.model_dump(mode="json"),
            "evidence_digest": packet.digest,
            "received_at": current.isoformat(),
        }
        audit = {
            "kind": "kubernetes.connector.evidence.accepted",
            "scope_digest": stream_digest,
            "evidence_digest": packet.digest,
            "sequence": packet.sequence,
            "recorded_at": current.isoformat(),
            "execution_authority": False,
            "inventory_promotion": False,
        }
        if previous is None:
            written = await self._store.write_state_with_audit_if_absent(key, value, audit)
        else:
            written = await self._store.compare_and_set_state_with_audit(
                key,
                value,
                expected_revision=prior_sequence,
                audit_entry=audit,
            )
        if written:
            return _receipt(packet, ConnectorAdmissionStatus.ACCEPTED)
        winner = await self._store.read_state(key)
        if winner is not None and (
            set(winner) == {"revision", "evidence", "evidence_digest", "received_at"}
            and winner.get("evidence_digest") == packet.digest
            and ConnectorEvidence.model_validate(winner.get("evidence")).digest == packet.digest
            and winner.get("evidence") == packet.model_dump(mode="json")
            and type(winner.get("revision")) is int
            and winner["revision"] == packet.sequence
            and connector_time(winner.get("received_at")) >= packet.observed_at
        ):
            return _receipt(packet, ConnectorAdmissionStatus.DUPLICATE)
        raise ConnectorAdmissionError(
            "connector checkpoint changed concurrently; reconcile the stream"
        )


def _receipt(
    packet: ConnectorEvidence, status: ConnectorAdmissionStatus
) -> ConnectorAdmissionReceipt:
    return ConnectorAdmissionReceipt(status, packet.digest, packet.sequence)
