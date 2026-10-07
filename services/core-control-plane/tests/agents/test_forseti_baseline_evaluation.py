from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.agents._framework.forseti_baseline_evaluation import (
    BASELINE_EVALUATION_COMPLETION_PREFIX,
    BASELINE_EVALUATION_OUTCOME_PREFIX,
    BaselineEvaluationAuditReference,
    record_baseline_evaluation,
)
from fdai.agents.forseti import Forseti
from fdai.core.tiers.t0_deterministic import PolicyResult, RuleIndex, T0Engine
from fdai.delivery.inventory_sync import PromotedInventoryObservation
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Provenance,
    Redistribution,
    Remediation,
    Rule,
    RuleSource,
    Severity,
)
from fdai.shared.providers.inventory import ResourceRecord
from fdai.shared.providers.testing.state_store import InMemoryStateStore

NOW = datetime(2026, 10, 2, tzinfo=UTC)
CATALOG_A = "sha256:" + "a" * 64
CATALOG_B = "sha256:" + "b" * 64


class _Evaluator:
    def __init__(self, results: Mapping[str, PolicyResult | None]) -> None:
        self.results = dict(results)

    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult | None:
        del resource_props
        return self.results.get(rule.id)


class _FailingEvaluator:
    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult:
        del rule, resource_props
        raise RuntimeError("OPA unavailable")


async def _audit_binder(record: Mapping[str, Any]) -> BaselineEvaluationAuditReference:
    digest = (
        "sha256:"
        + __import__("hashlib").sha256(repr(sorted(record.items())).encode("utf-8")).hexdigest()
    )
    return BaselineEvaluationAuditReference(ref="audit:" + digest[7:39], digest=digest)


def _rule(rule_id: str, *, resource_type: str = "example.resource") -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.SECURITY,
        resource_type=resource_type,
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/example.rego"),
        remediation=Remediation(template_ref="remediation/example.tftpl"),
        remediates="remediate.example",
        triggered_by=["inventory.resource_observed"],
        provenance=Provenance(
            source_url="https://example.com/rule",
            resolved_ref="0" * 40,
            content_hash="sha256:example",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at=NOW,
        ),
    )


def _observation(*resources: ResourceRecord) -> PromotedInventoryObservation:
    return PromotedInventoryObservation(
        generation="generation-1",
        resources=resources,
        links=(),
        complete=True,
        recorded_at=NOW,
    )


@pytest.mark.asyncio
async def test_records_compliant_violated_and_abstained_outcomes() -> None:
    rules = (_rule("rule.compliant"), _rule("rule.violated"), _rule("rule.abstained"))
    store = InMemoryStateStore()
    completion = await record_baseline_evaluation(
        observation=_observation(
            ResourceRecord(
                resource_id="resource-one",
                type="example.resource",
                props={"ready": True},
                last_seen=NOW.isoformat(),
            )
        ),
        engine=T0Engine(
            index=RuleIndex.build(rules),
            evaluator=_Evaluator(
                {
                    "rule.compliant": PolicyResult(denied=False, context={}),
                    "rule.violated": PolicyResult(denied=True, context={"deny_reason": "x"}),
                    "rule.abstained": None,
                }
            ),
        ),
        rules=rules,
        catalog_revision=CATALOG_A,
        audit_binder=_audit_binder,
        state_store=store,
        evaluated_at=NOW,
    )

    assert completion.expected_denominator == 3
    assert completion.compliant_count == 1
    assert completion.violated_count == 1
    assert completion.abstained_count == 1
    pages, _total = await store.read_state_page(prefix=BASELINE_EVALUATION_OUTCOME_PREFIX, limit=10)
    outcomes = {row["rule_ref"]: row for row in pages}
    assert outcomes["rule:rule.compliant"]["outcome"] == "compliant"
    assert outcomes["rule:rule.violated"]["outcome"] == "violated"
    assert outcomes["rule:rule.abstained"]["outcome"] == "abstained"
    assert outcomes["rule:rule.abstained"]["reason_code"] == "unsupported_evidence"


@pytest.mark.asyncio
async def test_catalog_revision_change_records_distinct_completion() -> None:
    rule = _rule("rule.compliant")
    store = InMemoryStateStore()
    kwargs = dict(
        observation=_observation(
            ResourceRecord(
                resource_id="resource-one",
                type="example.resource",
                props={},
                last_seen=NOW.isoformat(),
            )
        ),
        engine=T0Engine(
            index=RuleIndex.build((rule,)),
            evaluator=_Evaluator({"rule.compliant": PolicyResult(denied=False, context={})}),
        ),
        rules=(rule,),
        audit_binder=_audit_binder,
        state_store=store,
        evaluated_at=NOW,
    )

    first = await record_baseline_evaluation(catalog_revision=CATALOG_A, **kwargs)
    second = await record_baseline_evaluation(catalog_revision=CATALOG_B, **kwargs)

    assert first.completion_digest != second.completion_digest
    page, _total = await store.read_state_page(
        prefix=BASELINE_EVALUATION_COMPLETION_PREFIX, limit=10
    )
    assert len(page) == 2


@pytest.mark.asyncio
async def test_duplicate_delivery_is_idempotent() -> None:
    rule = _rule("rule.compliant")
    store = InMemoryStateStore()
    kwargs = dict(
        observation=_observation(
            ResourceRecord(
                resource_id="resource-one",
                type="example.resource",
                props={},
                last_seen=NOW.isoformat(),
            )
        ),
        engine=T0Engine(
            index=RuleIndex.build((rule,)),
            evaluator=_Evaluator({"rule.compliant": PolicyResult(denied=False, context={})}),
        ),
        rules=(rule,),
        catalog_revision=CATALOG_A,
        audit_binder=_audit_binder,
        state_store=store,
        evaluated_at=NOW,
    )

    first = await record_baseline_evaluation(**kwargs)
    second = await record_baseline_evaluation(**kwargs)

    assert first == second
    page, _total = await store.read_state_page(prefix=BASELINE_EVALUATION_OUTCOME_PREFIX, limit=10)
    assert len(page) == 1


@pytest.mark.asyncio
async def test_stale_and_missing_evidence_abstain() -> None:
    rule = _rule("rule.compliant")
    store = InMemoryStateStore()
    completion = await record_baseline_evaluation(
        observation=_observation(
            ResourceRecord(resource_id="missing", type="example.resource", props={}),
            ResourceRecord(
                resource_id="stale",
                type="example.resource",
                props={},
                last_seen="2026-10-01T00:00:00+00:00",
            ),
        ),
        engine=T0Engine(
            index=RuleIndex.build((rule,)),
            evaluator=_Evaluator({"rule.compliant": PolicyResult(denied=False, context={})}),
        ),
        rules=(rule,),
        catalog_revision=CATALOG_A,
        audit_binder=_audit_binder,
        state_store=store,
        evaluated_at=NOW,
        evidence_fresh_after=NOW,
    )

    assert completion.abstained_count == 2
    page, _total = await store.read_state_page(prefix=BASELINE_EVALUATION_OUTCOME_PREFIX, limit=10)
    assert {row["reason_code"] for row in page} == {"missing_evidence", "stale_evidence"}


@pytest.mark.asyncio
async def test_compliance_requires_every_declared_evaluated_property() -> None:
    observed = _rule("rule.observed").model_copy(
        update={"evaluates": ["property.example.resource.diagnostic_settings"]}
    )
    foreign = _rule("rule.foreign").model_copy(
        update={"evaluates": ["property.other.resource.diagnostic_settings"]}
    )
    denied = _rule("rule.denied").model_copy(
        update={"evaluates": ["property.example.resource.tags"]}
    )
    nested = _rule("rule.nested").model_copy(
        update={"evaluates": ["property.example.resource.tags.required_tag"]}
    )
    rules = (observed, foreign, denied, nested)
    store = InMemoryStateStore()
    completion = await record_baseline_evaluation(
        observation=_observation(
            ResourceRecord(
                resource_id="with-property",
                type="example.resource",
                props={"diagnostic_settings": [], "tags": {"owner": "team"}},
            ),
            ResourceRecord(
                resource_id="without-property",
                type="example.resource",
                props={"properties": {"diagnosticSettings": []}},
            ),
        ),
        engine=T0Engine(
            index=RuleIndex.build(rules),
            evaluator=_Evaluator(
                {
                    "rule.observed": PolicyResult(denied=False, context={}),
                    "rule.foreign": PolicyResult(denied=False, context={}),
                    "rule.denied": PolicyResult(denied=True, context={"deny_reason": "no_tags"}),
                    "rule.nested": PolicyResult(denied=False, context={}),
                }
            ),
        ),
        rules=rules,
        catalog_revision=CATALOG_A,
        audit_binder=_audit_binder,
        state_store=store,
        evaluated_at=NOW,
    )

    page, _total = await store.read_state_page(prefix=BASELINE_EVALUATION_OUTCOME_PREFIX, limit=10)
    outcomes = {(row["resource_ref"], row["rule_ref"]): row for row in page}
    # An empty but present property was observed; an absent one never proves compliance.
    assert outcomes[("resource:with-property", "rule:rule.observed")]["outcome"] == "compliant"
    unobserved = outcomes[("resource:without-property", "rule:rule.observed")]
    assert (unobserved["outcome"], unobserved["reason_code"]) == (
        "abstained",
        "property_unobserved",
    )
    assert {
        outcomes[(ref, "rule:rule.foreign")]["reason_code"]
        for ref in ("resource:with-property", "resource:without-property")
    } == {"property_unobserved"}
    # A deny stays the reviewed Rule's judgment even when its property is absent.
    assert outcomes[("resource:without-property", "rule:rule.denied")]["outcome"] == "violated"
    # A nested path is satisfied by its observed top-level property; the policy judges the rest.
    assert outcomes[("resource:with-property", "rule:rule.nested")]["outcome"] == "compliant"
    assert outcomes[("resource:without-property", "rule:rule.nested")]["reason_code"] == (
        "property_unobserved"
    )
    assert completion.compliant_count == 2
    assert completion.abstained_count == 4
    assert completion.violated_count == 2


@pytest.mark.asyncio
async def test_policy_evaluator_failure_abstains_without_losing_completion() -> None:
    rule = _rule("rule.compliant")
    store = InMemoryStateStore()

    completion = await record_baseline_evaluation(
        observation=_observation(
            ResourceRecord(
                resource_id="resource-one",
                type="example.resource",
                props={},
                last_seen=NOW.isoformat(),
            )
        ),
        engine=T0Engine(index=RuleIndex.build((rule,)), evaluator=_FailingEvaluator()),
        rules=(rule,),
        catalog_revision=CATALOG_A,
        audit_binder=_audit_binder,
        state_store=store,
        evaluated_at=NOW,
    )

    assert completion.abstained_count == 1
    page, _total = await store.read_state_page(prefix=BASELINE_EVALUATION_OUTCOME_PREFIX, limit=10)
    assert page[0]["outcome"] == "abstained"
    assert page[0]["reason_code"] == "unsupported_evidence"


@pytest.mark.asyncio
async def test_empty_complete_inventory_records_zero_denominator_completion() -> None:
    store = InMemoryStateStore()
    completion = await record_baseline_evaluation(
        observation=_observation(),
        engine=T0Engine(index=RuleIndex.build(())),
        rules=(),
        catalog_revision=CATALOG_A,
        audit_binder=_audit_binder,
        state_store=store,
        evaluated_at=NOW,
    )

    assert completion.expected_denominator == 0
    assert (
        completion.outcome_set_digest == "sha256:" + __import__("hashlib").sha256(b"[]").hexdigest()
    )
    page, _total = await store.read_state_page(prefix=BASELINE_EVALUATION_OUTCOME_PREFIX, limit=10)
    assert page == ()


@pytest.mark.asyncio
async def test_forseti_typed_port_uses_injected_state_store() -> None:
    rule = _rule("rule.compliant")
    store = InMemoryStateStore()
    forseti = Forseti(state_store=store)

    completion = await forseti.evaluate_baseline_generation(
        observation=_observation(
            ResourceRecord(
                resource_id="resource-one",
                type="example.resource",
                props={},
                last_seen=NOW.isoformat(),
            )
        ),
        engine=T0Engine(
            index=RuleIndex.build((rule,)),
            evaluator=_Evaluator({"rule.compliant": PolicyResult(denied=False, context={})}),
        ),
        rules=(rule,),
        catalog_revision=CATALOG_A,
        audit_binder=_audit_binder,
        evaluated_at=NOW,
    )

    assert completion.compliant_count == 1
    page, _total = await store.read_state_page(
        prefix=BASELINE_EVALUATION_COMPLETION_PREFIX,
        limit=10,
    )
    assert page[0]["completion_digest"] == completion.completion_digest
