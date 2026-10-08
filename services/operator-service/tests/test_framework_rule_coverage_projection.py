"""WAF control detail shows server-owned scoped Rule coverage only for the current baseline."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from fdai_operator_service.families.workflow.contracts import (
    WorkflowOperation,
    WorkflowReadRequest,
)
from fdai_operator_service.family_adapters import PostgresWorkflowAdapters
from fdai_service_contracts.baseline_evaluation import (
    BaselineEvaluationCoverage,
    baseline_evaluation_coverage_digest,
)
from fdai_service_contracts.framework_rule_coverage import (
    FRAMEWORK_RULE_COVERAGE_LATEST_KEY,
    ScopedRuleCoverageRecord,
    ScopedRuleCoverageResource,
    ScopedRuleCoverageRule,
    framework_rule_coverage_record_digest,
    scoped_rule_coverage_digest,
    scoped_rule_coverage_resource_set_digest,
)
from starlette.exceptions import HTTPException

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 10, 7, 15, 22, tzinfo=UTC)
ACTIVATED = "cache.zone-redundant"
NOT_ACTIVATED = "compute.vm.managed-identity.assigned"
SCOPE = "sha256:" + "1" * 64


def _digest(seed: str) -> str:
    return "sha256:" + (seed * 64)[:64]


def _baseline(**changes: object) -> BaselineEvaluationCoverage:
    values: dict[str, object] = {
        "schema_version": "1.0.0",
        "generation_id": "generation:inventory-1",
        "generation_digest": _digest("2"),
        "inventory_observation_digest": _digest("3"),
        "rule_activation_generation_id": "rule-activation-" + "4" * 32,
        "rule_activation_generation_digest": _digest("4"),
        "rule_catalog_digest": _digest("5"),
        "evaluated_rule_catalog_digest": _digest("5"),
        "dispatch_signal": "inventory.resource_observed",
        "expected_pair_set_digest": _digest("6"),
        "expected_pair_count": 3,
        "covered_pair_count": 3,
        "compliant_count": 1,
        "violated_count": 2,
        "abstained_count": 0,
        "missing_pair_count": 0,
        "duplicate_pair_count": 0,
        "conflicting_pair_count": 0,
        "unexpected_pair_count": 0,
        "revision_mismatch_count": 0,
        "outcome_set_digest": _digest("7"),
        "complete": True,
        "limitations": (),
        "audit_ref": "baseline-evaluation:coverage:example",
        "audit_digest": _digest("8"),
        "completed_at": NOW,
        **changes,
    }
    values["coverage_digest"] = baseline_evaluation_coverage_digest(**values)
    return BaselineEvaluationCoverage.model_validate(values)


def _record(baseline: BaselineEvaluationCoverage) -> ScopedRuleCoverageRecord:
    resources = (
        ScopedRuleCoverageResource(
            provider_resource_id="/providers/example/cache-1",
            resource_ref="resource:cache-1",
            resource_type="Example/caches",
        ),
        ScopedRuleCoverageResource(
            provider_resource_id="/providers/example/cache-2",
            resource_ref="resource:cache-2",
            resource_type="Example/caches",
        ),
    )
    rules = (
        ScopedRuleCoverageRule(
            rule_id=ACTIVATED,
            member_rule_digest=_digest("a"),
            evaluated_rule_digest=_digest("a"),
            eligible_set_digest=_digest("b"),
            eligible_count=2,
            compliant_count=1,
            violated_count=1,
            abstained_count=0,
            missing_count=0,
            duplicate_count=0,
            conflicting_count=0,
            unexpected_count=0,
            revision_mismatch_count=0,
        ),
    )
    values: dict[str, Any] = {
        "schema_version": "1.0.0",
        "framework_id": "azure-waf",
        "workload_id": "workload-example",
        "scope_digest": SCOPE,
        "resource_set_digest": scoped_rule_coverage_resource_set_digest(resources),
        "resources": resources,
        "rule_activation_generation_id": baseline.rule_activation_generation_id,
        "rule_activation_generation_digest": baseline.rule_activation_generation_digest,
        "rule_catalog_digest": baseline.rule_catalog_digest,
        "evaluated_rule_catalog_digest": baseline.evaluated_rule_catalog_digest,
        "dispatch_signal": baseline.dispatch_signal,
        "expected_pair_set_digest": baseline.expected_pair_set_digest,
        "inventory_generation": "inventory-1",
        "baseline_generation_id": baseline.generation_id,
        "inventory_observation_digest": baseline.inventory_observation_digest,
        "inventory_observed_at": NOW,
        "recorded_at": NOW,
        "rules": rules,
        "unattributed_unexpected_count": 0,
        "baseline_coverage_digest": baseline.coverage_digest,
        "baseline_audit_ref": baseline.audit_ref,
        "baseline_audit_digest": baseline.audit_digest,
        "audit_ref": "framework-rule-coverage:example",
        "audit_digest": _digest("c"),
    }
    values["scoped_coverage_digest"] = scoped_rule_coverage_digest(
        ScopedRuleCoverageRecord.model_construct(**values)
    )
    values["record_digest"] = framework_rule_coverage_record_digest(**values)
    return ScopedRuleCoverageRecord.model_validate(values)


def _control(*, scope: str | None = SCOPE) -> dict[str, object]:
    return {
        "id": "azure-waf.reliability.re-05",
        "control_id": "RE:05",
        "pillar": "reliability",
        "status": "unknown",
        "evaluation_scope": scope,
        "requirements": [
            {"kind": "rule", "ref": ACTIVATED, "status": "failed", "limitations": []},
            {
                "kind": "rule",
                "ref": NOT_ACTIVATED,
                "status": "unknown",
                "limitations": ["rule_not_activated"],
            },
            {"kind": "artifact", "ref": "target-architecture", "status": "unknown"},
        ],
        "provenance": {},
    }


class _Store:
    def __init__(self, state: dict[str, object], control: dict[str, object]) -> None:
        self.state = state
        self.control = control

    async def read_projection(self, *, family: str, operation: str) -> dict[str, object]:
        del family, operation
        return {
            "_revision": "best-practice-revision",
            "controls": [self.control],
            "evaluation_source": "framework-shadow-assessment",
        }

    async def read_state(self, key: str) -> object:
        return self.state.get(key)


async def _detail(state: dict[str, object], control: dict[str, object] | None = None):  # noqa: ANN202
    return await PostgresWorkflowAdapters(cast(Any, _Store(state, control or _control()))).read(
        WorkflowReadRequest(
            operation=WorkflowOperation.BEST_PRACTICE_DETAIL,
            principal_id="operator-a",
            query={},
            path_parameters={"best_practice_id": "azure-waf.reliability.re-05"},
        )
    )


async def test_current_record_attaches_per_rule_counts_and_activation_state() -> None:
    baseline = _baseline()
    record = _record(baseline)

    result = await _detail(
        {
            FRAMEWORK_RULE_COVERAGE_LATEST_KEY: record.model_dump(mode="json"),
            "baseline-evaluation:latest:coverage": baseline.model_dump(mode="json"),
        }
    )

    coverage = cast(dict[str, Any], result.payload["rule_coverage"])
    assert coverage["status"] == "current"
    assert coverage["matches_assessment_scope"] is True
    assert coverage["resource_count"] == 2
    assert coverage["execution_authority"] is False
    requirements = cast(list[dict[str, Any]], result.payload["requirements"])
    assert requirements[0]["coverage"] == {
        "activated": True,
        "eligible": 2,
        "covered": 2,
        "compliant": 1,
        "violated": 1,
        "held_for_review": 0,
        "missing": 0,
        "duplicate": 0,
        "conflicting": 0,
        "unexpected": 0,
        "revision_mismatch": 0,
    }
    assert requirements[1]["coverage"] == {"activated": False}
    assert "coverage" not in requirements[2]
    # The status stays the server-owned assessment result; counts never rewrite it.
    assert requirements[0]["status"] == "failed"
    assert result.provenance.revision != "best-practice-revision"


async def test_record_for_a_replaced_baseline_is_stale_without_counts() -> None:
    record = _record(_baseline())
    newer = _baseline(outcome_set_digest=_digest("9"))

    result = await _detail(
        {
            FRAMEWORK_RULE_COVERAGE_LATEST_KEY: record.model_dump(mode="json"),
            "baseline-evaluation:latest:coverage": newer.model_dump(mode="json"),
        }
    )

    coverage = cast(dict[str, Any], result.payload["rule_coverage"])
    assert (coverage["status"], coverage["reason"]) == ("stale", "baseline_changed")
    requirements = cast(list[dict[str, Any]], result.payload["requirements"])
    assert all("coverage" not in item for item in requirements)


async def test_missing_record_or_baseline_reports_unavailable_or_stale() -> None:
    record = _record(_baseline())

    missing = await _detail({})
    no_baseline = await _detail({FRAMEWORK_RULE_COVERAGE_LATEST_KEY: record.model_dump()})

    assert missing.payload["rule_coverage"] == {"status": "unavailable", "reason": "no_record"}
    stale = cast(dict[str, Any], no_baseline.payload["rule_coverage"])
    assert (stale["status"], stale["reason"]) == ("stale", "no_baseline")


async def test_other_assessment_scope_is_labelled_and_malformed_record_fails_closed() -> None:
    baseline = _baseline()
    record = _record(baseline)
    state = {
        FRAMEWORK_RULE_COVERAGE_LATEST_KEY: record.model_dump(mode="json"),
        "baseline-evaluation:latest:coverage": baseline.model_dump(mode="json"),
    }

    other_scope = await _detail(state, _control(scope=None))

    coverage = cast(dict[str, Any], other_scope.payload["rule_coverage"])
    assert coverage["matches_assessment_scope"] is False
    tampered = {**record.model_dump(mode="json"), "record_digest": _digest("d")}
    with pytest.raises(HTTPException) as error:
        await _detail({**state, FRAMEWORK_RULE_COVERAGE_LATEST_KEY: tampered})
    assert error.value.status_code == 503


async def test_control_without_rule_requirements_is_unchanged() -> None:
    control = {**_control(), "requirements": [{"kind": "artifact", "ref": "doc"}]}

    result = await _detail({}, control)

    assert "rule_coverage" not in result.payload
    assert result.provenance.revision == "best-practice-revision"
