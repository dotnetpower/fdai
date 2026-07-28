"""Read-only Best Practice catalog projection for the Rules console panel."""

from __future__ import annotations

from collections import Counter
from collections.abc import Awaitable, Callable, Sequence

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.shared.contracts.models import BestPractice, RequirementKind

DEFAULT_ROUTE_PATH = "/best-practices"
DETAIL_ROUTE_PATH = "/best-practices/{best_practice_id}"
DEFAULT_LIMIT = 100
MAX_LIMIT = 200

_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _pillar(control_id: str) -> str:
    if control_id.startswith("RE:"):
        return "reliability"
    if control_id.startswith("OE:"):
        return "operational_excellence"
    return "other"


def _owner(control: BestPractice) -> str | None:
    return next(
        (
            requirement.ref
            for requirement in control.requirements
            if requirement.kind is RequirementKind.APPROVAL
        ),
        None,
    )


def _summary(control: BestPractice) -> dict[str, object]:
    return {
        "id": control.id,
        "version": control.version,
        "framework": control.framework,
        "control_id": control.control_id,
        "title": control.title,
        "rationale": control.rationale,
        "severity": control.severity.value,
        "category": control.category.value,
        "pillar": _pillar(control.control_id),
        "requirement_mode": control.requirement_mode.value,
        "requirement_count": len(control.requirements),
        "owner": _owner(control),
        "status": "unknown",
        "satisfied_requirement_count": 0,
        "evaluation_source": "not_connected",
    }


def _detail(control: BestPractice) -> dict[str, object]:
    payload = _summary(control)
    payload["requirements"] = [
        {
            "kind": requirement.kind.value,
            "ref": requirement.ref,
            "freshness_days": requirement.freshness_days,
            "status": "unknown",
            "evidence_refs": [],
        }
        for requirement in control.requirements
    ]
    payload["provenance"] = control.provenance.model_dump(mode="json")
    return payload


def _counts(values: Sequence[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items(), key=lambda item: (-item[1], item[0])))


def make_best_practice_routes(
    *,
    controls: Sequence[BestPractice],
    authorize: Callable[[Request], Awaitable[str]],
    path: str = DEFAULT_ROUTE_PATH,
    detail_path: str = DETAIL_ROUTE_PATH,
) -> list[Route]:
    """Return immutable list/detail routes over validated catalog controls."""

    ordered = tuple(
        sorted(
            controls,
            key=lambda control: (
                -_SEVERITY_RANK.get(control.severity.value, 0),
                control.control_id,
            ),
        )
    )
    summaries = tuple(_summary(control) for control in ordered)
    by_id = {control.id: control for control in ordered}
    by_control_id = {control.control_id: control for control in ordered}
    facets = {
        "by_pillar": _counts([str(item["pillar"]) for item in summaries]),
        "by_status": {"unknown": len(summaries)} if summaries else {},
        "by_severity": _counts([str(item["severity"]) for item in summaries]),
    }

    def bad_request(message: str) -> Response:
        return JSONResponse({"error": {"status": 400, "message": message}}, status_code=400)

    async def list_handler(request: Request) -> Response:
        await authorize(request)
        params = request.query_params
        pillar = params.get("pillar", "").strip().lower()
        status = params.get("status", "").strip().lower()
        needle = params.get("q", "").strip().lower()
        try:
            limit = int(params.get("limit", str(DEFAULT_LIMIT)))
            offset = int(params.get("offset", "0"))
        except ValueError:
            return bad_request("limit and offset MUST be integers")
        if limit < 1 or limit > MAX_LIMIT:
            return bad_request(f"limit MUST be between 1 and {MAX_LIMIT}")
        if offset < 0:
            return bad_request("offset MUST be >= 0")
        matched = [
            item
            for item in summaries
            if (not pillar or item["pillar"] == pillar)
            and (not status or item["status"] == status)
            and (
                not needle
                or needle
                in " ".join(
                    str(item[key]).lower()
                    for key in ("id", "control_id", "title", "rationale", "owner")
                )
            )
        ]
        return JSONResponse(
            {
                "total": len(summaries),
                "filtered_total": len(matched),
                "offset": offset,
                "limit": limit,
                "facets": facets,
                "controls": matched[offset : offset + limit],
                "evaluation_source": "not_connected",
            }
        )

    async def detail_handler(request: Request) -> Response:
        await authorize(request)
        best_practice_id = request.path_params["best_practice_id"]
        control = by_id.get(best_practice_id) or by_control_id.get(best_practice_id.upper())
        if control is None:
            return JSONResponse(
                {
                    "error": {
                        "status": 404,
                        "message": f"unknown best-practice id {best_practice_id!r}",
                    }
                },
                status_code=404,
            )
        return JSONResponse(_detail(control))

    return [
        Route(path, list_handler, methods=["GET"]),
        Route(detail_path, detail_handler, methods=["GET"]),
    ]


__all__ = ["DEFAULT_ROUTE_PATH", "DETAIL_ROUTE_PATH", "make_best_practice_routes"]
