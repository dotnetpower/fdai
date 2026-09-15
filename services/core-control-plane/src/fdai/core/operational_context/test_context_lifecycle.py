"""Independently admitted, revisioned test-context state; no execution authority."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

from fdai.shared.providers.decision_evidence_verifier import (
    DecisionEvidenceAdmission,
    DecisionEvidenceAdmissionProvider,
    assess_decision_evidence_admission,
)
from fdai.shared.providers.state_store import StateStore

from .test_context import TestContextClaim


class GovernedTestContextStore:
    """Persist exact typed transitions only after independent identity/policy admission.

    The admission authority verifies authenticated ingress and reviewer permissions;
    strings in a claim never authenticate their own requester or reviewer.
    Target-scoped CAS serializes concurrent review and conflicting intervals.
    """

    def __init__(
        self,
        *,
        store: StateStore,
        admission: DecisionEvidenceAdmissionProvider,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._admission = admission
        self._clock = clock or (lambda: datetime.now(UTC))

    async def record_transition(
        self,
        claim: TestContextClaim,
        *,
        expected_revision: int,
        now: datetime,
    ) -> None:
        """Record a draft, independent review, or terminal revocation; failed CAS is retryable."""
        async with asyncio.timeout(5):
            await self._record(claim, expected_revision=expected_revision, now=now)

    async def _record(
        self, claim: TestContextClaim, *, expected_revision: int, now: datetime
    ) -> None:
        if now.utcoffset() is None or claim.recorded_at > now:
            raise ValueError("test context transition time is invalid")
        key = _state_key(claim.access_scope_digest, claim.target_ref)
        state = await self._store.read_state(key)
        revision, histories = _state(state)
        history = histories.get(claim.context_id, [])
        prior = _claim(history[-1]) if history else None
        if (
            any(_claim(item) == claim for item in history)
            and type(expected_revision) is int
            and expected_revision == claim.revision - 1
        ):
            return
        prior_revision = prior.revision if prior else 0
        if type(expected_revision) is not int or expected_revision != prior_revision:
            raise ValueError("test context expected revision is no longer current")
        if claim.revision != prior_revision + 1:
            raise ValueError("test context revision MUST advance exactly once")
        if prior is None:
            if claim.state != "proposed":
                raise PermissionError("test context requires an inert initial proposal")
        else:
            allowed = {("proposed", "reviewed"), ("proposed", "revoked"), ("reviewed", "revoked")}
            if (prior.state, claim.state) not in allowed:
                raise PermissionError("test context lifecycle transition is not allowed")
            stable = replace(
                claim,
                revision=prior.revision,
                state=prior.state,
                reviewed_by=prior.reviewed_by,
                recorded_at=prior.recorded_at,
            )
            if stable != prior or claim.recorded_at < prior.recorded_at:
                raise ValueError("review cannot change the proposed envelope or source")
        if claim.state == "reviewed":
            if claim.requested_by.strip().casefold() == claim.reviewed_by.strip().casefold():
                raise PermissionError("test context review MUST be independent")
            if now >= claim.effective_to:
                raise PermissionError("expired test context cannot be activated")
            for identity, items in histories.items():
                other = _claim(items[-1])
                if (
                    identity != claim.context_id
                    and other.state == "reviewed"
                    and (
                        other.signal_code == claim.signal_code
                        and max(other.effective_from, claim.effective_from)
                        < min(other.effective_to, claim.effective_to)
                    )
                ):
                    raise PermissionError(
                        "overlapping reviewed test contexts require conflict resolution"
                    )
        transition_digest = _digest(
            {"claim": claim.digest, "prior": prior.digest if prior else None}
        )
        receipt = await self._admission.admit(
            evidence_digest=transition_digest,
            scope_digest="sha256:" + claim.access_scope_digest,
            purpose_id="test-context-transition",
            source_revision=claim.policy_revision,
        )
        completed_at = self._clock()
        if not isinstance(receipt, DecisionEvidenceAdmission) or (
            completed_at.utcoffset() is None
            or not now <= completed_at
            or not claim.recorded_at <= receipt.verified_at <= completed_at < receipt.valid_until
            or assess_decision_evidence_admission(
                receipt,
                expected_evidence_digest=transition_digest,
                expected_scope_digest="sha256:" + claim.access_scope_digest,
                expected_purpose_id="test-context-transition",
                expected_source_revision=claim.policy_revision,
                evaluated_at=completed_at,
            )
        ):
            raise PermissionError("test context transition requires independent admission")
        if claim.state == "reviewed" and completed_at >= claim.effective_to:
            raise PermissionError("test context expired while review admission was pending")
        if len(histories) >= 32 and claim.context_id not in histories or len(history) >= 64:
            raise RuntimeError("test context target history capacity exhausted")
        histories[claim.context_id] = [*history, _mapping(claim)]
        updated = {"revision": revision + 1, "histories": histories}
        audit = {
            "action_kind": "test_context.transition",
            "owner_agent": "Mimir",
            "context_digest": claim.digest,
            "previous_digest": prior.digest if prior else None,
            "admission_ref": receipt.receipt_digest,
            "state": claim.state,
            "scope_digest": claim.access_scope_digest,
            "timestamp": now.isoformat(),
            "execution_authority": False,
            "promotion_authority": False,
        }
        applied = (
            await self._store.write_state_with_audit_if_absent(key, updated, audit)
            if state is None
            else await self._store.compare_and_set_state_with_audit(
                key,
                updated,
                expected_revision=revision,
                audit_entry=audit,
            )
        )
        if not applied:
            raise RuntimeError("test context changed concurrently; reload before retry")

    async def read(
        self,
        *,
        target_ref: str,
        access_scope_digest: str,
        at: datetime,
        signal_code: str | None = None,
    ) -> TestContextClaim | None:
        """Read current revisions only; ambiguous matching records return a conflict."""
        if at.utcoffset() is None:
            raise ValueError("test context read time MUST be timezone-aware")
        async with asyncio.timeout(5):
            _, histories = _state(
                await self._store.read_state(_state_key(access_scope_digest, target_ref))
            )
            matches = []
            for identity, items in histories.items():
                claim = _claim(items[-1])
                if (
                    claim.target_ref != target_ref
                    or claim.access_scope_digest != access_scope_digest
                    or claim.context_id != identity
                ):
                    raise PermissionError("test context stored scope mismatch")
                if signal_code is None or claim.signal_code == signal_code:
                    if claim.recorded_at > at:
                        raise ValueError("test context current revision is recorded in the future")
                    matches.append(claim)
            if not matches:
                return None
            active = [
                claim
                for claim in matches
                if claim.state == "reviewed" and claim.effective_from <= at < claim.effective_to
            ]
            if len(active) == 1:
                return active[0]
            selected = max(matches, key=lambda item: (item.recorded_at, item.context_id))
            return replace(selected, state="conflicting") if len(active) > 1 else selected

    async def read_revision(
        self,
        *,
        context_id: str,
        target_ref: str,
        access_scope_digest: str,
        revision: int | None = None,
    ) -> TestContextClaim | None:
        """Read current or pinned immutable context for an already-authorized command handler."""
        if revision is not None and (type(revision) is not int or not 1 <= revision <= 64):
            raise ValueError("test context revision must be a bounded positive integer")
        _, histories = _state(
            await self._store.read_state(_state_key(access_scope_digest, target_ref))
        )
        rows = histories.get(context_id)
        if not rows:
            return None
        if revision is not None and revision > len(rows):
            return None
        claim = _claim(rows[revision - 1] if revision is not None else rows[-1])
        if claim.target_ref != target_ref or claim.access_scope_digest != access_scope_digest:
            raise PermissionError("test context command source scope mismatch")
        return claim


def _state(value: Any) -> tuple[int, dict[str, Any]]:
    if value is None:
        return 0, {}
    if (
        not isinstance(value, dict)
        or set(value) != {"revision", "histories"}
        or type(value["revision"]) is not int
        or value["revision"] < 1
        or not isinstance(value["histories"], dict)
        or len(value["histories"]) > 32
        or any(
            not isinstance(items, list) or not 1 <= len(items) <= 64
            for items in value["histories"].values()
        )
    ):
        raise ValueError("test context stored history is malformed")
    for identity, items in value["histories"].items():
        previous = None
        for revision, item in enumerate(items, start=1):
            claim = _claim(item)
            if claim.context_id != identity or claim.revision != revision:
                raise ValueError("test context stored revision chain is invalid")
            if previous is None:
                if claim.state != "proposed":
                    raise ValueError("test context history requires an initial proposal")
            elif (
                (previous.state, claim.state)
                not in {
                    ("proposed", "reviewed"),
                    ("proposed", "revoked"),
                    ("reviewed", "revoked"),
                }
                or replace(
                    claim,
                    revision=previous.revision,
                    state=previous.state,
                    reviewed_by=previous.reviewed_by,
                    recorded_at=previous.recorded_at,
                )
                != previous
                or claim.recorded_at < previous.recorded_at
            ):
                raise ValueError("test context stored transition is invalid")
            previous = claim
    return value["revision"], dict(value["histories"])


def _mapping(claim: TestContextClaim) -> dict[str, Any]:
    value = asdict(claim)
    for name in ("effective_from", "effective_to", "recorded_at"):
        value[name] = getattr(claim, name).astimezone(UTC).isoformat()
    return value


def _claim(value: dict[str, Any]) -> TestContextClaim:
    parsed = dict(value)
    for name in ("effective_from", "effective_to", "recorded_at"):
        parsed[name] = datetime.fromisoformat(parsed[name])
    return TestContextClaim(**parsed)


def _digest(value: dict[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )


def _state_key(scope: str, target: str) -> str:
    return "test-context-target:v1:" + _digest({"scope": scope, "target": target}).split(":", 1)[1]
