"""Durable typed-proposal intake awaiting Forseti's read-only Twin review.

A typed-pipeline component that holds one FDAI ActionType proposal and its completed
what-if or dry-run result submits them here. Submitters MUST be trusted in-process
components holding an independently produced what-if; an ingress payload,
conversational text, or IaC artifact MUST NOT be submitted as review evidence. The
row is content-addressed by the proposal and what-if digests, so redelivery is a
no-op, and it carries no verdict, approval, execution, or promotion authority.

A row stays ``pending`` until Forseti's producer records exact review evidence, then
``recorded`` until the Forseti writer confirms that exact review. Only then is it
``reviewed``. A newer review of the same proposal makes it ``superseded``; exhausted
bounded re-derivations or a terminal evidence gap make it ``unavailable`` with the
real reason. Every transition appends an audit entry named for the new state.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from fdai.core.assurance_twin.typed_proposal import (
    ProposalWhatIfResult,
    TypedActionProposal,
    WhatIfStatus,
    canonical_targets,
    is_digest,
    target_material,
)
from fdai.delivery.assurance_twin_writers import AssuranceTwinPublishRequest
from fdai.shared.providers.projection import ResourceRef
from fdai.shared.providers.state_store import StateStore

PROPOSAL_INTAKE_PREFIX = "runtime:assurance-twin-proposal:"
_MAX_ACTIVE = 100
_ACTIVE_STATUSES = ("pending", "recorded")
_INTAKE_PRINCIPAL = "assurance-twin-proposal-intake"
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TypedProposalReviewInput:
    """One active intake row decoded into validated typed values.

    A ``recorded`` row names the exact evidence request and the Inventory revision
    and Rule generation that the writer must still hold when it commits.
    """

    key: str
    revision: int
    status: Literal["pending", "recorded"]
    attempts: int
    proposal: TypedActionProposal
    what_if: ProposalWhatIfResult | None
    correlation_id: str
    request: AssuranceTwinPublishRequest | None = None
    inventory_revision: str | None = None
    rule_generation_digest: str | None = None


class StateStoreTypedProposalReviewIntake:
    """Restart-safe handoff of typed proposals; submission never implies a review."""

    def __init__(self, *, store: StateStore) -> None:
        self._store = store

    async def submit(
        self,
        *,
        proposal: TypedActionProposal,
        what_if: ProposalWhatIfResult | None,
        correlation_id: str,
    ) -> str:
        """Durably queue one exact proposal and what-if pair, idempotent by content."""

        if not correlation_id.strip() or len(correlation_id) > 256:
            raise ValueError("Assurance Twin proposal correlation_id MUST be bounded text")
        key = intake_key(proposal, what_if)
        await self._store.write_state_with_audit_if_absent(
            key,
            {
                "kind": "assurance_twin_proposal_review_input",
                "schema_version": "1.0.0",
                "key": key,
                "revision": 1,
                "status": "pending",
                "reason_code": None,
                "attempts": 0,
                "request": None,
                "inventory_revision": None,
                "rule_generation_digest": None,
                "proposal": _proposal_record(proposal),
                "what_if": _what_if_record(what_if) if what_if is not None else None,
                "correlation_id": correlation_id,
            },
            {
                "kind": "assurance_twin_proposal_review_submitted",
                "producer_principal": _INTAKE_PRINCIPAL,
                "proposal_digest": proposal.proposal_digest,
                "what_if_digest": what_if.what_if_digest if what_if is not None else None,
                "execution_authority": False,
            },
        )
        return key

    async def active(self) -> tuple[TypedProposalReviewInput, ...]:
        """Return bounded pending and recorded batches; malformed rows settle unavailable."""

        items: list[TypedProposalReviewInput] = []
        for status in _ACTIVE_STATUSES:
            rows, _total = await self._store.read_state_page(
                PROPOSAL_INTAKE_PREFIX,
                limit=_MAX_ACTIVE,
                field="status",
                value=status,
            )
            for raw in rows:
                try:
                    items.append(_decode(raw))
                except (KeyError, TypeError, ValueError):
                    await self._settle_malformed(raw)
        return tuple(items)

    async def mark_recorded(
        self,
        item: TypedProposalReviewInput,
        *,
        request: AssuranceTwinPublishRequest,
        inventory_revision: str,
        rule_generation_digest: str,
    ) -> bool:
        """Bind the exact evidence request; the proposal is not reviewed yet."""

        return await self._transition(
            item,
            status="recorded",
            updates={
                "request": request.model_dump(mode="json"),
                "inventory_revision": inventory_revision,
                "rule_generation_digest": rule_generation_digest,
                "reason_code": None,
            },
            reason_code=None,
            request_key=request.idempotency_key,
        )

    async def retry(
        self,
        item: TypedProposalReviewInput,
        *,
        reason_code: str,
        max_attempts: int,
    ) -> bool:
        """Return the proposal for re-derivation, or settle it after bounded attempts."""

        if item.attempts + 1 >= max_attempts:
            return await self.settle(item, status="unavailable", reason_code=reason_code)
        return await self._transition(
            item,
            status="pending",
            updates={
                "attempts": item.attempts + 1,
                "request": None,
                "inventory_revision": None,
                "rule_generation_digest": None,
                "reason_code": reason_code,
            },
            reason_code=reason_code,
            request_key=item.request.idempotency_key if item.request is not None else None,
            audit_kind="assurance_twin_proposal_review_retry",
        )

    async def settle(
        self,
        item: TypedProposalReviewInput,
        *,
        status: Literal["reviewed", "superseded", "unavailable"],
        reason_code: str | None = None,
    ) -> bool:
        """Record Forseti's terminal review disposition exactly once."""

        return await self._transition(
            item,
            status=status,
            updates={"reason_code": reason_code},
            reason_code=reason_code,
            request_key=item.request.idempotency_key if item.request is not None else None,
        )

    async def _transition(
        self,
        item: TypedProposalReviewInput,
        *,
        status: str,
        updates: Mapping[str, Any],
        reason_code: str | None,
        request_key: str | None,
        audit_kind: str | None = None,
    ) -> bool:
        current = await self._store.read_state(item.key)
        if (
            current is None
            or current.get("revision") != item.revision
            or current.get("status") != item.status
        ):
            return False
        return await self._store.compare_and_set_state_with_audit(
            item.key,
            {**dict(current), **updates, "status": status, "revision": item.revision + 1},
            expected_revision=item.revision,
            audit_entry={
                "kind": audit_kind or f"assurance_twin_proposal_review_{status}",
                "producer_principal": "Forseti",
                "proposal_digest": item.proposal.proposal_digest,
                "reason_code": reason_code,
                "request_key": request_key,
                "attempts": updates.get("attempts", item.attempts),
                "execution_authority": False,
            },
        )

    async def _settle_malformed(self, raw: Mapping[str, Any]) -> None:
        key, revision = raw.get("key"), raw.get("revision")
        if (
            not isinstance(key, str)
            or not key.startswith(PROPOSAL_INTAKE_PREFIX)
            or not isinstance(revision, int)
            or isinstance(revision, bool)
        ):
            _LOG.warning("assurance_twin_proposal_intake_row_unaddressable")
            return
        await self._store.compare_and_set_state_with_audit(
            key,
            {
                **dict(raw),
                "revision": revision + 1,
                "status": "unavailable",
                "reason_code": "input_malformed",
            },
            expected_revision=revision,
            audit_entry={
                "kind": "assurance_twin_proposal_review_unavailable",
                "producer_principal": "Forseti",
                "reason_code": "input_malformed",
                "execution_authority": False,
            },
        )


def intake_key(proposal: TypedActionProposal, what_if: ProposalWhatIfResult | None) -> str:
    """Return the content address of one exact proposal and what-if pair."""

    material = json.dumps(
        [proposal.proposal_digest, what_if.what_if_digest if what_if is not None else None],
        separators=(",", ":"),
    )
    return PROPOSAL_INTAKE_PREFIX + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _proposal_record(proposal: TypedActionProposal) -> dict[str, Any]:
    return {
        "action_type": proposal.action_type,
        "action_type_version": proposal.action_type_version,
        "targets": target_material(proposal.targets),
        "parameters_json": proposal.parameters_json,
        "parameters_digest": proposal.parameters_digest,
        "proposal_digest": proposal.proposal_digest,
    }


def _what_if_record(what_if: ProposalWhatIfResult) -> dict[str, Any]:
    return {
        "proposal_digest": what_if.proposal_digest,
        "status": what_if.status.value,
        "complete": what_if.complete,
        "synthetic": what_if.synthetic,
        "source_authority": what_if.source_authority,
        "producer_id": what_if.producer_id,
        "observed_at": what_if.observed_at.astimezone(UTC).isoformat(),
        "expires_at": what_if.expires_at.astimezone(UTC).isoformat(),
        "affected_targets": target_material(what_if.affected_targets),
        "evidence_refs": list(what_if.evidence_refs),
    }


def _targets(raw: object) -> tuple[ResourceRef, ...]:
    if not isinstance(raw, list) or any(
        not isinstance(item, list) or len(item) != 2 for item in raw
    ):
        raise ValueError("Assurance Twin proposal targets are malformed")
    targets = tuple(ResourceRef(str(item[0]), str(item[1])) for item in raw)
    if targets != canonical_targets(targets):
        raise ValueError("Assurance Twin proposal targets are not canonical")
    return targets


def _decode(raw: Mapping[str, Any]) -> TypedProposalReviewInput:
    proposal_raw = raw["proposal"]
    proposal = TypedActionProposal(
        action_type=str(proposal_raw["action_type"]),
        action_type_version=str(proposal_raw["action_type_version"]),
        targets=_targets(proposal_raw["targets"]),
        parameters_json=str(proposal_raw["parameters_json"]),
        parameters_digest=str(proposal_raw["parameters_digest"]),
        proposal_digest=str(proposal_raw["proposal_digest"]),
    )
    what_if_raw = raw.get("what_if")
    what_if = (
        ProposalWhatIfResult(
            proposal_digest=str(what_if_raw["proposal_digest"]),
            status=WhatIfStatus(str(what_if_raw["status"])),
            complete=what_if_raw["complete"],
            synthetic=what_if_raw["synthetic"],
            source_authority=str(what_if_raw["source_authority"]),
            producer_id=str(what_if_raw["producer_id"]),
            observed_at=datetime.fromisoformat(str(what_if_raw["observed_at"])),
            expires_at=datetime.fromisoformat(str(what_if_raw["expires_at"])),
            affected_targets=_targets(what_if_raw["affected_targets"]),
            evidence_refs=tuple(str(ref) for ref in what_if_raw["evidence_refs"]),
        )
        if isinstance(what_if_raw, Mapping)
        else None
    )
    if what_if_raw is not None and what_if is None:
        raise ValueError("Assurance Twin proposal what-if is malformed")
    revision, attempts, status = raw["revision"], raw["attempts"], raw["status"]
    key = str(raw["key"])
    if (
        not isinstance(revision, int)
        or isinstance(revision, bool)
        or not isinstance(attempts, int)
        or isinstance(attempts, bool)
        or attempts < 0
        or status not in _ACTIVE_STATUSES
        or key != intake_key(proposal, what_if)
    ):
        raise ValueError("Assurance Twin proposal intake identity diverges from its content")
    request_raw = raw.get("request")
    request = (
        AssuranceTwinPublishRequest.model_validate(request_raw) if request_raw is not None else None
    )
    inventory_revision = raw.get("inventory_revision")
    generation = raw.get("rule_generation_digest")
    if status == "recorded" and (
        request is None
        or request.kind != "review"
        or not is_digest(inventory_revision)
        or not is_digest(generation)
    ):
        raise ValueError("Assurance Twin recorded proposal lacks its exact evidence binding")
    return TypedProposalReviewInput(
        key=key,
        revision=revision,
        status=status,
        attempts=attempts,
        proposal=proposal,
        what_if=what_if,
        correlation_id=str(raw["correlation_id"]),
        request=request,
        inventory_revision=str(inventory_revision) if status == "recorded" else None,
        rule_generation_digest=str(generation) if status == "recorded" else None,
    )


__all__ = [
    "PROPOSAL_INTAKE_PREFIX",
    "StateStoreTypedProposalReviewIntake",
    "TypedProposalReviewInput",
    "intake_key",
]
