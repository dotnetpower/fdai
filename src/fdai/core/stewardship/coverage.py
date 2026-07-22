"""Coverage + risk findings over a :class:`StewardshipMap` (verification surface).

These are the **non-blocking** checks from
[`agent-stewardship-and-handover.md § 7.2 / 7.3`]
(../../../../docs/roadmap/interfaces/agent-stewardship-and-handover.md#72-non-blocking-findings-warn-surfaced-in-the-coverage-report):
the hard fail-fast rules live in :mod:`fdai.core.stewardship.resolver`. A
finding never blocks the control loop; it surfaces in the console badge and logs.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum

from fdai.core.stewardship.directory import IdentityDirectory
from fdai.core.stewardship.model import StewardKind, StewardshipMap


class Severity(StrEnum):
    """Finding severity. ``WARN`` degrades the coverage badge; ``INFO`` does not."""

    WARN = "warn"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class Finding:
    """One coverage/risk observation, keyed by a stable ``code``."""

    code: str
    severity: Severity
    message: str
    agent: str | None = None


@dataclass(frozen=True, slots=True)
class CoverageReport:
    """The full set of findings plus headline counts for the console."""

    findings: tuple[Finding, ...]
    total_agents: int
    autonomous_agents: int
    maintainer_count: int

    @property
    def warnings(self) -> tuple[Finding, ...]:
        """Findings at :attr:`Severity.WARN`."""
        return tuple(f for f in self.findings if f.severity is Severity.WARN)

    @property
    def is_clean(self) -> bool:
        """Return ``True`` iff there are no ``WARN`` findings."""
        return not self.warnings


def build_coverage_report(mp: StewardshipMap) -> CoverageReport:
    """Compute the synchronous coverage report (no directory / network calls)."""
    findings: list[Finding] = []

    if len(mp.maintainers) == 1:
        findings.append(
            Finding(
                code="maintainer_single",
                severity=Severity.WARN,
                message="Only 1 maintainer configured; 2 are recommended for succession safety.",
            )
        )

    autonomous = 0
    # Count accountable-user assignments across agents for over-assignment.
    user_load: Counter[str] = Counter()

    for name in sorted(mp.agents):
        agent = mp.agents[name]
        if agent.is_autonomous:
            autonomous += 1
            findings.append(
                Finding(
                    code="autonomous_no_steward",
                    severity=Severity.INFO,
                    message=(
                        f"Agent {name} runs autonomous; escalation falls back to the maintainer."
                    ),
                    agent=name,
                )
            )
            continue

        accountable_units = {(subject.kind, subject.id) for subject in agent.accountable}
        bus_factor = len(accountable_units)
        if bus_factor == 1:
            findings.append(
                Finding(
                    code="bus_factor_one",
                    severity=Severity.WARN,
                    message=f"Agent {name} has a single accountable steward (bus-factor 1).",
                    agent=name,
                )
            )
        for oid in agent.accountable_user_ids:
            user_load[oid] += 1

    for oid, count in sorted(user_load.items()):
        if count > mp.over_assigned_max:
            findings.append(
                Finding(
                    code="over_assigned",
                    severity=Severity.WARN,
                    message=(
                        f"Person {oid} is accountable for {count} agents "
                        f"(over the threshold of {mp.over_assigned_max})."
                    ),
                )
            )

    return CoverageReport(
        findings=tuple(findings),
        total_agents=len(mp.agents),
        autonomous_agents=autonomous,
        maintainer_count=len(mp.maintainers),
    )


async def audit_stale_oids(mp: StewardshipMap, directory: IdentityDirectory) -> tuple[Finding, ...]:
    """Return ``stale_oid`` findings for maintainers/user-stewards no longer active.

    Off the hot path (scheduled). Group subjects are not checked here - group
    membership is validated by the directory that backs them, not by this OID
    liveness probe.
    """
    findings: list[Finding] = []

    for i, oid in enumerate(mp.maintainer_oids):
        if not await directory.is_active(oid):
            findings.append(
                Finding(
                    code="stale_oid",
                    severity=Severity.WARN,
                    message=f"Maintainer[{i}] {oid} no longer resolves to an active account.",
                )
            )

    for name in sorted(mp.agents):
        agent = mp.agents[name]
        for subject in agent.stewards:
            if subject.kind is not StewardKind.USER:
                continue
            if not await directory.is_active(subject.id):
                findings.append(
                    Finding(
                        code="stale_oid",
                        severity=Severity.WARN,
                        message=f"Steward {subject.id} for agent {name} is no longer active.",
                        agent=name,
                    )
                )

    return tuple(findings)


__all__ = [
    "CoverageReport",
    "Finding",
    "Severity",
    "audit_stale_oids",
    "build_coverage_report",
]
