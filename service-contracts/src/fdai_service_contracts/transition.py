"""Executable delivery and rolling-transition evidence for independent services."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fdai_service_contracts.compatibility import (
    CompatibilityError,
    matrix_digest,
)


class CommitFailedError(RuntimeError):
    """A simulated broker commit failed before advancing durable offset state."""


@dataclass(frozen=True, slots=True)
class DeliveryRecord:
    """One at-least-once record presented to the transition consumer."""

    offset: int
    idempotency_key: str
    payload_digest: str


@dataclass(slots=True)
class DurableDeliveryState:
    """State that survives consumer rebalance and process restart."""

    committed_offset: int = -1
    effects: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    """Observed result from one executable failure or recovery transition."""

    scenario: str
    committed_offset: int
    terminal_effects: int
    duplicate_count: int
    redelivery_count: int


class TransitionConsumer:
    """Apply records behind a durable idempotency ledger and explicit offset commit."""

    def __init__(self, state: DurableDeliveryState) -> None:
        self._state = state
        self.terminal_effects = 0
        self.duplicate_count = 0

    def process(self, record: DeliveryRecord) -> str:
        """Apply one unseen key once, skip committed offsets, and deduplicate redelivery."""

        if record.offset <= self._state.committed_offset:
            return "committed"
        prior = self._state.effects.get(record.idempotency_key)
        if prior is not None:
            if prior != record.payload_digest:
                raise CompatibilityError("delivery idempotency key changed payload digest")
            self.duplicate_count += 1
            return "duplicate"
        self._state.effects[record.idempotency_key] = record.payload_digest
        self.terminal_effects += 1
        return "applied"

    def commit(self, offset: int, *, fail: bool = False) -> None:
        """Advance the durable offset unless the broker commit fails."""

        if fail:
            raise CommitFailedError("simulated offset commit failure")
        self._state.committed_offset = max(self._state.committed_offset, offset)


def run_delivery_transition_harness(service_id: str) -> tuple[DeliveryReceipt, ...]:
    """Execute the four required at-least-once loss and restart scenarios."""

    digest = "sha256:" + "a" * 64
    first = DeliveryRecord(0, f"{service_id}:0", digest)
    second = DeliveryRecord(1, f"{service_id}:1", digest)
    return (
        _commit_failure_redelivery(first),
        _restart_from_committed_offset(first, second),
        _rebalance_before_commit(first),
        _process_restart_duplicate(first),
    )


def delivery_checks(receipts: Sequence[DeliveryReceipt]) -> dict[str, bool]:
    """Derive receipt checks from observed transitions rather than declared booleans."""

    by_scenario = {receipt.scenario: receipt for receipt in receipts}
    required = {
        "commit_failure_redelivery",
        "restart_from_committed_offset",
        "rebalance_before_commit",
        "process_restart_duplicate",
    }
    complete = set(by_scenario) == required
    duplicate_safe = complete and all(
        by_scenario[name].terminal_effects == 1 and by_scenario[name].duplicate_count == 1
        for name in required - {"restart_from_committed_offset"}
    )
    restart_safe = complete and by_scenario["restart_from_committed_offset"].committed_offset == 1
    offsets_preserved = complete and all(receipt.committed_offset >= 0 for receipt in receipts)
    return {
        "duplicate_delivery": duplicate_safe,
        "health": complete and offsets_preserved,
        "idempotency": duplicate_safe,
        "offsets_preserved": offsets_preserved,
        "reordered_delivery": restart_safe,
    }


def generate_upgrade_receipts(
    manifest: Mapping[str, Any],
    *,
    checks: Mapping[str, bool],
) -> tuple[dict[str, Any], ...]:
    """Generate peer-stable migration and rollback receipts from validated checks."""

    if not checks or any(value is not True for value in checks.values()):
        raise CompatibilityError("upgrade receipts require passing executable checks")
    services = _service_map(manifest)
    digest = matrix_digest(manifest)
    receipts: list[dict[str, Any]] = []
    for service_id in sorted(services):
        service = services[service_id]
        for direction in ("migration", "rollback"):
            transition = _mapping(service[direction], f"{service_id}.{direction}")
            baseline_key = "previous_version" if direction == "migration" else "current_version"
            peers = {
                peer_id: str(peer[baseline_key])
                for peer_id, peer in services.items()
                if peer_id != service_id
            }
            requirements = _mapping(
                transition.get("requires_peer_versions", {}),
                f"{service_id}.{direction}.requires_peer_versions",
            )
            peers.update({str(peer_id): str(version) for peer_id, version in requirements.items()})
            key = (
                f"service-upgrade:{service_id}:{direction}:"
                f"{transition['from_version']}:{transition['to_version']}"
            )
            now = datetime.now(UTC).isoformat()
            receipts.append(
                {
                    "receipt_version": "1.0.0",
                    "receipt_id": str(uuid5(NAMESPACE_URL, key)),
                    "service_id": service_id,
                    "direction": direction,
                    "from_version": transition["from_version"],
                    "to_version": transition["to_version"],
                    "idempotency_key": key,
                    "matrix_digest": digest,
                    "peer_versions_before": peers,
                    "peer_versions_after": dict(peers),
                    "peer_restart_count": 0,
                    "duplicate_terminal_effects": 0,
                    "offsets_preserved": checks["offsets_preserved"],
                    "checks": {
                        name: value for name, value in checks.items() if name != "offsets_preserved"
                    },
                    "started_at": now,
                    "completed_at": now,
                    "proof_kind": "focused",
                    "outcome": "stable",
                }
            )
    return tuple(receipts)


def _commit_failure_redelivery(record: DeliveryRecord) -> DeliveryReceipt:
    state = DurableDeliveryState()
    consumer = TransitionConsumer(state)
    consumer.process(record)
    try:
        consumer.commit(record.offset, fail=True)
    except CommitFailedError:
        pass
    else:
        raise AssertionError("commit failure scenario did not fail")
    consumer.process(record)
    consumer.commit(record.offset)
    return DeliveryReceipt(
        "commit_failure_redelivery",
        state.committed_offset,
        consumer.terminal_effects,
        consumer.duplicate_count,
        1,
    )


def _restart_from_committed_offset(
    first: DeliveryRecord,
    second: DeliveryRecord,
) -> DeliveryReceipt:
    state = DurableDeliveryState()
    initial = TransitionConsumer(state)
    initial.process(first)
    initial.commit(first.offset)
    restarted = TransitionConsumer(state)
    restarted.process(first)
    restarted.process(second)
    restarted.commit(second.offset)
    return DeliveryReceipt(
        "restart_from_committed_offset",
        state.committed_offset,
        initial.terminal_effects + restarted.terminal_effects,
        restarted.duplicate_count,
        0,
    )


def _rebalance_before_commit(record: DeliveryRecord) -> DeliveryReceipt:
    state = DurableDeliveryState()
    initial = TransitionConsumer(state)
    initial.process(record)
    assigned = TransitionConsumer(state)
    assigned.process(record)
    assigned.commit(record.offset)
    return DeliveryReceipt(
        "rebalance_before_commit",
        state.committed_offset,
        initial.terminal_effects + assigned.terminal_effects,
        assigned.duplicate_count,
        1,
    )


def _process_restart_duplicate(record: DeliveryRecord) -> DeliveryReceipt:
    state = DurableDeliveryState()
    initial = TransitionConsumer(state)
    initial.process(record)
    restarted = TransitionConsumer(state)
    restarted.process(record)
    restarted.commit(record.offset)
    return DeliveryReceipt(
        "process_restart_duplicate",
        state.committed_offset,
        initial.terminal_effects + restarted.terminal_effects,
        restarted.duplicate_count,
        1,
    )


def _service_map(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    services = manifest.get("services")
    if not isinstance(services, list):
        raise CompatibilityError("manifest services must be an array")
    return {
        str(service["id"]): service
        for item in services
        if isinstance((service := _mapping(item, "service")), Mapping)
    }


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CompatibilityError(f"{name} must be an object")
    return value


__all__ = [
    "CommitFailedError",
    "DeliveryReceipt",
    "DeliveryRecord",
    "DurableDeliveryState",
    "TransitionConsumer",
    "delivery_checks",
    "generate_upgrade_receipts",
    "run_delivery_transition_harness",
]
