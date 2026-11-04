"""Principal-scoped Operator Decision Queue projection reader and view builder."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal

import fdai_service_contracts as sc
from pydantic import Field, model_validator

from fdai_operator_service.families.operations import ProjectionQuery, ProjectionUnavailableError

FetchAll = Callable[[str, tuple[object, ...]], Awaitable[list[dict[str, Any]]]]


def decision_queue_operator_key(principal_id: str, scope_ref: str = "global") -> str:
    """Return the shared StateStore key written by Core's DecisionQueue producer."""

    clean_principal = principal_id.strip()
    clean_scope = scope_ref.strip()
    if not clean_principal or not clean_scope or "\x00" in clean_principal or "\x00" in clean_scope:
        raise ProjectionUnavailableError("Decision queue principal_id or scope_ref is malformed")
    digest = hashlib.sha256(f"{clean_principal}\x00{clean_scope}".encode()).hexdigest()
    return f"decision-queue:projection:v1:{digest}"


def catalog_knowledge_operator_key(scope_ref: str = "global") -> str:
    """Return the shared StateStore key for catalog, control, and cloud reference summaries."""

    clean_scope = scope_ref.strip()
    if not clean_scope or "\x00" in clean_scope:
        raise ProjectionUnavailableError("Catalog knowledge scope_ref is malformed")
    digest = hashlib.sha256(clean_scope.encode()).hexdigest()
    return f"catalog-knowledge:projection:v1:{digest}"


class DecisionQueueOperatorCard(sc.ContractBase):
    """Read-only Operator card for one queued decision."""

    rank: int = Field(ge=1)
    case_id: str = Field(min_length=1, max_length=256)
    process_id: str | None = None
    target_resource_ref: str = Field(min_length=1, max_length=512)
    recommended_action_type: str = Field(min_length=1, max_length=256)
    cost_badge: str = Field(min_length=1, max_length=128)
    blast_radius_tier: str = Field(min_length=1, max_length=32)
    change_risk_tier: str = Field(min_length=1, max_length=32)
    uncertainty: float = Field(ge=0.0, le=1.0)
    quorum_label: str = Field(min_length=1, max_length=128)
    approval_status: str = Field(min_length=1, max_length=64)
    evidence_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _validate_finite(self) -> DecisionQueueOperatorCard:
        if not math.isfinite(self.uncertainty):
            raise ValueError("DecisionQueueOperatorCard.uncertainty MUST be finite")
        return self


class DecisionQueueOperatorProjection(sc.ContractBase):
    """Authenticated, read-only Operator Decision Queue response."""

    type: Literal["decision-queue.operator-projection"] = "decision-queue.operator-projection"
    schema_version: Literal["1.0.0"] = "1.0.0"
    read_only: Literal[True] = True
    authority: Literal["none"] = "none"
    state: Literal["complete", "unavailable"]
    principal_id: str = Field(min_length=1, max_length=512)
    scope_ref: str = Field(min_length=1, max_length=512)
    ranking_currency: str | None = None
    total_pending_count: int = Field(ge=0)
    cards: tuple[DecisionQueueOperatorCard, ...] = ()
    projection_digest: str = ""


async def read_decision_queue_operator_projection(
    *,
    fetch_all: FetchAll,
    query: ProjectionQuery,
) -> Mapping[str, object]:
    """Read and build the authenticated Operator Decision Queue projection from state_kv."""

    if not query.principal_id.strip():
        raise PermissionError("Decision queue projection requires an authenticated principal")
    raw_scope = query.params.get("scope_ref")
    scope_ref = (raw_scope[-1] if raw_scope else "global").strip()
    if not scope_ref or len(scope_ref) > 512 or "\x00" in scope_ref:
        raise ProjectionUnavailableError("Decision queue scope_ref is malformed")
    key = decision_queue_operator_key(query.principal_id, scope_ref)
    rows = await fetch_all("SELECT value FROM state_kv WHERE key = %s", (key,))
    if not rows or not isinstance(rows[0].get("value"), Mapping):
        return DecisionQueueOperatorProjection(
            state="unavailable",
            principal_id=query.principal_id.strip(),
            scope_ref=scope_ref,
            total_pending_count=0,
        ).model_dump(mode="json")
    raw = dict(rows[0]["value"])
    raw_items = raw.get("items")
    if not isinstance(raw_items, list):
        return DecisionQueueOperatorProjection(
            state="unavailable",
            principal_id=query.principal_id.strip(),
            scope_ref=scope_ref,
            total_pending_count=0,
        ).model_dump(mode="json")
    cards: list[DecisionQueueOperatorCard] = []
    pending_count = 0
    for idx, item in enumerate(raw_items, start=1):
        if not isinstance(item, Mapping):
            continue
        ctrl = item.get("approval_control")
        ctrl_map = ctrl if isinstance(ctrl, Mapping) else {}
        status = str(ctrl_map.get("approval_status") or "pending")
        if status == "pending":
            pending_count += 1
        amt = item.get("cost_of_delay_amount")
        cur = item.get("cost_of_delay_currency")
        cost_badge = f"{amt} {cur}" if amt is not None and cur else "Unpriced"
        role = str(ctrl_map.get("required_role") or "owner")
        quorum = int(ctrl_map.get("quorum") or 1)
        cards.append(
            DecisionQueueOperatorCard(
                rank=idx,
                case_id=str(item.get("case_id") or f"case-{idx}"),
                process_id=(
                    str(item["process_id"]) if item.get("process_id") is not None else None
                ),
                target_resource_ref=str(item.get("target_resource_ref") or "unknown"),
                recommended_action_type=str(item.get("recommended_action_type") or "no-op"),
                cost_badge=cost_badge,
                blast_radius_tier=str(item.get("blast_radius_tier") or "unknown"),
                change_risk_tier=str(item.get("change_risk_tier") or "unknown"),
                uncertainty=float(item.get("uncertainty") or 0.0),
                quorum_label=f"{role} (quorum {quorum})",
                approval_status=status,
                evidence_refs=tuple(str(r) for r in (item.get("evidence_refs") or ())),
            )
        )
    return DecisionQueueOperatorProjection(
        state="complete",
        principal_id=query.principal_id.strip(),
        scope_ref=scope_ref,
        ranking_currency=(
            str(raw["ranking_currency"]) if raw.get("ranking_currency") is not None else None
        ),
        total_pending_count=pending_count,
        cards=tuple(cards),
        projection_digest=str(raw.get("projection_digest") or ""),
    ).model_dump(mode="json")


class CatalogKnowledgeOperatorProjection(sc.ContractBase):
    """Read-only Operator projection for workflows, rules/controls, and cloud reference topics."""

    type: Literal["catalog-knowledge.operator-projection"] = "catalog-knowledge.operator-projection"
    schema_version: Literal["1.0.0"] = "1.0.0"
    read_only: Literal[True] = True
    authority: Literal["none"] = "none"
    state: Literal["complete", "unavailable"]
    principal_id: str = Field(min_length=1, max_length=512)
    scope_ref: str = Field(min_length=1, max_length=512)
    workflow_count: int = Field(ge=0)
    business_scenario_count: int = Field(ge=0)
    rule_and_control_count: int = Field(ge=0)
    cloud_reference_topic_count: int = Field(ge=0)
    highlighted_topics: tuple[str, ...] = ()
    corpus_digest: str = ""


async def read_catalog_knowledge_operator_projection(
    *,
    fetch_all: FetchAll,
    query: ProjectionQuery,
) -> Mapping[str, object]:
    """Read the authenticated Catalog & Cloud Reference Knowledge projection from state_kv."""

    if not query.principal_id.strip():
        raise PermissionError("Catalog knowledge projection requires an authenticated principal")
    raw_scope = query.params.get("scope_ref")
    scope_ref = (raw_scope[-1] if raw_scope else "global").strip()
    key = catalog_knowledge_operator_key(scope_ref)
    rows = await fetch_all("SELECT value FROM state_kv WHERE key = %s", (key,))
    if not rows or not isinstance(rows[0].get("value"), Mapping):
        return CatalogKnowledgeOperatorProjection(
            state="unavailable",
            principal_id=query.principal_id.strip(),
            scope_ref=scope_ref,
            workflow_count=0,
            business_scenario_count=0,
            rule_and_control_count=0,
            cloud_reference_topic_count=0,
        ).model_dump(mode="json")
    raw = dict(rows[0]["value"])
    return CatalogKnowledgeOperatorProjection(
        state="complete",
        principal_id=query.principal_id.strip(),
        scope_ref=scope_ref,
        workflow_count=int(raw.get("workflow_count") or 0),
        business_scenario_count=int(raw.get("business_scenario_count") or 0),
        rule_and_control_count=int(raw.get("rule_and_control_count") or 0),
        cloud_reference_topic_count=int(raw.get("cloud_reference_topic_count") or 0),
        highlighted_topics=tuple(str(t) for t in (raw.get("highlighted_topics") or ())),
        corpus_digest=str(raw.get("corpus_digest") or ""),
    ).model_dump(mode="json")


__all__ = [
    "CatalogKnowledgeOperatorProjection",
    "DecisionQueueOperatorCard",
    "DecisionQueueOperatorProjection",
    "catalog_knowledge_operator_key",
    "decision_queue_operator_key",
    "read_catalog_knowledge_operator_projection",
    "read_decision_queue_operator_projection",
]
