"""FeasibilityProbe - the DI seam that collects pre-deployment blockers.

A *probe* inspects a :class:`PreflightTarget` (a scope plus the resource
types / egress hosts / links a deployment intends to touch) and returns
deterministic :class:`ProbeFinding` records. The
:class:`~fdai.core.deploy_preflight.analyzer.PreflightAnalyzer`
fans out over a set of probes and assembles a single
``DeploymentReadinessReport`` (see
``docs/roadmap/deployment/deployment-preflight.md``).

Boundary + portability
----------------------
``core/`` sees only this Protocol; no cloud SDK is imported here or in
``core/``. The upstream default probes are the deterministic,
config-driven analyzers in
:mod:`fdai.shared.providers.local.feasibility` (no network, no
credentials). A live Azure adapter (Policy Insights, Resource Graph,
Firewall / NSG, Quota) is registered at the composition root under
``delivery/azure/`` in a later increment and realizes the same Protocol.

Concurrency
-----------
:meth:`FeasibilityProbe.evaluate` is **async by default** - real probes
do I/O (policy queries, egress reachability, quota lookups) and would
block the event loop otherwise. The static upstream probes complete
synchronously but still expose the async signature so a live adapter is
a drop-in replacement.

Grounding
---------
Every :class:`ProbeFinding` MUST carry :class:`ProbeEvidence` citing the
exact policy id / firewall rule / quota number that produced it. A probe
that cannot cite a source MUST NOT emit a finding - the analyzer treats
an ungrounded blocker as a defect, mirroring the verifier-is-authority
rule in ``architecture.instructions.md § LLM Quality Gate``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable


class ProbeCategory(StrEnum):
    """The blocker taxonomy (see the roadmap doc's probe table)."""

    POLICY_GUARDRAIL = "policy_guardrail"
    SUPPLY_CHAIN_EGRESS = "supply_chain_egress"
    IDENTITY_RBAC = "identity_rbac"
    QUOTA_CAPACITY = "quota_capacity"
    DEPENDENCY_ORDERING = "dependency_ordering"
    SECRET_CONFIG = "secret_config"  # noqa: S105 - taxonomy label, not a credential


class FindingSeverity(StrEnum):
    """How a finding affects the deploy verdict.

    ``BLOCKING`` findings gate an enforce-mode deploy; ``WARNING``
    findings never gate but surface for review.
    """

    BLOCKING = "blocking"
    WARNING = "warning"


class ResolutionKind(StrEnum):
    """How a finding is expected to be cleared."""

    TERRAFORM_TOGGLE = "terraform_toggle"
    ROLE_ASSIGNMENT = "role_assignment"
    MANUAL = "manual"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class ProbeEvidence:
    """The grounded source of a finding.

    ``source`` is a stable, CSP-neutral reference (e.g.
    ``policy:<neutral-id>`` or ``nsg:<neutral-id>/rule:deny-internet-out``);
    ``detail`` is a one-line human-readable explanation. Neither field may
    carry a secret or customer-identifying value.
    """

    source: str
    detail: str


@dataclass(frozen=True, slots=True)
class ProbeResolution:
    """How to clear a finding, mapped to a concrete lever when possible.

    For ``TERRAFORM_TOGGLE`` findings, ``module`` + ``set_vars`` name the
    infra sub-module and the variable overrides that make the deployment
    comply (e.g. ``compute`` / ``{"disk_provisioning": "attach_existing"}``).
    ``autofix`` is ``True`` only when the analyzer can propose the change as
    a remediation PR without human judgment.
    """

    kind: ResolutionKind
    autofix: bool = False
    module: str | None = None
    set_vars: Mapping[str, str] = field(default_factory=dict)
    guidance: str | None = None


@dataclass(frozen=True, slots=True)
class ProbeFinding:
    """One deployment blocker or warning with its evidence and resolution."""

    id: str
    category: ProbeCategory
    severity: FindingSeverity
    title: str
    evidence: ProbeEvidence
    resolution: ProbeResolution

    def to_dict(self) -> dict[str, object]:
        """Serialize to a plain JSON-friendly dict for delivery adapters."""
        return {
            "id": self.id,
            "category": self.category.value,
            "severity": self.severity.value,
            "title": self.title,
            "evidence": {
                "source": self.evidence.source,
                "detail": self.evidence.detail,
            },
            "resolution": {
                "kind": self.resolution.kind.value,
                "autofix": self.resolution.autofix,
                "module": self.resolution.module,
                "set_vars": dict(self.resolution.set_vars),
                "guidance": self.resolution.guidance,
            },
        }


@dataclass(frozen=True, slots=True)
class PreflightTarget:
    """What a deployment intends to touch, in CSP-neutral terms.

    - ``scope`` - neutral scope id (resource-group-equivalent or
      subscription-equivalent) the deploy lands in.
    - ``resource_types`` - neutral resource types the plan will create.
    - ``egress_hosts`` - external hosts the build / runtime must reach
      (e.g. ``registry-1.docker.io``, ``pypi.org``).
    - ``required_links`` - ontology link types the plan depends on
      pre-existing (e.g. ``attached_to`` for a BYO disk / NSG).
    """

    scope: str
    resource_types: tuple[str, ...] = ()
    egress_hosts: tuple[str, ...] = ()
    required_links: tuple[str, ...] = ()


@runtime_checkable
class FeasibilityProbe(Protocol):
    """Inspect a target and return grounded deployment blockers."""

    @property
    def category(self) -> ProbeCategory:
        """The taxonomy bucket this probe reports under."""
        ...

    async def evaluate(self, target: PreflightTarget) -> Sequence[ProbeFinding]:
        """Return zero or more findings for ``target``.

        MUST be deterministic for a given target + probe configuration and
        MUST NOT mutate anything (read-only). An empty sequence means the
        probe found no blocker in its category.
        """
        ...
