"""Deterministic impact assessment for one normalized Change revision."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from fdai.core.impact_analysis.analyzer import ImpactAnalyzer, ImpactTraversalBounds
from fdai.core.impact_analysis.models import AffectedSet


@dataclass(frozen=True, slots=True)
class GraphFreshnessReceipt:
    """Authenticated active-graph observation used for one planned change."""

    receipt_digest: str
    ontology_release_digest: str
    target_ref: str
    source_generation: str
    graph_revision: str
    observed_at: datetime
    recorded_at: datetime
    valid_until: datetime
    complete: bool
    truncated: bool
    conflicts: tuple[str, ...] = ()
    source_identity: str = "postgres.inventory_active"
    verification_method: Literal["authoritative_state_store_read"] = (
        "authoritative_state_store_read"
    )
    execution_authority: Literal[False] = False

    def __post_init__(self) -> None:
        for name, value in (
            ("receipt_digest", self.receipt_digest),
            ("ontology_release_digest", self.ontology_release_digest),
            ("graph_revision", self.graph_revision),
        ):
            if not value.startswith("sha256:") or len(value) != 71:
                raise ValueError(f"graph freshness {name} MUST be a SHA-256 digest")
        for text_name, text_value in (
            ("target_ref", self.target_ref),
            ("source_generation", self.source_generation),
            ("source_identity", self.source_identity),
        ):
            if not text_value.strip():
                raise ValueError(f"graph freshness {text_name} MUST be non-empty")
        for timestamp_name, timestamp_value in (
            ("observed_at", self.observed_at),
            ("recorded_at", self.recorded_at),
            ("valid_until", self.valid_until),
        ):
            if timestamp_value.tzinfo is None or timestamp_value.utcoffset() is None:
                raise ValueError(f"graph freshness {timestamp_name} MUST be timezone-aware")
        if self.observed_at > self.recorded_at or self.valid_until < self.observed_at:
            raise ValueError("graph freshness receipt timestamps are inconsistent")
        if self.complete and (self.truncated or self.conflicts):
            raise ValueError("complete graph freshness receipt cannot be truncated or conflicting")
        if len(self.conflicts) > 64 or any(not item.strip() for item in self.conflicts):
            raise ValueError("graph freshness conflicts MUST be bounded non-empty codes")
        object.__setattr__(self, "conflicts", tuple(sorted(set(self.conflicts))))
        if self.execution_authority is not False:
            raise ValueError("graph freshness receipt MUST NOT grant execution authority")
        if self.receipt_digest != _graph_freshness_digest(self):
            raise ValueError("graph freshness receipt digest does not match canonical content")


class GraphFreshnessReceiptSource(Protocol):
    """Resolve a trusted active-graph receipt without granting authority."""

    async def resolve(self, *, target_ref: str) -> GraphFreshnessReceipt | None: ...


class ChangeAssessmentUnavailableError(RuntimeError):
    """An authoritative planned-change assessment dependency is unavailable."""


@dataclass(frozen=True, slots=True)
class ChangeAssessment:
    change_id: str
    correlation_id: str
    target_ref: str
    occurred_at: datetime
    affected_set: AffectedSet
    graph_freshness_receipt: GraphFreshnessReceipt | None
    review_required: bool
    reasons: tuple[str, ...]
    evidence_digest: str

    def to_mapping(self) -> dict[str, object]:
        return {
            "change_id": self.change_id,
            "correlation_id": self.correlation_id,
            "target_ref": self.target_ref,
            "occurred_at": self.occurred_at.isoformat(),
            "affected_resource_ids": list(self.affected_set.all_resource_ids),
            "protected_service_ids": list(self.affected_set.protected_services),
            "protected_objective_ids": list(self.affected_set.protected_objectives),
            "control_dependency_ids": list(self.affected_set.control_dependencies),
            "graph_revision": self.affected_set.graph_revision,
            "graph_freshness_receipt": (
                _graph_freshness_mapping(self.graph_freshness_receipt)
                if self.graph_freshness_receipt is not None
                else None
            ),
            "review_required": self.review_required,
            "reasons": list(self.reasons),
            "evidence_digest": self.evidence_digest,
        }


class ChangeAssessmentService:
    """Assess a Change against fresh bounded ontology impact evidence."""

    def __init__(
        self,
        *,
        analyzer: ImpactAnalyzer,
        graph_freshness_source: GraphFreshnessReceiptSource | None = None,
        ontology_release_digest: str | None = None,
        clock: Callable[[], datetime] | None = None,
        max_graph_age: timedelta = timedelta(hours=24),
        analysis_error_types: tuple[type[Exception], ...] = (),
        max_affected_resources: int = 10,
        traversal_bounds: ImpactTraversalBounds | None = None,
    ) -> None:
        if max_affected_resources < 1:
            raise ValueError("max_affected_resources MUST be positive")
        if max_graph_age <= timedelta(0) or max_graph_age > timedelta(days=7):
            raise ValueError("max_graph_age MUST be in (0, 7 days]")
        if (graph_freshness_source is None) != (ontology_release_digest is None):
            raise ValueError(
                "graph freshness source and ontology release digest MUST be configured together"
            )
        if ontology_release_digest is not None and (
            not ontology_release_digest.startswith("sha256:") or len(ontology_release_digest) != 71
        ):
            raise ValueError("ontology release digest MUST be a SHA-256 digest")
        if any(
            error_type in {Exception, BaseException} or not issubclass(error_type, Exception)
            for error_type in analysis_error_types
        ):
            raise ValueError("analysis error types MUST contain narrow Exception subclasses")
        self._analyzer = analyzer
        self._graph_freshness_source = graph_freshness_source
        self._ontology_release_digest = ontology_release_digest
        self._clock = clock or (lambda: datetime.now(UTC))
        self._max_graph_age = max_graph_age
        self._analysis_error_types = analysis_error_types
        self._max_affected_resources = max_affected_resources
        self._traversal_bounds = traversal_bounds or ImpactTraversalBounds()

    async def assess(
        self,
        change: Mapping[str, Any],
    ) -> ChangeAssessment:
        change_id = _required_text(change, "id")
        correlation_id = _required_text(change, "correlation_id")
        target_ref = _required_text(change, "target_ref")
        occurred_at = _required_datetime(change, "occurred_at")
        receipt = await self._resolve_graph_freshness(target_ref)
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("change assessment clock MUST be timezone-aware")
        graph_reasons = _graph_freshness_reasons(
            receipt,
            expected_release=self._ontology_release_digest,
            target_ref=target_ref,
            evaluated_at=now,
            max_graph_age=self._max_graph_age,
        )
        try:
            affected = await self._analyzer.analyze(
                direct_target_ids=(target_ref,),
                bounds=self._traversal_bounds,
                graph_fresh=not graph_reasons,
                unresolved_conflicts=tuple(graph_reasons),
                expected_source_generation=(
                    receipt.source_generation if receipt is not None else None
                ),
            )
        except self._analysis_error_types as exc:
            raise ChangeAssessmentUnavailableError(
                "planned-change graph traversal is unavailable"
            ) from exc
        reasons = list(affected.incomplete_reasons)
        if self._graph_freshness_source is not None:
            latest_receipt = await self._resolve_graph_freshness(target_ref)
            if (
                receipt is None
                or latest_receipt is None
                or latest_receipt.receipt_digest != receipt.receipt_digest
            ):
                reasons.append("graph_changed_during_assessment")
        if affected.truncated:
            reasons.append("impact_truncated")
        if not affected.protected_services:
            reasons.append("service_mapping_missing")
        if not affected.protected_objectives:
            reasons.append("objective_mapping_missing")
        if len(affected.all_resource_ids) > self._max_affected_resources:
            reasons.append("affected_resource_cap_exceeded")
        if str(change.get("intent_kind") or "") == "planned":
            if not str(change.get("desired_state_digest") or "").strip():
                reasons.append("desired_state_digest_missing")
            if not str(change.get("plan_receipt_ref") or "").strip():
                reasons.append("plan_receipt_missing")
        normalized_reasons = tuple(sorted(set(reasons)))
        evidence_digest = _assessment_digest(
            change_id=change_id,
            correlation_id=correlation_id,
            target_ref=target_ref,
            occurred_at=occurred_at,
            affected=affected,
            graph_freshness_receipt=receipt,
            reasons=normalized_reasons,
        )
        return ChangeAssessment(
            change_id=change_id,
            correlation_id=correlation_id,
            target_ref=target_ref,
            occurred_at=occurred_at,
            affected_set=affected,
            graph_freshness_receipt=receipt,
            review_required=bool(normalized_reasons),
            reasons=normalized_reasons,
            evidence_digest=evidence_digest,
        )

    async def _resolve_graph_freshness(
        self,
        target_ref: str,
    ) -> GraphFreshnessReceipt | None:
        if self._graph_freshness_source is None:
            return None
        try:
            return await self._graph_freshness_source.resolve(target_ref=target_ref)
        except self._analysis_error_types as exc:
            raise ChangeAssessmentUnavailableError(
                "planned-change graph freshness source is unavailable"
            ) from exc


def _required_text(value: Mapping[str, Any], name: str) -> str:
    resolved = str(value.get(name) or "").strip()
    if not resolved:
        raise ValueError(f"change {name} MUST be non-empty")
    return resolved


def _required_datetime(value: Mapping[str, Any], name: str) -> datetime:
    raw = _required_text(value, name)
    try:
        resolved = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"change {name} MUST be RFC 3339") from exc
    if resolved.tzinfo is None:
        raise ValueError(f"change {name} MUST be timezone-aware")
    return resolved


def _assessment_digest(
    *,
    change_id: str,
    correlation_id: str,
    target_ref: str,
    occurred_at: datetime,
    affected: AffectedSet,
    graph_freshness_receipt: GraphFreshnessReceipt | None,
    reasons: tuple[str, ...],
) -> str:
    material = {
        "change_id": change_id,
        "correlation_id": correlation_id,
        "target_ref": target_ref,
        "occurred_at": occurred_at.isoformat(),
        "affected_resource_ids": affected.all_resource_ids,
        "protected_services": affected.protected_services,
        "protected_objectives": affected.protected_objectives,
        "control_dependencies": affected.control_dependencies,
        "graph_revision": affected.graph_revision,
        "graph_freshness_receipt": (
            _graph_freshness_mapping(graph_freshness_receipt)
            if graph_freshness_receipt is not None
            else None
        ),
        "reasons": reasons,
    }
    encoded = json.dumps(material, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_graph_freshness_receipt(
    *,
    ontology_release_digest: str,
    target_ref: str,
    source_generation: str,
    graph_revision: str,
    observed_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
    complete: bool,
    truncated: bool,
    conflicts: tuple[str, ...] = (),
) -> GraphFreshnessReceipt:
    """Build one content-addressed no-authority freshness receipt."""

    normalized_conflicts = tuple(sorted(set(conflicts)))
    return GraphFreshnessReceipt(
        receipt_digest=_graph_freshness_digest_fields(
            ontology_release_digest=ontology_release_digest,
            target_ref=target_ref,
            source_generation=source_generation,
            graph_revision=graph_revision,
            observed_at=observed_at,
            recorded_at=recorded_at,
            valid_until=valid_until,
            complete=complete,
            truncated=truncated,
            conflicts=normalized_conflicts,
            source_identity="postgres.inventory_active",
            verification_method="authoritative_state_store_read",
            execution_authority=False,
        ),
        ontology_release_digest=ontology_release_digest,
        target_ref=target_ref,
        source_generation=source_generation,
        graph_revision=graph_revision,
        observed_at=observed_at,
        recorded_at=recorded_at,
        valid_until=valid_until,
        complete=complete,
        truncated=truncated,
        conflicts=normalized_conflicts,
    )


def _graph_freshness_reasons(
    receipt: GraphFreshnessReceipt | None,
    *,
    expected_release: str | None,
    target_ref: str,
    evaluated_at: datetime,
    max_graph_age: timedelta,
) -> tuple[str, ...]:
    if receipt is None:
        return ("graph_freshness_receipt_unavailable",)
    reasons: list[str] = []
    if receipt.target_ref.casefold() != target_ref.casefold():
        reasons.append("graph_target_mismatch")
    if expected_release is None or receipt.ontology_release_digest != expected_release:
        reasons.append("graph_release_mismatch")
    if receipt.observed_at > evaluated_at or receipt.recorded_at > evaluated_at:
        reasons.append("graph_time_invalid")
    if evaluated_at > receipt.valid_until or evaluated_at - receipt.observed_at > max_graph_age:
        reasons.append("graph_stale")
    if not receipt.complete:
        reasons.append("graph_incomplete")
    if receipt.truncated:
        reasons.append("graph_truncated")
    reasons.extend(receipt.conflicts)
    return tuple(sorted(set(reasons)))


def _graph_freshness_mapping(receipt: GraphFreshnessReceipt) -> dict[str, object]:
    return {
        "receipt_digest": receipt.receipt_digest,
        "ontology_release_digest": receipt.ontology_release_digest,
        "target_ref": receipt.target_ref,
        "source_generation": receipt.source_generation,
        "graph_revision": receipt.graph_revision,
        "observed_at": receipt.observed_at.isoformat(),
        "recorded_at": receipt.recorded_at.isoformat(),
        "valid_until": receipt.valid_until.isoformat(),
        "complete": receipt.complete,
        "truncated": receipt.truncated,
        "conflicts": list(receipt.conflicts),
        "source_identity": receipt.source_identity,
        "verification_method": receipt.verification_method,
        "execution_authority": False,
    }


def _graph_freshness_digest(receipt: GraphFreshnessReceipt) -> str:
    return _graph_freshness_digest_fields(
        ontology_release_digest=receipt.ontology_release_digest,
        target_ref=receipt.target_ref,
        source_generation=receipt.source_generation,
        graph_revision=receipt.graph_revision,
        observed_at=receipt.observed_at,
        recorded_at=receipt.recorded_at,
        valid_until=receipt.valid_until,
        complete=receipt.complete,
        truncated=receipt.truncated,
        conflicts=receipt.conflicts,
        source_identity=receipt.source_identity,
        verification_method=receipt.verification_method,
        execution_authority=receipt.execution_authority,
    )


def _graph_freshness_digest_fields(
    *,
    ontology_release_digest: str,
    target_ref: str,
    source_generation: str,
    graph_revision: str,
    observed_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
    complete: bool,
    truncated: bool,
    conflicts: tuple[str, ...],
    source_identity: str,
    verification_method: str,
    execution_authority: bool,
) -> str:
    material = {
        "ontology_release_digest": ontology_release_digest,
        "target_ref": target_ref,
        "source_generation": source_generation,
        "graph_revision": graph_revision,
        "observed_at": observed_at.isoformat(),
        "recorded_at": recorded_at.isoformat(),
        "valid_until": valid_until.isoformat(),
        "complete": complete,
        "truncated": truncated,
        "conflicts": list(conflicts),
        "source_identity": source_identity,
        "verification_method": verification_method,
        "execution_authority": execution_authority,
    }
    encoded = json.dumps(material, separators=(",", ":"), sort_keys=True).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "build_graph_freshness_receipt",
    "ChangeAssessment",
    "ChangeAssessmentService",
    "ChangeAssessmentUnavailableError",
    "GraphFreshnessReceipt",
    "GraphFreshnessReceiptSource",
]
