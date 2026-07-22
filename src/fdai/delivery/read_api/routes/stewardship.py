"""Read-only agent-stewardship / handover-map route.

``GET /stewardship`` returns the handover map (maintainers + 15 agents + their
stewards) plus the synchronous coverage report (bus-factor / over-assignment /
maintainer findings). A pure projection of the injected
:class:`~fdai.core.stewardship.model.StewardshipMap`: no state, no side effect,
Reader role required. Opt-in through
:class:`~fdai.delivery.read_api.main.ReadApiConfig` (``stewardship_map=None`` by
default).

The console renders this read-only; edits are governance draft PRs, never a
console mutation (app-shape read-only invariant).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.stewardship import (
    AgentStewardship,
    CoverageReport,
    Finding,
    Severity,
    StewardshipMap,
    build_coverage_report,
)

ROUTE_PATH = "/stewardship"
_HEALTH_STATE_KEY = "stewardship_health:current"


class StewardshipHealthReader(Protocol):
    async def read_state(self, key: str) -> Mapping[str, object] | None: ...


def _serialize_agent(agent: AgentStewardship) -> dict[str, object]:
    return {
        "name": agent.agent_name,
        "autonomous": agent.is_autonomous,
        "accept_autonomous_reason": agent.accept_autonomous_reason,
        "bus_factor": len(agent.accountable),
        "stewards": [
            {
                "kind": s.kind.value,
                "id": s.id,
                "responsibility": s.responsibility.value,
            }
            for s in agent.stewards
        ],
    }


def _serialize_map(mp: StewardshipMap) -> dict[str, object]:
    return {
        "version": mp.version,
        "maintainers": list(mp.maintainer_oids),
        "maintainer_count": len(mp.maintainers),
        "hop_timeout_seconds": mp.hop_timeout_seconds,
        "over_assigned_max": mp.over_assigned_max,
        "agents": [_serialize_agent(mp.agents[name]) for name in sorted(mp.agents)],
    }


def _serialize_report(report: CoverageReport) -> dict[str, object]:
    return {
        "is_clean": report.is_clean,
        "total_agents": report.total_agents,
        "autonomous_agents": report.autonomous_agents,
        "maintainer_count": report.maintainer_count,
        "findings": [
            {
                "code": f.code,
                "severity": f.severity.value,
                "message": f.message,
                "agent": f.agent,
            }
            for f in report.findings
        ],
    }


def make_stewardship_route(
    *,
    stewardship_map: StewardshipMap,
    authorize: Callable[[Request], Awaitable[str]],
    health_reader: StewardshipHealthReader | None = None,
    path: str = ROUTE_PATH,
) -> Route:
    """Return the ``GET /stewardship`` route bound to ``stewardship_map``."""

    async def handler(request: Request) -> Response:
        await authorize(request)
        report = build_coverage_report(stewardship_map)
        health: dict[str, object] = {"status": "not_configured", "checked_at": None}
        if health_reader is not None:
            raw_health = await health_reader.read_state(_HEALTH_STATE_KEY)
            report, health = _merge_health(report, raw_health, stewardship_map)
        return JSONResponse(
            {
                "map": _serialize_map(stewardship_map),
                "coverage": _serialize_report(report),
                "identity_health": health,
            }
        )

    return Route(path, handler, methods=["GET"])


def _merge_health(
    report: CoverageReport,
    raw: Mapping[str, object] | None,
    stewardship_map: StewardshipMap,
) -> tuple[CoverageReport, dict[str, object]]:
    if raw is None:
        return report, {"status": "pending", "checked_at": None}
    rows = raw.get("findings")
    checked_at = raw.get("checked_at")
    if not isinstance(rows, list) or len(rows) > 100 or not isinstance(checked_at, str):
        return report, {"status": "unavailable", "checked_at": None}
    findings: list[Finding] = []
    for row in rows:
        if not isinstance(row, Mapping):
            return report, {"status": "unavailable", "checked_at": None}
        agent = row.get("agent")
        message = row.get("message")
        if (
            row.get("code") != "stale_oid"
            or row.get("severity") != Severity.WARN.value
            or not isinstance(message, str)
            or (agent is not None and agent not in stewardship_map.agents)
        ):
            return report, {"status": "unavailable", "checked_at": None}
        findings.append(
            Finding(
                code="stale_oid",
                severity=Severity.WARN,
                message=message,
                agent=agent if isinstance(agent, str) else None,
            )
        )
    merged = CoverageReport(
        findings=(*report.findings, *findings),
        total_agents=report.total_agents,
        autonomous_agents=report.autonomous_agents,
        maintainer_count=report.maintainer_count,
    )
    return merged, {
        "status": "warn" if findings else "clean",
        "checked_at": checked_at,
        "finding_count": len(findings),
    }


__all__ = ["ROUTE_PATH", "StewardshipHealthReader", "make_stewardship_route"]
