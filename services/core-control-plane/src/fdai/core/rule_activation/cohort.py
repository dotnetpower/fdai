"""Dormant durable Rule activation cohort state machine."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fdai_service_contracts.rule_activation_cohort import (
    RuleCohortCandidateActiveV2,
    RuleCohortPrepareV2,
    RuleReplicaAcknowledgementV2,
    RuleReplicaAppliedV2,
    RuleReplicaDepartureKind,
    RuleReplicaDisposition,
    RuleReplicaIdentity,
    rule_acknowledgement_set_digest,
)

from fdai.shared.providers.rule_activation_cohort import RuleActivationCohortCommitStore
from fdai.shared.providers.state_store import StateStore

_PREPARE_PREFIX = "rule-activation-v2:prepare:"
_ACK_PREFIX = "rule-activation-v2:ack:"
_APPLIED_PREFIX = "rule-activation-v2:applied:"
_CANDIDATE_ACTIVE_KEY = "rule-activation-v2:candidate-active"
_LATEST_PREPARE_KEY = "rule-activation-v2:latest-prepare"
_RETENTION_EPOCH_KEY = "rule-activation-v2:retention-epoch"
_RETIRED_PREFIX = "rule-activation-v2:retired:"


class RuleCohortConflictError(RuntimeError):
    """Raised for replay, identity, lease, or compare-and-set conflicts."""


@dataclass(slots=True)
class LocalRuleActivationCohortCommitStore:
    """Process-local linearization used only for local/test StateStore bindings."""

    store: StateStore
    clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC)
    _lock: asyncio.Lock = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._lock = asyncio.Lock()

    async def advance_prepare(
        self,
        *,
        key: str,
        value: Mapping[str, Any],
        expected_revision: int,
        retention_epoch_key: str,
        retention_epoch_value: Mapping[str, Any],
        expected_retention_epoch_revision: int,
        retired_keys: tuple[str, ...],
    ) -> bool:
        async with self._lock:
            return await self.store.advance_state_with_epoch(
                key,
                value,
                expected_revision=expected_revision,
                epoch_key=retention_epoch_key,
                epoch_value=retention_epoch_value,
                expected_epoch_revision=expected_retention_epoch_revision,
                forbidden_keys=retired_keys,
            )

    async def activate_candidate(
        self,
        *,
        key: str,
        value: Mapping[str, Any],
        expected_revision: int,
        latest_prepare_key: str,
        expected_latest_prepare: Mapping[str, Any],
        lease_expires_at: datetime,
    ) -> bool:
        if lease_expires_at.tzinfo is None or lease_expires_at.utcoffset() is None:
            raise ValueError("lease_expires_at MUST be timezone-aware")
        async with self._lock:
            if _aware(self.clock()) >= lease_expires_at:
                return False
            if await self.store.read_state(latest_prepare_key) != expected_latest_prepare:
                return False
            if expected_revision == 0 and await self.store.read_state(key) is None:
                return await self.store.write_state_if_absent(key, value)
            return await self.store.compare_and_set_state(
                key,
                value,
                expected_revision=expected_revision,
            )

    async def insert_applied(
        self,
        *,
        candidate_key: str,
        expected_candidate: Mapping[str, Any],
        replacement_candidate: Mapping[str, Any],
        insert_key: str,
        insert_value: Mapping[str, Any],
        applied_at: datetime,
        lease_expires_at: datetime,
    ) -> bool:
        async with self._lock:
            current_time = _aware(self.clock())
            if applied_at > current_time or current_time >= lease_expires_at:
                return False
            current_state = await self.store.read_state(candidate_key)
            if current_state != expected_candidate:
                return False
            if await self.store.read_state(insert_key) is not None:
                return False
            expected_revision = int(current_state.get("revision", 0))
            return await self.store.compare_and_set_state_with_audit_and_insert(
                candidate_key,
                replacement_candidate,
                expected_revision=expected_revision,
                insert_key=insert_key,
                insert_value=insert_value,
                audit_entry={
                    "actor": "Mimir",
                    "action_kind": "rule-activation-v2.replica-applied",
                    "execution_authority": False,
                },
            )


class StateStoreRuleActivationCohort:
    """Persist a frozen cohort without changing the version 1 active pointer."""

    def __init__(
        self,
        *,
        store: StateStore,
        commit_store: RuleActivationCohortCommitStore,
    ) -> None:
        self._store = store
        self._commit_store = commit_store

    async def prepare(
        self,
        cohort: RuleCohortPrepareV2,
        *,
        now: datetime,
        expected_revision: int,
        authenticated_serving_inventory_digest: str,
        authenticated_replicas: tuple[RuleReplicaIdentity, ...],
        verified_departure_digests: Collection[str] = (),
    ) -> None:
        current = _aware(now)
        if (
            cohort.serving_inventory_digest != authenticated_serving_inventory_digest
            or cohort.replicas != authenticated_replicas
        ):
            raise RuleCohortConflictError("Rule cohort serving inventory identity mismatch")
        latest = await self._store.read_state(_LATEST_PREPARE_KEY)
        if cohort.predecessor_prepare_digest is None:
            if latest is not None or expected_revision != 0:
                raise RuleCohortConflictError("Rule cohort predecessor is required")
        else:
            if (
                latest is None
                or latest.get("prepare_digest") != cohort.predecessor_prepare_digest
                or int(latest.get("revision", -1)) != expected_revision
            ):
                raise RuleCohortConflictError("Rule cohort predecessor identity mismatch")
            predecessor = await self._prepare(cohort.predecessor_prepare_digest)
            self._validate_departures(
                predecessor,
                cohort,
                now=current,
                verified_departure_digests=verified_departure_digests,
            )
        key = _PREPARE_PREFIX + cohort.prepare_digest.removeprefix("sha256:")
        value = cohort.model_dump(mode="json")
        if await self._store.write_state_if_absent(key, value):
            pass
        elif await self._store.read_state(key) != value:
            raise RuleCohortConflictError("Rule cohort preparation identity conflict")
        pointer = {
            "revision": expected_revision + 1,
            "prepare_digest": cohort.prepare_digest,
            "serving_inventory_digest": cohort.serving_inventory_digest,
        }
        retention_epoch = await self._retention_epoch()
        if not await self._commit_store.advance_prepare(
            key=_LATEST_PREPARE_KEY,
            value=pointer,
            expected_revision=expected_revision,
            retention_epoch_key=_RETENTION_EPOCH_KEY,
            retention_epoch_value={
                "revision": retention_epoch + 1,
                "last_prepare_digest": cohort.prepare_digest,
            },
            expected_retention_epoch_revision=retention_epoch,
            retired_keys=tuple(
                _RETIRED_PREFIX + member.revision_digest.removeprefix("sha256:")
                for member in cohort.generation.members
            ),
        ):
            raise RuleCohortConflictError("Rule cohort latest-prepare CAS conflict")

    async def _retention_epoch(self) -> int:
        raw = await self._store.read_state(_RETENTION_EPOCH_KEY)
        if raw is None:
            await self._store.write_state_if_absent(
                _RETENTION_EPOCH_KEY,
                {"revision": 1, "last_prepare_digest": None},
            )
            raw = await self._store.read_state(_RETENTION_EPOCH_KEY)
        revision = raw.get("revision") if raw is not None else None
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise RuleCohortConflictError("Rule revision retention epoch is invalid")
        return revision

    async def acknowledge(
        self,
        acknowledgement: RuleReplicaAcknowledgementV2,
        *,
        authenticated_identity: RuleReplicaIdentity,
        authentication_receipt_digest: str,
        now: datetime,
    ) -> None:
        cohort = await self._prepare(acknowledgement.prepare_digest)
        current = _aware(now)
        replica = next(
            (item for item in cohort.replicas if item.replica_id == acknowledgement.replica_id),
            None,
        )
        if (
            replica is None
            or authenticated_identity != replica
            or authentication_receipt_digest != acknowledgement.authentication_receipt_digest
            or (
                replica.principal_id,
                replica.release_id,
                replica.startup_epoch,
                replica.serving_lease_id,
            )
            != (
                acknowledgement.principal_id,
                acknowledgement.release_id,
                acknowledgement.startup_epoch,
                acknowledgement.serving_lease_id,
            )
            or acknowledgement.revision_registry_root != cohort.revision_registry_root
            or acknowledgement.catalog_manifest_digest != cohort.catalog_manifest_digest
            or acknowledgement.profile_snapshot_digest != cohort.generation.profile_snapshot_digest
            or acknowledgement.generation_digest != cohort.generation.generation_digest
            or not cohort.prepared_at <= acknowledgement.observed_at <= current
            or current >= replica.serving_lease_expires_at
            or acknowledgement.observed_at >= replica.serving_lease_expires_at
        ):
            raise RuleCohortConflictError("Rule replica acknowledgement identity mismatch")
        key = self._ack_key(acknowledgement.prepare_digest, acknowledgement.replica_id)
        value = acknowledgement.model_dump(mode="json")
        if await self._store.write_state_if_absent(key, value):
            return
        if await self._store.read_state(key) != value:
            raise RuleCohortConflictError("Rule replica acknowledgement conflict")

    async def activate_candidate(
        self,
        prepare_digest: str,
        *,
        now: datetime,
        expected_revision: int,
    ) -> RuleCohortCandidateActiveV2:
        cohort = await self._prepare(prepare_digest)
        current = _aware(now)
        acknowledgements = await self._acknowledgements(cohort)
        if any(
            acknowledgement.disposition is RuleReplicaDisposition.REFUSED
            for acknowledgement in acknowledgements
        ):
            raise RuleCohortConflictError("Rule cohort refusal blocks candidate activation")
        if len(acknowledgements) != len(cohort.replicas):
            raise RuleCohortConflictError("Rule cohort acknowledgement set is incomplete")
        if any(replica.serving_lease_expires_at <= current for replica in cohort.replicas):
            raise RuleCohortConflictError("Rule cohort serving lease expired before activation")
        ack_set_digest = rule_acknowledgement_set_digest(acknowledgements)
        candidate = RuleCohortCandidateActiveV2(
            prepare_digest=prepare_digest,
            generation_digest=cohort.generation.generation_digest,
            acknowledgement_set_digest=ack_set_digest,
            activated_at=current,
        )
        value = {
            "revision": expected_revision + 1,
            "candidate": candidate.model_dump(mode="json"),
        }
        earliest_expiry = min(replica.serving_lease_expires_at for replica in cohort.replicas)
        latest_prepare = await self._store.read_state(_LATEST_PREPARE_KEY)
        if (
            latest_prepare is None
            or latest_prepare.get("prepare_digest") != cohort.prepare_digest
            or latest_prepare.get("serving_inventory_digest") != cohort.serving_inventory_digest
        ):
            raise RuleCohortConflictError("Rule cohort is not the latest frozen preparation")
        if not await self._commit_store.activate_candidate(
            key=_CANDIDATE_ACTIVE_KEY,
            value=value,
            expected_revision=expected_revision,
            latest_prepare_key=_LATEST_PREPARE_KEY,
            expected_latest_prepare=latest_prepare,
            lease_expires_at=earliest_expiry,
        ):
            raise RuleCohortConflictError("Rule cohort candidate-active CAS conflict")
        return candidate

    async def admit_replica(
        self,
        *,
        prepare_digest: str,
        replica_id: str,
        serving_lease_id: str,
        now: datetime,
    ) -> bool:
        cohort = await self._prepare(prepare_digest)
        current = _aware(now)
        replica = next((item for item in cohort.replicas if item.replica_id == replica_id), None)
        if (
            replica is None
            or replica.serving_lease_id != serving_lease_id
            or replica.serving_lease_expires_at <= current
        ):
            return False
        acknowledgement = await self._acknowledgement(prepare_digest, replica_id)
        return (
            acknowledgement is not None
            and acknowledgement.disposition is RuleReplicaDisposition.ACKNOWLEDGED
        )

    async def record_applied(
        self,
        record: RuleReplicaAppliedV2,
        *,
        authenticated_identity: RuleReplicaIdentity,
    ) -> None:
        candidate_raw = await self._store.read_state(_CANDIDATE_ACTIVE_KEY)
        if not isinstance(candidate_raw, dict):
            raise RuleCohortConflictError("Rule cohort candidate-active state is unavailable")
        candidate = RuleCohortCandidateActiveV2.model_validate(candidate_raw.get("candidate"))
        cohort = await self._prepare(record.prepare_digest)
        replica = next(
            (item for item in cohort.replicas if item.replica_id == record.replica_id),
            None,
        )
        if replica is None:
            raise RuleCohortConflictError("Rule replica applied readback is outside the cohort")
        if (
            authenticated_identity != replica
            or (
                record.principal_id,
                record.release_id,
                record.startup_epoch,
                record.serving_lease_id,
            )
            != (
                replica.principal_id,
                replica.release_id,
                replica.startup_epoch,
                replica.serving_lease_id,
            )
            or record.prepare_digest != candidate.prepare_digest
            or record.generation_digest != candidate.generation_digest
            or record.acknowledgement_set_digest != candidate.acknowledgement_set_digest
            or not candidate.activated_at <= record.applied_at < replica.serving_lease_expires_at
        ):
            raise RuleCohortConflictError("Rule replica applied readback identity mismatch")
        key = self._applied_key(record.prepare_digest, record.replica_id)
        value = record.model_dump(mode="json")
        candidate_revision = int(candidate_raw.get("revision", 0))
        replacement_candidate = {
            **candidate_raw,
            "revision": candidate_revision + 1,
        }
        if not await self._commit_store.insert_applied(
            candidate_key=_CANDIDATE_ACTIVE_KEY,
            expected_candidate=candidate_raw,
            replacement_candidate=replacement_candidate,
            insert_key=key,
            insert_value=value,
            applied_at=record.applied_at,
            lease_expires_at=replica.serving_lease_expires_at,
        ):
            raise RuleCohortConflictError("Rule replica applied readback conflict")

    @staticmethod
    def _validate_departures(
        predecessor: RuleCohortPrepareV2,
        cohort: RuleCohortPrepareV2,
        *,
        now: datetime,
        verified_departure_digests: Collection[str],
    ) -> None:
        current_by_id = {replica.replica_id: replica for replica in cohort.replicas}
        evidence_by_id = {item.replica_id: item for item in cohort.departures}
        for previous in predecessor.replicas:
            current = current_by_id.get(previous.replica_id)
            if current == previous:
                continue
            evidence = evidence_by_id.get(previous.replica_id)
            if (
                evidence is None
                or evidence.replica != previous
                or evidence.serving_inventory_digest != predecessor.serving_inventory_digest
                or evidence.evidence_digest not in verified_departure_digests
                or not predecessor.prepared_at <= evidence.observed_at <= now
            ):
                raise RuleCohortConflictError(
                    "Rule cohort membership removal lacks current departure evidence"
                )
            if evidence.kind is RuleReplicaDepartureKind.LEASE_EXPIRED and (
                previous.serving_lease_expires_at > evidence.observed_at
                or previous.serving_lease_expires_at > now
            ):
                raise RuleCohortConflictError(
                    "Rule cohort lease-expiry evidence precedes the frozen lease expiry"
                )

    async def _prepare(self, prepare_digest: str) -> RuleCohortPrepareV2:
        raw = await self._store.read_state(_PREPARE_PREFIX + prepare_digest.removeprefix("sha256:"))
        if raw is None:
            raise RuleCohortConflictError("Rule cohort preparation is unavailable")
        return RuleCohortPrepareV2.model_validate(raw)

    async def cohort(self, prepare_digest: str) -> RuleCohortPrepareV2:
        """Return one retained frozen cohort for downstream dormant verification."""

        return await self._prepare(prepare_digest)

    async def candidate_active(self) -> RuleCohortCandidateActiveV2:
        """Return the authority-neutral candidate-active record."""

        raw = await self._store.read_state(_CANDIDATE_ACTIVE_KEY)
        if raw is None:
            raise RuleCohortConflictError("Rule cohort candidate-active state is unavailable")
        return RuleCohortCandidateActiveV2.model_validate(raw.get("candidate"))

    async def applied(
        self,
        prepare_digest: str,
        replica_id: str,
    ) -> RuleReplicaAppliedV2 | None:
        """Return one exact replica applied readback."""

        raw = await self._store.read_state(self._applied_key(prepare_digest, replica_id))
        return RuleReplicaAppliedV2.model_validate(raw) if raw is not None else None

    async def acknowledgement(
        self,
        prepare_digest: str,
        replica_id: str,
    ) -> RuleReplicaAcknowledgementV2 | None:
        """Return one authenticated replica acknowledgement."""

        return await self._acknowledgement(prepare_digest, replica_id)

    async def _acknowledgements(
        self,
        cohort: RuleCohortPrepareV2,
    ) -> tuple[RuleReplicaAcknowledgementV2, ...]:
        records: list[RuleReplicaAcknowledgementV2] = []
        for replica in cohort.replicas:
            acknowledgement = await self._acknowledgement(cohort.prepare_digest, replica.replica_id)
            if acknowledgement is not None:
                records.append(acknowledgement)
        return tuple(records)

    async def _acknowledgement(
        self,
        prepare_digest: str,
        replica_id: str,
    ) -> RuleReplicaAcknowledgementV2 | None:
        raw = await self._store.read_state(self._ack_key(prepare_digest, replica_id))
        return RuleReplicaAcknowledgementV2.model_validate(raw) if raw is not None else None

    @staticmethod
    def _ack_key(prepare_digest: str, replica_id: str) -> str:
        return f"{_ACK_PREFIX}{prepare_digest.removeprefix('sha256:')}:{replica_id}"

    @staticmethod
    def _applied_key(prepare_digest: str, replica_id: str) -> str:
        return f"{_APPLIED_PREFIX}{prepare_digest.removeprefix('sha256:')}:{replica_id}"


__all__ = [
    "LocalRuleActivationCohortCommitStore",
    "RuleCohortConflictError",
    "StateStoreRuleActivationCohort",
]


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Rule cohort evaluation time MUST include a timezone")
    return value
