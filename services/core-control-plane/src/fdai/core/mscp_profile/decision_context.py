"""Read-only, revision-bound MSCP decision context from owner-supplied facts.

This projector never acquires authority from the facts it reads. Owner readers
must obtain their observations from the authoritative ontology, incident,
workflow, and audit stores; missing or contradictory facts remain a hold.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol

from fdai.core.mscp_profile.readiness import MscpCandidateKey

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_STATE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SCHEMA_VERSION = "1.0.0"


class DecisionSource(StrEnum):
    ONTOLOGY = "ontology"
    INCIDENT = "incident"
    WORKFLOW = "workflow"
    AUDIT = "audit"


@dataclass(frozen=True, slots=True)
class OwnerDecisionObservation:
    """One bounded owner projection, never a client-supplied decision."""

    source: DecisionSource
    decision_id: str
    subject_digest: str
    revision: int
    state: str
    evidence_digest: str
    observed_at: datetime
    recorded_at: datetime
    valid_until: datetime
    complete: bool
    audit_chain_verified: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.source, DecisionSource):
            raise ValueError("decision context source MUST be registered")
        _text("decision_id", self.decision_id)
        _digest("subject_digest", self.subject_digest)
        _digest("evidence_digest", self.evidence_digest)
        if not isinstance(self.state, str) or _STATE.fullmatch(self.state) is None:
            raise ValueError("decision context state MUST be a bounded machine token")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise ValueError("decision context revision MUST be positive")
        for name in ("observed_at", "recorded_at", "valid_until"):
            _instant(name, getattr(self, name))
        if not isinstance(self.complete, bool) or not isinstance(self.audit_chain_verified, bool):
            raise ValueError("decision context completeness and audit proof MUST be boolean")
        if self.source is not DecisionSource.AUDIT and self.audit_chain_verified:
            raise ValueError("only the audit owner can attest its chain")

    def to_mapping(self) -> dict[str, object]:
        return {
            **asdict(self),
            "source": self.source.value,
            "observed_at": _timestamp(self.observed_at),
            "recorded_at": _timestamp(self.recorded_at),
            "valid_until": _timestamp(self.valid_until),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> OwnerDecisionObservation:
        keys = set(cls.__dataclass_fields__)
        if set(value) != keys:
            raise ValueError("decision context observation fields are unsupported")
        return cls(
            source=DecisionSource(_required_text(value, "source")),
            decision_id=_required_text(value, "decision_id"),
            subject_digest=_required_text(value, "subject_digest"),
            revision=_integer(value, "revision"),
            state=_required_text(value, "state"),
            evidence_digest=_required_text(value, "evidence_digest"),
            observed_at=_parsed_at(value, "observed_at"),
            recorded_at=_parsed_at(value, "recorded_at"),
            valid_until=_parsed_at(value, "valid_until"),
            complete=_boolean(value, "complete"),
            audit_chain_verified=_boolean(value, "audit_chain_verified"),
        )


@dataclass(frozen=True, slots=True)
class MscpDecisionContext:
    """Immutable, digest-bound evidence; no profile or execution authority."""

    candidate: MscpCandidateKey
    decision_id: str
    subject_digest: str
    cutoff: datetime
    observations: tuple[OwnerDecisionObservation, ...]
    unavailable: tuple[DecisionSource, ...]
    reasons: tuple[str, ...]
    disposition: Literal["ready", "hold"]
    digest: str
    execution_authority: Literal[False] = False

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "candidate": asdict(self.candidate),
            "decision_id": self.decision_id,
            "subject_digest": self.subject_digest,
            "cutoff": _timestamp(self.cutoff),
            "observations": [item.to_mapping() for item in self.observations],
            "unavailable": [source.value for source in self.unavailable],
            "reasons": list(self.reasons),
            "disposition": self.disposition,
            "digest": self.digest,
            "execution_authority": False,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> MscpDecisionContext:
        keys = {
            "schema_version",
            "candidate",
            "decision_id",
            "subject_digest",
            "cutoff",
            "observations",
            "unavailable",
            "reasons",
            "disposition",
            "digest",
            "execution_authority",
        }
        if set(value) != keys or value.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("decision context state has an unsupported schema")
        if value.get("execution_authority") is not False:
            raise ValueError("decision context cannot grant execution authority")
        candidate = value.get("candidate")
        observations = value.get("observations")
        unavailable = value.get("unavailable")
        if not isinstance(candidate, Mapping) or set(candidate) != set(
            MscpCandidateKey.__dataclass_fields__
        ):
            raise ValueError("decision context candidate is malformed")
        if not isinstance(observations, list) or not isinstance(unavailable, list):
            raise ValueError("decision context owner observations are malformed")
        if any(not isinstance(item, Mapping) for item in observations):
            raise ValueError("decision context observation MUST be an object")
        if any(not isinstance(item, str) for item in unavailable):
            raise ValueError("decision context unavailable source MUST be text")
        expected = project_decision_context(
            candidate=MscpCandidateKey(
                **{
                    key: _required_text(candidate, key)
                    for key in MscpCandidateKey.__dataclass_fields__
                }
            ),
            decision_id=_required_text(value, "decision_id"),
            subject_digest=_required_text(value, "subject_digest"),
            cutoff=_parsed_at(value, "cutoff"),
            observations=tuple(
                OwnerDecisionObservation.from_mapping(item) for item in observations
            ),
            unavailable=tuple(DecisionSource(item) for item in unavailable),
        )
        if expected.to_mapping() != value:
            raise ValueError("decision context state does not match its immutable projection")
        return expected


class DecisionOwnerReader(Protocol):
    """A trusted owner-specific read, not a browser or caller assertion."""

    async def read(
        self, *, decision_id: str, subject_digest: str, cutoff: datetime
    ) -> OwnerDecisionObservation | None: ...


async def collect_decision_context(
    *,
    candidate: MscpCandidateKey,
    decision_id: str,
    subject_digest: str,
    cutoff: datetime,
    readers: Mapping[DecisionSource, DecisionOwnerReader],
) -> MscpDecisionContext:
    """Collect all four owners; an unavailable or faulty owner becomes a hold."""

    observations: list[OwnerDecisionObservation] = []
    unavailable: list[DecisionSource] = []
    for source in DecisionSource:
        reader = readers.get(source)
        if reader is None:
            continue
        try:
            observation = await reader.read(
                decision_id=decision_id, subject_digest=subject_digest, cutoff=cutoff
            )
        except Exception:
            unavailable.append(source)
            continue
        if observation is not None:
            observations.append(observation)
    return project_decision_context(
        candidate=candidate,
        decision_id=decision_id,
        subject_digest=subject_digest,
        cutoff=cutoff,
        observations=tuple(observations),
        unavailable=tuple(unavailable),
    )


def project_decision_context(
    *,
    candidate: MscpCandidateKey,
    decision_id: str,
    subject_digest: str,
    cutoff: datetime,
    observations: Sequence[OwnerDecisionObservation],
    unavailable: Sequence[DecisionSource] = (),
) -> MscpDecisionContext:
    """Join exactly one current, complete observation from each owner or hold."""

    _text("decision_id", decision_id)
    _digest("subject_digest", subject_digest)
    _instant("cutoff", cutoff)
    if len(observations) > 8 or len(unavailable) > 4:
        raise ValueError("decision context owner observations exceed their bound")
    grouped: dict[DecisionSource, list[OwnerDecisionObservation]] = {
        source: [] for source in DecisionSource
    }
    for item in observations:
        grouped[item.source].append(item)
    if any(not isinstance(source, DecisionSource) for source in unavailable):
        raise ValueError("decision context unavailable owner MUST be registered")
    reasons: set[str] = set()
    for source in DecisionSource:
        records = grouped[source]
        if source in unavailable:
            reasons.add(f"unavailable_{source.value}")
        if not records:
            reasons.add(f"missing_{source.value}")
            continue
        if len(records) != 1 or source in unavailable:
            reasons.add(f"conflicting_{source.value}")
            continue
        item = records[0]
        if item.decision_id != decision_id or item.subject_digest != subject_digest:
            reasons.add(f"conflicting_{source.value}")
        if not item.complete:
            reasons.add(f"incomplete_{source.value}")
        if (
            item.recorded_at < item.observed_at
            or item.observed_at > cutoff
            or item.recorded_at > cutoff
        ):
            reasons.add(f"future_{source.value}")
        if item.valid_until <= cutoff:
            reasons.add(f"stale_{source.value}")
        if source is DecisionSource.AUDIT and not item.audit_chain_verified:
            reasons.add("unverified_audit")
    lineages: dict[str, set[DecisionSource]] = {}
    for item in observations:
        lineages.setdefault(item.evidence_digest, set()).add(item.source)
    if any(len(sources) > 1 for sources in lineages.values()):
        reasons.add("conflicting_source_lineage")
    ordered = tuple(
        sorted(
            observations, key=lambda item: (item.source.value, item.revision, item.evidence_digest)
        )
    )
    failed = tuple(sorted(reasons))
    absent = tuple(sorted(set(unavailable), key=lambda source: source.value))
    payload = {
        "candidate": asdict(candidate),
        "decision_id": decision_id,
        "subject_digest": subject_digest,
        "cutoff": _timestamp(cutoff),
        "observations": [item.to_mapping() for item in ordered],
        "unavailable": [source.value for source in absent],
        "reasons": list(failed),
        "disposition": "hold" if failed else "ready",
        "execution_authority": False,
    }
    digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    return MscpDecisionContext(
        candidate=candidate,
        decision_id=decision_id,
        subject_digest=subject_digest,
        cutoff=cutoff,
        observations=ordered,
        unavailable=absent,
        reasons=failed,
        disposition="hold" if failed else "ready",
        digest=digest,
    )


def _text(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"decision context {name} MUST be bounded text")
    return value


def _digest(name: str, value: str) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"decision context {name} MUST be SHA-256")


def _instant(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"decision context {name} MUST be timezone-aware")


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _required_text(value: Mapping[str, Any], key: str) -> str:
    return _text(key, value.get(key))


def _integer(value: Mapping[str, Any], key: str) -> int:
    item = value.get(key)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"decision context {key} MUST be an integer")
    return item


def _boolean(value: Mapping[str, Any], key: str) -> bool:
    item = value.get(key)
    if not isinstance(item, bool):
        raise ValueError(f"decision context {key} MUST be boolean")
    return item


def _parsed_at(value: Mapping[str, Any], key: str) -> datetime:
    item = _required_text(value, key)
    parsed = datetime.fromisoformat(item.replace("Z", "+00:00"))
    _instant(key, parsed)
    return parsed
