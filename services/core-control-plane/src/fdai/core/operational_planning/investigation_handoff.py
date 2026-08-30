"""Authority-free handoff from adaptive investigation to operational planning."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from fdai.core.read_investigation.adaptive_contract import (
    AdaptiveInvestigationDisposition,
    AdaptiveInvestigationResult,
)
from fdai.shared.contracts.models import (
    ContractBase,
    OntologyDeclarationKind,
    OntologyTypeRef,
)

MAX_HANDOFF_ACTION_TYPE_REFS = 32
MAX_HANDOFF_BYTES = 64 * 1024
MAX_HANDOFF_EVIDENCE_REFS = 256
MAX_HANDOFF_TEXT_LENGTH = 512

_DIGEST_PATTERN = r"^sha256:[a-f0-9]{64}$"
_HANDOFF_ID_PATTERN = r"^investigation-planning-handoff:[a-f0-9]{64}$"


class InvestigationTerminalDisposition(StrEnum):
    """Terminal adaptive-investigation outcomes relevant to planning eligibility."""

    MATERIALLY_SUPPORTED = "materially_supported"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    ALL_REFUTED = "all_refuted"
    INCOMPLETE = "incomplete"
    TRUNCATED = "truncated"
    HELD = "held"
    BUDGET_EXHAUSTED = "budget_exhausted"
    COST_EXHAUSTED = "cost_exhausted"


class InvestigationPlanningHandoff(ContractBase):
    """Propose that Forseti start a separate planning Process from terminal evidence.

    This content-addressed input grants no authority and carries no planning constraints,
    simulations, candidates, or final :class:`PlanningRequest`. Forseti must refresh
    current context and construct the mandatory no-action baseline after accepting it.
    """

    schema_version: Literal["1.0.0"] = "1.0.0"
    handoff_id: Annotated[str, Field(pattern=_HANDOFF_ID_PATTERN)]
    handoff_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    terminal_session_digest: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    incident_id: Annotated[str, Field(min_length=1, max_length=MAX_HANDOFF_TEXT_LENGTH)]
    correlation_id: Annotated[str, Field(min_length=1, max_length=MAX_HANDOFF_TEXT_LENGTH)]
    target_resource_ref: Annotated[str, Field(min_length=1, max_length=MAX_HANDOFF_TEXT_LENGTH)]
    evidence_cutoff: datetime
    graph_revision: Annotated[str, Field(min_length=1, max_length=MAX_HANDOFF_TEXT_LENGTH)]
    evidence_refs: Annotated[
        tuple[Annotated[str, Field(min_length=1, max_length=MAX_HANDOFF_TEXT_LENGTH)], ...],
        Field(min_length=1, max_length=MAX_HANDOFF_EVIDENCE_REFS),
    ]
    terminal_disposition: InvestigationTerminalDisposition
    action_type_refs: Annotated[
        tuple[OntologyTypeRef, ...],
        Field(max_length=MAX_HANDOFF_ACTION_TYPE_REFS),
    ] = ()
    recipient_agent: Literal["forseti"] = "forseti"
    proposal_only: Literal[True] = True
    starts_separate_planning_process: Literal[True] = True
    refresh_context_required: Literal[True] = True
    no_action_baseline_required: Literal[True] = True
    mutation_authority: Literal[False] = False
    query_authority: Literal[False] = False
    approval_authority: Literal[False] = False
    execution_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    @classmethod
    def create(
        cls,
        *,
        terminal_session_digest: str,
        incident_id: str,
        correlation_id: str,
        target_resource_ref: str,
        evidence_cutoff: datetime,
        graph_revision: str,
        evidence_refs: tuple[str, ...],
        terminal_disposition: InvestigationTerminalDisposition,
        action_type_refs: tuple[OntologyTypeRef, ...] = (),
    ) -> Self:
        """Create a canonical handoff or reject an ineligible terminal session."""

        canonical_evidence = tuple(sorted(evidence_refs))
        canonical_action_refs = tuple(sorted(action_type_refs, key=_action_ref_key))
        material = _handoff_material(
            schema_version="1.0.0",
            terminal_session_digest=terminal_session_digest,
            incident_id=incident_id,
            correlation_id=correlation_id,
            target_resource_ref=target_resource_ref,
            evidence_cutoff=evidence_cutoff,
            graph_revision=graph_revision,
            evidence_refs=canonical_evidence,
            terminal_disposition=terminal_disposition,
            action_type_refs=canonical_action_refs,
        )
        handoff_digest = _digest(material)
        return cls(
            handoff_id=f"investigation-planning-handoff:{handoff_digest.removeprefix('sha256:')}",
            handoff_digest=handoff_digest,
            terminal_session_digest=terminal_session_digest,
            incident_id=incident_id,
            correlation_id=correlation_id,
            target_resource_ref=target_resource_ref,
            evidence_cutoff=evidence_cutoff,
            graph_revision=graph_revision,
            evidence_refs=canonical_evidence,
            terminal_disposition=terminal_disposition,
            action_type_refs=canonical_action_refs,
        )

    @model_validator(mode="after")
    def _validate_handoff(self) -> InvestigationPlanningHandoff:
        if self.terminal_disposition is not InvestigationTerminalDisposition.MATERIALLY_SUPPORTED:
            raise ValueError("only a materially_supported investigation can request planning")
        _canonical_unique("evidence_refs", self.evidence_refs)
        _validate_action_refs(self.action_type_refs)
        _timestamp(self.evidence_cutoff)
        material = _handoff_material(
            schema_version=self.schema_version,
            terminal_session_digest=self.terminal_session_digest,
            incident_id=self.incident_id,
            correlation_id=self.correlation_id,
            target_resource_ref=self.target_resource_ref,
            evidence_cutoff=self.evidence_cutoff,
            graph_revision=self.graph_revision,
            evidence_refs=self.evidence_refs,
            terminal_disposition=self.terminal_disposition,
            action_type_refs=self.action_type_refs,
        )
        canonical = _canonical_json(material)
        if len(canonical) > MAX_HANDOFF_BYTES:
            raise ValueError("investigation planning handoff exceeds its canonical byte limit")
        expected_digest = _digest_bytes(canonical)
        if self.handoff_digest != expected_digest:
            raise ValueError("investigation planning handoff digest does not match content")
        expected_id = f"investigation-planning-handoff:{expected_digest.removeprefix('sha256:')}"
        if self.handoff_id != expected_id:
            raise ValueError("investigation planning handoff id does not match content")
        return self


def build_investigation_planning_handoff(
    *,
    terminal_session_digest: str,
    incident_id: str,
    correlation_id: str,
    target_resource_ref: str,
    evidence_cutoff: datetime,
    graph_revision: str,
    evidence_refs: tuple[str, ...],
    terminal_disposition: InvestigationTerminalDisposition,
    action_type_refs: tuple[OntologyTypeRef, ...] = (),
) -> InvestigationPlanningHandoff:
    """Adapt one eligible terminal session into proposal-only Forseti input."""

    return InvestigationPlanningHandoff.create(
        terminal_session_digest=terminal_session_digest,
        incident_id=incident_id,
        correlation_id=correlation_id,
        target_resource_ref=target_resource_ref,
        evidence_cutoff=evidence_cutoff,
        graph_revision=graph_revision,
        evidence_refs=evidence_refs,
        terminal_disposition=terminal_disposition,
        action_type_refs=action_type_refs,
    )


def planning_handoff_from_adaptive_result(
    result: AdaptiveInvestigationResult,
    *,
    correlation_id: str,
    target_resource_ref: str,
    action_type_refs: tuple[OntologyTypeRef, ...] = (),
) -> InvestigationPlanningHandoff:
    """Adapt one converged complete session without reconstructing planning evidence."""

    if type(result) is not AdaptiveInvestigationResult:
        raise TypeError("planning handoff requires an AdaptiveInvestigationResult")
    if result.disposition is not AdaptiveInvestigationDisposition.CONVERGED:
        raise ValueError("only a converged adaptive investigation can request planning")
    if not result.iterations:
        raise ValueError("converged adaptive investigation requires iteration evidence")
    revision = result.iterations[-1].revision
    if (
        revision is None
        or revision.disposition is not AdaptiveInvestigationDisposition.CONVERGED
        or not revision.complete
        or revision.truncated
    ):
        raise ValueError("adaptive investigation terminal revision is not planning eligible")
    execution = result.iterations[-1].execution
    if execution is None:
        raise ValueError("planning-eligible investigation requires execution evidence")
    evidence_refs = (
        revision.revision_digest,
        execution.execution_digest,
        result.result_digest,
    )
    return build_investigation_planning_handoff(
        terminal_session_digest=result.result_digest,
        incident_id=result.incident_id,
        correlation_id=correlation_id,
        target_resource_ref=target_resource_ref,
        evidence_cutoff=revision.evidence_cutoff,
        graph_revision=revision.graph_revision,
        evidence_refs=tuple(sorted(evidence_refs)),
        terminal_disposition=InvestigationTerminalDisposition.MATERIALLY_SUPPORTED,
        action_type_refs=action_type_refs,
    )


def _handoff_material(
    *,
    schema_version: Literal["1.0.0"],
    terminal_session_digest: str,
    incident_id: str,
    correlation_id: str,
    target_resource_ref: str,
    evidence_cutoff: datetime,
    graph_revision: str,
    evidence_refs: tuple[str, ...],
    terminal_disposition: InvestigationTerminalDisposition,
    action_type_refs: tuple[OntologyTypeRef, ...],
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "terminal_session_digest": terminal_session_digest,
        "incident_id": incident_id,
        "correlation_id": correlation_id,
        "target_resource_ref": target_resource_ref,
        "evidence_cutoff": _timestamp(evidence_cutoff),
        "graph_revision": graph_revision,
        "evidence_refs": list(evidence_refs),
        "terminal_disposition": terminal_disposition.value,
        "action_type_refs": [item.model_dump(mode="json") for item in action_type_refs],
        "recipient_agent": "forseti",
        "proposal_only": True,
        "starts_separate_planning_process": True,
        "refresh_context_required": True,
        "no_action_baseline_required": True,
        "mutation_authority": False,
        "query_authority": False,
        "approval_authority": False,
        "execution_authority": False,
        "promotion_authority": False,
    }


def _validate_action_refs(action_type_refs: tuple[OntologyTypeRef, ...]) -> None:
    keys = tuple(_action_ref_key(item) for item in action_type_refs)
    if keys != tuple(sorted(set(keys))):
        raise ValueError("action_type_refs MUST be sorted, unique, and bounded")
    if any(item.kind is not OntologyDeclarationKind.ACTION for item in action_type_refs):
        raise ValueError("action_type_refs MUST contain only catalog-backed ActionType refs")


def _action_ref_key(item: OntologyTypeRef) -> tuple[str, str, str, str]:
    return (item.kind.value, item.name, item.version, item.catalog_digest)


def _canonical_unique(name: str, values: tuple[str, ...]) -> None:
    if values != tuple(sorted(set(values))):
        raise ValueError(f"{name} MUST be sorted and unique")


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evidence_cutoff MUST be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return _digest_bytes(_canonical_json(value))


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


__all__ = [
    "MAX_HANDOFF_ACTION_TYPE_REFS",
    "MAX_HANDOFF_BYTES",
    "MAX_HANDOFF_EVIDENCE_REFS",
    "MAX_HANDOFF_TEXT_LENGTH",
    "InvestigationPlanningHandoff",
    "InvestigationTerminalDisposition",
    "build_investigation_planning_handoff",
    "planning_handoff_from_adaptive_result",
]
