"""Escalation chain, channel bridge, group expansion, workflow-change tests."""

from __future__ import annotations

from fdai.core.stewardship import (
    EscalationTier,
    StaticGroupMembershipProvider,
    affected_agents_from_stewardship_change,
    affected_agents_from_workflow,
    build_escalation_plan,
    load_stewardship_from_mapping,
    resolve_person_channel,
    stakeholders_for_change,
)


def test_mapped_agent_chain_is_accountable_then_maintainer(valid_raw: dict) -> None:
    mp = load_stewardship_from_mapping(valid_raw)
    plan = build_escalation_plan(mp, "Thor")
    tiers = [r.tier for r in plan.recipients]
    assert tiers[0] is EscalationTier.ACCOUNTABLE
    assert EscalationTier.MAINTAINER in tiers
    assert plan.hop_timeout_seconds == 900


def test_autonomous_agent_chain_is_maintainer_only(valid_raw: dict) -> None:
    mp = load_stewardship_from_mapping(valid_raw)
    plan = build_escalation_plan(mp, "Loki")
    assert {r.tier for r in plan.recipients} == {EscalationTier.MAINTAINER}


def test_resolve_person_channel_explicit_wins(valid_raw: dict, oid) -> None:
    valid_raw["stewardship"]["channels"] = {oid(1): "teams-personal"}
    mp = load_stewardship_from_mapping(valid_raw)
    assert resolve_person_channel(mp, oid(1), "teams-ops-prd") == "teams-personal"
    assert resolve_person_channel(mp, oid(999), "teams-ops-prd") == "teams-ops-prd"


async def test_expand_group_recipients(valid_raw: dict, oid) -> None:
    valid_raw["stewardship"]["agents"]["Thor"] = {
        "stewards": [{"kind": "group", "id": oid(700), "responsibility": "accountable"}]
    }
    mp = load_stewardship_from_mapping(valid_raw)
    plan = build_escalation_plan(mp, "Thor")
    provider = StaticGroupMembershipProvider({oid(700): (oid(701), oid(702))})
    users = await plan_expand(plan, provider)
    assert oid(701) in users and oid(702) in users


async def test_expand_group_unknown_group_kept_opaque(valid_raw: dict, oid) -> None:
    valid_raw["stewardship"]["agents"]["Thor"] = {
        "stewards": [{"kind": "group", "id": oid(800), "responsibility": "accountable"}]
    }
    mp = load_stewardship_from_mapping(valid_raw)
    plan = build_escalation_plan(mp, "Thor")
    provider = StaticGroupMembershipProvider({})  # unknown group
    users = await plan_expand(plan, provider)
    assert oid(800) in users  # opaque unit, still notified


def test_affected_agents_from_workflow() -> None:
    workflow = {
        "name": "dr-drill",
        "steps": [{"owner": "Vidar"}, {"advisor": "Freyr"}],
        "note": "no agent here",
    }
    assert affected_agents_from_workflow(workflow) == frozenset({"Vidar", "Freyr"})


def test_affected_agents_from_stewardship_change_is_precise(valid_raw: dict, oid) -> None:
    before = load_stewardship_from_mapping(valid_raw)
    valid_raw["stewardship"]["agents"]["Thor"]["stewards"][0]["id"] = oid(999)
    after = load_stewardship_from_mapping(valid_raw)

    assert affected_agents_from_stewardship_change(before, after) == frozenset({"Thor"})


def test_global_stewardship_change_affects_every_agent(valid_raw: dict) -> None:
    before = load_stewardship_from_mapping(valid_raw)
    valid_raw["stewardship"]["escalation"]["hop_timeout_seconds"] = 120
    after = load_stewardship_from_mapping(valid_raw)

    assert len(affected_agents_from_stewardship_change(before, after)) == 15


def test_stakeholders_for_change_unions_and_dedups(valid_raw: dict) -> None:
    mp = load_stewardship_from_mapping(valid_raw)
    recips = stakeholders_for_change(mp, ["Thor", "Njord"])
    ids = [r.id for r in recips]
    assert len(ids) == len(set(ids))  # de-duplicated
    tiers = {r.tier for r in recips}
    assert EscalationTier.MAINTAINER in tiers


# Helper kept module-local to exercise the async expander through the facade.
async def plan_expand(plan, provider):
    from fdai.core.stewardship import expand_group_recipients

    return await expand_group_recipients(plan, provider)
