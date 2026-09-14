"""Durable, CAS-serialized HIL decision claims for Var."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fdai.shared.providers.state_store import StateStore

_MAX_CAS_ATTEMPTS = 16
_TERMINAL_DISPOSITIONS = frozenset({"approved", "rejected"})


@dataclass(frozen=True, slots=True)
class ApprovalDecisionState:
    """Validated durable decision aggregate for one HIL ticket."""

    revision: int
    disposition: str
    approved_principals: tuple[str, ...]

    @property
    def rejected(self) -> bool:
        return self.disposition == "rejected"

    @property
    def terminal(self) -> bool:
        return self.disposition in _TERMINAL_DISPOSITIONS


class VarDecisionJournal:
    """Atomically combine immutable per-principal decisions across replicas."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    async def record(
        self,
        *,
        state_key: str,
        correlation_id: str,
        action_type: str,
        quorum_required: int,
        ticket_identity: Mapping[str, Any],
        principal: str,
        decision: str,
    ) -> ApprovalDecisionState:
        """Record one decision and return the linearized aggregate state."""
        if decision not in _TERMINAL_DISPOSITIONS:
            raise ValueError("approval decision MUST be approved or rejected")
        ticket_digest = _ticket_digest(ticket_identity)
        claim_id = hashlib.sha256(principal.encode("utf-8")).hexdigest()
        claim = {
            "principal": principal,
            "decision": decision,
            "receipt_ref": _decision_receipt_ref(
                ticket_digest=ticket_digest,
                principal=principal,
                decision=decision,
            ),
        }
        for _attempt in range(_MAX_CAS_ATTEMPTS):
            stored = await self._store.read_state(state_key)
            if stored is None:
                claims = {claim_id: claim}
                value = _decision_state(
                    revision=1,
                    correlation_id=correlation_id,
                    action_type=action_type,
                    quorum_required=quorum_required,
                    ticket_digest=ticket_digest,
                    claims=claims,
                )
                created = await self._store.write_state_with_audit_if_absent(
                    state_key,
                    value,
                    _decision_audit_entry(
                        correlation_id=correlation_id,
                        action_type=action_type,
                        ticket_digest=ticket_digest,
                        claim_id=claim_id,
                        decision=decision,
                        revision=1,
                    ),
                )
                if created:
                    return _parse_decision_state(
                        value,
                        correlation_id=correlation_id,
                        action_type=action_type,
                        quorum_required=quorum_required,
                        ticket_digest=ticket_digest,
                    )[0]
                continue

            current, claims = _parse_decision_state(
                stored,
                correlation_id=correlation_id,
                action_type=action_type,
                quorum_required=quorum_required,
                ticket_digest=ticket_digest,
            )
            prior = claims.get(claim_id)
            if prior is not None:
                if prior != claim:
                    raise ValueError("approval principal cannot replace an existing decision")
                return current
            if current.terminal:
                return current

            next_revision = current.revision + 1
            next_claims = {**claims, claim_id: claim}
            value = _decision_state(
                revision=next_revision,
                correlation_id=correlation_id,
                action_type=action_type,
                quorum_required=quorum_required,
                ticket_digest=ticket_digest,
                claims=next_claims,
            )
            advanced = await self._store.compare_and_set_state_with_audit(
                state_key,
                value,
                expected_revision=current.revision,
                audit_entry=_decision_audit_entry(
                    correlation_id=correlation_id,
                    action_type=action_type,
                    ticket_digest=ticket_digest,
                    claim_id=claim_id,
                    decision=decision,
                    revision=next_revision,
                ),
            )
            if advanced:
                return _parse_decision_state(
                    value,
                    correlation_id=correlation_id,
                    action_type=action_type,
                    quorum_required=quorum_required,
                    ticket_digest=ticket_digest,
                )[0]
        raise RuntimeError("approval decision CAS retry limit exceeded")


def _decision_state(
    *,
    revision: int,
    correlation_id: str,
    action_type: str,
    quorum_required: int,
    ticket_digest: str,
    claims: Mapping[str, Mapping[str, str]],
) -> dict[str, Any]:
    approved = sum(claim["decision"] == "approved" for claim in claims.values())
    rejected = any(claim["decision"] == "rejected" for claim in claims.values())
    disposition = (
        "rejected" if rejected else "approved" if approved >= quorum_required else "pending"
    )
    return {
        "schema_version": "1.0.0",
        "revision": revision,
        "correlation_id": correlation_id,
        "action_type": action_type,
        "quorum_required": quorum_required,
        "ticket_digest": ticket_digest,
        "decision_claims": {claim_id: dict(claim) for claim_id, claim in sorted(claims.items())},
        "disposition": disposition,
    }


def _parse_decision_state(
    value: Mapping[str, Any],
    *,
    correlation_id: str,
    action_type: str,
    quorum_required: int,
    ticket_digest: str,
) -> tuple[ApprovalDecisionState, dict[str, dict[str, str]]]:
    revision = value.get("revision")
    claims_raw = value.get("decision_claims")
    if (
        value.get("schema_version") != "1.0.0"
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 1
        or value.get("correlation_id") != correlation_id
        or value.get("action_type") != action_type
        or value.get("quorum_required") != quorum_required
        or value.get("ticket_digest") != ticket_digest
        or not isinstance(claims_raw, Mapping)
        or not claims_raw
    ):
        raise ValueError("stored approval decision state conflicts with its ticket")

    claims: dict[str, dict[str, str]] = {}
    principals: set[str] = set()
    for claim_id, raw_claim in claims_raw.items():
        if not isinstance(claim_id, str) or not isinstance(raw_claim, Mapping):
            raise RuntimeError("stored approval decision claim is malformed")
        principal = raw_claim.get("principal")
        decision = raw_claim.get("decision")
        receipt_ref = raw_claim.get("receipt_ref")
        if (
            not isinstance(principal, str)
            or not principal
            or principal != principal.strip().casefold()
            or hashlib.sha256(principal.encode("utf-8")).hexdigest() != claim_id
            or decision not in _TERMINAL_DISPOSITIONS
            or receipt_ref
            != _decision_receipt_ref(
                ticket_digest=ticket_digest,
                principal=principal,
                decision=str(decision),
            )
            or principal in principals
        ):
            raise RuntimeError("stored approval decision claim is malformed")
        principals.add(principal)
        claims[claim_id] = {
            "principal": principal,
            "decision": str(decision),
            "receipt_ref": str(receipt_ref),
        }

    canonical = _decision_state(
        revision=revision,
        correlation_id=correlation_id,
        action_type=action_type,
        quorum_required=quorum_required,
        ticket_digest=ticket_digest,
        claims=claims,
    )
    if dict(value) != canonical:
        raise RuntimeError("stored approval decision aggregate is malformed")
    approved_principals = tuple(
        sorted(claim["principal"] for claim in claims.values() if claim["decision"] == "approved")
    )
    return (
        ApprovalDecisionState(
            revision=revision,
            disposition=str(canonical["disposition"]),
            approved_principals=approved_principals,
        ),
        claims,
    )


def _ticket_digest(ticket_identity: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        ticket_identity,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _decision_receipt_ref(
    *,
    ticket_digest: str,
    principal: str,
    decision: str,
) -> str:
    encoded = f"{ticket_digest}\x00{principal}\x00{decision}".encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _decision_audit_entry(
    *,
    correlation_id: str,
    action_type: str,
    ticket_digest: str,
    claim_id: str,
    decision: str,
    revision: int,
) -> dict[str, Any]:
    return {
        "actor": "Var",
        "action_kind": "approval.decision_recorded",
        "correlation_id": correlation_id,
        "action_type": action_type,
        "ticket_digest": ticket_digest,
        "approver_digest": f"sha256:{claim_id}",
        "decision": decision,
        "revision": revision,
        "recorded_at": datetime.now(tz=UTC).isoformat(),
    }


__all__ = ["ApprovalDecisionState", "VarDecisionJournal"]
