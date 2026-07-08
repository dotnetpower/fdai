"""FeatureVector extraction from an ActionType + context."""

from __future__ import annotations

from pathlib import Path

import pytest

from fdai.core.risk_gate.feature import feature_vector_from
from fdai.core.risk_gate.risk_table import RiskLevel, load_risk_table
from fdai.shared.contracts.models import (
    ActionBlastRadius,
    ActionInterface,
    BlastRadiusComputation,
    BlastRadiusScope,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TABLE_PATH = REPO_ROOT / "rule-catalog" / "risk-classification.yaml"


def _at(
    *,
    operation: Operation = Operation.TAG,
    interfaces: list[ActionInterface] | None = None,
    irreversible: bool = False,
    rollback: RollbackKind = RollbackKind.PR_REVERT,
    blast: ActionBlastRadius | None = None,
) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name="ops.example",
        version="1.0.0",
        operation=operation,
        interfaces=interfaces or [ActionInterface.CONTROL_PLANE],
        rollback_contract=rollback,
        irreversible=irreversible,
        promotion_gate=PromotionGate(
            min_shadow_days=1, min_samples=1, min_accuracy=0.9, max_policy_escapes=0
        ),
        blast_radius=blast,
    )


@pytest.mark.parametrize(
    "operation",
    [Operation.DELETE, Operation.DROP, Operation.PURGE, Operation.DETACH],
)
def test_destructive_operations_flagged(operation: Operation) -> None:
    fv = feature_vector_from(_at(operation=operation), environment="non-prod")
    assert fv.destructive is True


@pytest.mark.parametrize("operation", [Operation.TAG, Operation.UPDATE, Operation.ENABLE])
def test_non_destructive_operations_not_flagged(operation: Operation) -> None:
    fv = feature_vector_from(_at(operation=operation), environment="non-prod")
    assert fv.destructive is False


def test_data_plane_interface_flagged() -> None:
    fv = feature_vector_from(
        _at(interfaces=[ActionInterface.DATA_PLANE_MUTATING]), environment="non-prod"
    )
    assert fv.data_plane_touched is True


def test_control_plane_only_not_data_plane() -> None:
    fv = feature_vector_from(_at(), environment="non-prod")
    assert fv.data_plane_touched is False


def test_blast_radius_from_static_bucket() -> None:
    blast = ActionBlastRadius(
        computation=BlastRadiusComputation.STATIC_ENUM,
        static_bucket=BlastRadiusScope.RESOURCE_GROUP,
    )
    fv = feature_vector_from(_at(blast=blast), environment="non-prod")
    assert fv.blast_radius == "resource_group"


def test_blast_radius_none_when_undeclared() -> None:
    fv = feature_vector_from(_at(), environment="non-prod")
    assert fv.blast_radius is None


def test_irreversible_and_reversible_are_complementary() -> None:
    fv_irr = feature_vector_from(_at(irreversible=True), environment="non-prod")
    assert fv_irr.irreversible is True
    assert fv_irr.reversible is False
    fv_rev = feature_vector_from(_at(irreversible=False), environment="non-prod")
    assert fv_rev.irreversible is False
    assert fv_rev.reversible is True


def test_rollback_path_passthrough() -> None:
    fv = feature_vector_from(_at(rollback=RollbackKind.PITR), environment="non-prod")
    assert fv.rollback_path == "pitr"


def test_context_dimensions_passthrough() -> None:
    fv = feature_vector_from(
        _at(),
        environment="prod",
        policy_violation=True,
        verifier_confidence=0.7,
        cost_impact_monthly=250.0,
        graph_stale=True,
        cross_resource_impact=4,
        allowlist_prod_auto=True,
    )
    assert fv.environment == "prod"
    assert fv.policy_violation is True
    assert fv.verifier_confidence == 0.7
    assert fv.cost_impact_monthly == 250.0
    assert fv.graph_stale is True
    assert fv.cross_resource_impact == 4
    assert fv.allowlist_prod_auto is True


def test_extracted_vector_feeds_the_table_end_to_end() -> None:
    """A destructive ActionType flows through extraction to a HIL verdict."""
    table = load_risk_table(TABLE_PATH)
    fv = feature_vector_from(_at(operation=Operation.PURGE), environment="non-prod")
    verdict = table.evaluate(fv)
    assert verdict.decision is RiskLevel.HIL
    assert verdict.rule_id == "hil-destructive"


def test_every_operation_is_classified_destructive_or_not() -> None:
    """Every Operation verb MUST be classified exactly once as destructive
    or non-destructive. A new verb added to the enum without a decision
    here would silently default to non-destructive and escape the
    risk-classification `destructive` gate (action-ontology critique #13)."""

    from fdai.core.risk_gate.feature import _DESTRUCTIVE_OPS, _NON_DESTRUCTIVE_OPS

    all_ops = set(Operation)
    classified = _DESTRUCTIVE_OPS | _NON_DESTRUCTIVE_OPS
    unclassified = all_ops - classified
    assert not unclassified, (
        f"unclassified Operation verbs: {sorted(o.value for o in unclassified)}"
    )
    overlap = _DESTRUCTIVE_OPS & _NON_DESTRUCTIVE_OPS
    assert not overlap, f"Operation classified as both: {sorted(o.value for o in overlap)}"
    assert classified == all_ops

