"""Structural drift guards for the G-2 control_loop split (phase 1).

Phase 1 of G-2 (tracker #14, issue #16) extracts the module-level
helpers out of the 1725-LOC monolith. The follow-up Stage refactor is
deferred; these tests pin the current layout so it does not silently
re-monolith and so the follow-up has a stable baseline.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

import fdai.core.control_loop as control_loop_pkg
from fdai.core.control_loop import _helpers, orchestrator

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CL_DIR = _REPO_ROOT / "src" / "fdai" / "core" / "control_loop"

_PUBLIC_NAMES = (
    "ControlLoop",
    "ControlLoopOutcome",
    "ControlLoopResult",
    "build_shadow_authority_audit",
    "build_unified_risk_audit",
    "evaluate_unified",
    "_compute_authority",
    "_extract_environment",
    "_extract_resource_id",
    "_extract_resource_props",
    "_is_execution_success",
    "_synthetic_action_build_failure",
    "_unified_audit_dict",
)


# ---------------------------------------------------------------------------
# H1: layout - exactly the three files that phase 1 produces plus the
# optional stages/ scaffold (see H9).
# ---------------------------------------------------------------------------


def test_control_loop_package_layout() -> None:
    top_pyfiles = {p.name for p in _CL_DIR.glob("*.py")}
    required = {"__init__.py", "orchestrator.py", "_helpers.py"}
    missing = required - top_pyfiles
    assert not missing, (
        f"control_loop/ missing files: {sorted(missing)}"
    )


# ---------------------------------------------------------------------------
# H2: public-API completeness - every pre-split name that used to
# resolve at 'from fdai.core.control_loop import <X>' still does.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", _PUBLIC_NAMES)
def test_public_name_still_resolves(name: str) -> None:
    assert hasattr(control_loop_pkg, name), (
        f"public name {name!r} was lost in the G-2 split"
    )


# ---------------------------------------------------------------------------
# H3: orchestrator.py LOC ceiling. Pre-split was 1725 LOC. Phase 1
# brought it to ~1479. Ceiling set to 1600 so a small edit fits but a
# regression that puts everything back in one file fails loudly.
# ---------------------------------------------------------------------------


def test_orchestrator_loc_ceiling() -> None:
    loc = (_CL_DIR / "orchestrator.py").read_text().count("\n")
    assert loc <= 1600, (
        f"orchestrator.py has {loc} LOC (> 1600). G-2 phase 2 (Stage "
        "protocol) is the next step; do not let this file grow back."
    )


def test_helpers_loc_ceiling() -> None:
    loc = (_CL_DIR / "_helpers.py").read_text().count("\n")
    assert loc <= 400, (
        f"_helpers.py has {loc} LOC (> 400). Split further if you need "
        "to add more helpers."
    )


# ---------------------------------------------------------------------------
# H4: helpers stay pure - no _helpers function may take a ControlLoop
# instance as an argument. That would put orchestration state back
# into pure-function land and defeat the extraction.
# ---------------------------------------------------------------------------


def test_helpers_do_not_accept_controlloop_instances() -> None:
    from fdai.core.control_loop.orchestrator import ControlLoop

    offenders: list[str] = []
    for name, obj in vars(_helpers).items():
        if not callable(obj) or name.startswith("__"):
            continue
        try:
            sig = inspect.signature(obj)
        except (TypeError, ValueError):
            continue
        for param in sig.parameters.values():
            ann = param.annotation
            if ann is ControlLoop:
                offenders.append(f"{name} takes ControlLoop as {param.name}")
    assert not offenders, (
        "helpers took a ControlLoop instance - state-carrying "
        "arguments defeat pure-helper extraction: " + str(offenders)
    )


# ---------------------------------------------------------------------------
# H5: _helpers.py MUST NOT import from orchestrator.py. That would
# create a circular dependency and re-couple the two files.
# ---------------------------------------------------------------------------


def test_helpers_does_not_import_orchestrator() -> None:
    body = (_CL_DIR / "_helpers.py").read_text()
    bad = re.search(
        r"(?:from|import)\s+fdai\.core\.control_loop(?:\.orchestrator|\s|$|\))",
        body,
    )
    assert bad is None, (
        "_helpers.py imports from control_loop package/orchestrator - "
        "extract shared types into a third file instead."
    )


# ---------------------------------------------------------------------------
# H6: idempotency invariant - the extracted _is_execution_success
# helper's contract is that a dispatched-but-already-applied outcome
# counts as success. This is the linchpin of at-least-once delivery
# safety: re-delivery of the same event yields an ALREADY_APPLIED
# result, and the audit MUST treat it as success (never as a retry
# that mutates twice).
# ---------------------------------------------------------------------------


def test_is_execution_success_treats_already_applied_as_success() -> None:
    from fdai.core.executor.direct_api import (
        DirectApiExecutionOutcome,
        DirectApiExecutionResult,
    )

    for outcome in (
        DirectApiExecutionOutcome.DISPATCHED,
        DirectApiExecutionOutcome.ALREADY_APPLIED,
    ):
        result = DirectApiExecutionResult(
            action_id="a-1",
            outcome=outcome,
        )
        assert _helpers._is_execution_success(result), (
            f"outcome {outcome!r} MUST count as success - re-delivery "
            "safety depends on this"
        )


# ---------------------------------------------------------------------------
# H7: safety-invariant audit shape - build_unified_risk_audit MUST
# always emit the four safety-invariant keys.
# ---------------------------------------------------------------------------


def test_build_unified_risk_audit_signature_stable() -> None:
    sig = inspect.signature(_helpers.build_unified_risk_audit)
    params = set(sig.parameters.keys())
    # Signature MUST retain event + action + rule + action_type + table
    # + risk_gate so callers do not have to re-plumb parameters when
    # G-2 phase 2 lands (Stage refactor). cost_override may vary.
    for expected in ("event", "action", "rule", "action_type", "table", "risk_gate"):
        assert expected in params, (
            f"build_unified_risk_audit lost the {expected!r} parameter"
        )


# ---------------------------------------------------------------------------
# H10: docstring anchor pins the follow-up scope declaration.
# ---------------------------------------------------------------------------


def test_facade_docstring_anchors_follow_up_scope() -> None:
    doc = (control_loop_pkg.__doc__ or "").lower()
    for anchor in ("stage", "follow-up", "orchestrator"):
        assert anchor in doc, (
            f"control_loop/__init__.py docstring lost anchor {anchor!r}"
        )


# ---------------------------------------------------------------------------
# H11: subsystem-fanout allowlist entry exists. orchestrator.py imports
# from 10+ sibling core subsystems by design; without the allowlist
# entry, promoting check-subsystem-fanout to enforce would fail.
# ---------------------------------------------------------------------------


def test_subsystem_fanout_allowlist_has_orchestrator_entry() -> None:
    allowlist_path = _REPO_ROOT / "scripts" / ".check-subsystem-fanout.allowlist"
    if not allowlist_path.exists():
        pytest.skip("allowlist not yet created (H12 lands the entry)")
    body = allowlist_path.read_text()
    assert "src/fdai/core/control_loop/orchestrator.py" in body, (
        "allowlist missing orchestrator.py entry - the Stage refactor "
        "is the fix, not raising the fan-out threshold"
    )
