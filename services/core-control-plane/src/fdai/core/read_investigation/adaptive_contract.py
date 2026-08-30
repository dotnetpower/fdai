"""Immutable contracts for bounded adaptive read-investigation sessions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from fdai_service_contracts.ontology_query import OntologyQueryPlan, content_digest
from pydantic import BaseModel

from fdai.core.ontology_platform.query_execution import QueryPlanExecution
from fdai.core.ontology_platform.query_manifest import QueryManifest
from fdai.core.rca.discrimination import (
    HypothesisDiscriminationFrame,
    HypothesisDiscriminationSelection,
    build_hypothesis_discrimination_frame,
)

MAX_ADAPTIVE_ROUNDS = 8
MAX_ADAPTIVE_QUERIES = 8
MAX_ADAPTIVE_COST_UNITS = 1_000_000_000
MAX_ADAPTIVE_EVIDENCE_REFS = 128
ADAPTIVE_SESSION_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"
ADAPTIVE_SESSION_REDUCER_VERSION = "adaptive-investigation-reducer-v1"


class AdaptiveInvestigationDisposition(StrEnum):
    """Terminal or continuing causal state owned by the hypothesis reviser."""

    CONTINUE = "continue"
    CONVERGED = "converged"
    ALL_REFUTED = "all_refuted"
    HELD = "held"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    ROUND_EXHAUSTED = "round_exhausted"
    QUERY_EXHAUSTED = "query_exhausted"
    COST_EXHAUSTED = "cost_exhausted"

    @property
    def terminal(self) -> bool:
        return self is not AdaptiveInvestigationDisposition.CONTINUE


@dataclass(frozen=True, slots=True)
class AdaptiveInvestigationBudget:
    """Pinned round, query, cost, and deadline ceiling for one session."""

    max_rounds: int
    max_queries: int
    max_cost_units: int
    deadline_at: datetime
    policy_digest: str

    def __post_init__(self) -> None:
        if type(self.max_rounds) is not int or not 1 <= self.max_rounds <= MAX_ADAPTIVE_ROUNDS:
            raise ValueError(f"max_rounds MUST be in [1, {MAX_ADAPTIVE_ROUNDS}]")
        if type(self.max_queries) is not int or not 1 <= self.max_queries <= MAX_ADAPTIVE_QUERIES:
            raise ValueError(f"max_queries MUST be in [1, {MAX_ADAPTIVE_QUERIES}]")
        if (
            type(self.max_cost_units) is not int
            or not 0 <= self.max_cost_units <= MAX_ADAPTIVE_COST_UNITS
        ):
            raise ValueError(f"max_cost_units MUST be in [0, {MAX_ADAPTIVE_COST_UNITS}]")
        _aware("deadline_at", self.deadline_at)
        _digest("policy_digest", self.policy_digest)


@dataclass(frozen=True, slots=True)
class AdaptiveQueryAuthorityContext:
    """Server-owned current manifest and authenticated principal query ceiling."""

    manifest: QueryManifest
    principal_scope_digest: str
    caller_role: str
    purpose: str

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, QueryManifest):
            raise ValueError("adaptive query authority manifest has an invalid type")
        _digest("principal_scope_digest", self.principal_scope_digest)
        _text("caller_role", self.caller_role)
        _text("purpose", self.purpose)
        if self.manifest.coverage_receipt.principal_scope_digest != self.principal_scope_digest:
            raise ValueError("adaptive query authority scope does not match its manifest")
        if self.manifest.principal_role.value != self.caller_role:
            raise ValueError("adaptive query authority role does not match its manifest")
        if self.purpose not in self.manifest.purposes:
            raise ValueError("adaptive query authority purpose is absent from its manifest")
        validate_query_manifest_snapshot(self.manifest)


@dataclass(frozen=True, slots=True)
class VerifiedObservationPlanBinding:
    """Exact candidate-to-query-plan lineage accepted before provider I/O."""

    frame_digest: str
    plan: OntologyQueryPlan
    manifest: QueryManifest
    principal_scope_digest: str
    cost_units: int
    verification_receipt_digest: str
    binding_digest: str
    execution_authority: Literal[False] = False
    query_execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        _digest("frame_digest", self.frame_digest)
        _digest("principal_scope_digest", self.principal_scope_digest)
        _digest("verification_receipt_digest", self.verification_receipt_digest)
        _digest("binding_digest", self.binding_digest)
        if self.plan.ontology_release_digest != self.manifest.release_digest:
            raise ValueError("observation plan release does not match query manifest")
        if self.plan.semantic_catalog_digest != self.manifest.manifest_digest:
            raise ValueError("observation plan catalog does not match query manifest")
        if self.plan.caller_role != self.manifest.principal_role.value:
            raise ValueError("observation plan role does not match query manifest")
        if self.plan.purpose not in self.manifest.purposes:
            raise ValueError("observation plan purpose is absent from query manifest")
        if self.principal_scope_digest != self.manifest.coverage_receipt.principal_scope_digest:
            raise ValueError("observation plan principal scope does not match query manifest")
        validate_query_manifest_snapshot(self.manifest)
        if type(self.cost_units) is not int or not 0 <= self.cost_units <= MAX_ADAPTIVE_COST_UNITS:
            raise ValueError("observation plan cost_units MUST be bounded")
        _authority_free(
            "verified observation plan",
            self.execution_authority,
            self.query_execution_authority,
        )
        verification = _verification_receipt_material(self)
        if self.verification_receipt_digest != content_digest(verification):
            raise ValueError("observation verification receipt digest does not match content")
        if self.binding_digest != content_digest(_binding_material(self)):
            raise ValueError("observation plan binding digest does not match content")


@dataclass(frozen=True, slots=True)
class AdaptiveObservationExecution:
    """One exact selected observation and its authority-free query result."""

    round_index: int
    frame_digest: str
    selection_digest: str
    candidate_digest: str
    binding_digest: str
    verification_receipt_digest: str
    plan_digest: str
    result_digest: str
    query_status: str
    evidence_refs: tuple[str, ...]
    reserved_cost_units: int
    actual_cost_units: int | None
    execution_digest: str
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if type(self.round_index) is not int or not 1 <= self.round_index <= MAX_ADAPTIVE_ROUNDS:
            raise ValueError("adaptive observation round_index is invalid")
        for name, value in (
            ("frame_digest", self.frame_digest),
            ("selection_digest", self.selection_digest),
            ("candidate_digest", self.candidate_digest),
            ("binding_digest", self.binding_digest),
            ("verification_receipt_digest", self.verification_receipt_digest),
            ("plan_digest", self.plan_digest),
            ("result_digest", self.result_digest),
            ("execution_digest", self.execution_digest),
        ):
            _digest(name, value)
        _text("query_status", self.query_status)
        _refs(self.evidence_refs)
        if (
            type(self.reserved_cost_units) is not int
            or not 0 <= self.reserved_cost_units <= MAX_ADAPTIVE_COST_UNITS
        ):
            raise ValueError("reserved_cost_units MUST be bounded")
        if self.actual_cost_units is not None and (
            type(self.actual_cost_units) is not int
            or not 0 <= self.actual_cost_units <= MAX_ADAPTIVE_COST_UNITS
        ):
            raise ValueError("actual_cost_units MUST be bounded or unknown")
        _authority_free(
            "adaptive observation execution",
            self.execution_authority,
            self.mutation_authority,
        )
        if self.execution_digest != content_digest(_execution_material(self)):
            raise ValueError("adaptive observation execution digest does not match content")


@dataclass(frozen=True, slots=True)
class HypothesisRevisionSet:
    """Forseti-owned complete active-set revision after one observation."""

    prior_active_set_receipt_digest: str
    prior_frame_digest: str
    observation_result_digest: str
    scorer_version: str
    graph_revision: str
    evidence_cutoff: datetime
    active_hypothesis_ids: tuple[str, ...]
    active_set_receipt_digest: str
    evidence_refs: tuple[str, ...]
    complete: bool
    truncated: bool
    disposition: AdaptiveInvestigationDisposition
    revision_digest: str
    owner_agent: Literal["Forseti"] = "Forseti"
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        for name, value in (
            ("prior_active_set_receipt_digest", self.prior_active_set_receipt_digest),
            ("prior_frame_digest", self.prior_frame_digest),
            ("observation_result_digest", self.observation_result_digest),
            ("active_set_receipt_digest", self.active_set_receipt_digest),
            ("revision_digest", self.revision_digest),
        ):
            _digest(name, value)
        _text("scorer_version", self.scorer_version)
        _text("graph_revision", self.graph_revision)
        _aware("evidence_cutoff", self.evidence_cutoff)
        if self.active_hypothesis_ids != tuple(sorted(set(self.active_hypothesis_ids))):
            raise ValueError("active hypothesis ids MUST be sorted and unique")
        if len(self.active_hypothesis_ids) > 32:
            raise ValueError("active hypothesis ids exceed the hard limit")
        if not isinstance(self.complete, bool) or not isinstance(self.truncated, bool):
            raise ValueError("hypothesis revision completeness flags MUST be boolean")
        if not isinstance(self.disposition, AdaptiveInvestigationDisposition):
            raise ValueError("hypothesis revision disposition is invalid")
        if self.disposition not in {
            AdaptiveInvestigationDisposition.CONTINUE,
            AdaptiveInvestigationDisposition.CONVERGED,
            AdaptiveInvestigationDisposition.ALL_REFUTED,
            AdaptiveInvestigationDisposition.HELD,
        }:
            raise ValueError("hypothesis reviser cannot emit a mechanical terminal state")
        if self.disposition is AdaptiveInvestigationDisposition.CONTINUE:
            if not self.complete or self.truncated or len(self.active_hypothesis_ids) < 2:
                raise ValueError("continuing hypothesis revision requires a complete active set")
        if self.disposition is AdaptiveInvestigationDisposition.CONVERGED:
            if not self.complete or self.truncated or len(self.active_hypothesis_ids) != 1:
                raise ValueError("converged hypothesis revision requires one complete hypothesis")
        if self.disposition is AdaptiveInvestigationDisposition.ALL_REFUTED:
            if not self.complete or self.truncated or self.active_hypothesis_ids:
                raise ValueError("all-refuted hypothesis revision requires an empty complete set")
        _refs(self.evidence_refs)
        if self.owner_agent != "Forseti":
            raise ValueError("hypothesis revisions MUST be owned by Forseti")
        _authority_free("hypothesis revision", self.execution_authority)
        if self.revision_digest != content_digest(_revision_material(self)):
            raise ValueError("hypothesis revision digest does not match content")


@dataclass(frozen=True, slots=True)
class AdaptiveInvestigationIteration:
    """One replayable frame, selection, execution, and revision chain."""

    round_index: int
    frame: HypothesisDiscriminationFrame
    selection: HypothesisDiscriminationSelection
    execution: AdaptiveObservationExecution | None
    revision: HypothesisRevisionSet | None
    shadow_comparison_digest: str | None
    iteration_digest: str

    def __post_init__(self) -> None:
        if type(self.round_index) is not int or not 1 <= self.round_index <= MAX_ADAPTIVE_ROUNDS:
            raise ValueError("adaptive iteration round_index is invalid")
        if not isinstance(self.frame, HypothesisDiscriminationFrame):
            raise ValueError("adaptive iteration frame has an invalid type")
        if not isinstance(self.selection, HypothesisDiscriminationSelection):
            raise ValueError("adaptive iteration selection has an invalid type")
        if self.execution is not None and not isinstance(
            self.execution,
            AdaptiveObservationExecution,
        ):
            raise ValueError("adaptive iteration execution has an invalid type")
        if self.revision is not None and not isinstance(self.revision, HypothesisRevisionSet):
            raise ValueError("adaptive iteration revision has an invalid type")
        if self.selection.frame_digest != self.frame.frame_digest:
            raise ValueError("adaptive iteration selection does not match its frame")
        if self.execution is not None:
            if self.execution.round_index != self.round_index:
                raise ValueError("adaptive iteration execution round does not match")
            if self.execution.frame_digest != self.frame.frame_digest:
                raise ValueError("adaptive iteration execution frame does not match")
            if self.execution.selection_digest != self.selection.selection_digest:
                raise ValueError("adaptive iteration execution selection does not match")
            selected_id = self.selection.selected_candidate_id
            expected_candidate_id = f"observation-candidate-{self.execution.candidate_digest[7:39]}"
            if selected_id is None or selected_id != expected_candidate_id:
                raise ValueError(
                    "adaptive iteration execution does not match the selected candidate"
                )
        if self.revision is not None:
            if self.execution is None:
                raise ValueError("adaptive iteration revision requires an execution")
            if self.revision.prior_frame_digest != self.frame.frame_digest:
                raise ValueError("hypothesis revision does not descend from the iteration frame")
            if (
                self.revision.prior_active_set_receipt_digest
                != self.frame.active_set_receipt_digest
            ):
                raise ValueError("hypothesis revision does not cite the prior active set")
            if self.revision.observation_result_digest != self.execution.result_digest:
                raise ValueError("hypothesis revision does not cite the observation result")
            if self.execution.query_status != "completed":
                raise ValueError("hypothesis revision requires a completed observation")
            if self.revision.evidence_cutoff < self.frame.evidence_cutoff:
                raise ValueError("hypothesis revision evidence cutoff moved backward")
            if not set(self.revision.active_hypothesis_ids) <= set(
                self.frame.active_hypothesis_ids
            ):
                raise ValueError("hypothesis revision introduced an unknown hypothesis")
        if self.shadow_comparison_digest is not None:
            _digest("shadow_comparison_digest", self.shadow_comparison_digest)
        _digest("iteration_digest", self.iteration_digest)
        if self.iteration_digest != content_digest(_iteration_material(self)):
            raise ValueError("adaptive iteration digest does not match content")


@dataclass(frozen=True, slots=True)
class AdaptiveInvestigationResult:
    """Terminal replay receipt for one authority-free adaptive investigation."""

    session_id: str
    incident_id: str
    workflow_version: str
    reducer_version: str
    active_strategy_digest: str
    challenger_strategy_digest: str | None
    budget: AdaptiveInvestigationBudget
    iterations: tuple[AdaptiveInvestigationIteration, ...]
    disposition: AdaptiveInvestigationDisposition
    terminal_frame_digest: str
    terminal_active_set_receipt_digest: str
    used_queries: int
    used_cost_units: int
    result_digest: str
    execution_authority: Literal[False] = False
    mutation_authority: Literal[False] = False
    promotion_authority: Literal[False] = False

    def __post_init__(self) -> None:
        if not isinstance(self.budget, AdaptiveInvestigationBudget):
            raise ValueError("adaptive investigation budget has an invalid type")
        if not isinstance(self.iterations, tuple) or any(
            not isinstance(item, AdaptiveInvestigationIteration) for item in self.iterations
        ):
            raise ValueError("adaptive investigation iterations MUST be an immutable typed tuple")
        if len(self.iterations) > self.budget.max_rounds:
            raise ValueError("adaptive investigation iterations exceed the round budget")
        if not isinstance(self.disposition, AdaptiveInvestigationDisposition):
            raise ValueError("adaptive investigation disposition has an invalid type")
        _text("session_id", self.session_id)
        _text("incident_id", self.incident_id)
        _text("workflow_version", self.workflow_version)
        if self.reducer_version != ADAPTIVE_SESSION_REDUCER_VERSION:
            raise ValueError("unsupported adaptive investigation reducer version")
        _digest("active_strategy_digest", self.active_strategy_digest)
        if self.challenger_strategy_digest is not None:
            _digest("challenger_strategy_digest", self.challenger_strategy_digest)
        if not self.disposition.terminal:
            raise ValueError("adaptive investigation result MUST be terminal")
        _digest("terminal_frame_digest", self.terminal_frame_digest)
        _digest(
            "terminal_active_set_receipt_digest",
            self.terminal_active_set_receipt_digest,
        )
        if (
            type(self.used_queries) is not int
            or not 0 <= self.used_queries <= self.budget.max_queries
        ):
            raise ValueError("adaptive investigation used_queries is invalid")
        if (
            type(self.used_cost_units) is not int
            or not 0 <= self.used_cost_units <= self.budget.max_cost_units
        ):
            raise ValueError("adaptive investigation used_cost_units is invalid")
        if tuple(item.round_index for item in self.iterations) != tuple(
            range(1, len(self.iterations) + 1)
        ):
            raise ValueError("adaptive investigation iterations MUST be contiguous")
        self._validate_lineage()
        _authority_free(
            "adaptive investigation result",
            self.execution_authority,
            self.mutation_authority,
            self.promotion_authority,
        )
        _digest("result_digest", self.result_digest)
        if self.result_digest != content_digest(_result_material(self)):
            raise ValueError("adaptive investigation result digest does not match content")

    def _validate_lineage(self) -> None:
        if self.iterations and self.iterations[0].frame.incident_id != self.incident_id:
            raise ValueError("adaptive investigation first frame belongs to another incident")
        for previous, current in zip(self.iterations, self.iterations[1:], strict=False):
            revision = previous.revision
            if (
                revision is None
                or revision.disposition is not AdaptiveInvestigationDisposition.CONTINUE
            ):
                raise ValueError("adaptive investigation iteration advanced without continuation")
            if (
                current.frame.incident_id != previous.frame.incident_id
                or current.frame.cost_model_digest != previous.frame.cost_model_digest
                or current.frame.active_set_receipt_digest != revision.active_set_receipt_digest
                or current.frame.graph_revision != revision.graph_revision
                or current.frame.evidence_cutoff != revision.evidence_cutoff
                or current.frame.active_hypothesis_ids != revision.active_hypothesis_ids
            ):
                raise ValueError("adaptive investigation round-to-round lineage is broken")
        executions = tuple(item.execution for item in self.iterations if item.execution is not None)
        if self.used_queries != len(executions):
            raise ValueError("adaptive investigation query count does not match iterations")
        if self.used_cost_units != sum(
            (
                item.actual_cost_units
                if item.actual_cost_units is not None
                else item.reserved_cost_units
            )
            for item in executions
        ):
            raise ValueError("adaptive investigation cost does not match iterations")
        expected_frame, expected_active_set = self._expected_terminal_lineage()
        if self.terminal_frame_digest != expected_frame:
            raise ValueError("adaptive investigation terminal frame lineage is invalid")
        if self.terminal_active_set_receipt_digest != expected_active_set:
            raise ValueError("adaptive investigation terminal active-set lineage is invalid")

    def _expected_terminal_lineage(self) -> tuple[str, str]:
        if self.disposition in {
            AdaptiveInvestigationDisposition.CONVERGED,
            AdaptiveInvestigationDisposition.ALL_REFUTED,
        } and (
            not self.iterations
            or self.iterations[-1].revision is None
            or self.iterations[-1].revision.disposition is not self.disposition
        ):
            raise ValueError("terminal causal disposition requires a matching hypothesis revision")
        if not self.iterations:
            return self.terminal_frame_digest, self.terminal_active_set_receipt_digest
        last = self.iterations[-1]
        revision = last.revision
        if revision is None:
            return last.frame.frame_digest, last.frame.active_set_receipt_digest
        if revision.disposition.terminal:
            if revision.disposition is not self.disposition:
                raise ValueError("terminal hypothesis revision disposition does not match result")
            return last.frame.frame_digest, revision.active_set_receipt_digest
        if revision.disposition is not AdaptiveInvestigationDisposition.CONTINUE:
            raise ValueError("adaptive investigation terminal revision is invalid")
        next_frame = build_hypothesis_discrimination_frame(
            incident_id=last.frame.incident_id,
            graph_revision=revision.graph_revision,
            evidence_cutoff=revision.evidence_cutoff,
            active_hypothesis_ids=revision.active_hypothesis_ids,
            active_set_receipt_digest=revision.active_set_receipt_digest,
            cost_model_digest=last.frame.cost_model_digest,
        )
        return next_frame.frame_digest, revision.active_set_receipt_digest


def build_verified_observation_plan_binding(
    *,
    frame_digest: str,
    plan: OntologyQueryPlan,
    manifest: QueryManifest,
    principal_scope_digest: str,
    cost_units: int,
) -> VerifiedObservationPlanBinding:
    """Build an exact query verification receipt before candidate construction."""

    verification_material = {
        "frame_digest": frame_digest,
        "plan_digest": plan.plan_digest,
        "release_digest": manifest.release_digest,
        "manifest_digest": manifest.manifest_digest,
        "principal_scope_digest": principal_scope_digest,
        "caller_role": plan.caller_role,
        "purpose": plan.purpose,
    }
    verification_receipt_digest = content_digest(verification_material)
    binding_material = {
        **verification_material,
        "verification_receipt_digest": verification_receipt_digest,
        "cost_units": cost_units,
    }
    return VerifiedObservationPlanBinding(
        frame_digest=frame_digest,
        plan=plan,
        manifest=manifest,
        principal_scope_digest=principal_scope_digest,
        cost_units=cost_units,
        verification_receipt_digest=verification_receipt_digest,
        binding_digest=content_digest(binding_material),
    )


def build_hypothesis_revision_set(
    *,
    prior_active_set_receipt_digest: str,
    prior_frame_digest: str,
    observation_result_digest: str,
    scorer_version: str,
    graph_revision: str,
    evidence_cutoff: datetime,
    active_hypothesis_ids: tuple[str, ...],
    active_set_receipt_digest: str,
    evidence_refs: tuple[str, ...],
    complete: bool,
    truncated: bool,
    disposition: AdaptiveInvestigationDisposition,
) -> HypothesisRevisionSet:
    """Build one content-addressed Forseti hypothesis-set revision."""

    canonical_active_ids = tuple(sorted(active_hypothesis_ids))
    canonical_evidence_refs = tuple(sorted(evidence_refs))
    material = {
        "prior_active_set_receipt_digest": prior_active_set_receipt_digest,
        "prior_frame_digest": prior_frame_digest,
        "observation_result_digest": observation_result_digest,
        "scorer_version": scorer_version,
        "graph_revision": graph_revision,
        "evidence_cutoff": _utc_timestamp(evidence_cutoff),
        "active_hypothesis_ids": canonical_active_ids,
        "active_set_receipt_digest": active_set_receipt_digest,
        "evidence_refs": canonical_evidence_refs,
        "complete": complete,
        "truncated": truncated,
        "disposition": disposition.value,
        "owner_agent": "Forseti",
        "execution_authority": False,
    }
    return HypothesisRevisionSet(
        prior_active_set_receipt_digest=prior_active_set_receipt_digest,
        prior_frame_digest=prior_frame_digest,
        observation_result_digest=observation_result_digest,
        scorer_version=scorer_version,
        graph_revision=graph_revision,
        evidence_cutoff=evidence_cutoff,
        active_hypothesis_ids=canonical_active_ids,
        active_set_receipt_digest=active_set_receipt_digest,
        evidence_refs=canonical_evidence_refs,
        complete=complete,
        truncated=truncated,
        disposition=disposition,
        revision_digest=content_digest(material),
    )


def build_adaptive_investigation_iteration(
    *,
    round_index: int,
    frame: HypothesisDiscriminationFrame,
    selection: HypothesisDiscriminationSelection,
    execution: AdaptiveObservationExecution | None,
    revision: HypothesisRevisionSet | None,
    shadow_comparison_digest: str | None = None,
) -> AdaptiveInvestigationIteration:
    """Build one content-addressed iteration lineage."""

    material = {
        "round_index": round_index,
        "frame_digest": frame.frame_digest,
        "selection_digest": selection.selection_digest,
        "execution_digest": execution.execution_digest if execution is not None else None,
        "revision_digest": revision.revision_digest if revision is not None else None,
        "shadow_comparison_digest": shadow_comparison_digest,
    }
    return AdaptiveInvestigationIteration(
        round_index=round_index,
        frame=frame,
        selection=selection,
        execution=execution,
        revision=revision,
        shadow_comparison_digest=shadow_comparison_digest,
        iteration_digest=content_digest(material),
    )


def build_adaptive_investigation_result(
    *,
    session_id: str,
    incident_id: str,
    workflow_version: str,
    active_strategy_digest: str,
    challenger_strategy_digest: str | None,
    budget: AdaptiveInvestigationBudget,
    iterations: tuple[AdaptiveInvestigationIteration, ...],
    disposition: AdaptiveInvestigationDisposition,
    terminal_frame_digest: str,
    terminal_active_set_receipt_digest: str,
    used_queries: int,
    used_cost_units: int,
) -> AdaptiveInvestigationResult:
    """Build the terminal content-addressed session receipt."""

    material = {
        "session_id": session_id,
        "incident_id": incident_id,
        "workflow_version": workflow_version,
        "reducer_version": ADAPTIVE_SESSION_REDUCER_VERSION,
        "active_strategy_digest": active_strategy_digest,
        "challenger_strategy_digest": challenger_strategy_digest,
        "budget": {
            "max_rounds": budget.max_rounds,
            "max_queries": budget.max_queries,
            "max_cost_units": budget.max_cost_units,
            "deadline_at": _utc_timestamp(budget.deadline_at),
            "policy_digest": budget.policy_digest,
        },
        "iteration_digests": tuple(item.iteration_digest for item in iterations),
        "disposition": disposition.value,
        "terminal_frame_digest": terminal_frame_digest,
        "terminal_active_set_receipt_digest": terminal_active_set_receipt_digest,
        "used_queries": used_queries,
        "used_cost_units": used_cost_units,
        "execution_authority": False,
    }
    return AdaptiveInvestigationResult(
        session_id=session_id,
        incident_id=incident_id,
        workflow_version=workflow_version,
        reducer_version=ADAPTIVE_SESSION_REDUCER_VERSION,
        active_strategy_digest=active_strategy_digest,
        challenger_strategy_digest=challenger_strategy_digest,
        budget=budget,
        iterations=iterations,
        disposition=disposition,
        terminal_frame_digest=terminal_frame_digest,
        terminal_active_set_receipt_digest=terminal_active_set_receipt_digest,
        used_queries=used_queries,
        used_cost_units=used_cost_units,
        result_digest=content_digest(material),
    )


def execution_result_digest(execution: QueryPlanExecution) -> str:
    """Return a bounded content digest without retaining raw result values."""

    material = {
        "plan_digest": execution.plan_digest,
        "status": execution.status,
        "output_node_ids": execution.output_node_ids,
        "receipts": [
            {
                **receipt.model_dump(mode="json"),
                "started_at": _utc_timestamp(receipt.started_at),
                "completed_at": _utc_timestamp(receipt.completed_at),
            }
            for receipt in execution.receipts
        ],
        "results": {
            node_id: {
                "value": _canonical_query_value(execution.results[node_id].value),
                "evidence_refs": execution.results[node_id].evidence_refs,
            }
            for node_id in sorted(execution.results)
        },
        "execution_authority": False,
    }
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    for chunk in encoder.iterencode(material):
        digest.update(chunk.encode("utf-8"))
    return f"sha256:{digest.hexdigest()}"


def validate_query_manifest_snapshot(manifest: QueryManifest) -> None:
    """Reject a forged or post-construction-mutated query manifest."""

    material = {
        "release_digest": manifest.release_digest,
        "principal_role": manifest.principal_role.value,
        "purposes": tuple(sorted(set(manifest.purposes))),
        "descriptors": manifest.descriptors,
        "unavailable": manifest.unavailable,
        "mutation_authority": False,
    }
    encoded = json.dumps(
        material,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    expected = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
    if manifest.manifest_digest != expected:
        raise ValueError("query manifest digest does not match its content")
    if manifest.coverage_receipt.manifest_digest != expected:
        raise ValueError("query manifest coverage receipt does not match its content")


def build_adaptive_observation_execution(
    *,
    round_index: int,
    frame_digest: str,
    selection_digest: str,
    candidate_digest: str,
    binding_digest: str,
    verification_receipt_digest: str,
    plan_digest: str,
    result_digest: str,
    query_status: str,
    evidence_refs: tuple[str, ...],
    reserved_cost_units: int,
    actual_cost_units: int | None,
) -> AdaptiveObservationExecution:
    """Build one content-addressed execution lineage receipt."""

    canonical_evidence_refs = tuple(sorted(evidence_refs))
    material = {
        "round_index": round_index,
        "frame_digest": frame_digest,
        "selection_digest": selection_digest,
        "candidate_digest": candidate_digest,
        "binding_digest": binding_digest,
        "verification_receipt_digest": verification_receipt_digest,
        "plan_digest": plan_digest,
        "result_digest": result_digest,
        "query_status": query_status,
        "evidence_refs": list(canonical_evidence_refs),
        "reserved_cost_units": reserved_cost_units,
        "actual_cost_units": actual_cost_units,
        "execution_authority": False,
        "mutation_authority": False,
    }
    return AdaptiveObservationExecution(
        round_index=round_index,
        frame_digest=frame_digest,
        selection_digest=selection_digest,
        candidate_digest=candidate_digest,
        binding_digest=binding_digest,
        verification_receipt_digest=verification_receipt_digest,
        plan_digest=plan_digest,
        result_digest=result_digest,
        query_status=query_status,
        evidence_refs=canonical_evidence_refs,
        reserved_cost_units=reserved_cost_units,
        actual_cost_units=actual_cost_units,
        execution_digest=content_digest(material),
    )


def _verification_receipt_material(
    binding: VerifiedObservationPlanBinding,
) -> dict[str, object]:
    return {
        "frame_digest": binding.frame_digest,
        "plan_digest": binding.plan.plan_digest,
        "release_digest": binding.manifest.release_digest,
        "manifest_digest": binding.manifest.manifest_digest,
        "principal_scope_digest": binding.principal_scope_digest,
        "caller_role": binding.plan.caller_role,
        "purpose": binding.plan.purpose,
    }


def _binding_material(binding: VerifiedObservationPlanBinding) -> dict[str, object]:
    return {
        **_verification_receipt_material(binding),
        "verification_receipt_digest": binding.verification_receipt_digest,
        "cost_units": binding.cost_units,
    }


def _revision_material(revision: HypothesisRevisionSet) -> dict[str, object]:
    return {
        "prior_active_set_receipt_digest": revision.prior_active_set_receipt_digest,
        "prior_frame_digest": revision.prior_frame_digest,
        "observation_result_digest": revision.observation_result_digest,
        "scorer_version": revision.scorer_version,
        "graph_revision": revision.graph_revision,
        "evidence_cutoff": _utc_timestamp(revision.evidence_cutoff),
        "active_hypothesis_ids": revision.active_hypothesis_ids,
        "active_set_receipt_digest": revision.active_set_receipt_digest,
        "evidence_refs": revision.evidence_refs,
        "complete": revision.complete,
        "truncated": revision.truncated,
        "disposition": revision.disposition.value,
        "owner_agent": revision.owner_agent,
        "execution_authority": False,
    }


def _iteration_material(iteration: AdaptiveInvestigationIteration) -> dict[str, object]:
    return {
        "round_index": iteration.round_index,
        "frame_digest": iteration.frame.frame_digest,
        "selection_digest": iteration.selection.selection_digest,
        "execution_digest": (
            iteration.execution.execution_digest if iteration.execution is not None else None
        ),
        "revision_digest": iteration.revision.revision_digest if iteration.revision else None,
        "shadow_comparison_digest": iteration.shadow_comparison_digest,
    }


def _result_material(result: AdaptiveInvestigationResult) -> dict[str, object]:
    return {
        "session_id": result.session_id,
        "incident_id": result.incident_id,
        "workflow_version": result.workflow_version,
        "reducer_version": result.reducer_version,
        "active_strategy_digest": result.active_strategy_digest,
        "challenger_strategy_digest": result.challenger_strategy_digest,
        "budget": {
            "max_rounds": result.budget.max_rounds,
            "max_queries": result.budget.max_queries,
            "max_cost_units": result.budget.max_cost_units,
            "deadline_at": _utc_timestamp(result.budget.deadline_at),
            "policy_digest": result.budget.policy_digest,
        },
        "iteration_digests": tuple(item.iteration_digest for item in result.iterations),
        "disposition": result.disposition.value,
        "terminal_frame_digest": result.terminal_frame_digest,
        "terminal_active_set_receipt_digest": result.terminal_active_set_receipt_digest,
        "used_queries": result.used_queries,
        "used_cost_units": result.used_cost_units,
        "execution_authority": False,
    }


def _execution_material(execution: AdaptiveObservationExecution) -> dict[str, object]:
    return {
        "round_index": execution.round_index,
        "frame_digest": execution.frame_digest,
        "selection_digest": execution.selection_digest,
        "candidate_digest": execution.candidate_digest,
        "binding_digest": execution.binding_digest,
        "verification_receipt_digest": execution.verification_receipt_digest,
        "plan_digest": execution.plan_digest,
        "result_digest": execution.result_digest,
        "query_status": execution.query_status,
        "evidence_refs": list(execution.evidence_refs),
        "reserved_cost_units": execution.reserved_cost_units,
        "actual_cost_units": execution.actual_cost_units,
        "execution_authority": False,
        "mutation_authority": False,
    }


def _text(name: str, value: str) -> None:
    if not value.strip() or len(value) > 512:
        raise ValueError(f"{name} MUST be non-empty and bounded")


def _digest(name: str, value: str) -> None:
    if (
        len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ValueError(f"{name} MUST be a SHA-256 digest")


def _aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} MUST be timezone-aware")


def _utc_timestamp(value: datetime) -> str:
    _aware("timestamp", value)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _refs(values: tuple[str, ...]) -> None:
    if (
        not isinstance(values, tuple)
        or len(values) > MAX_ADAPTIVE_EVIDENCE_REFS
        or values != tuple(sorted(set(values)))
        or any(not value or len(value) > 512 for value in values)
    ):
        raise ValueError("adaptive investigation evidence refs MUST be sorted, unique, and bounded")


def _authority_free(label: str, *values: object) -> None:
    if any(value is not False for value in values):
        raise ValueError(f"{label} MUST NOT grant authority")


def _canonical_query_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return _utc_timestamp(value)
    if isinstance(value, BaseModel):
        return _canonical_query_value(value.model_dump(mode="json"))
    if is_dataclass(value) and not isinstance(value, type):
        return _canonical_query_value(asdict(value))
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("query result mappings require string keys")
        return {key: _canonical_query_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical_query_value(item) for item in value]
    raise ValueError("query result contains an unsupported value type")


__all__ = [
    "ADAPTIVE_SESSION_REDUCER_VERSION",
    "AdaptiveInvestigationBudget",
    "AdaptiveInvestigationDisposition",
    "AdaptiveInvestigationIteration",
    "AdaptiveQueryAuthorityContext",
    "AdaptiveInvestigationResult",
    "AdaptiveObservationExecution",
    "HypothesisRevisionSet",
    "VerifiedObservationPlanBinding",
    "build_adaptive_investigation_iteration",
    "build_adaptive_investigation_result",
    "build_adaptive_observation_execution",
    "build_hypothesis_revision_set",
    "build_verified_observation_plan_binding",
    "execution_result_digest",
    "validate_query_manifest_snapshot",
]
