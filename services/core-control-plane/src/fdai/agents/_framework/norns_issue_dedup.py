"""Restart-safe issue-learning application journal for Norns."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.agents._framework.bounded import BoundedLruDict
from fdai.agents._framework.norns_learning import (
    NornsLearningState,
    apply_fingerprint_count,
    observe_fingerprint,
)
from fdai.shared.providers.state_store import StateStore

_OPERATION_PREFIX = "pantheon/norns/issue-learning/operations"
_FINGERPRINT_PREFIX = "pantheon/norns/issue-learning/fingerprints"
_MAX_CAS_ATTEMPTS = 16
_CANDIDATE_STATES = frozenset({"collecting", "pending", "delivered"})


@dataclass(frozen=True, slots=True)
class _FingerprintApplication:
    state_key: str
    fingerprint: str
    promotion_threshold: int
    occurrence_count: int
    candidate_state: str
    operation_counted: bool


class NornsIssueDeduplicator:
    """Apply each Saga issue operation to durable learning state exactly once."""

    def __init__(self, state_store: StateStore | None, local_capacity: int) -> None:
        self._state_store = state_store
        self._recovery_limit = local_capacity
        self._local_claims: BoundedLruDict[str, str] = BoundedLruDict(local_capacity)
        self._pending_completions: BoundedLruDict[str, str] = BoundedLruDict(local_capacity)

    async def observe(
        self,
        state: NornsLearningState,
        payload: Mapping[str, Any],
    ) -> None:
        """Apply or resume one fingerprint operation without losing its count."""
        if self._state_store is None:
            if self._claim_local(payload):
                observe_fingerprint(state, payload)
            else:
                state.record_behavior("issue_learning_duplicate")
            return

        operation_id, fingerprint = _issue_identity(payload)
        application, replayed = await self._apply_durable(
            operation_id=operation_id,
            fingerprint=fingerprint,
            promotion_threshold=state._promotion_threshold,
        )
        apply_fingerprint_count(
            state,
            fingerprint,
            application.occurrence_count,
            propose=application.candidate_state == "pending",
        )
        if replayed or not application.operation_counted:
            state.record_behavior("issue_learning_duplicate")
        if application.candidate_state == "pending":
            self._pending_completions.set(fingerprint, application.state_key)

    async def after_flush(self, state: NornsLearningState) -> None:
        """Mark candidates delivered only after publish or deterministic hold."""
        if self._state_store is None:
            return
        for fingerprint, state_key in tuple(self._pending_completions.items()):
            if _has_pending_candidate(state.pending_candidates, fingerprint):
                continue
            await self._mark_candidate_delivered(
                state_key=state_key,
                fingerprint=fingerprint,
            )
            self._pending_completions.pop(fingerprint)

    async def recover(self, state: NornsLearningState) -> int:
        """Restore pending operations, counts, and candidate delivery state."""
        store = self._state_store
        if store is None:
            return 0
        pending_from_operations = 0
        for index in range(self._recovery_limit + 1):
            row = await store.find_state(
                f"{_OPERATION_PREFIX}/",
                field="status",
                value="pending",
            )
            if row is None:
                break
            if index == self._recovery_limit:
                raise RuntimeError("pending issue learning operation recovery capacity exceeded")
            operation_digest, fingerprint, _status = _operation_identity_from_state(row)
            application = await self._apply_fingerprint_operation(
                operation_digest=operation_digest,
                fingerprint=fingerprint,
                promotion_threshold=state._promotion_threshold,
            )
            apply_fingerprint_count(
                state,
                fingerprint,
                application.occurrence_count,
                propose=application.candidate_state == "pending",
            )
            if (
                application.candidate_state == "pending"
                and self._pending_completions.get(fingerprint) is None
            ):
                self._pending_completions.set(fingerprint, application.state_key)
                pending_from_operations += 1
            await store.write_state(
                f"{_OPERATION_PREFIX}/{operation_digest}",
                _operation_state(
                    operation_digest=operation_digest,
                    fingerprint=fingerprint,
                    status="applied",
                    revision=2,
                ),
            )

        row = await store.find_state(
            f"{_FINGERPRINT_PREFIX}/",
            field="candidate_state",
            value="pending",
        )
        if row is None:
            return pending_from_operations
        recovered_fingerprint = row.get("fingerprint")
        threshold = row.get("promotion_threshold")
        if (
            not isinstance(recovered_fingerprint, str)
            or not isinstance(threshold, int)
            or isinstance(threshold, bool)
        ):
            raise RuntimeError("stored issue learning fingerprint state is malformed")
        if self._pending_completions.get(recovered_fingerprint) is not None:
            return pending_from_operations
        state_key = (
            f"{_FINGERPRINT_PREFIX}/"
            f"{hashlib.sha256(recovered_fingerprint.encode('utf-8')).hexdigest()}"
        )
        application = _application_from_state(
            row,
            state_key=state_key,
            fingerprint=recovered_fingerprint,
            promotion_threshold=state._promotion_threshold,
            operation_counted=False,
        )
        apply_fingerprint_count(
            state,
            recovered_fingerprint,
            application.occurrence_count,
            propose=True,
        )
        self._pending_completions.set(recovered_fingerprint, state_key)
        return pending_from_operations + 1

    def _claim_local(self, payload: Mapping[str, Any]) -> bool:
        operation_id = payload.get("idempotency_key")
        fingerprint = payload.get("fingerprint")
        if not isinstance(fingerprint, str) or not fingerprint:
            return False
        if (
            not isinstance(operation_id, str)
            or not operation_id
            or operation_id != operation_id.strip()
        ):
            return True

        prior_fingerprint = self._local_claims.get(operation_id)
        if prior_fingerprint is not None:
            if prior_fingerprint != fingerprint:
                raise ValueError("issue learning operation collides with a fingerprint")
            return False
        self._local_claims.set(operation_id, fingerprint)
        return True

    async def _apply_durable(
        self,
        *,
        operation_id: str,
        fingerprint: str,
        promotion_threshold: int,
    ) -> tuple[_FingerprintApplication, bool]:
        store = self._state_store
        if store is None:
            raise RuntimeError("durable issue learning requires a StateStore")
        operation_digest = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
        operation_key = f"{_OPERATION_PREFIX}/{operation_digest}"
        pending_claim = _operation_state(
            operation_digest=operation_digest,
            fingerprint=fingerprint,
            status="pending",
            revision=1,
        )
        created = await store.write_state_with_audit_if_absent(
            operation_key,
            pending_claim,
            _audit_entry(
                action_kind="issue_learning.claimed",
                fingerprint=fingerprint,
                operation_digest=operation_digest,
                revision=1,
            ),
        )
        if not created:
            stored_claim = await store.read_state(operation_key)
            if stored_claim is None:
                raise RuntimeError("issue learning claim disappeared after collision")
            _validate_operation_state(
                stored_claim,
                operation_digest=operation_digest,
                fingerprint=fingerprint,
            )

        application = await self._apply_fingerprint_operation(
            operation_digest=operation_digest,
            fingerprint=fingerprint,
            promotion_threshold=promotion_threshold,
        )
        await store.write_state(
            operation_key,
            _operation_state(
                operation_digest=operation_digest,
                fingerprint=fingerprint,
                status="applied",
                revision=2,
            ),
        )
        self._local_claims.set(operation_id, fingerprint)
        return application, not created

    async def _apply_fingerprint_operation(
        self,
        *,
        operation_digest: str,
        fingerprint: str,
        promotion_threshold: int,
    ) -> _FingerprintApplication:
        store = self._state_store
        if store is None:
            raise RuntimeError("durable issue learning requires a StateStore")
        fingerprint_digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
        state_key = f"{_FINGERPRINT_PREFIX}/{fingerprint_digest}"
        for _attempt in range(_MAX_CAS_ATTEMPTS):
            stored = await store.read_state(state_key)
            if stored is None:
                operations = (operation_digest,)
                value = _fingerprint_state(
                    revision=1,
                    fingerprint=fingerprint,
                    promotion_threshold=promotion_threshold,
                    operation_digests=operations,
                    candidate_state=("pending" if promotion_threshold == 1 else "collecting"),
                )
                created = await store.write_state_with_audit_if_absent(
                    state_key,
                    value,
                    _audit_entry(
                        action_kind="issue_learning.applied",
                        fingerprint=fingerprint,
                        operation_digest=operation_digest,
                        revision=1,
                    ),
                )
                if created:
                    return _application_from_state(
                        value,
                        state_key=state_key,
                        fingerprint=fingerprint,
                        promotion_threshold=promotion_threshold,
                        operation_counted=True,
                    )
                continue

            current = _application_from_state(
                stored,
                state_key=state_key,
                fingerprint=fingerprint,
                promotion_threshold=promotion_threshold,
                operation_counted=False,
            )
            operation_digests = tuple(str(item) for item in stored["operation_digests"])
            if operation_digest in operation_digests:
                return current
            if current.candidate_state != "collecting":
                return current

            next_operations = tuple(sorted((*operation_digests, operation_digest)))
            next_revision = int(stored["revision"]) + 1
            value = _fingerprint_state(
                revision=next_revision,
                fingerprint=fingerprint,
                promotion_threshold=promotion_threshold,
                operation_digests=next_operations,
                candidate_state=(
                    "pending" if len(next_operations) >= promotion_threshold else "collecting"
                ),
            )
            advanced = await store.compare_and_set_state_with_audit(
                state_key,
                value,
                expected_revision=int(stored["revision"]),
                audit_entry=_audit_entry(
                    action_kind="issue_learning.applied",
                    fingerprint=fingerprint,
                    operation_digest=operation_digest,
                    revision=next_revision,
                ),
            )
            if advanced:
                return _application_from_state(
                    value,
                    state_key=state_key,
                    fingerprint=fingerprint,
                    promotion_threshold=promotion_threshold,
                    operation_counted=True,
                )
        raise RuntimeError("issue learning fingerprint CAS retry limit exceeded")

    async def _mark_candidate_delivered(
        self,
        *,
        state_key: str,
        fingerprint: str,
    ) -> None:
        store = self._state_store
        if store is None:
            raise RuntimeError("durable issue learning requires a StateStore")
        for _attempt in range(_MAX_CAS_ATTEMPTS):
            stored = await store.read_state(state_key)
            if stored is None:
                raise RuntimeError("issue learning fingerprint state disappeared")
            threshold = stored.get("promotion_threshold")
            if not isinstance(threshold, int) or isinstance(threshold, bool):
                raise RuntimeError("stored issue learning threshold is malformed")
            current = _application_from_state(
                stored,
                state_key=state_key,
                fingerprint=fingerprint,
                promotion_threshold=threshold,
                operation_counted=False,
            )
            if current.candidate_state == "delivered":
                return
            if current.candidate_state != "pending":
                raise RuntimeError("issue learning candidate is not pending delivery")
            operation_digests = tuple(str(item) for item in stored["operation_digests"])
            next_revision = int(stored["revision"]) + 1
            value = _fingerprint_state(
                revision=next_revision,
                fingerprint=fingerprint,
                promotion_threshold=threshold,
                operation_digests=operation_digests,
                candidate_state="delivered",
            )
            advanced = await store.compare_and_set_state_with_audit(
                state_key,
                value,
                expected_revision=int(stored["revision"]),
                audit_entry=_audit_entry(
                    action_kind="issue_learning.candidate_delivered",
                    fingerprint=fingerprint,
                    operation_digest="",
                    revision=next_revision,
                ),
            )
            if advanced:
                return
        raise RuntimeError("issue learning delivery CAS retry limit exceeded")


def _issue_identity(payload: Mapping[str, Any]) -> tuple[str, str]:
    operation_id = payload.get("idempotency_key")
    fingerprint = payload.get("fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        raise ValueError("durable Norns issue learning requires a fingerprint")
    if (
        not isinstance(operation_id, str)
        or not operation_id
        or operation_id != operation_id.strip()
    ):
        raise ValueError("durable Norns issue learning requires a stable idempotency_key")
    return operation_id, fingerprint


def _operation_state(
    *,
    operation_digest: str,
    fingerprint: str,
    status: str,
    revision: int,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "status": status,
        "operation_digest": f"sha256:{operation_digest}",
        "fingerprint": fingerprint,
    }


def _validate_operation_state(
    value: Mapping[str, Any],
    *,
    operation_digest: str,
    fingerprint: str,
) -> None:
    status = value.get("status")
    expected_revision = 1 if status == "pending" else 2
    if status not in {"pending", "applied"} or dict(value) != _operation_state(
        operation_digest=operation_digest,
        fingerprint=fingerprint,
        status=str(status),
        revision=expected_revision,
    ):
        raise ValueError("issue learning operation collides with different content")


def _operation_identity_from_state(
    value: Mapping[str, Any],
) -> tuple[str, str, str]:
    operation_ref = value.get("operation_digest")
    fingerprint = value.get("fingerprint")
    status = value.get("status")
    if (
        not isinstance(operation_ref, str)
        or not operation_ref.startswith("sha256:")
        or len(operation_ref) != 71
        or any(character not in "0123456789abcdef" for character in operation_ref[7:])
        or not isinstance(fingerprint, str)
        or not fingerprint
        or status not in {"pending", "applied"}
    ):
        raise RuntimeError("stored issue learning operation state is malformed")
    operation_digest = operation_ref[7:]
    _validate_operation_state(
        value,
        operation_digest=operation_digest,
        fingerprint=fingerprint,
    )
    return operation_digest, fingerprint, str(status)


def _fingerprint_state(
    *,
    revision: int,
    fingerprint: str,
    promotion_threshold: int,
    operation_digests: tuple[str, ...],
    candidate_state: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "fingerprint": fingerprint,
        "promotion_threshold": promotion_threshold,
        "operation_digests": list(operation_digests),
        "occurrence_count": len(operation_digests),
        "candidate_state": candidate_state,
    }


def _application_from_state(
    value: Mapping[str, Any],
    *,
    state_key: str,
    fingerprint: str,
    promotion_threshold: int,
    operation_counted: bool,
) -> _FingerprintApplication:
    revision = value.get("revision")
    operations = value.get("operation_digests")
    candidate_state = value.get("candidate_state")
    if (
        value.get("schema_version") != "1.0.0"
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
        or value.get("fingerprint") != fingerprint
        or value.get("promotion_threshold") != promotion_threshold
        or not isinstance(operations, list)
        or not operations
        or len(operations) > promotion_threshold
        or any(
            not isinstance(item, str)
            or len(item) != 64
            or any(character not in "0123456789abcdef" for character in item)
            for item in operations
        )
        or operations != sorted(set(operations))
        or value.get("occurrence_count") != len(operations)
        or candidate_state not in _CANDIDATE_STATES
        or (candidate_state == "collecting" and len(operations) >= promotion_threshold)
        or (candidate_state in {"pending", "delivered"} and len(operations) != promotion_threshold)
    ):
        raise RuntimeError("stored issue learning fingerprint state is malformed")
    canonical = _fingerprint_state(
        revision=revision,
        fingerprint=fingerprint,
        promotion_threshold=promotion_threshold,
        operation_digests=tuple(str(item) for item in operations),
        candidate_state=str(candidate_state),
    )
    if dict(value) != canonical:
        raise RuntimeError("stored issue learning fingerprint state is malformed")
    return _FingerprintApplication(
        state_key=state_key,
        fingerprint=fingerprint,
        promotion_threshold=promotion_threshold,
        occurrence_count=len(operations),
        candidate_state=str(candidate_state),
        operation_counted=operation_counted,
    )


def _has_pending_candidate(
    candidates: list[dict[str, Any]],
    fingerprint: str,
) -> bool:
    return any(
        candidate.get("source_signal") == "handoff_fingerprint"
        and isinstance(candidate.get("evidence"), Mapping)
        and candidate["evidence"].get("fingerprint") == fingerprint
        for candidate in candidates
    )


def _audit_entry(
    *,
    action_kind: str,
    fingerprint: str,
    operation_digest: str,
    revision: int,
) -> dict[str, Any]:
    return {
        "actor": "Norns",
        "action_kind": action_kind,
        "operation_id_digest": (f"sha256:{operation_digest}" if operation_digest else None),
        "fingerprint": fingerprint,
        "revision": revision,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
    }


__all__ = ["NornsIssueDeduplicator"]
