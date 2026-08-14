"""End-to-end control-loop proof that rubric provenance reaches the audit log.

Covers the hallucination-rubric-gate contract: with a rubric evaluator bound, a
T2 consultation persists bounded `rubric_*` provenance in the
`control_loop.t2_evaluate` audit row, and the judge's untrusted free-text
rationale never reaches durable state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fdai.core.control_loop import ControlLoop
from fdai.core.event_ingest import EventIngest
from fdai.core.executor import ResourceLockManager, ShadowExecutor, TemplateRenderer
from fdai.core.executor.action_builder import ActionBuilder
from fdai.core.quality_gate.gate import QualityCandidate, QualityGate, QualityGateConfig
from fdai.core.quality_gate.rubric import RubricCriterion, RubricOutput, RubricScore
from fdai.core.quality_gate.testing import (
    InMemoryGroundingSource,
    MatchTypeCrossCheckModel,
    StaticRubricEvaluator,
    StaticVerifier,
)
from fdai.core.tiers.t0_deterministic import RuleIndex, T0Engine
from fdai.core.tiers.t2_reasoning import T2ProposalContext, T2Tier
from fdai.core.trust_router import RoutingDecision, RoutingTier, TrustRouter
from fdai.shared.contracts.models import Event, Mode, Rule
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry
from fdai.shared.contracts.validation import (
    JsonSchemaContractValidator,
    JsonSchemaEventValidator,
)
from fdai.shared.providers.testing.state_store import InMemoryStateStore

RATIONALE = "judge free text that MUST NOT be persisted"


def _validator() -> JsonSchemaEventValidator:
    return JsonSchemaEventValidator(JsonSchemaContractValidator(PackageResourceSchemaRegistry()))


def _rule() -> Rule:
    return Rule.model_validate(
        {
            "schema_version": "1.0.0",
            "id": "r1",
            "version": "1.0.0",
            "source": "custom",
            "severity": "low",
            "category": "config_drift",
            "resource_type": "compute.vm.novel",
            "check_logic": {"kind": "rego", "reference": "policies/example.rego"},
            "remediation": {"template_ref": "remediations/example"},
            "remediates": "remediate.tag-add",
            "provenance": {
                "source_url": "https://example.com/rules/r1",
                "resolved_ref": "0000000000000000000000000000000000000000",
                "content_hash": "sha256:example",
                "license": "MIT",
                "redistribution": "embeddable",
                "retrieved_at": "2026-07-05T00:00:00Z",
            },
        }
    )


def _event_dict(idempotency: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "event_id": "00000000-0000-0000-0000-000000000321",
        "idempotency_key": idempotency,
        "source": "test_source",
        "event_type": "novel.event",
        "detected_at": datetime.now(tz=UTC).isoformat(),
        "ingested_at": datetime.now(tz=UTC).isoformat(),
        "mode": Mode.SHADOW.value,
        "payload": {"resource": {"type": "compute.vm.novel", "resource_id": "res-01"}},
    }


def _candidate() -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="resource:example/rg/x",
        params={"tag": "owner"},
        cited_rule_ids=("r1",),
        confidence_signals={"a": 0.8, "b": 0.9},
        reasoning_trace="the drifted tag violates r1",
    )


class _Proposer:
    async def propose(self, *, context: T2ProposalContext) -> QualityCandidate | None:
        del context
        return _candidate()


class _NoopPublisher:
    async def publish(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("publisher MUST NOT be invoked on a shadow T2 path")


def _rubric_output(*, score: float) -> RubricOutput:
    return RubricOutput(
        scores=tuple(
            RubricScore(
                criterion=criterion.value,
                score=score,
                threshold=0.7,
                rationale=RATIONALE,
                supporting_rule_ids=("r1",),
            )
            for criterion in RubricCriterion
        )
    )


def _loop(
    *,
    audit: InMemoryStateStore,
    tmp_path: Path,
    score: float,
    rubric_shadow: bool,
) -> ControlLoop:
    index = RuleIndex.build(rules=[])
    gate = QualityGate(
        verifier=StaticVerifier(outcome=True),
        cross_check_models=(
            MatchTypeCrossCheckModel(model_id="m1"),
            MatchTypeCrossCheckModel(model_id="m2"),
        ),
        grounding=InMemoryGroundingSource(rules={"r1": _rule()}),
        rubric_evaluator=StaticRubricEvaluator(output=_rubric_output(score=score)),
        config=QualityGateConfig(rubric_shadow=rubric_shadow),
    )
    return ControlLoop(
        event_ingest=EventIngest(validator=_validator()),
        trust_router=TrustRouter(index=index),
        t0_engine=T0Engine(index=index),
        action_builder=ActionBuilder(action_types_by_name={}),
        executor=ShadowExecutor(
            publisher=_NoopPublisher(),
            audit_store=audit,
            renderer=TemplateRenderer(remediation_root=tmp_path),
            resource_lock=ResourceLockManager(),
        ),
        audit_store=audit,
        rules_by_id={"r1": _rule()},
        t2_engine=T2Tier(proposer=_Proposer(), quality_gate=gate),
    )


async def _consult(loop: ControlLoop, idempotency: str) -> Event:
    event = EventIngest(validator=_validator()).ingest(_event_dict(idempotency))
    assert event is not None
    await loop._consult_t2(  # noqa: SLF001 - direct stage hook, mirrors the T2 wire tests
        event=event,
        decision=RoutingDecision(
            tier=RoutingTier.T0,
            resource_type="compute.vm.novel",
            candidate_rule_ids=("r1",),
            reason=None,
        ),
        citing=("r1",),
        cs_decision=None,
        t1_decision=None,
        event_id=str(event.event_id),
        correlation_id=str(event.event_id),
    )
    return event


def _t2_rows(audit: InMemoryStateStore) -> list[dict[str, Any]]:
    return [
        row["entry"]
        for row in audit.audit_entries
        if row["entry"].get("action_kind") == "control_loop.t2_evaluate"
    ]


@pytest.mark.parametrize(
    ("score", "rubric_shadow", "expected_verdict"),
    [(0.9, True, "pass"), (0.2, False, "fail")],
)
async def test_bound_rubric_persists_provenance_without_rationale(
    tmp_path: Path,
    score: float,
    rubric_shadow: bool,
    expected_verdict: str,
) -> None:
    audit = InMemoryStateStore()
    loop = _loop(audit=audit, tmp_path=tmp_path, score=score, rubric_shadow=rubric_shadow)

    await _consult(loop, f"evt-rubric-{expected_verdict}")

    rows = _t2_rows(audit)
    assert len(rows) == 1
    quality = rows[0]["t2_quality"]
    assert quality["rubric_verdict"] == expected_verdict
    assert quality["rubric_min_score"] == pytest.approx(score)
    assert quality["rubric_shadow"] is rubric_shadow
    scores = quality["rubric_scores"]
    assert {entry["criterion"] for entry in scores} == {c.value for c in RubricCriterion}
    assert all(entry["supporting_rule_ids"] == ["r1"] for entry in scores)
    assert all("rationale" not in entry for entry in scores)
    assert RATIONALE not in repr(audit.audit_entries)


async def test_enforce_rubric_failure_lowers_confidence_in_the_audit_record(
    tmp_path: Path,
) -> None:
    audit = InMemoryStateStore()
    loop = _loop(audit=audit, tmp_path=tmp_path, score=0.2, rubric_shadow=False)

    await _consult(loop, "evt-rubric-subtractive")

    quality = _t2_rows(audit)[0]["t2_quality"]
    assert quality["outcome"] == "abstain"
    assert quality["aggregate_confidence"] == pytest.approx(0.2)
    assert any(reason.startswith("rubric_failed:") for reason in quality["reasons"])
