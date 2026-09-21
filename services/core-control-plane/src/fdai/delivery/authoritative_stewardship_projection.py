"""Build the reviewed Pantheon stewardship coverage projection."""

from __future__ import annotations

from pathlib import Path

from fdai.agents import PANTHEON_SPECS
from fdai.core.stewardship.coverage import build_coverage_report
from fdai.core.stewardship.model import StewardshipMap
from fdai.core.stewardship.resolver import load_stewardship_from_yaml


def _stewardship_snapshot(repo_root: Path) -> dict[str, object]:
    """Project the reviewed stewardship declaration and its computed coverage."""
    stewardship = load_stewardship_from_yaml(repo_root / "config" / "agent-stewardship.yaml")
    report = build_coverage_report(stewardship)
    return {
        "map": _stewardship_map(stewardship),
        "coverage": {
            "is_clean": report.is_clean,
            "total_agents": report.total_agents,
            "autonomous_agents": report.autonomous_agents,
            "maintainer_count": report.maintainer_count,
            "findings": [
                {
                    "code": finding.code,
                    "severity": str(finding.severity),
                    "message": finding.message,
                    "agent": finding.agent,
                }
                for finding in report.findings
            ],
        },
        # No identity directory is bound here, so no directory health is claimed.
        # `finding_count` stays absent: an explicit null is not a measured count.
        "identity_health": {"status": "not_configured", "checked_at": None},
    }


def _stewardship_map(stewardship: StewardshipMap) -> dict[str, object]:
    maintainers = list(stewardship.maintainer_oids)
    return {
        "version": stewardship.version,
        "maintainers": maintainers,
        "maintainer_count": len(maintainers),
        "hop_timeout_seconds": stewardship.hop_timeout_seconds,
        "over_assigned_max": stewardship.over_assigned_max,
        "agents": [_stewardship_agent(stewardship, spec.name) for spec in PANTHEON_SPECS],
    }


def _stewardship_agent(stewardship: StewardshipMap, name: str) -> dict[str, object]:
    agent = stewardship.agent(name)
    return {
        "name": name,
        "autonomous": agent.is_autonomous,
        "accept_autonomous_reason": agent.accept_autonomous_reason,
        "bus_factor": len({(subject.kind, subject.id) for subject in agent.accountable}),
        "stewards": [
            {
                "kind": str(subject.kind),
                "id": subject.id,
                "responsibility": str(subject.responsibility),
                "duty": None if subject.duty is None else str(subject.duty),
            }
            for subject in agent.stewards
        ],
    }
