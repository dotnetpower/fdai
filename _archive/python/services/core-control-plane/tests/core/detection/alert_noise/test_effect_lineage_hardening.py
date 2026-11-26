"""Round 15: outcome projection requires exact dispatch lineage and independently bound receipt."""

from dataclasses import replace
from datetime import timedelta

import pytest
from fdai.core.detection.alert_noise.execution import AlertExecutionHeld
from fdai.core.detection.alert_noise.outcomes import (
    AlertExecutedActionRecord,
    alert_executed_action_key,
    alert_response_outcome,
    require_alert_dispatch_lineage,
)
from fdai.core.executor.safeguards import full_action_digest

from .test_outcomes import _fixture_context, _fixture_observation


@pytest.mark.parametrize("change", ["bundle", "dispatch"])
def test_context_rejects_wrong_bundle_or_correlated_dispatch(change: str) -> None:
    context = _fixture_context()
    if change == "bundle":
        context = replace(context, safeguard_bundle_digest="not-a-digest")
    else:
        context = replace(
            context,
            process_events=(replace(context.process_events[0], correlation_id="trace:other"),),
        )
    with pytest.raises(AlertExecutionHeld):
        require_alert_dispatch_lineage(context)


def test_separate_recovery_coordinator_cannot_impersonate_compensation() -> None:
    context = _fixture_context(restore=True)
    execution = context.execution
    action = execution.action.model_copy(
        update={
            "workflow_action": execution.action.workflow_action.model_copy(
                update={"step_id": "recover_update_routing"}
            )
        }
    )
    execution = AlertExecutedActionRecord.model_validate(
        execution.model_copy(
            update={
                "action": action,
                "source_event": execution.source_event.model_copy(
                    update={"action_digest": full_action_digest(action)}
                ),
            }
        )
    )
    context = replace(
        context,
        execution=execution,
        process_events=(
            *context.process_events[:-1],
            replace(context.process_events[-1], step_id="recover_update_routing"),
        ),
    )
    with pytest.raises(AlertExecutionHeld, match="recovery_coordinator_required"):
        require_alert_dispatch_lineage(context)


def test_invalid_action_and_receipt_addresses_never_make_an_outcome() -> None:
    context = _fixture_context()
    observation = _fixture_observation(context)
    with pytest.raises(AlertExecutionHeld, match="action_digest_invalid"):
        alert_executed_action_key("sha256:partial")
    with pytest.raises(AlertExecutionHeld, match="receipt_digest_invalid"):
        alert_response_outcome(
            context, observation, receipt_digest="sha256:partial", now=observation.recorded_at
        )


def test_late_or_unadmitted_observation_cannot_become_numeric_success() -> None:
    context = _fixture_context()
    observation = _fixture_observation(context)
    for observed in (
        observation.model_copy(update={"coverage": "partial"}),
        observation.model_copy(update={"recorded_at": observation.recorded_at + timedelta(days=1)}),
    ):
        assert (
            alert_response_outcome(
                context, observed, receipt_digest="sha256:" + "a" * 64, now=observed.recorded_at
            )
            is None
        )
