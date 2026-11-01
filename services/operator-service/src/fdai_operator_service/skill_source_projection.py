"""Authority-free event-path bridge and read-only projection for skill-source management."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from fdai_service_contracts import JsonObject, JsonValue

from fdai_operator_service.families.workflow.contracts import (
    ProjectionProvenance,
    WorkflowOperation,
    WorkflowProposal,
    WorkflowProposalReceipt,
    WorkflowReadRequest,
    WorkflowReadResult,
)

SKILL_SOURCE_PROPOSAL_TOPIC = "fdai.skill_source.proposal.v1"
_SOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9.-]{2,127}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_READ_ROLES = frozenset({"reader", "contributor", "approver", "owner"})
_APPROVAL_ROLES = frozenset({"approver", "owner"})
_REVOCATION_ROLES = frozenset({"owner"})
_FORBIDDEN_SECRET_KEYS = frozenset(
    {
        "access_token",
        "authentication_token",
        "authorization",
        "bearer_token",
        "credential",
        "credentials",
        "private_key",
        "publisher_signature",
        "raw_token",
        "secret",
        "secrets",
    }
)


class SkillSourceProjectionError(ValueError):
    """Raised when a skill-source read or proposal violates RBAC, idempotency, or bounds."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code, self.code, self.message = status_code, code, message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class SkillSourceProjectionRecord:
    source_id: str
    kind: str
    location: str
    trust_tier: str
    owner: str
    allowed_path: str
    refresh_policy: str
    refresh_interval_seconds: int
    enabled: bool = False
    revision: str = "rev-1"
    last_refresh_at: str | None = None
    next_refresh_at: str | None = None
    last_etag: str | None = None
    last_revision: str | None = None
    error_count: int = 0
    retry_at: str | None = None
    last_error_kind: str | None = None

    def __post_init__(self) -> None:
        if _SOURCE_ID_RE.fullmatch(self.source_id) is None:
            raise ValueError("source_id MUST be lowercase ASCII")
        if not 300 <= self.refresh_interval_seconds <= 604_800:
            raise ValueError("refresh_interval_seconds MUST be in [300, 604800]")

    def to_json(self) -> JsonObject:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SkillCandidateProjectionRecord:
    candidate_id: str
    source_id: str
    quarantine_id: str
    artifact_digest: str
    prior_installed_digest: str | None
    created_at: str
    verdict: str = "pass"
    state: str = "proposed"
    disabled: bool = True

    def __post_init__(self) -> None:
        if (
            not self.candidate_id.strip()
            or not self.quarantine_id.strip()
            or _has_control_chars(self.candidate_id)
            or _has_control_chars(self.quarantine_id)
        ):
            raise ValueError("candidate_id and quarantine_id MUST be non-empty")
        if _DIGEST_RE.fullmatch(self.artifact_digest) is None:
            raise ValueError("artifact_digest MUST be lowercase SHA-256")
        if not self.disabled:
            raise ValueError("skill update candidates MUST remain disabled")

    def to_json(self) -> JsonObject:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SkillRevocationProjectionRecord:
    revocation_id: str
    source_id: str
    artifact_digest: str
    reason: str
    revoked_at: str

    def __post_init__(self) -> None:
        if not self.reason.strip() or _has_control_chars(self.reason):
            raise ValueError("reason MUST be non-empty without control characters")

    def to_json(self) -> JsonObject:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class SkillSourceProposalEvent:
    sequence: int
    proposal_id: str
    event_topic: str
    operation: str
    source_id: str
    principal_id: str
    principal_roles: tuple[str, ...]
    idempotency_key: str
    expected_revision: str
    payload: JsonObject
    payload_digest: str
    submitted_at: str
    mode: Literal["shadow"] = "shadow"
    execution_authority: Literal["none"] = "none"
    target_remains_disabled: Literal[True] = True

    def to_json(self, *, duplicate: bool = False) -> JsonObject:
        record = asdict(self)
        record["principal_roles"] = list(self.principal_roles)
        record["duplicate"] = duplicate
        return record


class SkillSourceProposalEventSink(Protocol):
    async def publish_proposal_event(self, event: SkillSourceProposalEvent) -> None: ...


class SkillSourceWorkflowBridge:
    """Read-only projection and authority-free event bridge for skill-source operations."""

    def __init__(
        self,
        *,
        event_sink: SkillSourceProposalEventSink | None = None,
        provenance_revision: str = "skill-source-projection-v1",
    ) -> None:
        self._sources: dict[str, SkillSourceProjectionRecord] = {}
        self._candidates: dict[str, SkillCandidateProjectionRecord] = {}
        self._revocations: list[SkillRevocationProjectionRecord] = []
        self._events: list[SkillSourceProposalEvent] = []
        self._idempotency: dict[tuple[str, str, str], SkillSourceProposalEvent] = {}
        self._event_sink = event_sink
        self._provenance_revision = provenance_revision

    def register_source(
        self, source: SkillSourceProjectionRecord, *, allow_enabled: bool = False
    ) -> SkillSourceProjectionRecord:
        """Register a source projection; new registrations are disabled by default."""
        stored = source if allow_enabled else replace(source, enabled=False)
        existing = self._sources.get(stored.source_id)
        if existing is not None and existing != stored:
            raise SkillSourceProjectionError(
                409, "source_conflict", "skill source registration conflict"
            )
        self._sources[stored.source_id] = stored
        return stored

    def put_candidate(
        self, candidate: SkillCandidateProjectionRecord
    ) -> SkillCandidateProjectionRecord:
        if not candidate.disabled:
            raise SkillSourceProjectionError(
                400, "candidate_must_be_disabled", "candidate MUST stay disabled"
            )
        self._candidates[candidate.candidate_id] = candidate
        return candidate

    def put_revocation(
        self, revocation: SkillRevocationProjectionRecord
    ) -> SkillRevocationProjectionRecord:
        self._revocations.append(revocation)
        return revocation

    def _read_result(self, payload: JsonObject) -> WorkflowReadResult:
        return WorkflowReadResult(
            payload={"read_only": True, "execution_authority": "none", **payload},
            provenance=ProjectionProvenance(
                "postgresql:skill_source_projection", self._provenance_revision
            ),
        )

    async def read(
        self,
        request: WorkflowReadRequest,
        *,
        roles: frozenset[str] | set[str] | Sequence[str] = ("reader",),
    ) -> WorkflowReadResult:
        """Materialize read-only skill-source projections after verifying Reader+ RBAC."""
        _require_roles(request.principal_id, roles, _READ_ROLES, "read skill sources")
        op = request.operation
        if op is WorkflowOperation.SKILL_SOURCE_BROWSE:
            sources: list[JsonValue] = [
                i.to_json() for i in sorted(self._sources.values(), key=lambda r: r.source_id)
            ]
            candidates: list[JsonValue] = [
                i.to_json()
                for i in sorted(
                    self._candidates.values(), key=lambda r: (r.created_at, r.candidate_id)
                )
            ]
            revocations: list[JsonValue] = [item.to_json() for item in self._revocations]
            return self._read_result(
                {
                    "sources": sources,
                    "source_count": len(sources),
                    "candidates": candidates,
                    "candidate_count": len(candidates),
                    "revocations": revocations,
                }
            )
        if op is WorkflowOperation.SKILL_SOURCE_SEARCH:
            needle = request.query.get("q", "").strip().casefold()
            if not needle or len(needle) > 128:
                raise SkillSourceProjectionError(400, "invalid_query", "query q MUST be bounded")
            matched: list[JsonValue] = [
                i.to_json()
                for i in sorted(self._sources.values(), key=lambda r: r.source_id)
                if needle in f"{i.source_id} {i.location} {i.owner}".casefold()
            ]
            return self._read_result({"query": needle, "sources": matched})
        source_id = request.path_parameters.get("source_id", "").strip()
        source = self._sources.get(source_id)
        if source is None:
            raise SkillSourceProjectionError(404, "source_not_found", "skill source not found")
        source_candidates: list[JsonValue] = [
            i.to_json()
            for i in sorted(self._candidates.values(), key=lambda r: (r.created_at, r.candidate_id))
            if i.source_id == source_id
        ]
        if op is WorkflowOperation.SKILL_SOURCE_CANDIDATES:
            return self._read_result({"source_id": source_id, "candidates": source_candidates})
        if op is WorkflowOperation.SKILL_SOURCE_CHECK_UPDATE:
            return self._read_result(
                {
                    "source_id": source_id,
                    "enabled": source.enabled,
                    "last_etag": source.last_etag,
                    "last_revision": source.last_revision,
                    "newest_candidate": source_candidates[-1] if source_candidates else None,
                }
            )
        if op is WorkflowOperation.SKILL_SOURCE_INSPECT:
            source_revocations: list[JsonValue] = [
                i.to_json() for i in self._revocations if i.source_id == source_id
            ]
            return self._read_result(
                {
                    "source": source.to_json(),
                    "candidates": source_candidates,
                    "revocations": source_revocations,
                }
            )
        raise SkillSourceProjectionError(400, "unsupported_operation", f"unsupported read {op}")

    async def submit_proposal(
        self, proposal: WorkflowProposal, *, now: datetime | None = None
    ) -> JsonObject:
        if not isinstance(proposal.payload, Mapping) or _has_forbidden_secret_key(proposal.payload):
            raise SkillSourceProjectionError(
                400, "forbidden_secret_field", "secret fields forbidden"
            )
        if proposal.operation is WorkflowOperation.SKILL_SOURCE_APPROVAL_PROPOSAL:
            _require_roles(
                proposal.principal_id, proposal.principal_roles, _APPROVAL_ROLES, "approve"
            )
            raw_cid = proposal.payload.get("candidate_id")
            if not isinstance(raw_cid, str) or not raw_cid.strip():
                raise SkillSourceProjectionError(
                    400, "missing_candidate_id", "candidate_id required"
                )
            if _has_control_chars(raw_cid):
                raise SkillSourceProjectionError(
                    400, "invalid_candidate_id", "candidate_id contains control characters"
                )
        elif proposal.operation is WorkflowOperation.SKILL_SOURCE_REVOCATION_PROPOSAL:
            _require_roles(
                proposal.principal_id, proposal.principal_roles, _REVOCATION_ROLES, "revoke"
            )
            raw_reason = proposal.payload.get("reason")
            reason = raw_reason.strip() if isinstance(raw_reason, str) else ""
            if not reason or len(reason) > 512 or _has_control_chars(str(raw_reason)):
                raise SkillSourceProjectionError(400, "invalid_reason", "revocation reason invalid")
        else:
            raise SkillSourceProjectionError(400, "unsupported_proposal", "unsupported proposal")

        source_id = proposal.path_parameters.get("source_id", "").strip()
        source = self._sources.get(source_id)
        if source is None:
            raise SkillSourceProjectionError(404, "source_not_found", "skill source not found")
        if proposal.operation is WorkflowOperation.SKILL_SOURCE_APPROVAL_PROPOSAL:
            cid = str(proposal.payload.get("candidate_id", "")).strip()
            candidate = self._candidates.get(cid)
            if self._candidates and (candidate is None or candidate.source_id != source_id):
                raise SkillSourceProjectionError(
                    404, "candidate_not_found", "skill update candidate not found for source"
                )

        digest = _payload_digest(proposal.expected_revision, proposal.payload)
        key = (proposal.operation.value, source_id, proposal.idempotency_key)
        existing = self._idempotency.get(key)
        if existing is not None:
            if existing.payload_digest != digest:
                raise SkillSourceProjectionError(
                    409, "idempotency_conflict", "idempotency conflict"
                )
            return existing.to_json(duplicate=True)
        if proposal.expected_revision != source.revision:
            raise SkillSourceProjectionError(409, "revision_conflict", "revision conflict")

        timestamp = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        proposal_id = (
            f"skill-source-proposal-{hashlib.sha256(f'{key}:{digest}'.encode()).hexdigest()[:16]}"
        )
        roles = tuple(sorted({r.strip().lower() for r in proposal.principal_roles if r.strip()}))
        event = SkillSourceProposalEvent(
            len(self._events) + 1,
            proposal_id,
            SKILL_SOURCE_PROPOSAL_TOPIC,
            proposal.operation.value,
            source_id,
            proposal.principal_id.strip(),
            roles,
            proposal.idempotency_key,
            proposal.expected_revision,
            dict(proposal.payload),
            digest,
            timestamp,
        )
        self._idempotency[key] = event
        self._events.append(event)
        if self._event_sink is not None:
            await self._event_sink.publish_proposal_event(event)
        return event.to_json(duplicate=False)

    async def submit(self, proposal: WorkflowProposal) -> WorkflowProposalReceipt:
        """WorkflowProposalWriter adapter returning a durable-shaped receipt."""
        recorded = await self.submit_proposal(proposal)
        return WorkflowProposalReceipt(
            proposal_id=str(recorded["proposal_id"]),
            revision=self._provenance_revision,
            duplicate=bool(recorded["duplicate"]),
        )

    def replay_proposals(self, *, after_sequence: int = 0) -> tuple[SkillSourceProposalEvent, ...]:
        """Replay recorded proposal events in deterministic sequence order."""
        return tuple(event for event in self._events if event.sequence > after_sequence)


def _require_roles(
    principal_id: str,
    roles: frozenset[str] | set[str] | Sequence[str],
    allowed: frozenset[str],
    action: str,
) -> None:
    if not principal_id or not principal_id.strip():
        raise SkillSourceProjectionError(
            401, "unauthenticated", f"authenticated principal required to {action}"
        )
    normalized = {role.strip().lower() for role in roles if isinstance(role, str) and role.strip()}
    if not (normalized & allowed):
        raise SkillSourceProjectionError(
            403, "forbidden_role", f"principal lacks required role to {action}"
        )


def _has_control_chars(value: str) -> bool:
    return any(ord(ch) < 32 or ord(ch) == 127 for ch in value)


def _has_forbidden_secret_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(k).strip().casefold() in _FORBIDDEN_SECRET_KEYS or _has_forbidden_secret_key(v)
            for k, v in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(_has_forbidden_secret_key(item) for item in value)
    return False


def _payload_digest(expected_revision: str, payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {"expected_revision": expected_revision, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
