"""FeasibilityProbe types + the deterministic upstream probes."""

from __future__ import annotations

import pytest

from aiopspilot.shared.providers.feasibility_probe import (
    FeasibilityProbe,
    FindingSeverity,
    PreflightTarget,
    ProbeCategory,
    ProbeFinding,
    ResolutionKind,
)
from aiopspilot.shared.providers.local import (
    DenylistResourceTypeProbe,
    EgressDenylistProbe,
    ToggleResolution,
)


def test_probes_satisfy_protocol_structurally() -> None:
    disk = DenylistResourceTypeProbe(
        denied_types=frozenset({"compute.disk"}),
        policy_source="policy:not-allowed-resource-types",
    )
    egress = EgressDenylistProbe(
        blocked_hosts=frozenset({"registry-1.docker.io"}),
        firewall_source="nsg:hub/rule:deny-internet-out",
    )
    assert isinstance(disk, FeasibilityProbe)
    assert isinstance(egress, FeasibilityProbe)
    assert disk.category is ProbeCategory.POLICY_GUARDRAIL
    assert egress.category is ProbeCategory.SUPPLY_CHAIN_EGRESS


async def test_denylist_probe_maps_to_terraform_toggle() -> None:
    probe = DenylistResourceTypeProbe(
        denied_types=frozenset({"compute.disk"}),
        policy_source="policy:not-allowed-resource-types",
        resolutions={
            "compute.disk": ToggleResolution(
                module="compute",
                set_vars={"disk_provisioning": "attach_existing"},
                autofix=True,
            )
        },
    )
    target = PreflightTarget(scope="rg:example", resource_types=("compute.disk", "compute.vm"))

    findings = list(await probe.evaluate(target))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity is FindingSeverity.BLOCKING
    assert finding.resolution.kind is ResolutionKind.TERRAFORM_TOGGLE
    assert finding.resolution.module == "compute"
    assert finding.resolution.set_vars["disk_provisioning"] == "attach_existing"
    assert finding.resolution.autofix is True
    # Grounded: every finding cites its policy source.
    assert finding.evidence.source == "policy:not-allowed-resource-types"


async def test_denylist_probe_without_toggle_is_manual() -> None:
    probe = DenylistResourceTypeProbe(
        denied_types=frozenset({"object_storage.account"}),
        policy_source="policy:allowed-resource-types",
    )
    target = PreflightTarget(scope="rg:example", resource_types=("object_storage.account",))

    findings = list(await probe.evaluate(target))

    assert len(findings) == 1
    assert findings[0].resolution.kind is ResolutionKind.MANUAL
    assert findings[0].resolution.autofix is False


async def test_denylist_probe_ignores_allowed_types() -> None:
    probe = DenylistResourceTypeProbe(
        denied_types=frozenset({"compute.disk"}),
        policy_source="policy:not-allowed-resource-types",
    )
    target = PreflightTarget(scope="rg:example", resource_types=("compute.vm",))

    assert list(await probe.evaluate(target)) == []


async def test_egress_probe_maps_docker_io_to_mirror() -> None:
    probe = EgressDenylistProbe(
        blocked_hosts=frozenset({"registry-1.docker.io", "pypi.org"}),
        firewall_source="nsg:hub/rule:deny-internet-out",
        mirror_resolutions={
            "registry-1.docker.io": ToggleResolution(
                module="compute",
                set_vars={"registry_source": "acr_mirror"},
                autofix=True,
            )
        },
    )
    target = PreflightTarget(
        scope="rg:example",
        egress_hosts=("registry-1.docker.io", "pypi.org", "example.com"),
    )

    findings = {f.id: f for f in await probe.evaluate(target)}

    assert set(findings) == {
        "blocked-egress:registry-1.docker.io",
        "blocked-egress:pypi.org",
    }
    docker = findings["blocked-egress:registry-1.docker.io"]
    assert docker.resolution.set_vars["registry_source"] == "acr_mirror"
    # pypi has no registered mirror -> manual guidance, not an autofix.
    assert findings["blocked-egress:pypi.org"].resolution.kind is ResolutionKind.MANUAL


def test_finding_to_dict_is_json_friendly() -> None:
    finding = ProbeFinding(
        id="x",
        category=ProbeCategory.POLICY_GUARDRAIL,
        severity=FindingSeverity.BLOCKING,
        title="t",
        evidence=probe_evidence(),
        resolution=probe_resolution(),
    )
    payload = finding.to_dict()
    assert payload["category"] == "policy_guardrail"
    assert payload["severity"] == "blocking"
    assert payload["resolution"]["kind"] == "manual"


def probe_evidence():
    from aiopspilot.shared.providers.feasibility_probe import ProbeEvidence

    return ProbeEvidence(source="policy:x", detail="d")


def probe_resolution():
    from aiopspilot.shared.providers.feasibility_probe import ProbeResolution

    return ProbeResolution(kind=ResolutionKind.MANUAL)


def test_finding_is_frozen() -> None:
    finding = ProbeFinding(
        id="x",
        category=ProbeCategory.POLICY_GUARDRAIL,
        severity=FindingSeverity.BLOCKING,
        title="t",
        evidence=probe_evidence(),
        resolution=probe_resolution(),
    )
    with pytest.raises((AttributeError, TypeError)):
        finding.id = "y"  # type: ignore[misc]
