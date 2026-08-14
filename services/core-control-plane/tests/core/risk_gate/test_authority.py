"""Unified execution-authority pipeline (feature -> table -> ceiling)."""

from __future__ import annotations

from pathlib import Path

from fdai.core.risk_gate.authority import evaluate_execution_authority
from fdai.core.risk_gate.ceiling import AxisLevel
from fdai.core.risk_gate.live_probe import LiveProbeObservation
from fdai.core.risk_gate.risk_table import (
    FeatureVector,
    load_risk_table,
    load_risk_table_from_mapping,
)
from fdai.shared.contracts.models import (
    ActionBlastRadius,
    ActionInterface,
    Autonomy,
    BlastRadiusComputation,
    BlastRadiusScope,
    CeilingByTier,
    CeilingRole,
    OntologyActionType,
    Operation,
    PromotionGate,
    RollbackKind,
    Tier,
    TierCeiling,
)
from fdai.shared.providers.blast_probe import ProbeVerdict

REPO_ROOT = Path(__file__).resolve().parents[5]
TABLE_PATH = REPO_ROOT / "rule-catalog" / "risk-classification.yaml"


def _table():  # type: ignore[no-untyped-def]
    return load_risk_table(TABLE_PATH)


def _low_risk_at(*, ceiling: CeilingByTier | None = None) -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name="remediate.tag-add",
        version="1.0.0",
        operation=Operation.TAG,
        interfaces=[ActionInterface.CONTROL_PLANE, ActionInterface.IDEMPOTENT_BY_KEY],
        rollback_contract=RollbackKind.PR_REVERT,
        irreversible=False,
        promotion_gate=PromotionGate(
            min_shadow_days=1, min_samples=1, min_accuracy=0.9, max_policy_escapes=0
        ),
        blast_radius=ActionBlastRadius(
            computation=BlastRadiusComputation.STATIC_ENUM,
            static_bucket=BlastRadiusScope.RESOURCE,
        ),
        ceiling_by_tier=ceiling,
    )


def _destructive_at() -> OntologyActionType:
    return OntologyActionType(
        schema_version="1.0.0",
        name="remediate.remove-orphan-resource",
        version="1.0.0",
        operation=Operation.DELETE,
        interfaces=[ActionInterface.CONTROL_PLANE],
        rollback_contract=RollbackKind.SNAPSHOT_RESTORE,
        promotion_gate=PromotionGate(
            min_shadow_days=1, min_samples=1, min_accuracy=0.9, max_policy_escapes=0
        ),
        blast_radius=ActionBlastRadius(
            computation=BlastRadiusComputation.STATIC_ENUM,
            static_bucket=BlastRadiusScope.RESOURCE,
        ),
    )


def test_low_risk_action_is_auto_end_to_end() -> None:
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=50.0,
    )
    assert d.decision == "auto"
    assert d.is_auto is True
    assert d.table_verdict.rule_id == "auto-low-risk"


def test_system_degraded_flips_auto_to_shadow() -> None:
    """The advertised fail-toward-safety wiring (csp-neutrality.md 4): the same
    low-risk action that is ``auto`` end-to-end when healthy is capped to
    ``shadow`` when the control plane is DEGRADED - a failing critical
    dependency MUST NOT drive an enforce-mode mutation."""
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=50.0,
        system_degraded=True,
    )
    assert d.decision == "shadow"
    assert d.is_auto is False
    assert d.resolved_ceiling.winning_axis == "system_health"


def test_kill_switch_flips_auto_to_shadow() -> None:
    """The operator emergency stop (security-and-identity.md): the same low-risk
    action that is ``auto`` end-to-end flips to ``shadow`` when the global
    kill-switch is engaged, halting all auto-execution."""
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=50.0,
        kill_switch_engaged=True,
    )
    assert d.decision == "shadow"
    assert d.is_auto is False
    assert d.resolved_ceiling.winning_axis == "kill_switch"


def test_destructive_action_is_hil() -> None:
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_destructive_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=10.0,
    )
    assert d.decision == "hil"
    assert d.requires_hil is True
    assert d.table_verdict.rule_id == "hil-destructive"


def test_policy_violation_denies_end_to_end() -> None:
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        policy_violation=True,
    )
    assert d.decision == "deny"
    assert d.is_denied is True
    assert d.resolved_ceiling.winning_axis == "risk_table"


def test_prod_downgrades_to_hil_via_table() -> None:
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="prod",
        cost_impact_monthly=50.0,
        allowlist_prod_auto=False,
    )
    assert d.decision == "hil"
    assert d.table_verdict.rule_id == "hil-prod"


def test_ceiling_lowers_a_table_auto_via_role_axis() -> None:
    # Table says auto (low risk) but the role ceiling requires Owner and the
    # caller is a Reader -> the role axis denies. Proves the six-axis ceiling
    # can only ever lower the table baseline, never the reverse.
    ceiling = CeilingByTier(
        t0=TierCeiling(max_autonomy=Autonomy.ENFORCE_AUTO, min_role=CeilingRole.OWNER)
    )
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(ceiling=ceiling),
        table=_table(),
        principal_role=CeilingRole.READER,
        environment="non-prod",
        cost_impact_monthly=50.0,
    )
    assert d.table_verdict.rule_id == "auto-low-risk"  # table still said auto
    assert d.decision == "deny"  # but the ceiling lowered it
    assert d.resolved_ceiling.winning_axis == "role"


def test_t2_tier_forces_shadow() -> None:
    d = evaluate_execution_authority(
        tier=Tier.T2,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=CeilingRole.OWNER,
        environment="non-prod",
        cost_impact_monthly=50.0,
    )
    assert d.decision == "shadow"
    assert d.final_level is AxisLevel.SHADOW_ONLY


def test_audit_dict_shape() -> None:
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_destructive_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=10.0,
    )
    audit = d.as_audit_dict()
    assert audit["decision"] == "hil"
    assert audit["matched_rule_id"] == "hil-destructive"
    assert "resolved_ceiling" in audit
    assert set(audit["resolved_ceiling"]["axes"]) == {
        "risk_table",
        "tier",
        "ceiling",
        "static_blast",
        "live_blast",
        "role",
        "env",
    }


def test_environment_normalization_feeds_both_axes() -> None:
    # "non-prod" (table word) maps to the ceiling's "non_prod"; a prod word
    # reaches the table hil-prod rule. Both axes see one classification.
    d_prod = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="prod",
        cost_impact_monthly=50.0,
    )
    assert d_prod.feature_vector.environment == "prod"
    assert d_prod.decision == "hil"


def test_audit_dict_serializes_the_exact_feature_vector_and_catalog_version() -> None:
    table = _table()
    d = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=table,
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=50.0,
    )
    audit = d.as_audit_dict()
    assert audit["catalog_version"] == table.version
    assert audit["feature_vector"] == d.feature_vector.as_lookup()
    # Every declared dimension is present, including the unset ones, so a
    # replay never has to guess whether a signal was absent or dropped.
    assert set(audit["feature_vector"]) == set(FeatureVector().as_lookup())
    assert audit["feature_vector"]["environment"] == "non-prod"
    assert audit["feature_vector"]["cost_impact_monthly"] == 50.0
    assert audit["feature_vector"]["verifier_confidence"] is None


def test_recorded_payload_replays_against_its_own_catalog_version() -> None:
    # A historical decision must stay reconstructable after the table changes.
    audit = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_low_risk_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        cost_impact_monthly=50.0,
    ).as_audit_dict()

    historical = _table()
    tightened = load_risk_table_from_mapping(
        {
            "version": "9.9.9",
            "owner_group": "aw-owners",
            "rules": [
                {
                    "id": "hil-all-non-prod",
                    "if": {"environment": "non-prod"},
                    "decision": "hil",
                    "reason": "tightened after the original decision",
                },
                {"id": "default-hil", "default": "hil", "reason": "fail toward safety"},
            ],
        }
    )
    replayed_vector = FeatureVector(**audit["feature_vector"])

    assert audit["catalog_version"] == historical.version != tightened.version
    replayed = historical.evaluate(replayed_vector)
    assert replayed.rule_id == audit["matched_rule_id"]
    assert replayed.decision.value == audit["decision"]
    # The same recorded signals against the newer table decide differently,
    # so the version stamp is what keeps the replay honest.
    assert tightened.evaluate(replayed_vector).rule_id == "hil-all-non-prod"


def _probe_at() -> OntologyActionType:
    return _low_risk_at().model_copy(update={"live_probe_ref": "vm_traffic_last_5m"})


def test_audit_records_every_ceiling_input_the_feature_vector_omits() -> None:
    observation = LiveProbeObservation(
        probe_id="vm_traffic_last_5m",
        verdict=ProbeVerdict.ACTIVE,
        age_seconds=5.0,
        max_age_seconds=60.0,
    )
    audit = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_probe_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        live_probe_observation=observation,
        live_probe_failure_streak=1,
        graph_affected=3,
        system_degraded=True,
        kill_switch_engaged=False,
    ).as_audit_dict()

    inputs = audit["ceiling_inputs"]
    assert inputs["live_probe"] == {
        "probe_id": "vm_traffic_last_5m",
        "verdict": "active",
        "degraded": False,
        "age_seconds": 5.0,
        "max_age_seconds": 60.0,
    }
    assert inputs["live_probe_failure_streak"] == 1
    assert inputs["graph_affected"] == 3
    assert inputs["system_degraded"] is True
    assert inputs["kill_switch_engaged"] is False


def test_recorded_probe_reading_replays_without_re_querying_the_probe() -> None:
    original = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_probe_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        live_probe_observation=LiveProbeObservation(
            probe_id="vm_traffic_last_5m",
            verdict=ProbeVerdict.QUIET,
            age_seconds=5.0,
            max_age_seconds=60.0,
        ),
    )
    recorded = original.as_audit_dict()["ceiling_inputs"]["live_probe"]

    replayed = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_probe_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
        live_probe_observation=LiveProbeObservation(
            probe_id=recorded["probe_id"],
            verdict=ProbeVerdict(recorded["verdict"]),
            degraded=recorded["degraded"],
            age_seconds=recorded["age_seconds"],
            max_age_seconds=recorded["max_age_seconds"],
        ),
    )

    assert replayed.as_audit_dict() == original.as_audit_dict()
    # Losing the recorded reading must not replay as if the probe were quiet:
    # an unavailable probe lowers the Axis-E contribution to HIL.
    without_reading = evaluate_execution_authority(
        tier=Tier.T0,
        action_type=_probe_at(),
        table=_table(),
        principal_role=None,
        environment="non-prod",
    )
    original_axis = original.as_audit_dict()["resolved_ceiling"]["axes"]["live_blast"]
    blind_axis = without_reading.as_audit_dict()["resolved_ceiling"]["axes"]["live_blast"]
    assert original_axis["level"] == "enforce_auto"
    assert blind_axis["level"] == "enforce_hil"
    assert "unavailable" in blind_axis["reason"]
