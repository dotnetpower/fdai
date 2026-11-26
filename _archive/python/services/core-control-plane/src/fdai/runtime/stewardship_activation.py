"""Apply Owner-queued activations of Console stewardship revision candidates.

The Operator API stores one inert ``stewardship.candidate_activation`` proposal. This processor
re-reads the stored Owner role and the exact candidate bytes before it records the activation,
so a forged role, a stale digest, or a replayed delivery never changes ownership. Each proposal
gets one durable receipt, which makes redelivery change nothing.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from fdai_service_contracts.stewardship_activation import (
    CANDIDATE_ID_PATTERN,
    STEWARDSHIP_ACTIVATION_OPERATION,
    StewardshipCandidateActivationBody,
)
from pydantic import ValidationError

from fdai.core.stewardship.governance import StewardshipGovernanceError
from fdai.runtime.stewardship_governance import (
    CANDIDATE_PREFIX,
    activate_console_stewardship_candidate,
)
from fdai.shared.providers.state_store import StateStore

_PROPOSAL_PREFIX: Final = "operator-proposal:operations:"
_MERGE_PREFIX: Final = "stewardship_merge:"
RECEIPT_PREFIX: Final = "stewardship_activation:"
PROJECTION_KEY: Final = "operator-projection:operations:stewardship.candidates"
PROJECTION_LIMIT: Final = 20
_TEXT_LIMIT: Final = 4_000
_YAML_LIMIT: Final = 64_000
_PROPOSAL_ID: Final = re.compile(r"^operator-[0-9a-f]{32}$")
_PRINCIPAL: Final = re.compile(r"^[A-Za-z0-9@._:/+-]{1,128}$")
_OWNER_ROLE: Final = "Owner"
_LOGGER = logging.getLogger("fdai.stewardship.activation")

REJECT_MALFORMED: Final = "request_malformed"
REJECT_ROLE: Final = "requester_role_insufficient"
REJECT_UNKNOWN: Final = "candidate_unknown"
REJECT_DIGEST: Final = "candidate_digest_mismatch"
REJECT_INVALID: Final = "candidate_invalid"


@dataclass(frozen=True, slots=True)
class ActivationRequest:
    """One typed Owner request recovered from a stored Operator proposal."""

    proposal_id: str
    principal_id: str
    principal_roles: tuple[str, ...]
    body: StewardshipCandidateActivationBody


def parse_activation_request(record: Mapping[str, Any]) -> ActivationRequest | None:
    """Return the typed request, or ``None`` when the stored proposal is malformed."""

    if record.get("operation") != STEWARDSHIP_ACTIVATION_OPERATION:
        return None
    proposal_id, principal = record.get("proposal_id"), record.get("principal_id")
    envelope = record.get("payload")
    if not isinstance(proposal_id, str) or _PROPOSAL_ID.fullmatch(proposal_id) is None:
        return None
    if not isinstance(principal, str) or _PRINCIPAL.fullmatch(principal) is None:
        return None
    if not isinstance(envelope, Mapping):
        return None
    body, roles = envelope.get("payload"), envelope.get("principal_roles", ())
    if (
        not isinstance(body, Mapping)
        or not isinstance(roles, list | tuple)
        or not all(isinstance(role, str) and role.strip() for role in roles)
    ):
        return None
    try:
        parsed = StewardshipCandidateActivationBody.model_validate(dict(body))
    except ValidationError:
        return None
    return ActivationRequest(proposal_id, principal, tuple(role.strip() for role in roles), parsed)


@dataclass(frozen=True, slots=True)
class StewardshipActivationProcessor:
    """Drain pending Owner activation proposals with one durable receipt each."""

    store: StateStore
    validation_environ: Mapping[str, str] | None = None
    batch_limit: int = 100

    def __post_init__(self) -> None:
        if (
            isinstance(self.batch_limit, bool)
            or not isinstance(self.batch_limit, int)
            or not 1 <= self.batch_limit <= 1000
        ):
            raise ValueError("stewardship activation batch limit MUST be between 1 and 1000")

    async def run_once(self) -> int:
        """Record a receipt for each unseen proposal and return how many were processed."""

        rows, _ = await self.store.read_state_page(
            _PROPOSAL_PREFIX,
            limit=self.batch_limit,
            field="operation",
            value=STEWARDSHIP_ACTIVATION_OPERATION,
        )
        processed = 0
        for raw in rows:
            processed += int(await self._process(raw))
        await self._refresh_projection()
        return processed

    async def _refresh_projection(self) -> None:
        """Publish the newest candidates for the Owner-only review list when they changed."""

        candidates = await self.store.read_states(CANDIDATE_PREFIX, limit=PROJECTION_LIMIT)
        items = []
        for raw in candidates:
            candidate_id = str(raw.get("candidate_id", ""))
            if re.fullmatch(CANDIDATE_ID_PATTERN, candidate_id) is None:
                continue
            active = await self.store.read_state(f"{_MERGE_PREFIX}console-{candidate_id}")
            items.append(
                {
                    "candidate_id": candidate_id,
                    "candidate_digest": str(raw.get("candidate_digest", "")),
                    "title": str(raw.get("title", ""))[:_TEXT_LIMIT],
                    "body": str(raw.get("body", ""))[:_TEXT_LIMIT],
                    "yaml": str(raw.get("yaml", ""))[:_YAML_LIMIT],
                    "state": "activated" if active is not None else "open",
                    "recorded_at": str(raw.get("recorded_at", "")),
                }
            )
        projection = {"schema_version": "1.0.0", "total": len(items), "items": items}
        current = await self.store.read_state(PROJECTION_KEY)
        if current is not None and {k: current.get(k) for k in projection} == projection:
            return
        await self.store.write_state(
            PROJECTION_KEY,
            {**projection, "generated_at": datetime.now(UTC).isoformat()},
        )

    async def _process(self, raw: Mapping[str, Any]) -> bool:
        proposal_id = raw.get("proposal_id")
        if not isinstance(proposal_id, str) or _PROPOSAL_ID.fullmatch(proposal_id) is None:
            return False
        receipt_key = f"{RECEIPT_PREFIX}{proposal_id}"
        if await self.store.read_state(receipt_key) is not None:
            return False
        request = parse_activation_request(raw)
        if request is None:
            return await self._record(receipt_key, proposal_id, None, "rejected", REJECT_MALFORMED)
        outcome, reason = await self._decide(request)
        return await self._record(receipt_key, proposal_id, request, outcome, reason)

    async def _decide(self, request: ActivationRequest) -> tuple[str, str | None]:
        if _OWNER_ROLE not in request.principal_roles:
            return "rejected", REJECT_ROLE
        candidate_id = request.body.candidate_id
        candidate = await self.store.read_state(f"{CANDIDATE_PREFIX}{candidate_id}")
        if candidate is None:
            return "rejected", REJECT_UNKNOWN
        if str(candidate.get("candidate_digest", "")) != request.body.candidate_digest:
            return "rejected", REJECT_DIGEST
        try:
            inserted = await activate_console_stewardship_candidate(
                self.store,
                candidate_id=candidate_id,
                reviewer_identity=request.principal_id,
                validation_environ=self.validation_environ,
            )
        except StewardshipGovernanceError:
            return "rejected", REJECT_INVALID
        return ("activated" if inserted else "already_active"), None

    async def _record(
        self,
        receipt_key: str,
        proposal_id: str,
        request: ActivationRequest | None,
        outcome: str,
        reason: str | None,
    ) -> bool:
        recorded_at = datetime.now(UTC).isoformat()
        candidate_id = request.body.candidate_id if request is not None else None
        reviewer = request.principal_id if request is not None else None
        _LOGGER.info(
            "stewardship_activation_recorded",
            extra={"outcome": outcome, "reason": reason},
        )
        return await self.store.write_state_with_audit_if_absent(
            receipt_key,
            {
                "proposal_id": proposal_id,
                "candidate_id": candidate_id,
                "outcome": outcome,
                "reason": reason,
                "recorded_at": recorded_at,
            },
            {
                "actor": "Saga",
                "action_kind": f"stewardship.console_activation_{outcome}",
                "proposal_id": proposal_id,
                "candidate_id": candidate_id,
                "reviewer_identity": reviewer,
                "reason": reason,
                "recorded_at": recorded_at,
            },
        )
