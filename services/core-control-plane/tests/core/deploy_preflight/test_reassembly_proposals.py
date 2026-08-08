"""Reassembly -> Action proposals (granularity A: one Action per toggle)."""

from __future__ import annotations

import pytest
from fdai.core.deploy_preflight import (
    ACTION_TYPE,
    AppliedToggle,
    ReassemblyOutcome,
    ReassemblyReason,
    ReassemblyStatus,
    build_toggle_proposals,
    submit_toggle_proposals,
)


def _cleared(*toggles: AppliedToggle) -> ReassemblyOutcome:
    return ReassemblyOutcome(
        status=ReassemblyStatus.CLEARED,
        reason=ReassemblyReason.NONE,
        overrides={k: v for t in toggles for k, v in t.set_vars.items()},
        iterations=len(toggles),
        applied_toggles=tuple(toggles),
    )


def _toggle(finding_id: str, module: str, set_vars: dict[str, str]) -> AppliedToggle:
    return AppliedToggle(
        finding_id=finding_id, module=module, set_vars=set_vars, scope="rg:example"
    )


def test_one_proposal_per_toggle() -> None:
    outcome = _cleared(
        _toggle("denied-resource-type:disk", "compute", {"disk_provisioning": "attach_existing"}),
        _toggle("blocked-egress:docker.io", "registry", {"registry_source": "acr_mirror"}),
    )
    proposals = build_toggle_proposals(outcome, initiator_principal="control-plane")
    assert len(proposals) == 2
    assert {p.finding_id for p in proposals} == {
        "denied-resource-type:disk",
        "blocked-egress:docker.io",
    }
    assert {p.toggle_module for p in proposals} == {"compute", "registry"}


def test_proposal_dict_shape_matches_argument_schema() -> None:
    outcome = _cleared(_toggle("f0", "compute", {"disk_provisioning": "attach_existing"}))
    proposal = build_toggle_proposals(outcome, initiator_principal="control-plane")[0]
    envelope = proposal.to_dict()
    assert envelope["action_type"] == ACTION_TYPE
    assert envelope["operator_initiated"] is False
    assert envelope["resource_id"] == "rg:example"
    assert envelope["event_type"] == "rule_violation"
    assert set(envelope["params"]) == {
        "scope",
        "finding_id",
        "toggle_module",
        "set_vars",
        "reason",
    }
    assert envelope["params"]["set_vars"] == {"disk_provisioning": "attach_existing"}
    assert len(envelope["params"]["reason"]) >= 10


def test_escalated_outcome_yields_no_proposals() -> None:
    outcome = ReassemblyOutcome(
        status=ReassemblyStatus.ESCALATED,
        reason=ReassemblyReason.MANUAL_BLOCKER,
        applied_toggles=(_toggle("f0", "compute", {"a": "1"}),),
    )
    assert build_toggle_proposals(outcome, initiator_principal="control-plane") == ()


def test_idempotency_key_deterministic_and_distinct() -> None:
    t0 = _toggle("f0", "compute", {"disk_provisioning": "attach_existing"})
    t1 = _toggle("f1", "registry", {"registry_source": "acr_mirror"})
    a = build_toggle_proposals(_cleared(t0, t1), initiator_principal="cp")
    b = build_toggle_proposals(_cleared(t0, t1), initiator_principal="cp")
    assert [p.idempotency_key for p in a] == [p.idempotency_key for p in b]
    assert a[0].idempotency_key != a[1].idempotency_key


def test_explicit_reason_overrides_default() -> None:
    outcome = _cleared(_toggle("f0", "compute", {"a": "1"}))
    proposal = build_toggle_proposals(outcome, initiator_principal="cp", reason="operator asked")[0]
    assert proposal.reason == "operator asked"


class _RecordingSink:
    def __init__(self) -> None:
        self.received: list[dict] = []

    async def __call__(self, envelope):  # type: ignore[no-untyped-def]
        self.received.append(dict(envelope))
        return {"submitted": True, "correlation_id": envelope["correlation_id"]}


async def test_submit_hands_each_proposal_to_sink_in_order() -> None:
    outcome = _cleared(
        _toggle("f0", "compute", {"disk_provisioning": "attach_existing"}),
        _toggle("f1", "registry", {"registry_source": "acr_mirror"}),
    )
    sink = _RecordingSink()
    results = await submit_toggle_proposals(outcome, sink=sink, initiator_principal="control-plane")
    assert len(results) == 2
    assert all(r["submitted"] for r in results)  # type: ignore[index]
    assert [e["params"]["finding_id"] for e in sink.received] == ["f0", "f1"]
    assert all(e["action_type"] == ACTION_TYPE for e in sink.received)


async def test_submit_nothing_for_escalated() -> None:
    outcome = ReassemblyOutcome(
        status=ReassemblyStatus.ESCALATED, reason=ReassemblyReason.NON_CONVERGENT
    )
    sink = _RecordingSink()
    results = await submit_toggle_proposals(outcome, sink=sink, initiator_principal="cp")
    assert results == ()
    assert sink.received == []


async def test_submit_propagates_sink_error_fail_closed() -> None:
    outcome = _cleared(_toggle("f0", "compute", {"a": "1"}))

    async def _boom(_envelope):  # type: ignore[no-untyped-def]
        raise RuntimeError("pipeline down")

    with pytest.raises(RuntimeError, match="pipeline down"):
        await submit_toggle_proposals(outcome, sink=_boom, initiator_principal="cp")
