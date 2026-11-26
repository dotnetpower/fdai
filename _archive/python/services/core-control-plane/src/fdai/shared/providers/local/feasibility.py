"""Deterministic, config-driven FeasibilityProbe implementations.

These are the **upstream default** probes: no network, no cloud
credentials, fully reproducible. They realize the
:class:`~fdai.shared.providers.feasibility_probe.FeasibilityProbe`
Protocol from declarative denylists supplied at construction time, so a
laptop with no Azure access can exercise the whole preflight pass offline
(same intent as :mod:`fdai.shared.providers.local.inventory`).

A live Azure adapter (Policy Insights / Firewall / Quota) lands under
``delivery/azure/`` later and replaces these at the composition root; the
:class:`PreflightAnalyzer` never changes.

Customer-agnostic
-----------------
No denylist value is baked in upstream. The denied resource types, blocked
egress hosts, and the terraform-toggle resolution map are all passed in by
the composition root / a fork from config, so this module stays generic
(see ``.github/instructions/generic-scope.instructions.md``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from fdai.shared.providers.feasibility_probe import (
    FindingSeverity,
    PreflightTarget,
    ProbeCategory,
    ProbeEvidence,
    ProbeFinding,
    ProbeResolution,
    ResolutionKind,
)


@dataclass(frozen=True, slots=True)
class ToggleResolution:
    """A terraform-toggle resolution template for a denied resource type.

    ``module`` + ``set_vars`` describe how to make a deployment comply by
    provisioning the resource out-of-line (e.g. attach an existing disk
    instead of creating one inline). ``autofix`` marks whether the analyzer
    may propose it as a remediation PR without human judgment.
    """

    module: str
    set_vars: Mapping[str, str]
    autofix: bool = False


@dataclass(frozen=True, slots=True)
class DenylistResourceTypeProbe:
    """POLICY_GUARDRAIL probe: deny inline creation of listed resource types.

    Models the Azure Policy ``Not allowed resource types`` / ``Allowed
    resource types`` deny guardrails (see the roadmap doc). When a target
    plans to create a denied resource type, the probe emits a blocking
    finding and, if a :class:`ToggleResolution` is registered for that
    type, maps it to the terraform toggle that provisions the resource
    out-of-line instead.
    """

    denied_types: frozenset[str]
    policy_source: str
    resolutions: Mapping[str, ToggleResolution] = field(default_factory=dict)

    @property
    def category(self) -> ProbeCategory:
        return ProbeCategory.POLICY_GUARDRAIL

    async def evaluate(self, target: PreflightTarget) -> Sequence[ProbeFinding]:
        findings: list[ProbeFinding] = []
        for rtype in target.resource_types:
            if rtype not in self.denied_types:
                continue
            toggle = self.resolutions.get(rtype)
            if toggle is None:
                resolution = ProbeResolution(
                    kind=ResolutionKind.MANUAL,
                    guidance=(
                        f"resource type {rtype!r} is denied by policy in this "
                        "scope; provision it through the approved out-of-line "
                        "process or request a scoped exemption"
                    ),
                )
            else:
                resolution = ProbeResolution(
                    kind=ResolutionKind.TERRAFORM_TOGGLE,
                    autofix=toggle.autofix,
                    module=toggle.module,
                    set_vars=dict(toggle.set_vars),
                )
            findings.append(
                ProbeFinding(
                    id=f"denied-resource-type:{rtype}",
                    category=ProbeCategory.POLICY_GUARDRAIL,
                    severity=FindingSeverity.BLOCKING,
                    title=f"Inline creation of {rtype} is denied by policy",
                    evidence=ProbeEvidence(
                        source=self.policy_source,
                        detail=f"deny effect matches resource type {rtype}",
                    ),
                    resolution=resolution,
                )
            )
        return findings


@dataclass(frozen=True, slots=True)
class EgressDenylistProbe:
    """SUPPLY_CHAIN_EGRESS probe: flag blocked external hosts the build needs.

    Models the common hardened-network guardrail where egress to public
    package / image sources (``registry-1.docker.io``, ``pypi.org``, ...) is
    denied and an internal mirror MUST be used instead. A blocked host the
    target intends to reach becomes a blocking finding, mapped to the toggle
    that repoints it at the approved mirror when one is registered.
    """

    blocked_hosts: frozenset[str]
    firewall_source: str
    mirror_resolutions: Mapping[str, ToggleResolution] = field(default_factory=dict)

    @property
    def category(self) -> ProbeCategory:
        return ProbeCategory.SUPPLY_CHAIN_EGRESS

    async def evaluate(self, target: PreflightTarget) -> Sequence[ProbeFinding]:
        findings: list[ProbeFinding] = []
        for host in target.egress_hosts:
            if host not in self.blocked_hosts:
                continue
            mirror = self.mirror_resolutions.get(host)
            if mirror is None:
                resolution = ProbeResolution(
                    kind=ResolutionKind.MANUAL,
                    guidance=(
                        f"egress to {host!r} is denied; route the dependency "
                        "through an approved internal mirror"
                    ),
                )
            else:
                resolution = ProbeResolution(
                    kind=ResolutionKind.TERRAFORM_TOGGLE,
                    autofix=mirror.autofix,
                    module=mirror.module,
                    set_vars=dict(mirror.set_vars),
                )
            findings.append(
                ProbeFinding(
                    id=f"blocked-egress:{host}",
                    category=ProbeCategory.SUPPLY_CHAIN_EGRESS,
                    severity=FindingSeverity.BLOCKING,
                    title=f"Egress to {host} is blocked",
                    evidence=ProbeEvidence(
                        source=self.firewall_source,
                        detail=f"outbound to {host} denied by network policy",
                    ),
                    resolution=resolution,
                )
            )
        return findings
