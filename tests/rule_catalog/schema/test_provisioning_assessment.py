"""Unit tests for :mod:`fdai.rule_catalog.schema.provisioning_assessment`."""

from __future__ import annotations

from typing import Any

from fdai.rule_catalog.schema.llm_registry import load_llm_registry_from_mapping
from fdai.rule_catalog.schema.llm_resolver import (
    CapabilityStatus,
    ResolvedCapability,
    ResolvedModels,
)
from fdai.rule_catalog.schema.provisioning_assessment import (
    CapabilityTier,
    ProvisioningSeverity,
    ProvisioningState,
    assess_provisioning,
)

_REGION = "koreacentral"
_ZERO = "00000000-0000-0000-0000-000000000000"


def _registry(mode: str = "azure-foundry") -> Any:
    raw = {
        "schema_version": "1.0.0",
        "mixed_model_mode": mode,
        "models": {
            "t1.embedding": {
                "preferences": [{"publisher": "OpenAI", "family": "text-embedding-3-small"}],
                "capacity_tpm": 100_000,
            },
            "t1.judge": {
                "preferences": [{"publisher": "OpenAI", "family": "gpt-4o-mini"}],
                "capacity_tpm": 40_000,
            },
            "t2.reasoner.primary": {
                "preferences": [{"publisher": "OpenAI", "family": "gpt-4o"}],
                "capacity_tpm": 20_000,
            },
            "t2.reasoner.secondary": {
                "preferences": [{"publisher": "Anthropic", "family": "claude-opus-4"}],
                "capacity_tpm": 10_000,
            },
            "t2.critic": {
                "preferences": [{"publisher": "Anthropic", "family": "claude-opus-4"}],
                "capacity_tpm": 5_000,
                "invocation": "on_disagreement",
            },
        },
    }
    return load_llm_registry_from_mapping(raw)


def _cap(name: str, status: CapabilityStatus = CapabilityStatus.RESOLVED) -> ResolvedCapability:
    return ResolvedCapability(
        name=name,
        status=status,
        publisher="OpenAI",
        family="fam",
        sku="Standard",
        capacity_tpm=1000,
        invocation="always",
    )


def _resolved(
    names: dict[str, CapabilityStatus],
    *,
    mode: str = "azure-foundry",
) -> ResolvedModels:
    return ResolvedModels(
        schema_version="1.0.0",
        region=_REGION,
        subscription_id=_ZERO,
        deployer_object_id=_ZERO,
        mixed_model_mode=mode,
        capabilities=tuple(_cap(n, s) for n, s in names.items()),
    )


_ALL = {
    "t1.embedding": CapabilityStatus.RESOLVED,
    "t1.judge": CapabilityStatus.RESOLVED,
    "t2.reasoner.primary": CapabilityStatus.RESOLVED,
    "t2.reasoner.secondary": CapabilityStatus.RESOLVED,
    "t2.critic": CapabilityStatus.RESOLVED,
}


def test_fully_provisioned_is_ok() -> None:
    report = assess_provisioning(registry=_registry(), resolved=_resolved(_ALL))
    assert report.severity is ProvisioningSeverity.OK
    assert report.is_complete is True
    assert report.quorum_ok is True
    assert report.reasons == ()
    assert report.degraded == ()


def test_secondary_missing_is_critical_and_breaks_quorum() -> None:
    subset = dict(_ALL)
    del subset["t2.reasoner.secondary"]
    report = assess_provisioning(registry=_registry(), resolved=_resolved(subset))
    assert report.severity is ProvisioningSeverity.CRITICAL
    assert report.quorum_ok is False
    names = {a.name: a for a in report.capabilities}
    assert names["t2.reasoner.secondary"].state is ProvisioningState.MISSING
    assert names["t2.reasoner.secondary"].tier is CapabilityTier.QUORUM
    assert any("t2.quorum:unavailable" in r for r in report.reasons)


def test_matches_the_shipped_partial_dev_deployment() -> None:
    # The real dev resolved-models.json ships only 3 of the declared caps.
    subset = {
        "t1.embedding": CapabilityStatus.RESOLVED,
        "t1.judge": CapabilityStatus.RESOLVED,
        "t2.reasoner.primary": CapabilityStatus.RESOLVED,
    }
    report = assess_provisioning(registry=_registry(), resolved=_resolved(subset))
    assert report.severity is ProvisioningSeverity.CRITICAL
    assert report.quorum_ok is False


def test_only_optional_missing_is_degraded() -> None:
    subset = dict(_ALL)
    del subset["t2.critic"]
    report = assess_provisioning(registry=_registry(), resolved=_resolved(subset))
    assert report.severity is ProvisioningSeverity.DEGRADED
    assert report.quorum_ok is True
    names = {a.name: a for a in report.capabilities}
    assert names["t2.critic"].tier is CapabilityTier.OPTIONAL
    assert names["t2.critic"].impact is not None


def test_core_hil_only_is_critical() -> None:
    subset = dict(_ALL)
    subset["t2.reasoner.primary"] = CapabilityStatus.HIL_ONLY
    report = assess_provisioning(registry=_registry(), resolved=_resolved(subset))
    assert report.severity is ProvisioningSeverity.CRITICAL
    names = {a.name: a for a in report.capabilities}
    assert names["t2.reasoner.primary"].state is ProvisioningState.HIL_ONLY


def test_capacity_reduced_still_available() -> None:
    subset = dict(_ALL)
    subset["t2.reasoner.secondary"] = CapabilityStatus.CAPACITY_REDUCED
    report = assess_provisioning(registry=_registry(), resolved=_resolved(subset))
    assert report.severity is ProvisioningSeverity.OK
    assert report.quorum_ok is True


def test_hil_only_mode_does_not_flag_missing_secondary() -> None:
    subset = {
        "t1.embedding": CapabilityStatus.RESOLVED,
        "t1.judge": CapabilityStatus.RESOLVED,
        "t2.reasoner.primary": CapabilityStatus.RESOLVED,
        "t2.critic": CapabilityStatus.RESOLVED,
    }
    report = assess_provisioning(
        registry=_registry(mode="hil-only"),
        resolved=_resolved(subset, mode="hil-only"),
    )
    # secondary missing, but hil-only mode expects no quorum -> not critical.
    assert report.severity is ProvisioningSeverity.DEGRADED
    assert report.quorum_ok is False
