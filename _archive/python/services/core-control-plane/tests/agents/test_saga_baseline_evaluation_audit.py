from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest
from fdai.agents._framework.forseti_baseline_evaluation import (
    BASELINE_EVALUATION_OUTCOME_PREFIX,
    record_baseline_evaluation,
)
from fdai.agents.saga import Saga
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
CATALOG = "sha256:" + "c" * 64


class _CompliantEvaluator:
    def evaluate(self, rule: Rule, resource_props: Mapping[str, Any]) -> PolicyResult:
        del rule, resource_props
        return PolicyResult(denied=False, context={})


def _rule() -> Rule:
    return Rule(
        schema_version="1.0.0",
        id="rule.compliant",
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.LOW,
        category=Category.SECURITY,
        resource_type="example.resource",
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


@pytest.mark.asyncio
async def test_saga_binds_replayable_audit_before_outcome_record() -> None:
    state_store = InMemoryStateStore()
    saga = Saga(durable_state_store=state_store, clock=lambda: NOW)
    rule = _rule()

    await record_baseline_evaluation(
        observation=PromotedInventoryObservation(
            generation="generation-1",
            resources=(
                ResourceRecord(
                    resource_id="resource-one",
                    type="example.resource",
                    props={},
                    last_seen=NOW.isoformat(),
                ),
            ),
            links=(),
            complete=True,
            recorded_at=NOW,
        ),
        engine=T0Engine(index=RuleIndex.build((rule,)), evaluator=_CompliantEvaluator()),
        rules=(rule,),
        catalog_revision=CATALOG,
        audit_binder=saga.bind_baseline_evaluation_audit,
        state_store=state_store,
        evaluated_at=NOW,
    )

    outcomes, _total = await state_store.read_state_page(
        prefix=BASELINE_EVALUATION_OUTCOME_PREFIX,
        limit=10,
    )
    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome["saga_audit_ref"].startswith("audit:")
    assert outcome["saga_audit_digest"].startswith("sha256:")
    assert all(entry.topic == "object.audit-entry" for entry in saga.audit_chain.entries)
    assert outcome["saga_audit_ref"] in {entry.correlation_id for entry in saga.audit_chain.entries}
    durable_audits = tuple(state_store.audit_entries)
    assert any(
        entry.get("entry", {}).get("audit_ref") == outcome["saga_audit_ref"]
        and entry.get("entry", {}).get("audit_digest") == outcome["saga_audit_digest"]
        for entry in durable_audits
    )
