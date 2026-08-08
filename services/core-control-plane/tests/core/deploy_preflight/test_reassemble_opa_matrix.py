"""OPA-emulated matrix for active plan reassembly (issue #13).

Drives the bounded reassembly loop in
:mod:`fdai.core.deploy_preflight.reassemble` through a **real OPA evaluation**
of emulated policy guardrails (not scripted synthetic reports). Each
``reanalyze`` pass renders the accumulated tfvars overrides into an OPA input,
runs ``opa eval`` over an emulated Rego module, and maps every ``deny`` object
back into a :class:`ProbeFinding` - so the loop's verdict, the accumulated
toggle overrides, and the one-proposal-per-toggle output are exercised against
an actual policy engine.

Covers the taxonomy + convergence + safety rows from the issue:

- ``policy_guardrail`` inline-disk deny -> ``disk_provisioning=attach_existing``.
- ``supply_chain_egress`` docker.io deny -> ``registry_source=acr_mirror``.
- ``supply_chain_egress`` pypi.org deny -> ``python_index_url=internal``.
- ``policy_guardrail`` NSG-create deny -> ``nsg_provisioning=byo``.
- ``dependency_ordering`` loose prerequisite -> ``dependency_ordering=strict``.
- multi-toggle single pass (all-or-nothing, one proposal per toggle).
- two-step convergence (toggle A reveals blocker B, then clear).
- ``identity_rbac`` / ``quota_capacity`` / ``secret_config`` manual blockers with
  no toggle -> ``hil`` (never a false CLEARED).
- non-convergence (a toggle that does not clear its finding) -> ``hil``.
- regression (a toggle introduces more blockers) -> ``hil``.
- idempotency: re-running the same scenario yields the same override map and
  the same deterministic proposal keys.

Gated on the ``opa`` binary; skipped when it is not on ``PATH``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from fdai.core.deploy_preflight import (
    DeploymentReadinessReport,
    ReadinessVerdict,
    ReassemblyReason,
    ReassemblyStatus,
    reassemble,
)
from fdai.core.deploy_preflight.reassembly_proposals import build_toggle_proposals
from fdai.shared.contracts.models import Mode
from fdai.shared.providers.feasibility_probe import (
    FindingSeverity,
    ProbeCategory,
    ProbeEvidence,
    ProbeFinding,
    ProbeResolution,
    ResolutionKind,
)

_OPA = shutil.which("opa")
pytestmark = pytest.mark.skipif(_OPA is None, reason="opa binary not on PATH")

_SCOPE = "rg:example"
_CLOCK = "2026-07-12T00:00:00+00:00"

_EMULATED_REGO = """
package fdai.preflight.emulated
import rego.v1

# policy_guardrail: inline-disk deny, cleared by disk_provisioning=attach_existing.
deny contains f if {
    input.plan.disk_inline == true
    object.get(input.overrides, "disk_provisioning", "") != "attach_existing"
    f := {"id": "inline-disk-deny", "category": "policy_guardrail",
          "module": "compute", "var": "disk_provisioning",
          "value": "attach_existing", "autofix": true}
}

# supply_chain_egress: docker.io deny, cleared by registry_source=acr_mirror.
deny contains f if {
    input.plan.registry == "docker.io"
    object.get(input.overrides, "registry_source", "") != "acr_mirror"
    f := {"id": "registry-egress-deny", "category": "supply_chain_egress",
          "module": "compute", "var": "registry_source",
          "value": "acr_mirror", "autofix": true}
}

# two-step: choosing the acr mirror reveals a pull-role blocker.
deny contains f if {
    input.overrides.registry_source == "acr_mirror"
    object.get(input.overrides, "acr_pull_role", "") != "granted"
    f := {"id": "acr-pull-deny", "category": "identity_rbac",
          "module": "identity", "var": "acr_pull_role",
          "value": "granted", "autofix": true}
}

# policy_guardrail: NSG-create deny, cleared by nsg_provisioning=byo.
deny contains f if {
    input.plan.nsg_create == true
    object.get(input.overrides, "nsg_provisioning", "") != "byo"
    f := {"id": "nsg-deny", "category": "policy_guardrail",
          "module": "network", "var": "nsg_provisioning",
          "value": "byo", "autofix": true}
}

# identity_rbac: manual blocker with no autofix toggle.
deny contains f if {
    input.plan.needs_owner_rbac == true
    f := {"id": "owner-rbac-deny", "category": "identity_rbac",
          "autofix": false, "manual": true}
}

# non-convergent: the advertised toggle never satisfies the clear condition.
deny contains f if {
    input.plan.nonconvergent == true
    object.get(input.overrides, "actually_clears", "") != "yes"
    f := {"id": "nonconvergent-deny", "category": "policy_guardrail",
          "module": "compute", "var": "wrong_var",
          "value": "wrong_value", "autofix": true}
}

# regression: applying its toggle reveals two brand-new blockers.
deny contains f if {
    input.plan.regression == true
    object.get(input.overrides, "regress_trigger", "") != "on"
    f := {"id": "regress-root", "category": "policy_guardrail",
          "module": "compute", "var": "regress_trigger",
          "value": "on", "autofix": true}
}
deny contains f if {
    input.overrides.regress_trigger == "on"
    f := {"id": "regress-child-1", "category": "policy_guardrail",
          "module": "compute", "var": "never1", "value": "x", "autofix": true}
}
deny contains f if {
    input.overrides.regress_trigger == "on"
    f := {"id": "regress-child-2", "category": "policy_guardrail",
          "module": "compute", "var": "never2", "value": "y", "autofix": true}
}

# staircase: each toggle reveals exactly one NEW blocker (no repeat, no net
# increase), so a low iteration cap trips before convergence.
deny contains f if {
    input.plan.staircase == true
    object.get(input.overrides, "s0", "") != "on"
    f := {"id": "stair-0", "category": "policy_guardrail",
          "module": "compute", "var": "s0", "value": "on", "autofix": true}
}
deny contains f if {
    input.overrides.s0 == "on"
    object.get(input.overrides, "s1", "") != "on"
    f := {"id": "stair-1", "category": "policy_guardrail",
          "module": "compute", "var": "s1", "value": "on", "autofix": true}
}
deny contains f if {
    input.overrides.s1 == "on"
    object.get(input.overrides, "s2", "") != "on"
    f := {"id": "stair-2", "category": "policy_guardrail",
          "module": "compute", "var": "s2", "value": "on", "autofix": true}
}
deny contains f if {
    input.overrides.s2 == "on"
    object.get(input.overrides, "s3", "") != "on"
    f := {"id": "stair-3", "category": "policy_guardrail",
          "module": "compute", "var": "s3", "value": "on", "autofix": true}
}

# supply_chain_egress: pypi.org deny, cleared by python_index_url=internal.
deny contains f if {
    input.plan.pip_index == "pypi.org"
    object.get(input.overrides, "python_index_url", "") != "internal"
    f := {"id": "pypi-egress-deny", "category": "supply_chain_egress",
          "module": "compute", "var": "python_index_url",
          "value": "internal", "autofix": true}
}

# dependency_ordering: prerequisite-before-resource, cleared by strict ordering.
deny contains f if {
    input.plan.prereq_ordering == "loose"
    object.get(input.overrides, "dependency_ordering", "") != "strict"
    f := {"id": "prereq-order-deny", "category": "dependency_ordering",
          "module": "compute", "var": "dependency_ordering",
          "value": "strict", "autofix": true}
}

# quota_capacity: manual blocker with no autofix toggle -> hil.
deny contains f if {
    input.plan.over_quota == true
    f := {"id": "quota-deny", "category": "quota_capacity",
          "autofix": false, "manual": true}
}

# secret_config: manual blocker with no autofix toggle -> hil.
deny contains f if {
    input.plan.missing_secret == true
    f := {"id": "secret-deny", "category": "secret_config",
          "autofix": false, "manual": true}
}
"""


@pytest.fixture(scope="module")
def policy_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("emulated_policies")
    path = root / "emulated.rego"
    path.write_text(_EMULATED_REGO, encoding="utf-8")
    return path


def _opa_deny(policy_file: Path, input_doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Run ``opa eval`` for the emulated deny set and return the deny objects."""
    proc = subprocess.run(  # noqa: S603 - opa resolved via shutil.which
        [
            _OPA,  # type: ignore[list-item]
            "eval",
            "--stdin-input",
            "--format",
            "json",
            "--data",
            str(policy_file),
            "data.fdai.preflight.emulated.deny",
        ],
        input=json.dumps(input_doc),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0, f"opa eval failed: {proc.stderr}"
    parsed = json.loads(proc.stdout)
    result = parsed.get("result")
    if not result:
        return []
    value = result[0]["expressions"][0]["value"]
    return list(value)


def _finding_from_deny(obj: Mapping[str, Any]) -> ProbeFinding:
    if obj.get("manual"):
        resolution = ProbeResolution(kind=ResolutionKind.MANUAL, guidance="ask an owner")
    else:
        resolution = ProbeResolution(
            kind=ResolutionKind.TERRAFORM_TOGGLE,
            autofix=bool(obj.get("autofix")),
            module=str(obj["module"]),
            set_vars={str(obj["var"]): str(obj["value"])},
        )
    return ProbeFinding(
        id=str(obj["id"]),
        category=ProbeCategory(str(obj["category"])),
        severity=FindingSeverity.BLOCKING,
        title=str(obj["id"]),
        evidence=ProbeEvidence(source=f"policy:{obj['id']}", detail="emulated OPA deny"),
        resolution=resolution,
    )


class _OpaReanalyze:
    """A ``reanalyze`` that runs the real OPA policy over a fixed plan."""

    def __init__(self, policy_file: Path, plan: Mapping[str, Any]) -> None:
        self._policy_file = policy_file
        self._plan = dict(plan)
        self.calls: list[dict[str, str]] = []

    async def __call__(self, overrides: Mapping[str, str]) -> DeploymentReadinessReport:
        self.calls.append(dict(overrides))
        denies = _opa_deny(self._policy_file, {"plan": self._plan, "overrides": dict(overrides)})
        findings = tuple(_finding_from_deny(d) for d in denies)
        verdict = ReadinessVerdict.BLOCKED if findings else ReadinessVerdict.CLEAR
        return DeploymentReadinessReport(
            scope=_SCOPE,
            generated_at=_CLOCK,
            mode=Mode.ENFORCE,
            verdict=verdict,
            findings=findings,
            checked_categories=(ProbeCategory.POLICY_GUARDRAIL,),
        )


async def _run(policy_file: Path, plan: Mapping[str, Any]):
    reanalyze = _OpaReanalyze(policy_file, plan)
    initial = await reanalyze({})
    outcome = await reassemble(initial_report=initial, reanalyze=reanalyze)
    return outcome, reanalyze


# ---------------------------------------------------------------------------
# Policy-category rows
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inline_disk_autofix_clears(policy_file: Path) -> None:
    outcome, _ = await _run(policy_file, {"disk_inline": True})
    assert outcome.status is ReassemblyStatus.CLEARED
    assert outcome.overrides == {"disk_provisioning": "attach_existing"}
    assert len(outcome.applied_toggles) == 1
    proposals = build_toggle_proposals(outcome, initiator_principal="huginn")
    assert len(proposals) == 1
    assert proposals[0].set_vars == {"disk_provisioning": "attach_existing"}


@pytest.mark.asyncio
async def test_registry_egress_autofix_clears(policy_file: Path) -> None:
    # docker.io registry -> acr_mirror; choosing the mirror reveals the
    # acr-pull blocker (two-step), and both clear.
    outcome, _ = await _run(policy_file, {"registry": "docker.io"})
    assert outcome.status is ReassemblyStatus.CLEARED
    assert outcome.overrides["registry_source"] == "acr_mirror"
    assert outcome.overrides["acr_pull_role"] == "granted"


@pytest.mark.asyncio
async def test_nsg_create_autofix_clears(policy_file: Path) -> None:
    outcome, _ = await _run(policy_file, {"nsg_create": True})
    assert outcome.status is ReassemblyStatus.CLEARED
    assert outcome.overrides == {"nsg_provisioning": "byo"}


@pytest.mark.asyncio
async def test_pypi_egress_autofix_clears(policy_file: Path) -> None:
    # supply_chain_egress: pypi.org blocked -> internal python index toggle.
    outcome, _ = await _run(policy_file, {"pip_index": "pypi.org"})
    assert outcome.status is ReassemblyStatus.CLEARED
    assert outcome.overrides == {"python_index_url": "internal"}
    proposals = build_toggle_proposals(outcome, initiator_principal="huginn")
    assert len(proposals) == 1
    assert proposals[0].set_vars == {"python_index_url": "internal"}


@pytest.mark.asyncio
async def test_dependency_ordering_autofix_clears(policy_file: Path) -> None:
    # dependency_ordering: loose prerequisite ordering -> strict ordering toggle.
    outcome, _ = await _run(policy_file, {"prereq_ordering": "loose"})
    assert outcome.status is ReassemblyStatus.CLEARED
    assert outcome.overrides == {"dependency_ordering": "strict"}
    proposals = build_toggle_proposals(outcome, initiator_principal="huginn")
    assert len(proposals) == 1
    assert proposals[0].set_vars == {"dependency_ordering": "strict"}


# ---------------------------------------------------------------------------
# Convergence / loop behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_multi_toggle_single_pass_one_proposal_each(policy_file: Path) -> None:
    outcome, reanalyze = await _run(policy_file, {"disk_inline": True, "nsg_create": True})
    assert outcome.status is ReassemblyStatus.CLEARED
    assert outcome.overrides == {
        "disk_provisioning": "attach_existing",
        "nsg_provisioning": "byo",
    }
    # all-or-nothing: cleared in ONE reassembly pass (initial + one reanalyze)
    assert outcome.iterations == 1
    proposals = build_toggle_proposals(outcome, initiator_principal="huginn")
    assert {p.finding_id for p in proposals} == {"inline-disk-deny", "nsg-deny"}
    assert len(proposals) == 2


@pytest.mark.asyncio
async def test_two_step_convergence(policy_file: Path) -> None:
    outcome, _ = await _run(policy_file, {"registry": "docker.io"})
    assert outcome.status is ReassemblyStatus.CLEARED
    # took two passes: registry toggle, then the revealed acr-pull toggle.
    assert outcome.iterations == 2
    assert {t.finding_id for t in outcome.applied_toggles} == {
        "registry-egress-deny",
        "acr-pull-deny",
    }


@pytest.mark.asyncio
async def test_manual_blocker_escalates(policy_file: Path) -> None:
    outcome, _ = await _run(policy_file, {"needs_owner_rbac": True})
    assert outcome.status is ReassemblyStatus.ESCALATED
    assert outcome.reason is ReassemblyReason.MANUAL_BLOCKER
    assert build_toggle_proposals(outcome, initiator_principal="huginn") == ()


@pytest.mark.asyncio
async def test_quota_capacity_has_no_toggle_escalates(policy_file: Path) -> None:
    # quota_capacity has no autofix toggle today -> must route to hil, never a
    # false CLEARED.
    outcome, _ = await _run(policy_file, {"over_quota": True})
    assert outcome.status is ReassemblyStatus.ESCALATED
    assert outcome.reason is ReassemblyReason.MANUAL_BLOCKER
    assert outcome.overrides == {}
    assert build_toggle_proposals(outcome, initiator_principal="huginn") == ()


@pytest.mark.asyncio
async def test_secret_config_has_no_toggle_escalates(policy_file: Path) -> None:
    # secret_config has no autofix toggle today -> must route to hil.
    outcome, _ = await _run(policy_file, {"missing_secret": True})
    assert outcome.status is ReassemblyStatus.ESCALATED
    assert outcome.reason is ReassemblyReason.MANUAL_BLOCKER
    assert build_toggle_proposals(outcome, initiator_principal="huginn") == ()


@pytest.mark.asyncio
async def test_mixed_autofix_and_manual_whole_pass_escalates(policy_file: Path) -> None:
    outcome, _ = await _run(policy_file, {"disk_inline": True, "needs_owner_rbac": True})
    # one autofix + one manual -> whole pass to hil, nothing applied.
    assert outcome.status is ReassemblyStatus.ESCALATED
    assert outcome.reason is ReassemblyReason.MANUAL_BLOCKER
    assert outcome.overrides == {}


@pytest.mark.asyncio
async def test_non_convergent_escalates(policy_file: Path) -> None:
    outcome, _ = await _run(policy_file, {"nonconvergent": True})
    assert outcome.status is ReassemblyStatus.ESCALATED
    assert outcome.reason is ReassemblyReason.NON_CONVERGENT


@pytest.mark.asyncio
async def test_regression_escalates(policy_file: Path) -> None:
    outcome, _ = await _run(policy_file, {"regression": True})
    assert outcome.status is ReassemblyStatus.ESCALATED
    assert outcome.reason is ReassemblyReason.REGRESSION


@pytest.mark.asyncio
async def test_iteration_cap_escalates(policy_file: Path) -> None:
    # A staircase reveals a fresh blocker each pass (no repeat, no regression),
    # so a low iteration cap trips before it can converge.
    reanalyze = _OpaReanalyze(policy_file, {"staircase": True})
    initial = await reanalyze({})
    outcome = await reassemble(initial_report=initial, reanalyze=reanalyze, max_iterations=2)
    assert outcome.status is ReassemblyStatus.ESCALATED
    assert outcome.reason is ReassemblyReason.MAX_ITERATIONS


# ---------------------------------------------------------------------------
# Safety posture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotent_same_overrides_and_proposal_keys(policy_file: Path) -> None:
    out1, _ = await _run(policy_file, {"disk_inline": True, "nsg_create": True})
    out2, _ = await _run(policy_file, {"disk_inline": True, "nsg_create": True})
    assert out1.overrides == out2.overrides
    keys1 = {p.idempotency_key for p in build_toggle_proposals(out1, initiator_principal="h")}
    keys2 = {p.idempotency_key for p in build_toggle_proposals(out2, initiator_principal="h")}
    assert keys1 == keys2  # deterministic key on scope + finding + set_vars


@pytest.mark.asyncio
async def test_grounding_every_finding_cites_a_source(policy_file: Path) -> None:
    reanalyze = _OpaReanalyze(policy_file, {"disk_inline": True})
    report = await reanalyze({})
    assert report.findings
    assert all(f.evidence.source.startswith("policy:") for f in report.findings)


@pytest.mark.asyncio
async def test_clear_plan_needs_no_reassembly(policy_file: Path) -> None:
    outcome, reanalyze = await _run(policy_file, {"disk_inline": False})
    assert outcome.status is ReassemblyStatus.CLEARED
    assert outcome.overrides == {}
    assert outcome.iterations == 0  # already clear, loop never reanalyzed
    assert len(reanalyze.calls) == 1  # only the initial probe
