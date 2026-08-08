"""PreflightAnalyzer - fan out over probes, assemble one readiness report.

The analyzer is the deterministic (T0-flavored) orchestrator of the
deployment-preflight subsystem: it runs every registered
:class:`~fdai.shared.providers.feasibility_probe.FeasibilityProbe`
against a :class:`PreflightTarget`, collects the grounded findings, and
computes a fail-closed :class:`DeploymentReadinessReport`.

Design references:
- ``docs/roadmap/deployment/deployment-preflight.md``
- ``.github/instructions/architecture.instructions.md § Control Loop``

Boundaries: this module lives in ``core/`` and imports only ``shared/``
(providers, contracts). It constructs no adapter and imports no cloud SDK;
probes are injected.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from fdai.core.deploy_preflight.report import (
    DeploymentReadinessReport,
    ReadinessVerdict,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.feasibility_probe import (
    FeasibilityProbe,
    FindingSeverity,
    PreflightTarget,
    ProbeFinding,
)


def _utc_now_iso() -> str:
    """Default clock: RFC 3339 UTC timestamp. Injected in tests."""
    return datetime.now(UTC).isoformat()


class PreflightAnalyzer:
    """Run probes over a target and assemble a fail-closed readiness report.

    ``mode`` selects whether the pass is authoritative: ``ENFORCE`` lets a
    blocking finding gate the deploy; ``SHADOW`` (the default for any
    unproven probe set) reports blockers but never gates - the report's
    :meth:`~fdai.core.deploy_preflight.report.DeploymentReadinessReport.blocks_deploy`
    stays ``False`` (see the shadow-first rule in the roadmap doc).
    """

    def __init__(
        self,
        probes: Sequence[FeasibilityProbe],
        *,
        mode: Mode = Mode.SHADOW,
        clock: Callable[[], str] = _utc_now_iso,
    ) -> None:
        self._probes = tuple(probes)
        self._mode = mode
        self._clock = clock

    async def analyze(self, target: PreflightTarget) -> DeploymentReadinessReport:
        """Return the assembled readiness report for ``target``.

        Probes run concurrently under a :class:`asyncio.TaskGroup` so a
        probe raising is a fail-closed condition - every sibling probe
        is cancelled by the group, no background task leaks past the
        call, and the exception propagates so the caller degrades to
        review rather than silently reporting ``CLEAR`` on a partial
        pass.
        """
        tasks: list[asyncio.Task[Sequence[ProbeFinding]]] = []
        async with asyncio.TaskGroup() as group:
            for probe in self._probes:
                tasks.append(group.create_task(probe.evaluate(target)))
        findings: list[ProbeFinding] = []
        for task in tasks:
            findings.extend(task.result())
        # Stable ordering: blocking before warning, then by finding id, so a
        # re-run over the same inputs produces byte-identical output.
        findings.sort(key=lambda f: (f.severity is not FindingSeverity.BLOCKING, f.id))
        ordered = tuple(findings)
        return DeploymentReadinessReport(
            scope=target.scope,
            generated_at=self._clock(),
            mode=self._mode,
            verdict=self._verdict(ordered),
            findings=ordered,
            checked_categories=tuple(
                sorted({probe.category for probe in self._probes}, key=lambda value: value.value)
            ),
        )

    @staticmethod
    def _verdict(findings: tuple[ProbeFinding, ...]) -> ReadinessVerdict:
        if not findings:
            return ReadinessVerdict.CLEAR
        if any(f.severity is FindingSeverity.BLOCKING for f in findings):
            return ReadinessVerdict.BLOCKED
        return ReadinessVerdict.NEEDS_REVIEW
