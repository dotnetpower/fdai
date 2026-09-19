"""Atomic complete-snapshot inbox and existing inventory-source adapter."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol

from fdai_service_contracts.cluster_connector import (
    ConnectorEvidence,
    ConnectorRegistration,
    connector_time,
)
from fdai_service_contracts.compatibility import canonical_digest

from fdai.delivery.kubernetes_api_inventory import KubernetesApiInventorySnapshot
from fdai.delivery.kubernetes_api_status import KubernetesApiInventoryError
from fdai.delivery.kubernetes_connector import (
    ConnectorAdmissionError,
    ConnectorAdmissionReceipt,
    ConnectorAdmissionStatus,
)
from fdai.delivery.kubernetes_connector_artifact import decode_snapshot
from fdai.shared.providers.state_store import StateStore


class ConnectorRegistrationReader(Protocol):
    """Resolve current server-owned enrollment from an independently authenticated principal."""

    async def read(self, principal_ref: str) -> ConnectorRegistration | None: ...


def snapshot_key(registration: ConnectorRegistration) -> str:
    return "kubernetes-connector:snapshot:v1:" + canonical_digest(
        registration.scope.model_dump(mode="json")
    )


class ConnectorSnapshotInbox:
    """Commit complete artifact, sequence and audit together using the existing Core store."""

    def __init__(
        self,
        store: StateStore,
        *,
        registrations: ConnectorRegistrationReader,
        allow_cluster_resources: bool,
        now: Callable[[], datetime],
        max_age_seconds: int = 300,
    ) -> None:
        if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 3600:
            raise ValueError("connector freshness limit must be in [1, 3600]")
        self._store = store
        self._registrations = registrations
        self._cluster_resources = allow_cluster_resources
        self._now = now
        self._max_age = max_age_seconds

    async def accept(
        self, packet: ConnectorEvidence, content: bytes, *, principal_ref: str
    ) -> ConnectorAdmissionReceipt:
        """Authenticate scope before content parsing, then commit all accepted bytes atomically."""
        registration = await self._registration(principal_ref)
        current = connector_time(self._now())
        packet = ConnectorEvidence.model_validate_json(packet.model_dump_json())
        packet.admit(
            registration, principal_ref=principal_ref, now=current, max_age_seconds=self._max_age
        )
        if packet.namespaces != registration.namespaces:
            raise ConnectorAdmissionError(
                "connector complete snapshot must cover the registered namespace set"
            )
        decode_snapshot(content, packet, allow_cluster_resources=self._cluster_resources)
        key = snapshot_key(registration)
        previous = await self._store.read_state(key)
        sequence = 0
        if previous is not None:
            prior, prior_content = self._validate(previous, registration)
            sequence = prior.sequence
            if prior.digest == packet.digest and prior_content == content:
                return ConnectorAdmissionReceipt(
                    ConnectorAdmissionStatus.DUPLICATE, packet.digest, packet.sequence
                )
            if prior.stream_id != packet.stream_id or packet.observed_at < prior.observed_at:
                raise ConnectorAdmissionError("connector stream changed or observation regressed")
        if packet.sequence != sequence + 1:
            raise ConnectorAdmissionError("connector snapshot sequence is not contiguous")
        refreshed = await self._registration(principal_ref)
        if refreshed != registration:
            raise ConnectorAdmissionError("connector registration changed during admission")
        current = connector_time(self._now())
        packet.admit(
            refreshed, principal_ref=principal_ref, now=current, max_age_seconds=self._max_age
        )
        value = {
            "revision": packet.sequence,
            "evidence": packet.model_dump(mode="json"),
            "content": content.decode("utf-8"),
            "received_at": current.isoformat(),
        }
        audit = {
            "kind": "kubernetes.connector.snapshot.accepted",
            "correlation_id": packet.digest,
            "scope_digest": canonical_digest(packet.scope.model_dump(mode="json")),
            "artifact_digest": packet.artifact_digest,
            "sequence": packet.sequence,
            "recorded_at": current.isoformat(),
            "execution_authority": False,
            "inventory_promotion": False,
        }
        if previous is None:
            created = await self._store.write_state_with_audit_if_absent(key, value, audit)
        else:
            created = await self._store.compare_and_set_state_with_audit(
                key, value, expected_revision=sequence, audit_entry=audit
            )
        if created:
            return ConnectorAdmissionReceipt(
                ConnectorAdmissionStatus.ACCEPTED, packet.digest, packet.sequence
            )
        winner = await self._store.read_state(key)
        if winner is not None:
            winning_packet, winning_content = self._validate(winner, registration)
            if winning_packet.digest == packet.digest and winning_content == content:
                return ConnectorAdmissionReceipt(
                    ConnectorAdmissionStatus.DUPLICATE, packet.digest, packet.sequence
                )
        raise ConnectorAdmissionError(
            "connector snapshot changed concurrently; reconcile before retry"
        )

    async def current(self, *, principal_ref: str) -> KubernetesApiInventorySnapshot:
        """Recheck current enrollment and original freshness before exposing inventory input."""
        registration = await self._registration(principal_ref)
        value = await self._store.read_state(snapshot_key(registration))
        if value is None:
            raise ConnectorAdmissionError("connector has no accepted snapshot")
        packet, content = self._validate(value, registration)
        packet.admit(
            registration,
            principal_ref=principal_ref,
            now=self._now(),
            max_age_seconds=self._max_age,
        )
        return decode_snapshot(content, packet, allow_cluster_resources=self._cluster_resources)

    async def _registration(self, principal_ref: str) -> ConnectorRegistration:
        registration = await self._registrations.read(principal_ref)
        if registration is None:
            raise ConnectorAdmissionError("connector principal has no current registration")
        return ConnectorRegistration.model_validate_json(registration.model_dump_json())

    def _validate(
        self, value: Mapping[str, object], registration: ConnectorRegistration
    ) -> tuple[ConnectorEvidence, bytes]:
        if set(value) != {"revision", "evidence", "content", "received_at"} or not isinstance(
            value["content"], str
        ):
            raise ConnectorAdmissionError("connector snapshot checkpoint has an invalid shape")
        packet = ConnectorEvidence.model_validate(value["evidence"])
        content = value["content"].encode("utf-8")
        if (
            type(value["revision"]) is not int
            or value["revision"] != packet.sequence
            or packet.scope != registration.scope
            or packet.namespaces != registration.namespaces
            or not packet.observed_at
            <= connector_time(value["received_at"])
            <= connector_time(self._now())
        ):
            raise ConnectorAdmissionError("connector snapshot checkpoint failed integrity checks")
        decode_snapshot(content, packet, allow_cluster_resources=self._cluster_resources)
        return packet, content


class ConnectorInventorySource:
    """Implement the existing Kubernetes source interface without another graph writer."""

    def __init__(self, inbox: ConnectorSnapshotInbox, *, principal_ref: str) -> None:
        self._inbox = inbox
        self._principal = principal_ref

    async def collect(self) -> KubernetesApiInventorySnapshot:
        try:
            return await self._inbox.current(principal_ref=self._principal)
        except (ValueError, TypeError, KeyError):
            raise KubernetesApiInventoryError(
                "Kubernetes connector snapshot is unavailable"
            ) from None
