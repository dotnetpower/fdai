"""Tests for remediation, runbook, what-if, and typed-action observations."""

from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.audit.what_if_replay import ReconstructedEvent, WhatIfReplayReport
from fdai.core.conversation_assurance.quality_action_observations import (
    RemediationScenarioResult,
    RunbookScenarioResult,
    TypedActionScenarioResult,
    WhatIfScenarioResult,
    observe_remediation_scenario,
    observe_runbook_scenario,
    observe_typed_action_scenario,
    observe_what_if_scenario,
)
from fdai.core.investigation import Priority
from fdai.core.irp.coordinator import MitigationProposal
from fdai.core.runbook.models import RunbookResult, RunbookStepOutcome
from fdai.shared.contracts.models import Action, Operation

_EVIDENCE = "a" * 64


def _proposal() -> MitigationProposal:
    return MitigationProposal(
        proposal_id="proposal-1",
        alert_id="alert-1",
        remediation_ref="runbook.restart",
        detail="Restart the unhealthy instance.",
        priority=Priority.P1,
        approver_role="approver",
        citations=("rule-1",),
        requested_at=datetime(2026, 8, 27, tzinfo=UTC),
        target_resource_ref="resource-1",
    )


def _replay() -> WhatIfReplayReport:
    return WhatIfReplayReport(
        event=ReconstructedEvent("correlation-1", "resource-1", "type-1", {}),
        matched_rules=({"rule_id": "rule-1", "denied": False},),
        original_action_kinds=("proposal.created",),
    )


def test_remediation_and_runbook_compare_exact_identifiers() -> None:
    remediation = observe_remediation_scenario(
        RemediationScenarioResult("case-1", "runbook.restart", _proposal(), _EVIDENCE)
    )
    runbook = observe_runbook_scenario(
        RunbookScenarioResult(
            "case-1",
            "runbook.restart",
            RunbookResult("runbook.restart", (), RunbookStepOutcome.SUCCESS),
            _EVIDENCE,
        )
    )
    assert remediation.item_id == 21
    assert runbook.item_id == 22
    assert remediation.value == runbook.value == 1.0


def test_what_if_compares_normalized_rule_set() -> None:
    matching = observe_what_if_scenario(
        WhatIfScenarioResult("case-1", ("rule-1",), _replay(), _EVIDENCE)
    )
    mismatch = observe_what_if_scenario(
        WhatIfScenarioResult("case-2", ("rule-2",), _replay(), _EVIDENCE)
    )
    assert matching.item_id == 23
    assert matching.value == 1.0
    assert mismatch.value == 0.0


def test_typed_action_compares_type_target_and_operation() -> None:
    action = Action.model_construct(
        action_type="resource.restart",
        target_resource_ref="resource-1",
        operation=Operation.UPDATE,
    )
    matching = observe_typed_action_scenario(
        TypedActionScenarioResult(
            "case-1",
            "resource.restart",
            "resource-1",
            Operation.UPDATE,
            action,
            _EVIDENCE,
        )
    )
    mismatch = observe_typed_action_scenario(
        TypedActionScenarioResult(
            "case-2",
            "resource.restart",
            "resource-2",
            Operation.UPDATE,
            action,
            _EVIDENCE,
        )
    )
    assert matching.item_id == 24
    assert matching.value == 1.0
    assert mismatch.value == 0.0
