"""Authenticated evidence-run command for configuration review campaigns."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai.core.conversation import Principal, Role
from fdai.core.conversation.session import principal_has_role_at_least
from fdai.delivery.configuration_review_runtime import ConfigurationReviewRuntime

ConfigurationReviewAuthorizer = Callable[[Request], Awaitable[Principal]]
_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def make_configuration_review_routes(
    *,
    runtime: ConfigurationReviewRuntime,
    authorize: ConfigurationReviewAuthorizer,
) -> tuple[Route, ...]:
    """Build a command route that records evidence but exposes no executor."""

    async def run_review(request: Request) -> Response:
        principal = await authorize(request)
        if not principal_has_role_at_least(principal.role, Role.CONTRIBUTOR):
            raise HTTPException(status_code=403, detail="configuration review requires Contributor")
        run_id = request.headers.get("idempotency-key", "").strip()
        if _RUN_ID.fullmatch(run_id) is None:
            raise HTTPException(status_code=400, detail="valid Idempotency-Key header is required")
        result = await runtime.run(
            principal_id=principal.id,
            run_id=run_id,
            now=_request_time(request),
        )
        return JSONResponse(
            {
                "campaign_id": result.campaign.campaign_id,
                "state": result.campaign.state.value,
                "completed_runs": len(result.campaign.runs),
                "required_runs": result.campaign.required_successes,
                "report_verdict": result.report.verdict.value,
                "blueprint_candidate_id": (
                    result.blueprint.candidate_id if result.blueprint is not None else None
                ),
                "mutation_count": result.report.mutation_count,
            }
        )

    return (Route("/configuration-baselines/review/run", run_review, methods=["POST"]),)


def _request_time(request: Request) -> datetime:
    value = getattr(request.state, "configuration_review_now", None)
    return value if isinstance(value, datetime) else datetime.now(tz=UTC)


__all__ = ["ConfigurationReviewAuthorizer", "make_configuration_review_routes"]
