"""PreflightAnalyzer: verdict, shadow-first gating, idempotent ordering."""

from __future__ import annotations

from collections.abc import Sequence

from fdai.core.deploy_preflight import (
    PreflightAnalyzer,
    ReadinessVerdict,
)
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.feasibility_probe import (
    FindingSeverity,
    PreflightTarget,
    ProbeCategory,
    ProbeEvidence,
    ProbeFinding,
    ProbeResolution,
    ResolutionKind,
)
from fdai.shared.providers.local import (
    DenylistResourceTypeProbe,
    EgressDenylistProbe,
    ToggleResolution,
)

_FIXED_CLOCK = "2026-07-06T00:00:00+00:00"


def _finding(fid: str, severity: FindingSeverity) -> ProbeFinding:
    return ProbeFinding(
        id=fid,
        category=ProbeCategory.POLICY_GUARDRAIL,
        severity=severity,
        title=fid,
        evidence=ProbeEvidence(source="policy:x", detail="d"),
        resolution=ProbeResolution(kind=ResolutionKind.MANUAL),
    )


class _StubProbe:
    def __init__(self, findings: Sequence[ProbeFinding]) -> None:
        self._findings = tuple(findings)

    @property
    def category(self) -> ProbeCategory:
        return ProbeCategory.POLICY_GUARDRAIL

    async def evaluate(self, target: PreflightTarget) -> Sequence[ProbeFinding]:
        return self._findings


async def test_no_findings_is_clear() -> None:
    analyzer = PreflightAnalyzer([_StubProbe([])], clock=lambda: _FIXED_CLOCK)
    report = await analyzer.analyze(PreflightTarget(scope="rg:example"))
    assert report.verdict is ReadinessVerdict.CLEAR
    assert report.findings == ()
    assert report.blocks_deploy is False
    assert report.to_dict()["checks"] == [
        {
            "category": "policy_guardrail",
            "status": "clear",
            "finding_count": 0,
        }
    ]


async def test_warning_only_is_needs_review() -> None:
    analyzer = PreflightAnalyzer(
        [_StubProbe([_finding("w1", FindingSeverity.WARNING)])],
        clock=lambda: _FIXED_CLOCK,
    )
    report = await analyzer.analyze(PreflightTarget(scope="rg:example"))
    assert report.verdict is ReadinessVerdict.NEEDS_REVIEW
    assert report.blocks_deploy is False


async def test_blocking_finding_is_blocked() -> None:
    analyzer = PreflightAnalyzer(
        [_StubProbe([_finding("b1", FindingSeverity.BLOCKING)])],
        mode=Mode.ENFORCE,
        clock=lambda: _FIXED_CLOCK,
    )
    report = await analyzer.analyze(PreflightTarget(scope="rg:example"))
    assert report.verdict is ReadinessVerdict.BLOCKED
    assert report.blocks_deploy is True


async def test_shadow_mode_never_gates_even_when_blocked() -> None:
    """Shadow-first: a blocker is reported truthfully but does not gate."""
    analyzer = PreflightAnalyzer(
        [_StubProbe([_finding("b1", FindingSeverity.BLOCKING)])],
        mode=Mode.SHADOW,
        clock=lambda: _FIXED_CLOCK,
    )
    report = await analyzer.analyze(PreflightTarget(scope="rg:example"))
    assert report.verdict is ReadinessVerdict.BLOCKED
    assert report.blocks_deploy is False


async def test_findings_ordered_blocking_first_then_id() -> None:
    probe = _StubProbe(
        [
            _finding("z-warn", FindingSeverity.WARNING),
            _finding("a-warn", FindingSeverity.WARNING),
            _finding("m-block", FindingSeverity.BLOCKING),
        ]
    )
    analyzer = PreflightAnalyzer([probe], clock=lambda: _FIXED_CLOCK)
    report = await analyzer.analyze(PreflightTarget(scope="rg:example"))
    assert [f.id for f in report.findings] == ["m-block", "a-warn", "z-warn"]


async def test_analysis_is_idempotent() -> None:
    probe = _StubProbe(
        [
            _finding("b1", FindingSeverity.BLOCKING),
            _finding("w1", FindingSeverity.WARNING),
        ]
    )
    analyzer = PreflightAnalyzer([probe], clock=lambda: _FIXED_CLOCK)
    target = PreflightTarget(scope="rg:example")
    first = await analyzer.analyze(target)
    second = await analyzer.analyze(target)
    assert first.to_dict() == second.to_dict()


async def test_end_to_end_with_real_probes_and_toggle_map() -> None:
    """docker.io + inline disk denied -> two blockers, both mapped to toggles."""
    analyzer = PreflightAnalyzer(
        [
            DenylistResourceTypeProbe(
                denied_types=frozenset({"compute.disk"}),
                policy_source="policy:not-allowed-resource-types",
                resolutions={
                    "compute.disk": ToggleResolution(
                        module="compute",
                        set_vars={"disk_provisioning": "attach_existing"},
                        autofix=True,
                    )
                },
            ),
            EgressDenylistProbe(
                blocked_hosts=frozenset({"registry-1.docker.io"}),
                firewall_source="nsg:hub/rule:deny-internet-out",
                mirror_resolutions={
                    "registry-1.docker.io": ToggleResolution(
                        module="compute",
                        set_vars={"registry_source": "acr_mirror"},
                        autofix=True,
                    )
                },
            ),
        ],
        mode=Mode.ENFORCE,
        clock=lambda: _FIXED_CLOCK,
    )
    target = PreflightTarget(
        scope="rg:example",
        resource_types=("compute.disk", "compute.vm"),
        egress_hosts=("registry-1.docker.io",),
    )

    report = await analyzer.analyze(target)

    assert report.verdict is ReadinessVerdict.BLOCKED
    assert report.blocks_deploy is True
    ids = {f.id for f in report.findings}
    assert ids == {
        "denied-resource-type:compute.disk",
        "blocked-egress:registry-1.docker.io",
    }
    assert all(f.resolution.autofix for f in report.findings)
    assert [check["category"] for check in report.to_dict()["checks"]] == [
        "policy_guardrail",
        "supply_chain_egress",
    ]
