"""Contracts for the deterministic decision functions and the registry-backed gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fdai.core.ontology_platform.decision_functions import (
    BLAST_RADIUS_FUNCTION_NAME,
    CHANGE_RISK_FUNCTION_NAME,
    COST_OF_DELAY_FUNCTION_NAME,
    DECISION_PURPOSE,
    BlastRadiusEvidence,
    ChangeRiskEvidence,
    CostOfDelayEvidence,
    ImpactedResource,
    assess_blast_radius,
    assess_change_risk,
    assess_cost_of_delay,
    blast_radius_function,
    blast_radius_function_type,
    change_risk_function,
    change_risk_function_type,
    cost_of_delay_function,
    cost_of_delay_function_type,
    decision_function_types,
)
from fdai.core.ontology_platform.functions import (
    FunctionInvocationContext,
    OntologyFunctionRegistry,
)
from fdai.core.ontology_platform.operational_functions import operational_function_types
from fdai.core.ontology_platform.workflow_gate_reader import (
    GateTargetAnchorResolver,
    RegistryOntologyGateReader,
)
from fdai.core.workflow import OntologyFunctionGateEvaluator
from fdai.shared.ontology.release import build_ontology_release

_NOW = datetime(2026, 11, 4, tzinfo=UTC)


def _blast(*resources: ImpactedResource, complete: bool = True) -> BlastRadiusEvidence:
    return BlastRadiusEvidence(
        resources=resources,
        traversal_complete=complete,
        source_generation="generation-1",
        observed_at=_NOW,
    )


def _risk(**overrides: object) -> ChangeRiskEvidence:
    values: dict[str, object] = {
        "blast_radius_tier": "low",
        "change_window_active": True,
        "recent_failed_changes": 0,
        "rollback_tested": True,
        "dry_run_passed": True,
        "source_generation": "generation-1",
        "observed_at": _NOW,
    }
    values.update(overrides)
    return ChangeRiskEvidence(**values)  # type: ignore[arg-type]


def test_blast_radius_weighs_criticality_and_proximity() -> None:
    near = assess_blast_radius(
        _blast(
            ImpactedResource("a", 0, "low"),
            ImpactedResource("b", 1, "critical"),
            ImpactedResource("c", 1, "critical"),
        ),
        target_ref="a",
        max_tier="high",
    )
    far = assess_blast_radius(
        _blast(ImpactedResource("a", 0, "low"), ImpactedResource("b", 5, "critical")),
        target_ref="a",
        max_tier="high",
    )

    assert near["score"] == 6 + 2 * 8 * 5
    assert far["score"] == 6 + 8 * 1
    assert near["tier"] == "high"
    assert far["tier"] == "medium"
    assert near["affected_count"] == 2
    assert near["execution_authority"] is False
    assert near["mutation_authority"] is False


@pytest.mark.parametrize(
    ("max_tier", "satisfied"), [("low", False), ("medium", False), ("high", True)]
)
def test_blast_radius_gate_respects_the_configured_ceiling(max_tier: str, satisfied: bool) -> None:
    result = assess_blast_radius(
        _blast(ImpactedResource("a", 0, "high"), ImpactedResource("b", 1, "critical")),
        target_ref="a",
        max_tier=max_tier,
    )

    assert result["tier"] == "high"
    assert result["gate_satisfied"] is satisfied


def test_unreviewed_criticality_or_incomplete_traversal_is_unknown_and_shut() -> None:
    unreviewed = assess_blast_radius(
        _blast(ImpactedResource("a", 0, None)), target_ref="a", max_tier="high"
    )
    incomplete = assess_blast_radius(
        _blast(ImpactedResource("a", 0, "low"), complete=False), target_ref="a", max_tier="high"
    )

    for result in (unreviewed, incomplete):
        assert result["tier"] == "unknown"
        assert result["complete"] is False
        assert result["gate_satisfied"] is False
    assert unreviewed["reason_codes"] == ["criticality_unreviewed"]
    assert incomplete["reason_codes"] == ["traversal_incomplete"]


def test_blast_radius_rejects_duplicate_and_out_of_bound_evidence() -> None:
    with pytest.raises(ValueError, match="once"):
        assess_blast_radius(
            _blast(ImpactedResource("a", 0, "low"), ImpactedResource("a", 1, "low")),
            target_ref="a",
            max_tier="low",
        )
    with pytest.raises(ValueError, match="depth"):
        assess_blast_radius(_blast(ImpactedResource("a", 6, "low")), target_ref="a", max_tier="low")


def test_change_risk_adds_each_observed_hazard() -> None:
    safe = assess_change_risk(_risk(), target_ref="a", max_tier="low")
    hazardous = assess_change_risk(
        _risk(
            blast_radius_tier="critical",
            change_window_active=False,
            recent_failed_changes=9,
            rollback_tested=False,
            dry_run_passed=False,
        ),
        target_ref="a",
        max_tier="high",
    )

    assert (safe["points"], safe["tier"], safe["gate_satisfied"]) == (0, "low", True)
    assert hazardous["points"] == 6 + 3 + 3 + 3 + 2
    assert hazardous["tier"] == "critical"
    assert hazardous["gate_satisfied"] is False


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("blast_radius_tier", "blast_radius_unobserved"),
        ("change_window_active", "change_window_unobserved"),
        ("recent_failed_changes", "recent_failed_changes_unobserved"),
        ("rollback_tested", "rollback_tested_unobserved"),
        ("dry_run_passed", "dry_run_unobserved"),
    ],
)
def test_any_unobserved_change_risk_factor_is_unknown_and_shut(field: str, reason: str) -> None:
    result = assess_change_risk(_risk(**{field: None}), target_ref="a", max_tier="high")

    assert result["tier"] == "unknown"
    assert result["gate_satisfied"] is False
    assert result["reason_codes"] == [reason]


def test_cost_of_delay_prices_the_delay_and_gates_on_the_minimum() -> None:
    evidence = CostOfDelayEvidence(Decimal("12.5"), "USD", "basis-1", _NOW)

    opens = assess_cost_of_delay(
        evidence, target_ref="a", delay_hours=4, min_total_amount=Decimal("50")
    )
    shut = assess_cost_of_delay(
        evidence, target_ref="a", delay_hours=4, min_total_amount=Decimal("50.01")
    )

    assert opens["total_amount"] == "50"
    assert opens["currency"] == "USD"
    assert opens["gate_satisfied"] is True
    assert shut["gate_satisfied"] is False


def test_cost_of_delay_without_a_basis_is_unknown_and_shut() -> None:
    result = assess_cost_of_delay(
        CostOfDelayEvidence(None, None, "basis-1", _NOW),
        target_ref="a",
        delay_hours=1,
        min_total_amount=Decimal(0),
    )

    assert result["tier"] == "unknown"
    assert result["total_amount"] is None
    assert result["gate_satisfied"] is False
    assert result["reason_codes"] == ["currency_unobserved", "hourly_cost_unobserved"]
    with pytest.raises(ValueError, match="delay_hours"):
        assess_cost_of_delay(
            CostOfDelayEvidence(Decimal(1), "USD", "b", _NOW),
            target_ref="a",
            delay_hours=0,
            min_total_amount=Decimal(0),
        )


def test_decision_declarations_are_read_only_and_part_of_the_operational_release() -> None:
    declarations = decision_function_types()
    released = {item.name for item in operational_function_types(())}

    assert {item.name for item in declarations} == {
        BLAST_RADIUS_FUNCTION_NAME,
        CHANGE_RISK_FUNCTION_NAME,
        COST_OF_DELAY_FUNCTION_NAME,
    }
    assert {item.name for item in declarations} <= released
    for item in declarations:
        assert item.execution_authority is False
        assert item.network_allowed is False
        assert item.credentials_allowed is False


class _Reader:
    def __init__(self, evidence: object | None) -> None:
        self.evidence = evidence
        self.targets: list[str] = []

    async def read(self, *, target_ref: str) -> object | None:
        self.targets.append(target_ref)
        return self.evidence


def _registry(
    blast: object | None, risk: object | None, cost: object | None
) -> tuple[OntologyFunctionRegistry, _Reader]:
    declarations = decision_function_types()
    release = build_ontology_release(function_types=declarations)
    registry = OntologyFunctionRegistry(release=release)
    anchor = GateTargetAnchorResolver()
    blast_reader = _Reader(blast)
    registry.register_contextual(
        blast_radius_function_type(),
        blast_radius_function(reader=blast_reader, anchor_resolver=anchor),  # type: ignore[arg-type]
    )
    registry.register_contextual(
        change_risk_function_type(),
        change_risk_function(reader=_Reader(risk), anchor_resolver=anchor),  # type: ignore[arg-type]
    )
    registry.register_contextual(
        cost_of_delay_function_type(),
        cost_of_delay_function(reader=_Reader(cost), anchor_resolver=anchor),  # type: ignore[arg-type]
    )
    return registry, blast_reader


def _gate(registry: OntologyFunctionRegistry) -> OntologyFunctionGateEvaluator:
    return OntologyFunctionGateEvaluator(
        reader=RegistryOntologyGateReader(
            registry=registry,
            gate_arguments={
                BLAST_RADIUS_FUNCTION_NAME: {"max_tier": "medium"},
                CHANGE_RISK_FUNCTION_NAME: {"max_tier": "medium"},
                COST_OF_DELAY_FUNCTION_NAME: {"delay_hours": 4, "min_total_amount": "10"},
            },
            purposes=(DECISION_PURPOSE,),
        ),
        max_reading_age=timedelta(minutes=5),
    )


async def _open(gate: OntologyFunctionGateEvaluator, name: str, target: str = "res-1") -> bool:
    return await gate.evaluate_context(
        rule_id=f"ontology-function:{name}",
        step_id="gate",
        process_id="process-1",
        target_resource_id=target,
        at=_NOW + timedelta(seconds=30),
    )


async def test_registry_gate_opens_end_to_end_for_receipted_complete_evidence() -> None:
    registry, blast_reader = _registry(
        _blast(ImpactedResource("res-1", 0, "low")),
        _risk(),
        CostOfDelayEvidence(Decimal("5"), "USD", "basis", _NOW),
    )
    gate = _gate(registry)

    assert await _open(gate, BLAST_RADIUS_FUNCTION_NAME) is True
    assert await _open(gate, CHANGE_RISK_FUNCTION_NAME) is True
    assert await _open(gate, COST_OF_DELAY_FUNCTION_NAME) is True
    assert blast_reader.targets == ["res-1"]


async def test_registry_gate_stays_shut_when_evidence_is_missing_or_unsafe() -> None:
    registry, _ = _registry(
        _blast(ImpactedResource("res-1", 0, "critical"), ImpactedResource("x", 1, "critical")),
        None,
        CostOfDelayEvidence(Decimal("1"), "USD", "basis", _NOW),
    )
    gate = _gate(registry)

    assert await _open(gate, BLAST_RADIUS_FUNCTION_NAME) is False  # tier exceeds the ceiling
    assert await _open(gate, CHANGE_RISK_FUNCTION_NAME) is False  # evidence unavailable
    assert await _open(gate, COST_OF_DELAY_FUNCTION_NAME) is False  # 4 < 10
    assert await _open(gate, "decision.unconfigured") is False


async def test_gate_reader_derives_the_target_from_server_context_only() -> None:
    resolver = GateTargetAnchorResolver()

    assert await resolver.resolve(FunctionInvocationContext(caller_agent="A")) is None
    assert (
        await resolver.resolve(
            FunctionInvocationContext(
                caller_agent="A", evidence_refs=("gate-target:x", "gate-target:y")
            )
        )
        is None
    )
    assert (
        await resolver.resolve(
            FunctionInvocationContext(caller_agent="A", evidence_refs=("gate-target:x",))
        )
        == "x"
    )


def test_gate_reader_requires_a_purpose() -> None:
    registry, _ = _registry(None, None, None)
    with pytest.raises(ValueError, match="purposes"):
        RegistryOntologyGateReader(registry=registry, gate_arguments={}, purposes=())
