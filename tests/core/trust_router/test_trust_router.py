"""TrustRouter - P1 routing surface tests."""

from __future__ import annotations

from typing import Any

import pytest

from fdai.core.tiers.t0_deterministic.index import RuleIndex
from fdai.core.trust_router import RoutingTier, TrustRouter
from fdai.shared.contracts.models import (
    Category,
    CheckLogic,
    CheckLogicKind,
    Event,
    Provenance,
    Redistribution,
    Remediation,
    Rule,
    RuleSource,
    Severity,
)


def _rule(
    rule_id: str,
    resource_type: str,
    *,
    triggered_by: list[str] | None = None,
) -> Rule:
    return Rule(
        schema_version="1.0.0",
        id=rule_id,
        version="1.0.0",
        source=RuleSource.CUSTOM,
        severity=Severity.HIGH,
        category=Category.SECURITY,
        resource_type=resource_type,
        applies_to=[resource_type],
        triggered_by=triggered_by or ["*"],
        check_logic=CheckLogic(kind=CheckLogicKind.REGO, reference="policies/x.rego"),
        remediation=Remediation(template_ref="remediation/x.tftpl"),
        remediates="remediate.tag-add",
        provenance=Provenance(
            source_url="https://example.com/x",
            resolved_ref="0" * 40,
            content_hash="sha256:0",
            license="MIT",
            redistribution=Redistribution.EMBEDDABLE,
            retrieved_at="2026-07-05T00:00:00Z",  # type: ignore[arg-type]
        ),
    )


def _index(rules: list[Rule]) -> RuleIndex:
    return RuleIndex.build(rules)


def _event(payload: dict[str, Any]) -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000001",
            "idempotency_key": "k1",
            "source": "example_source",
            "event_type": "change_detected",
            "detected_at": "2026-07-05T08:00:00Z",
            "ingested_at": "2026-07-05T08:00:01Z",
            "mode": "shadow",
            "payload": payload,
        }
    )


def test_routes_to_t0_when_resource_type_matches_a_rule() -> None:
    router = TrustRouter(index=_index([_rule("r.x", "compute.vm")]))
    decision = router.route(_event({"resource": {"type": "compute.vm"}}))
    assert decision.tier is RoutingTier.T0
    assert decision.resource_type == "compute.vm"
    assert decision.candidate_rule_ids == ("r.x",)
    assert decision.reason is None


def test_abstains_when_payload_lacks_resource_type() -> None:
    router = TrustRouter(index=_index([_rule("r.x", "compute.vm")]))
    decision = router.route(_event({}))
    assert decision.tier is RoutingTier.ABSTAIN
    assert decision.resource_type is None
    assert decision.candidate_rule_ids == ()
    assert decision.reason == "event_payload_missing_resource_type"


def test_routes_t1_when_no_rule_matches_known_resource_type() -> None:
    router = TrustRouter(index=_index([_rule("r.x", "compute.vm")]))
    decision = router.route(_event({"resource": {"type": "object-storage"}}))
    assert decision.tier is RoutingTier.T1
    assert decision.resource_type == "object-storage"
    assert decision.candidate_rule_ids == ()
    assert decision.reason == "no_rule_matches_resource_and_signal_type"


def test_routes_t1_when_resource_matches_but_signal_does_not() -> None:
    router = TrustRouter(
        index=_index([_rule("r.x", "compute.vm", triggered_by=["availability.probe_failed"])])
    )
    decision = router.route(_event({"resource": {"type": "compute.vm"}}))
    assert decision.tier is RoutingTier.T1
    assert decision.candidate_rule_ids == ()
    assert decision.reason == "no_rule_matches_resource_and_signal_type"


def test_flat_resource_type_key_is_accepted() -> None:
    router = TrustRouter(index=_index([_rule("r.x", "compute.vm")]))
    decision = router.route(_event({"resource_type": "compute.vm"}))
    assert decision.tier is RoutingTier.T0


def test_non_string_resource_type_is_treated_as_missing() -> None:
    router = TrustRouter(index=_index([_rule("r.x", "compute.vm")]))
    decision = router.route(_event({"resource": {"type": 42}}))
    assert decision.tier is RoutingTier.ABSTAIN


@pytest.mark.parametrize("payload", [{"resource": {}}, {"resource": None}])
def test_empty_or_missing_resource_dict_abstains(payload: dict[str, Any]) -> None:
    router = TrustRouter(index=_index([_rule("r.x", "compute.vm")]))
    decision = router.route(_event(payload))
    assert decision.tier is RoutingTier.ABSTAIN


def test_multiple_matching_rules_are_all_reported_as_candidates() -> None:
    router = TrustRouter(
        index=_index(
            [
                _rule("r.a", "compute.vm"),
                _rule("r.b", "compute.vm"),
                _rule("r.c", "object-storage"),  # different type
            ]
        )
    )
    decision = router.route(_event({"resource": {"type": "compute.vm"}}))
    assert set(decision.candidate_rule_ids) == {"r.a", "r.b"}
