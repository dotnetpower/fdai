"""Focused L1-L5 replay proof for rule-to-decision lookup lineage."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import pytest
from fdai.core.control_loop._audit_helpers import write_t1_audit
from fdai.core.control_loop._learned_reuse import record_learned_reuse_advisory
from fdai.core.tiers.t0_deterministic import AbstainEvaluator, RuleIndex, T0Engine
from fdai.core.tiers.t0_deterministic.models import PipelineStage
from fdai.core.tiers.t1_lightweight import LearnedAction, T1Outcome, T1Tier
from fdai.core.tiers.t1_lightweight.testing import (
    DeterministicEmbeddingModel,
    InMemoryPatternLibrary,
)
from fdai.rule_catalog.schema.catalog_search import build_discovery_catalog_search_documents
from fdai.shared.contracts.models import Event, Rule
from fdai.shared.providers.catalog_search import catalog_search_document_digest

CATALOG_V1 = "catalog-v1"
CATALOG_V2 = "catalog-v2"
MODEL_V1 = "model-v1"
MODEL_V2 = "model-v2"
MODE_SHADOW = "shadow"
MODE_ENFORCE = "enforce"


class _AuditSink:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    async def append_audit_entry(self, entry: Mapping[str, Any]) -> None:
        self.entries.append(dict(entry))

    def audit_id(self, layer: str) -> str:
        payload = {"layer": layer, "ordinal": len(self.entries)}
        return (
            "audit:"
            + hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        )

    def append_layer(self, **entry: Any) -> str:
        audit_id = self.audit_id(str(entry["layer"]))
        self.entries.append({"audit_id": audit_id, **entry})
        return audit_id

    def by_id(self, audit_id: str) -> dict[str, Any]:
        for entry in self.entries:
            if entry.get("audit_id") == audit_id:
                return entry
        raise AssertionError(f"missing audit entry {audit_id!r}")


class _CountingFrontierModel:
    def __init__(self) -> None:
        self.calls = 0

    async def reason(self, *, signature: str, rule: Rule) -> Mapping[str, Any]:
        self.calls += 1
        return {
            "signature": signature,
            "rule_id": rule.id,
            "rule_version": rule.version,
            "decision": "abstain",
            "risk_gate_decision": "hil",
        }


async def _noop_emit_stage(**_kwargs: object) -> None:
    return None


@dataclass(frozen=True, slots=True)
class _LayeredSignature:
    base: str
    l2: str
    l4: str


class _ExactLearnedActionStore:
    def __init__(self) -> None:
        self._actions: dict[str, LearnedAction] = {}

    def put(self, signature: str, action: LearnedAction) -> None:
        self._actions[signature] = action

    def get(self, signature: str) -> LearnedAction | None:
        return self._actions.get(signature)


class _ExactResultCache:
    def __init__(self) -> None:
        self._items: dict[str, Mapping[str, Any]] = {}

    def put(self, signature: str, output: Mapping[str, Any]) -> None:
        self._items[signature] = dict(output)

    def get(self, signature: str) -> Mapping[str, Any] | None:
        hit = self._items.get(signature)
        return dict(hit) if hit is not None else None


def _rule() -> Rule:
    return Rule.model_validate(
        {
            "schema_version": "2.0.0",
            "id": "object-storage.public-access.deny",
            "version": "1.0.0",
            "source": "custom",
            "severity": "medium",
            "category": "security",
            "resource_type": "object-storage",
            "applies_to": ["object-storage"],
            "triggered_by": ["resource.configuration.observed"],
            "evaluates": ["property.object-storage.public_access"],
            "required_interfaces": ["Evaluable", "Remediable"],
            "submission_criteria": [
                {"kind": "resource_type_registered", "value": "object-storage"},
                {"kind": "property_exists", "value": "property.object-storage.public_access"},
            ],
            "check_logic": {"kind": "rego", "reference": "policies/object_storage/public.rego"},
            "remediation": {"template_ref": "remediation/object_storage/disable.tftpl"},
            "remediates": "remediate.disable-public-access",
            "provenance": {
                "source_url": "https://example.com/rules/object-storage-public-access",
                "resolved_ref": "rule:object-storage.public-access.deny@1.0.0",
                "content_hash": "sha256:" + "1" * 64,
                "license": "MIT",
                "redistribution": "embeddable",
                "retrieved_at": "2026-10-04T00:00:00Z",
            },
        }
    )


def _event() -> Event:
    return Event.model_validate(
        {
            "schema_version": "1.0.0",
            "event_id": "00000000-0000-0000-0000-000000000321",
            "idempotency_key": "layered-replay-event",
            "source": "unit-test",
            "event_type": "resource.configuration.observed",
            "detected_at": "2026-10-04T00:00:00Z",
            "ingested_at": "2026-10-04T00:00:01Z",
            "mode": MODE_SHADOW,
            "payload": {
                "resource": {
                    "id": "example-object-storage",
                    "type": "object-storage",
                    "props": {"public_access": True, "unrelated": "ignored"},
                }
            },
        }
    )


def _hash(value: Mapping[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
        ).hexdigest()
    )


def _signatures(
    *,
    event: Event,
    rule: Rule,
    catalog_version: str,
    model_config_version: str,
    mode: str,
) -> _LayeredSignature:
    payload = event.payload
    resource = payload["resource"]
    assert isinstance(resource, Mapping)
    props = resource["props"]
    assert isinstance(props, Mapping)
    base = _hash(
        {
            "signal_type": event.event_type,
            "signal_params": {},
            "resource_type": resource["type"],
            "resource_props": {"public_access": props["public_access"]},
            "rule_id": rule.id,
            "rule_version": rule.version,
            "catalog_version": catalog_version,
            "mode": mode,
        }
    )
    l4 = _hash({"base": base, "model_config_version": model_config_version})
    return _LayeredSignature(base=base, l2=base, l4=l4)


def _event_resource(event: Event) -> tuple[str, str, Mapping[str, Any]]:
    resource = event.payload["resource"]
    assert isinstance(resource, Mapping)
    props = resource["props"]
    assert isinstance(props, Mapping)
    return str(resource["id"]), str(resource["type"]), props


async def _run_l1(
    *,
    event: Event,
    rule: Rule,
    audit: _AuditSink,
) -> None:
    documents = build_discovery_catalog_search_documents((rule,))
    assert len(documents) == 1
    audit.append_layer(
        layer="catalog_search",
        rule_id=rule.id,
        document_digest=catalog_search_document_digest(documents[0]),
        terminal=False,
    )

    resource_id, resource_type, props = _event_resource(event)
    verdict = T0Engine(
        index=RuleIndex.build((rule,)),
        evaluator=AbstainEvaluator(),
    ).evaluate(
        event_id=str(event.event_id),
        signal_id=str(event.event_id),
        resource_id=resource_id,
        resource_type=resource_type,
        resource_props=props,
        signal_type=event.event_type,
    )
    assert verdict.audit_hint is not None
    assert verdict.audit_hint.pipeline_stage is PipelineStage.ABSTAIN
    audit.append_layer(
        layer="L1",
        pipeline_stage=verdict.audit_hint.pipeline_stage.value,
        rule_id=rule.id,
        rule_version=rule.version,
        terminal=False,
        reason=verdict.audit_hint.reason,
    )


async def _run_l3_similarity(
    *,
    event: Event,
    pattern_library: InMemoryPatternLibrary,
) -> None:
    decision = await T1Tier(
        embedding_model=DeterministicEmbeddingModel(),
        pattern_library=pattern_library,
    ).evaluate(event=event)
    assert decision.outcome is T1Outcome.ABSTAIN
    assert decision.reason == "no_neighbour_found"


async def _promote_verified_outcome(
    *,
    event: Event,
    rule: Rule,
    signatures: _LayeredSignature,
    origin_audit_id: str,
    learned_actions: _ExactLearnedActionStore,
    result_cache: _ExactResultCache,
    pattern_library: InMemoryPatternLibrary,
) -> None:
    action = LearnedAction(
        signature=signatures.l2,
        rule_id=rule.id,
        action_type=rule.remediates,
        params={},
        incident_id=origin_audit_id,
        success_rate=0.99,
        reuse_count=1,
    )
    learned_actions.put(signatures.l2, action)
    embed = DeterministicEmbeddingModel()
    from fdai.core.tiers.t1_lightweight.tier import _event_text  # type: ignore

    await pattern_library.upsert_pattern(
        vector=await embed.embed(_event_text(event)),
        action=action,
    )
    result_cache.put(
        signatures.l4,
        {
            "rule_id": rule.id,
            "rule_version": rule.version,
            "risk_gate_decision": "hil",
            "reused_from": origin_audit_id,
        },
    )


async def _assert_l2_reuse(
    *,
    event: Event,
    rule: Rule,
    signatures: _LayeredSignature,
    learned_actions: _ExactLearnedActionStore,
    audit: _AuditSink,
    origin_audit_id: str,
) -> None:
    action = learned_actions.get(signatures.l2)
    assert action is not None
    audit_id = audit.append_layer(
        layer="L2",
        rule_id=rule.id,
        rule_version=rule.version,
        signature=signatures.l2,
        match="exact_hit",
        reused_from=action.incident_id,
        terminal=True,
        risk_gate_decision="hil",
    )
    assert audit.by_id(str(audit.by_id(audit_id)["reused_from"]))["layer"] == "L5"
    assert action.incident_id == origin_audit_id

    embed = DeterministicEmbeddingModel()
    pattern_library = InMemoryPatternLibrary()
    from fdai.core.tiers.t1_lightweight.tier import _event_text  # type: ignore

    pattern_library.add(vector=await embed.embed(_event_text(event)), action=action)
    t1 = await T1Tier(embedding_model=embed, pattern_library=pattern_library).evaluate(event=event)
    assert t1.outcome is T1Outcome.REUSED
    await write_t1_audit(
        audit,
        event=event,
        decision=type("Decision", (), {"resource_type": rule.resource_type})(),
        t1=t1,
    )
    await record_learned_reuse_advisory(
        audit,
        _noop_emit_stage,
        event=event,
        decision=type("Decision", (), {"resource_type": rule.resource_type})(),
        t1=t1,
        cs_decision=None,
        event_id=str(event.event_id),
        correlation_id=str(event.event_id),
    )
    assert audit.entries[-2]["t1_best_match"]["reused_from"] == origin_audit_id
    assert audit.entries[-1]["reused_from"] == origin_audit_id


def _assert_l4_reuse(
    *,
    rule: Rule,
    signatures: _LayeredSignature,
    result_cache: _ExactResultCache,
    audit: _AuditSink,
    origin_audit_id: str,
) -> None:
    output = result_cache.get(signatures.l4)
    assert output is not None
    audit_id = audit.append_layer(
        layer="L4",
        rule_id=rule.id,
        rule_version=rule.version,
        signature=signatures.l4,
        match="cache_hit",
        reused_from=output["reused_from"],
        terminal=True,
        risk_gate_decision=output["risk_gate_decision"],
    )
    assert audit.by_id(str(audit.by_id(audit_id)["reused_from"]))["layer"] == "L5"
    assert output["reused_from"] == origin_audit_id


def _assert_reuse_misses_after_identity_changes(
    *,
    event: Event,
    rule: Rule,
    learned_actions: _ExactLearnedActionStore,
    result_cache: _ExactResultCache,
) -> None:
    changed_catalog = _signatures(
        event=event,
        rule=rule,
        catalog_version=CATALOG_V2,
        model_config_version=MODEL_V1,
        mode=MODE_SHADOW,
    )
    changed_model = _signatures(
        event=event,
        rule=rule,
        catalog_version=CATALOG_V1,
        model_config_version=MODEL_V2,
        mode=MODE_SHADOW,
    )
    changed_mode = _signatures(
        event=event,
        rule=rule,
        catalog_version=CATALOG_V1,
        model_config_version=MODEL_V1,
        mode=MODE_ENFORCE,
    )
    assert learned_actions.get(changed_catalog.l2) is None
    assert learned_actions.get(changed_mode.l2) is None
    assert result_cache.get(changed_catalog.l4) is None
    assert result_cache.get(changed_model.l4) is None
    assert result_cache.get(changed_mode.l4) is None


@pytest.mark.asyncio
async def test_layered_replay_audits_l1_to_l5_and_reuse_backreferences() -> None:
    event = _event()
    rule = _rule()
    signatures = _signatures(
        event=event,
        rule=rule,
        catalog_version=CATALOG_V1,
        model_config_version=MODEL_V1,
        mode=MODE_SHADOW,
    )
    audit = _AuditSink()
    model = _CountingFrontierModel()
    learned_actions = _ExactLearnedActionStore()
    result_cache = _ExactResultCache()
    pattern_library = InMemoryPatternLibrary()

    await _run_l1(event=event, rule=rule, audit=audit)
    assert learned_actions.get(signatures.l2) is None
    await _run_l3_similarity(event=event, pattern_library=pattern_library)
    assert result_cache.get(signatures.l4) is None

    reasoned = await model.reason(signature=signatures.l4, rule=rule)
    origin_audit_id = audit.append_layer(
        layer="L5",
        rule_id=reasoned["rule_id"],
        rule_version=reasoned["rule_version"],
        signature=signatures.l4,
        frontier_model_invoked=True,
        terminal=True,
        risk_gate_decision=reasoned["risk_gate_decision"],
    )
    await _promote_verified_outcome(
        event=event,
        rule=rule,
        signatures=signatures,
        origin_audit_id=origin_audit_id,
        learned_actions=learned_actions,
        result_cache=result_cache,
        pattern_library=pattern_library,
    )

    await _assert_l2_reuse(
        event=event,
        rule=rule,
        signatures=signatures,
        learned_actions=learned_actions,
        audit=audit,
        origin_audit_id=origin_audit_id,
    )
    _assert_l4_reuse(
        rule=rule,
        signatures=signatures,
        result_cache=result_cache,
        audit=audit,
        origin_audit_id=origin_audit_id,
    )
    _assert_reuse_misses_after_identity_changes(
        event=event,
        rule=rule,
        learned_actions=learned_actions,
        result_cache=result_cache,
    )

    assert model.calls == 1
    assert [entry["layer"] for entry in audit.entries if entry.get("frontier_model_invoked")] == [
        "L5"
    ]
    terminal = [entry for entry in audit.entries if entry.get("terminal")]
    assert terminal
    assert all(entry.get("risk_gate_decision") for entry in terminal)
    assert all(
        audit.by_id(str(entry["reused_from"]))["layer"] == "L5"
        for entry in terminal
        if entry.get("layer") in {"L2", "L4"}
    )
