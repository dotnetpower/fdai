"""FeatureVector extraction - the producer the risk table was missing.

Maps an :class:`~fdai.shared.contracts.models.OntologyActionType`
plus per-dispatch context into the :class:`FeatureVector` the
risk-classification table (:mod:`fdai.core.risk_gate.risk_table`)
evaluates. This is the codification of the "Classification Dimensions"
table in risk-classification.md - the mapping used to live only in the
doc, so the table had no real input source.

Pure function: no I/O. Signals the extractor cannot derive from the
ActionType itself (the verifier verdict, the environment classification,
the cost estimate, inventory freshness) are passed in by the caller, which
owns those subsystems.
"""

from __future__ import annotations

from fdai.core.risk_gate.risk_table import FeatureVector
from fdai.shared.contracts.models import (
    ActionInterface,
    OntologyActionType,
    Operation,
)

# Operations that are inherently destructive (risk-classification.md
# `destructive` dimension). Every Operation is classified EXACTLY ONCE as
# destructive or non-destructive so a new verb added to the Operation enum
# forces an explicit decision here - the completeness test in
# test_feature.py fails if a member is unclassified, instead of the verb
# silently defaulting to non-destructive and escaping the
# risk-classification `destructive` gate (action-ontology critique #13).
_DESTRUCTIVE_OPS: frozenset[Operation] = frozenset(
    {Operation.DELETE, Operation.DROP, Operation.PURGE, Operation.DETACH}
)
_NON_DESTRUCTIVE_OPS: frozenset[Operation] = frozenset(
    {
        Operation.CREATE,
        Operation.UPDATE,
        Operation.DISABLE,
        Operation.ENABLE,
        Operation.TAG,
        Operation.SCALE,
        Operation.RESTART,
        Operation.FAILOVER,
        Operation.ROTATE,
        Operation.REVERT,
        Operation.ATTACH,
        Operation.QUARANTINE,
    }
)


def feature_vector_from(
    action_type: OntologyActionType,
    *,
    environment: str,
    policy_violation: bool = False,
    verifier_confidence: float | None = None,
    cost_impact_monthly: float | None = None,
    graph_stale: bool | None = None,
    cross_resource_impact: int | None = None,
    allowlist_prod_auto: bool = False,
) -> FeatureVector:
    """Build the risk-table :class:`FeatureVector` for one ActionType.

    ActionType-derived dimensions (``destructive``, ``irreversible``,
    ``reversible``, ``blast_radius``, ``rollback_path``,
    ``data_plane_touched``) come straight from the ontology entry.
    Context dimensions (verifier verdict, environment, cost, inventory
    freshness, cross-resource impact, the prod-auto allowlist) are passed
    in because they belong to subsystems outside the ontology.
    """
    destructive = action_type.operation in _DESTRUCTIVE_OPS
    data_plane = ActionInterface.DATA_PLANE_MUTATING in action_type.interfaces
    blast_radius: str | None = None
    if action_type.blast_radius is not None and action_type.blast_radius.static_bucket is not None:
        blast_radius = action_type.blast_radius.static_bucket.value
    return FeatureVector(
        policy_violation=policy_violation,
        destructive=destructive,
        irreversible=action_type.irreversible,
        reversible=not action_type.irreversible,
        blast_radius=blast_radius,
        rollback_path=action_type.rollback_contract.value,
        environment=environment,
        data_plane_touched=data_plane,
        graph_stale=graph_stale,
        cross_resource_impact=cross_resource_impact,
        cost_impact_monthly=cost_impact_monthly,
        verifier_confidence=verifier_confidence,
        allowlist_prod_auto=allowlist_prod_auto,
    )


__all__ = ["feature_vector_from"]
