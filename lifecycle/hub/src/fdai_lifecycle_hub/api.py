"""The Hub HTTP API that installation agents poll.

Lifecycle I0 serves on loopback only and has no caller authentication. Agent identity and
transport authentication are Lifecycle I1 work and gate any non-loopback binding.
"""

from __future__ import annotations

from base64 import b64encode

from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_lifecycle_hub.domain import Clock, utc_now
from fdai_lifecycle_hub.enrollment import EnrollmentStatus, KeyProofVerifier
from fdai_lifecycle_hub.errors import (
    ConcurrentWriteError,
    EnrollmentProofError,
    InstallationExistsError,
    PlanDigestMismatchError,
    ReportConflictError,
    UnknownInstallationError,
    UnknownPlanError,
)
from fdai_lifecycle_hub.schemas import PlanReport, SignedEnrollment, enrollment_request
from fdai_lifecycle_hub.signing import verify_key_proof
from fdai_lifecycle_hub.store import HubStore

MAX_REPORT_BYTES = 16 * 1024
MAX_ENROLLMENT_BYTES = 64 * 1024


def create_app(
    store: HubStore, *, clock: Clock = utc_now, verify_proof: KeyProofVerifier = verify_key_proof
) -> Starlette:
    """The agent API. Approval is an operator action and is deliberately absent here."""

    async def healthz(request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def get_plan(request: Request) -> Response:
        installation_id = request.path_params["installation_id"]
        plan = await run_in_threadpool(store.current_plan, installation_id, now=clock())
        if plan is None:
            return Response(status_code=204)
        return JSONResponse(
            {
                "plan": {
                    "signed_payload": b64encode(plan.signed_payload).decode("ascii"),
                    "signature": b64encode(plan.signature).decode("ascii"),
                }
            }
        )

    async def post_enrollment(request: Request) -> Response:
        body = await _read_limited(request, MAX_ENROLLMENT_BYTES)
        if body is None:
            return _error(413, "enrollment_too_large")
        try:
            signed = SignedEnrollment.model_validate_json(body)
            enrollment = enrollment_request(signed.signed_payload, signed.proof)
        except ValueError:  # Includes pydantic's ValidationError.
            return _error(422, "enrollment_invalid")
        if enrollment.installation.installation_id != request.path_params["installation_id"]:
            return _error(422, "enrollment_invalid")
        try:
            await run_in_threadpool(
                store.request_enrollment, enrollment, verify=verify_proof, now=clock()
            )
        except EnrollmentProofError as error:
            return _error(403, error.failure)
        return JSONResponse(
            {
                "enrollment": EnrollmentStatus.PENDING,
                "installation_key_id": enrollment.installation_key_id,
            },
            status_code=202,
        )

    async def post_report(request: Request) -> Response:
        body = await _read_limited(request, MAX_REPORT_BYTES)
        if body is None:
            return _error(413, "report_too_large")
        try:
            report = PlanReport.model_validate_json(body)
        except ValidationError:
            return _error(422, "report_invalid")
        await run_in_threadpool(
            store.record_report,
            request.path_params["installation_id"],
            request.path_params["plan_id"],
            report,
            now=clock(),
        )
        return Response(status_code=202)

    async def not_found(request: Request, exc: Exception) -> Response:
        return _error(404, "not_found")

    async def exists(request: Request, exc: Exception) -> Response:
        return _error(409, "installation_exists")

    async def conflict(request: Request, exc: Exception) -> Response:
        return _error(409, "report_conflict")

    async def digest_mismatch(request: Request, exc: Exception) -> Response:
        return _error(409, "plan_digest_mismatch")

    async def retry(request: Request, exc: Exception) -> Response:
        response = _error(503, "concurrent_write")
        response.headers["Retry-After"] = "1"
        return response

    return Starlette(
        routes=[
            Route("/healthz", healthz),
            Route(
                "/v1/installations/{installation_id}/enrollment", post_enrollment, methods=["POST"]
            ),
            Route("/v1/installations/{installation_id}/plan", get_plan),
            Route(
                "/v1/installations/{installation_id}/plans/{plan_id}/reports",
                post_report,
                methods=["POST"],
            ),
        ],
        exception_handlers={
            UnknownInstallationError: not_found,
            UnknownPlanError: not_found,
            InstallationExistsError: exists,
            ReportConflictError: conflict,
            PlanDigestMismatchError: digest_mismatch,
            ConcurrentWriteError: retry,
        },
    )


async def _read_limited(request: Request, limit: int) -> bytes | None:
    """Read the body, or return None as soon as it exceeds `limit` bytes."""

    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            return None
    return bytes(body)


def _error(status_code: int, reason_code: str) -> Response:
    return JSONResponse({"error": reason_code}, status_code=status_code)
