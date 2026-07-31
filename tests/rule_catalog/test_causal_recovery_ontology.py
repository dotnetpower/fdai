from __future__ import annotations

from pathlib import Path

from fdai.rule_catalog.schema.ontology_catalog import load_ontology_catalog
from fdai.shared.contracts.models import LifecycleOwner
from fdai.shared.contracts.registry import PackageResourceSchemaRegistry

_ROOT = Path(__file__).resolve().parents[2]


def _catalog():  # type: ignore[no-untyped-def]
    return load_ontology_catalog(
        _ROOT / "rule-catalog",
        schema_registry=PackageResourceSchemaRegistry(),
        probes_root=_ROOT / "rule-catalog" / "probes",
    )


def test_causal_recovery_object_types_are_complete_and_owned() -> None:
    by_name = {item.name: item for item in _catalog().object_types}
    expected_owners = {
        "Incident": LifecycleOwner.HEIMDALL,
        "Observation": LifecycleOwner.HUGINN,
        "Change": LifecycleOwner.HUGINN,
        "Experiment": LifecycleOwner.LOKI,
        "DecisionCase": LifecycleOwner.FORSETI,
        "ActionOption": LifecycleOwner.FORSETI,
        "ExpectedEffect": LifecycleOwner.FORSETI,
        "ActionRun": LifecycleOwner.THOR,
        "ObservedOutcome": LifecycleOwner.HEIMDALL,
        "CausalHypothesis": LifecycleOwner.FORSETI,
        "ImpactEnvelope": LifecycleOwner.FORSETI,
        "RecoveryPlan": LifecycleOwner.VIDAR,
    }

    assert set(expected_owners) <= set(by_name)
    assert {
        name: by_name[name].lifecycle.owner if by_name[name].lifecycle else None
        for name in expected_owners
    } == expected_owners


def test_causal_recovery_links_have_exact_endpoints_and_semantics() -> None:
    by_name = {item.name: item for item in _catalog().link_types}
    expected = {
        "hypothesis_explains_finding": ("CausalHypothesis", "Finding", True, False),
        "hypothesis_claims_change": ("CausalHypothesis", "Change", True, False),
        "hypothesis_claims_experiment": ("CausalHypothesis", "Experiment", True, False),
        "evidence_supports_hypothesis": (
            "EvidenceArtifact",
            "CausalHypothesis",
            False,
            False,
        ),
        "evidence_refutes_hypothesis": (
            "EvidenceArtifact",
            "CausalHypothesis",
            False,
            False,
        ),
        "hypothesis_precedes_hypothesis": (
            "CausalHypothesis",
            "CausalHypothesis",
            False,
            True,
        ),
        "outcome_tests_hypothesis": ("ObservedOutcome", "CausalHypothesis", True, False),
        "envelope_bounds_experiment": ("ImpactEnvelope", "Experiment", False, False),
        "envelope_bounds_action_option": (
            "ImpactEnvelope",
            "ActionOption",
            False,
            False,
        ),
        "envelope_protects_objective": (
            "ImpactEnvelope",
            "ServiceObjective",
            False,
            False,
        ),
        "recovery_addresses_hypothesis": (
            "RecoveryPlan",
            "CausalHypothesis",
            True,
            False,
        ),
        "recovery_targets_resource": ("RecoveryPlan", "Resource", False, False),
        "recovery_realized_as_process": ("RecoveryPlan", "Process", False, False),
        "outcome_evaluates_envelope": (
            "ObservedOutcome",
            "ImpactEnvelope",
            False,
            False,
        ),
    }

    assert set(expected) <= set(by_name)
    assert {
        name: (
            by_name[name].from_type,
            by_name[name].to_type,
            by_name[name].is_causal,
            by_name[name].temporal_order,
        )
        for name in expected
    } == expected
    assert by_name["hypothesis_precedes_hypothesis"].order_by_property == "created_at"
