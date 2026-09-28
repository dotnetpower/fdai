"""A verifier trust anchor must be exclusive, so separation checks can't skip an independent one."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from fdai.core.operational_evidence.registry_json import content_pin
from fdai.core.operational_evidence.separation import (
    VerifierSeparationError,
    assert_verifier_separation,
)
from fdai.core.operational_evidence.trust_registry import (
    TrustRegistry,
    VerifierEntry,
    purpose_defects,
)
from fdai.core.operational_evidence.trust_registry_loader import load_trust_registry
from tests.core.operational_evidence.support import NOW, anchors, encode, trust_bytes

_COMMAND = "operator-test-context-command"
_VERIFIER = "operational-evidence-verifier"
_VERIFIER_ANCHOR = "anchor:operational-evidence-verifier"


def _load(document: dict[str, Any]) -> TrustRegistry:
    data = encode(document)
    return load_trust_registry(data, expected_pin=content_pin(data))


def _add_binding(entry: dict[str, Any], trust_anchor_id: str) -> None:
    entry["verifiers"].append(
        {
            **entry["verifiers"][0],
            "verifier_version": "1.1.0",
            "trust_anchor_id": trust_anchor_id,
            "valid_from": NOW.isoformat(),
        }
    )


def _defects(registry: TrustRegistry, purpose: str = _COMMAND) -> tuple[str, ...]:
    return purpose_defects(
        registry,
        anchors(overrides={_VERIFIER_ANCHOR: "fdai_core"}),
        purpose_id=purpose,
        verifier_id=_VERIFIER,
        at=NOW,
        verifier_version="1.0.0",
    )


def test_binding_on_an_independent_anchor_cannot_hide_a_shared_identity() -> None:
    assert _defects(_load(json.loads(trust_bytes()))) == ("self_verified",)
    document = json.loads(trust_bytes())
    for entry in document["purposes"]:
        _add_binding(entry, "anchor:core-runtime")
    registry = _load(document)
    assert registry.purposes == {}
    for entry in document["purposes"]:
        purpose = entry["purpose_id"]
        assert registry.defects[purpose] == ("verifier_anchor_not_exclusive",)
        assert _defects(registry, purpose) == ("verifier_anchor_not_exclusive",)


@pytest.mark.parametrize("kind", ["producers", "sources", "separation"])
def test_verifier_anchor_reused_by_any_independent_role_leaves_the_purpose_unavailable(
    kind: str,
) -> None:
    document = json.loads(trust_bytes())
    entry = next(item for item in document["purposes"] if item["purpose_id"] == _COMMAND)
    producer = entry["producers"][0]["anchor_id"]
    sources = {item["anchor_id"] for item in entry["sources"]}
    if kind == "producers":
        entry["separation"] = [item for item in entry["separation"] if item != producer]
        shared = producer
    elif kind == "sources":
        shared = next(iter(sorted(sources)))
    else:
        shared = next(item for item in entry["separation"] if item not in sources | {producer})
    _add_binding(entry, shared)
    registry = _load(document)
    assert registry.defects[_COMMAND] == ("verifier_anchor_not_exclusive",)
    assert _COMMAND not in registry.purposes
    assert "operational-test-context" in registry.purposes


def test_separation_checks_skip_only_anchors_used_exclusively_by_verifier_bindings() -> None:
    loaded = _load(json.loads(trust_bytes()))
    entry = loaded.purposes[_COMMAND]
    shared = VerifierEntry(
        verifier_id=_VERIFIER,
        verifier_version="1.1.0",
        trust_anchor_id="anchor:core-runtime",
        window=entry.verifiers[0].window,
    )
    widened = replace(entry, verifiers=(*entry.verifiers, shared))
    registry = replace(loaded, purposes={_COMMAND: widened}, defects={})
    assert widened.shared_verifier_anchors() == {"anchor:core-runtime"}
    assert _defects(registry) == ("self_verified",)
    with pytest.raises(VerifierSeparationError):
        assert_verifier_separation(
            registry,
            anchors(overrides={_VERIFIER_ANCHOR: "fdai_core"}),
            verifier_principal="fdai_core",
            executor_class_principals=(),
        )


def test_upstream_forecast_context_reuses_the_verifier_anchor_and_stays_unavailable() -> None:
    registry = _load(json.loads(trust_bytes()))
    assert registry.defects == {"forecast-context": ("verifier_anchor_not_exclusive",)}
    assert_verifier_separation(
        registry,
        anchors(),
        verifier_principal="fdai_operational_evidence_verifier",
        executor_class_principals=(),
    )
