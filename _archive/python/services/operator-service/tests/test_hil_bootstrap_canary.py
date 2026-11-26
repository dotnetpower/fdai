"""Focused proof for the no-network composed human approval bootstrap canary."""

from __future__ import annotations

from fdai_operator_service.families.iam.hil_bootstrap_canary import (
    run_local_hil_bootstrap_canary,
)


async def test_local_hil_bootstrap_canary_proves_channels_audit_replay_and_teardown() -> None:
    result = await run_local_hil_bootstrap_canary()

    assert result.mode == "local_dry_run_no_network"
    assert result.slack_approval == "recorded_then_redriven"
    assert result.teams_rejection == "rejected"
    assert result.timeout == "expired_fail_closed"
    assert result.teams_tampered_card == "refused_unknown_card_field"
    assert result.audit_records_before_teardown == 8
    assert result.retained_records_after_teardown == 0
    assert result.client_closed is True
    assert result.broker_publications == 2
    assert result.replayed_after_broker_failure is True
    assert result.live_network_calls == 0
    assert result.live_teams_proof is False


async def test_local_hil_bootstrap_canary_reports_it_is_not_a_live_teams_proof() -> None:
    projection = (await run_local_hil_bootstrap_canary()).to_dict()

    assert projection["mode"] == "local_dry_run_no_network"
    assert projection["live_teams_proof"] is False
    assert projection["live_network_calls"] == 0
