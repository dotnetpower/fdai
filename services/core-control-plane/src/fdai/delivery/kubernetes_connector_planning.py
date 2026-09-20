"""Deterministic least-change selection of supported observer deployment profiles."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fdai_service_contracts.cluster_connector import connector_time
from fdai_service_contracts.compatibility import canonical_digest
from fdai_service_contracts.observer_deployment import (
    ConstraintBlocker,
    ConstraintName,
    InstallMethod,
    ObserverDeploymentCandidate,
    ObserverDeploymentContext,
    ObserverDeploymentProposal,
)
from pydantic import TypeAdapter

_COMMON: tuple[ConstraintName, ...] = (
    "azure_policy",
    "kubernetes_read",
    "admission",
    "capacity",
    "artifact_verified",
    "persistent_storage",
    "mtls_gateway",
    "ownership_known",
)
_METHODS: dict[InstallMethod, tuple[ConstraintName, ...]] = {
    "gitops": ("gitops_authorized",),
    "existing_host": ("existing_host_authorized",),
    "managed_host": (
        "managed_host_authorized",
        "managed_host_budget",
        "managed_host_plan_feasible",
    ),
    "run_command": ("run_command_authorized",),
}
_EGRESS: tuple[tuple[Literal["private", "public"], ConstraintName], ...] = (
    ("private", "private_egress"),
    ("public", "public_egress"),
)


def propose_observer_deployment(
    context: ObserverDeploymentContext, *, now: datetime
) -> ObserverDeploymentProposal:
    """Rank only fully evidenced supported combinations; never turn unknown into permission."""
    context = ObserverDeploymentContext.model_validate_json(context.model_dump_json())
    cutoff = connector_time(now)
    if not context.observed_at <= cutoff < context.expires_at:
        raise ValueError("observer deployment context is future or expired")
    evidence = {fact.name: fact for fact in context.facts}
    candidates: list[ObserverDeploymentCandidate] = []
    if context.private_cluster:
        for method, required in _METHODS.items():
            for egress, transport in _EGRESS:
                requirements: tuple[ConstraintName, ...] = (*_COMMON, *required, transport)
                blockers: list[ConstraintBlocker] = []
                missing: list[ConstraintName] = []
                if context.existing_method is not None and method != context.existing_method:
                    blockers.append("existing_owner_preserved")
                if context.requested_method is not None and method != context.requested_method:
                    blockers.append("operator_method_pinned")
                if method == "run_command" and context.requested_method != "run_command":
                    blockers.append("run_command_requires_explicit_selection")
                for name in requirements:
                    fact = evidence.get(name)
                    if (
                        fact is None
                        or not fact.observed_at <= cutoff < fact.expires_at
                        or fact.state == "unknown"
                    ):
                        missing.append(name)
                    elif fact.state == "denied":
                        blockers.append(name)
                candidates.append(
                    ObserverDeploymentCandidate(
                        method=method,
                        egress=egress,
                        state="blocked" if blockers else "unknown" if missing else "eligible",
                        blockers=tuple(sorted(set(blockers))),
                        missing=tuple(sorted(set(missing))),
                    )
                )
    selected = next((item for item in candidates if item.state == "eligible"), None)
    status = (
        "not_applicable"
        if not context.private_cluster
        else "ready_for_review"
        if selected is not None
        else "needs_evidence"
        if any(item.state == "unknown" for item in candidates)
        else "blocked"
    )
    expiry = min(
        [
            context.expires_at,
            *(
                fact.expires_at
                for fact in context.facts
                if fact.observed_at <= cutoff < fact.expires_at
            ),
        ]
    )
    normalized_context = context.model_dump(mode="json")
    normalized_context["facts"] = sorted(normalized_context["facts"], key=lambda item: item["name"])
    values = {
        "schema_version": "1.0.0",
        "target_ref": context.target_ref,
        "context_digest": canonical_digest(normalized_context),
        "evaluated_at": cutoff,
        "expires_at": expiry,
        "status": status,
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        "recommended": selected.model_dump(mode="json") if selected else None,
        "approval_required": True,
        "execution_authority": False,
    }
    clock_codec = TypeAdapter(datetime)
    serialized = {
        **values,
        "evaluated_at": clock_codec.dump_python(cutoff, mode="json"),
        "expires_at": clock_codec.dump_python(expiry, mode="json"),
    }
    return ObserverDeploymentProposal.model_validate(
        {**values, "proposal_digest": canonical_digest(serialized)}
    )
