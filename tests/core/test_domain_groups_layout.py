"""Structural drift guards for the G-1 domain-group facades (phase 1).

Phase 1 of G-1 (tracker #14, issue #15) creates five domain-group
packages under ``fdai.core.`` that re-export the existing subsystems
along the target taxonomy. These tests pin the shape of the taxonomy
so a stray addition (subsystem in two groups; subsystem missing from
its group; a subsystem's old import path breaks) surfaces here
instead of at runtime.

The physical ``git mv`` mass move is deferred to phase 2 - phase 1 is
the additive enabling step.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CORE_DIR = _REPO_ROOT / "src" / "fdai" / "core"

_DOMAIN_MEMBERSHIP: dict[str, tuple[str, ...]] = {
    "pipeline": (
        "event_ingest",
        "trust_router",
        "tiers",
        "quality_gate",
        "risk_gate",
        "hil_resume",
        "executor",
        "audit",
        "control_loop",
    ),
    "incident": (
        "rca",
        "slo",
        "runbook",
        "postmortem",
        "oncall",
        "irp",
        "investigation",
        "chaos",
        "capacity",
    ),
    "operator": (
        "conversation",
        "operator_memory",
        "rbac",
        "notifications",
        "report_feed",
    ),
    "knowledge": (
        "prompts",
        "tools",
        "web_search",
        "capability_catalog",
        "rule_catalog_profiles",
        "ontology_explorer",
    ),
    "platform": (
        "scheduler",
        "metering",
        "measurement",
        "security",
        "reporting",
        "onboarding",
        "workflow",
        "detection",
        "deploy_preflight",
        "assurance_twin",
    ),
}


# ---------------------------------------------------------------------------
# H1: all five domain packages exist.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("domain", sorted(_DOMAIN_MEMBERSHIP))
def test_domain_package_exists(domain: str) -> None:
    module = importlib.import_module(f"fdai.core.{domain}")
    assert module is not None


# ---------------------------------------------------------------------------
# H2: domain membership pinning. Every subsystem the taxonomy says
# lives under a domain MUST resolve via that domain's facade.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "domain,subsystem",
    [(d, s) for d, subs in _DOMAIN_MEMBERSHIP.items() for s in subs],
)
def test_domain_reexports_subsystem(domain: str, subsystem: str) -> None:
    module = importlib.import_module(f"fdai.core.{domain}")
    assert hasattr(module, subsystem), (
        f"fdai.core.{domain} does not re-export {subsystem!r}; check "
        f"fdai/core/{domain}/__init__.py facade block"
    )


# ---------------------------------------------------------------------------
# H3: single-owner invariant. A subsystem MUST belong to exactly one
# domain group. Cross-listing creates ambiguity about the "canonical"
# import path.
# ---------------------------------------------------------------------------


def test_no_subsystem_in_two_domains() -> None:
    seen: dict[str, str] = {}
    for domain, subs in _DOMAIN_MEMBERSHIP.items():
        for sub in subs:
            if sub in seen:
                raise AssertionError(
                    f"subsystem {sub!r} listed under both {seen[sub]!r} "
                    f"and {domain!r} - pick one canonical home"
                )
            seen[sub] = domain


# ---------------------------------------------------------------------------
# H4: verticals stays outside the five groups. G-6 already sub-packaged
# verticals into its own three-vertical sub-tree; it is not re-shuffled
# by G-1.
# ---------------------------------------------------------------------------


def test_verticals_is_not_a_domain_group_member() -> None:
    for domain, subs in _DOMAIN_MEMBERSHIP.items():
        assert "verticals" not in subs, (
            f"verticals must NOT be listed under {domain!r} - it is a "
            "top-level group (G-6 already sub-packaged it)"
        )


# ---------------------------------------------------------------------------
# H5: old import path still works (phase 1 is additive, never migratory).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subsystem",
    [s for subs in _DOMAIN_MEMBERSHIP.values() for s in subs],
)
def test_legacy_import_still_resolves(subsystem: str) -> None:
    # ``from fdai.core.<subsystem>`` MUST continue to import cleanly.
    module = importlib.import_module(f"fdai.core.{subsystem}")
    assert module is not None


# ---------------------------------------------------------------------------
# H6: name collision handling. The two subsystems whose names collide
# with their group name (incident, knowledge) MUST expose both roles.
# ---------------------------------------------------------------------------


def test_incident_facade_absorbs_both_roles() -> None:
    incident_pkg = importlib.import_module("fdai.core.incident")
    # Group role: exposes sibling subsystems.
    for name in _DOMAIN_MEMBERSHIP["incident"]:
        assert hasattr(incident_pkg, name), (
            f"incident/ group role lost {name!r}"
        )
    # Subsystem role: exposes StormCoordinator + friends.
    from fdai.core.incident import IncidentRegistry, IncidentStateMachine  # noqa: F401

    assert IncidentRegistry is not None


def test_knowledge_facade_absorbs_both_roles() -> None:
    knowledge_pkg = importlib.import_module("fdai.core.knowledge")
    for name in _DOMAIN_MEMBERSHIP["knowledge"]:
        assert hasattr(knowledge_pkg, name), (
            f"knowledge/ group role lost {name!r}"
        )
    # Subsystem role: exposes KnowledgeSourceKind + friends.
    from fdai.core.knowledge import KnowledgeSourceKind  # noqa: F401


# ---------------------------------------------------------------------------
# H7: facade docstring anchors the phase-1 / phase-2 split so a
# well-meaning refactor cannot silently erase the intent.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("domain", sorted(_DOMAIN_MEMBERSHIP))
def test_facade_docstring_anchors_phase_1(domain: str) -> None:
    facade_path = _CORE_DIR / domain / "__init__.py"
    body = facade_path.read_text(encoding="utf-8").lower()
    # 'incident' and 'knowledge' packages carry the ORIGINAL subsystem
    # docstring plus an appended facade comment block; look for the
    # phase-1 anchor anywhere in the file rather than only in __doc__.
    for anchor in ("g-1", "phase 1"):
        assert anchor in body, (
            f"fdai.core.{domain}/__init__.py file body lost anchor "
            f"{anchor!r} - phase-1 intent is drifting"
        )


# ---------------------------------------------------------------------------
# H8: no domain facade imports from another domain facade. Domain
# groups are peer-level; cross-domain composition happens at the
# composition root, not inside a domain __init__.
# ---------------------------------------------------------------------------


import re


@pytest.mark.parametrize("domain", sorted(_DOMAIN_MEMBERSHIP))
def test_domain_facade_does_not_import_other_domain(domain: str) -> None:
    peers = set(_DOMAIN_MEMBERSHIP) - {domain}
    facade_path = _CORE_DIR / domain / "__init__.py"
    body = facade_path.read_text(encoding="utf-8")
    for peer in peers:
        # Match `from fdai.core.<peer>` or `import fdai.core.<peer>`
        # where <peer> is the group name (not a subsystem that happens
        # to share the name).
        pattern = re.compile(
            rf"(?:from|import)\s+fdai\.core\.{peer}\s"
        )
        if pattern.search(body):
            # incident/knowledge legitimately import their sibling
            # subsystems that happen to share domain-facade names.
            # Only complain about a domain facade referencing OTHER
            # domain facades.
            raise AssertionError(
                f"fdai.core.{domain}/__init__.py imports from peer "
                f"domain {peer!r}"
            )


# ---------------------------------------------------------------------------
# H9: total subsystem count sanity. 41 subsystems across 5 groups.
# ---------------------------------------------------------------------------


def test_total_subsystem_count_is_stable() -> None:
    total = sum(len(v) for v in _DOMAIN_MEMBERSHIP.values())
    assert total == 39, (
        f"domain-group membership sums to {total}; expected 39 (nine "
        "pipeline + nine incident + five operator + six knowledge + "
        "ten platform - the incident and knowledge subsystems that "
        "share their group name are counted once as the package, not "
        "as a member of themselves). Adjust _DOMAIN_MEMBERSHIP if a "
        "subsystem was added or retired."
    )
