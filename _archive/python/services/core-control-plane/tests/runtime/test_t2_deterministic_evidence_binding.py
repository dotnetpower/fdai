from __future__ import annotations

from dataclasses import replace

from fdai.composition import Container
from fdai.core.quality_gate import (
    DeterministicEvidenceKind,
    DeterministicEvidenceStatus,
    QualityCandidate,
)
from fdai.runtime.control_loop import _resolve_t2_deterministic_evidence_verifiers


def _candidate() -> QualityCandidate:
    return QualityCandidate(
        action_type="remediate.tag-add",
        target_resource_ref="resource-a",
        params={},
        cited_rule_ids=("rule-a",),
    )


def test_runtime_binds_both_evidence_families_to_explicit_unavailable_by_default(
    container: Container,
) -> None:
    verifiers = _resolve_t2_deterministic_evidence_verifiers(container)
    assert set(verifiers) == set(DeterministicEvidenceKind)
    for kind, verifier in verifiers.items():
        evidence = verifier.verify(_candidate())
        assert evidence.kind is kind
        assert evidence.status is DeterministicEvidenceStatus.UNAVAILABLE
        assert evidence.reason == f"{kind.value}_evidence_provider_unavailable"


def test_runtime_uses_injected_provider_neutral_evidence_verifiers(
    container: Container,
) -> None:
    defaults = tuple(_resolve_t2_deterministic_evidence_verifiers(container).values())
    configured = replace(container, t2_deterministic_evidence_verifiers=defaults)

    assert tuple(_resolve_t2_deterministic_evidence_verifiers(configured).values()) == defaults
