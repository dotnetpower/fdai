"""The Hub HTTP API: the routes installation agents poll and the routes the operator UI reads.

Lifecycle I0 serves on loopback only and has no caller authentication. Agent identity, operator
sign-in, and transport authentication are Lifecycle I1 work and gate any non-loopback binding.
"""

from __future__ import annotations

from base64 import b64encode
from functools import partial
from pathlib import Path
from typing import Literal

from fdai_deployment_cli.lifecycle_plan import SuppressionWindow
from pydantic import ValidationError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import BaseRoute, Route

from fdai_lifecycle_hub.configuration_key_api import key_routes
from fdai_lifecycle_hub.configuration_key_store import ConfigurationKeyStore
from fdai_lifecycle_hub.domain import Clock, utc_now
from fdai_lifecycle_hub.enrollment import EnrollmentStatus, KeyProofVerifier
from fdai_lifecycle_hub.entitlement_handoff import (
    GovernedEntitlementRotationReceipt,
    HubEntitlementHandoffStore,
    OpaqueEntitlementCarrierHandoff,
)
from fdai_lifecycle_hub.errors import (
    ConcurrentWriteError,
    EnrollmentProofError,
    InstallationExistsError,
    InstallationKeyMismatchError,
    NotEnrolledError,
    NotPendingError,
    PlanDigestMismatchError,
    ReportAttemptGapError,
    ReportConflictError,
    ReportProgressionError,
    SchemaMigrationPendingError,
    StateRejectedError,
    UnknownInstallationError,
    UnknownPlanError,
)
from fdai_lifecycle_hub.execution_settings_api import execution_settings_routes
from fdai_lifecycle_hub.native_ownership_api import native_ownership_routes
from fdai_lifecycle_hub.remote_auth import RemoteAuth, secure_app
from fdai_lifecycle_hub.schemas import (
    ApprovalRequest,
    LiftSuppressionRequest,
    PlanReport,
    RejectionRequest,
    SignedEnrollment,
    SuppressionCommandRequest,
    actor_name,
    enrollment_request,
    installation_detail_record,
    installation_summary_record,
    pending_enrollment_record,
    plan_record,
    reported_state_json,
)
from fdai_lifecycle_hub.signing import HubSigningKey, verify_key_proof
from fdai_lifecycle_hub.store import HubStore

MAX_REPORT_BYTES = 16 * 1024
MAX_ENROLLMENT_BYTES = 64 * 1024
# An enrollment request carries the same reported-state snapshot, so the same bound fits.
MAX_STATE_BYTES = 64 * 1024
MAX_APPROVAL_BYTES = 4 * 1024
# `src/fdai_lifecycle_hub/api.py` -> `src` -> `hub`, then the UI's Vite build output.
DEFAULT_UI_DIST = Path(__file__).resolve().parent.parent.parent / "ui" / "dist"


def create_app(
    store: HubStore,
    *,
    clock: Clock = utc_now,
    verify_proof: KeyProofVerifier = verify_key_proof,
    static_dir: Path | None = None,
    remote_auth: RemoteAuth | None = None,
    remote_origin: str | None = None,
    transition_key: HubSigningKey | None = None,
) -> Starlette:
    """The agent API, plus the read-only and approval routes the operator UI calls.

    `static_dir`, when given an existing directory, serves the built operator UI from it as a
    single-page app, so `/v1/...` and `/healthz` always take priority over the UI's own routes.
    """

    async def healthz(request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    async def list_configurations(request: Request) -> Response:
        return JSONResponse(await run_in_threadpool(store.configuration_inventory))

    async def get_plan(request: Request) -> Response:
        installation_id = request.path_params["installation_id"]
        plan = await run_in_threadpool(store.current_plan, installation_id, now=clock())
        if plan is None:
            return Response(status_code=204)
        payload: dict[str, object] = {
            "plan": {
                "signed_payload": b64encode(plan.signed_payload).decode("ascii"),
                "signature": b64encode(plan.signature).decode("ascii"),
            }
        }
        handoff = await run_in_threadpool(store.plan_entitlement_handoff, plan.plan_id)
        if handoff is not None:
            payload["entitlement_handoff"] = handoff.to_plan_attachment()
        return JSONResponse(payload)

    async def get_entitlement_handoff(request: Request) -> Response:
        installation_id = request.path_params["installation_id"]
        handoff = await run_in_threadpool(store.entitlement_handoff, installation_id)
        if handoff is None:
            return Response(status_code=204)
        return JSONResponse({"entitlement_handoff": handoff.to_plan_attachment()})

    async def post_enrollment(
        request: Request,
        *,
        requested_by: str | None = None,
        requested_via: Literal["agent", "operator"] | None = None,
    ) -> Response:
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
                store.request_enrollment,
                enrollment,
                verify=verify_proof,
                now=clock(),
                requested_by=requested_by,
                requested_via=requested_via,
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

    async def post_operator_enrollment(request: Request) -> Response:
        if error := _decision_request_error(request):
            return error
        if remote_auth is None or not any(
            principal.installation_id == request.path_params["installation_id"]
            for principal in remote_auth.agent_principals
        ):
            return _error(403, "installation_not_bound")
        return await post_enrollment(
            request, requested_by=request.state.operator, requested_via="operator"
        )

    async def post_agent_enrollment(request: Request) -> Response:
        """Let the Agent bound to exactly this installation propose, never decide, enrollment."""

        principal = getattr(request.state, "principal", None)
        installation_id = request.path_params["installation_id"]
        if (
            remote_auth is None
            or hasattr(request.state, "operator")
            or not isinstance(principal, str)
            or not any(
                bound.installation_id == installation_id and bound.object_id == principal
                for bound in remote_auth.agent_principals
            )
        ):
            return _error(403, "principal_not_authorized")
        try:
            schemas_actor = actor_name.validate_python(principal)
        except ValidationError:
            return _error(403, "principal_not_authorized")
        return await post_enrollment(request, requested_by=schemas_actor, requested_via="agent")

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

    async def post_state(request: Request) -> Response:
        body = await _read_limited(request, MAX_STATE_BYTES)
        if body is None:
            return _error(413, "state_too_large")
        try:
            state = reported_state_json.validate_json(body)
        except ValidationError:
            return _error(422, "state_invalid")
        try:
            await run_in_threadpool(
                store.record_state, request.path_params["installation_id"], state, now=clock()
            )
        except StateRejectedError as error:
            return _error(409, "stale_state") if error.stale else _error(422, "state_invalid")
        return Response(status_code=202)

    async def list_installations(request: Request) -> Response:
        now = clock()
        overviews = await run_in_threadpool(store.list_installations)
        return JSONResponse(
            {
                "installations": [
                    installation_summary_record(overview, now=now) for overview in overviews
                ]
            }
        )

    async def get_installation(request: Request) -> Response:
        installation_id = request.path_params["installation_id"]
        status = await run_in_threadpool(store.enrollment_status, installation_id)
        if status is not EnrollmentStatus.ENROLLED:
            # Only an enrolled installation is on the list screen or has its own detail page.
            raise NotEnrolledError(installation_id)
        now = clock()
        installation = await run_in_threadpool(store.load, installation_id)
        last_evaluation = await run_in_threadpool(store.last_evaluation, installation_id)
        open_plan = await run_in_threadpool(store.current_plan, installation_id, now=now)
        reports = await run_in_threadpool(store.reports, installation_id)
        return JSONResponse(
            installation_detail_record(
                installation,
                enrollment=status,
                open_plan=open_plan,
                last_evaluation=last_evaluation,
                reports=reports,
                now=now,
            )
        )

    async def get_plan_detail(request: Request) -> Response:
        installation_id = request.path_params["installation_id"]
        plan_id = request.path_params["plan_id"]
        record = await run_in_threadpool(store.plan_detail, installation_id, plan_id)
        reports = await run_in_threadpool(store.plan_reports, plan_id)
        return JSONResponse(plan_record(record, installation_id=installation_id, reports=reports))

    async def list_pending(request: Request) -> Response:
        pending = await run_in_threadpool(store.list_pending_enrollments)
        return JSONResponse({"enrollments": [pending_enrollment_record(item) for item in pending]})

    async def list_bindable(request: Request) -> Response:
        """Installations the deployment bound to an Agent, so the operator picks, not types."""

        pending, enrolled = await run_in_threadpool(
            lambda: (store.list_pending_enrollments(), store.list_installations())
        )
        status = {item.installation.installation_id: "pending" for item in pending} | {
            item.installation.installation_id: "enrolled" for item in enrolled
        }
        principals = remote_auth.agent_principals if remote_auth is not None else ()
        bound = sorted({principal.installation_id for principal in principals})
        return JSONResponse(
            {
                "installations": [
                    {"installation_id": name, "status": status.get(name, "unrequested")}
                    for name in bound
                ]
            }
        )

    async def get_pending(request: Request) -> Response:
        installation_id = request.path_params["installation_id"]
        pending = await run_in_threadpool(store.pending_enrollment, installation_id)
        return JSONResponse(pending_enrollment_record(pending))

    async def post_approve(request: Request) -> Response:
        if error := _decision_request_error(request):
            return error
        body = await _read_limited(request, MAX_APPROVAL_BYTES)
        if body is None:
            return _error(413, "request_too_large")
        try:
            approval = ApprovalRequest.model_validate_json(body)
        except ValidationError:
            return _error(422, "approval_invalid")
        installation_id = request.path_params["installation_id"]
        await run_in_threadpool(
            store.approve,
            installation_id,
            approver=request.state.operator if remote_auth else approval.approver,
            installation_key_id=approval.installation_key_id,
            now=clock(),
        )
        return JSONResponse({"enrolled": installation_id})

    async def post_reject(request: Request) -> Response:
        if error := _decision_request_error(request):
            return error
        body = await _read_limited(request, MAX_APPROVAL_BYTES)
        if body is None:
            return _error(413, "request_too_large")
        try:
            rejection = RejectionRequest.model_validate_json(body)
        except ValidationError:
            return _error(422, "rejection_invalid")
        installation_id = request.path_params["installation_id"]
        await run_in_threadpool(
            store.reject,
            installation_id,
            approver=request.state.operator if remote_auth else rejection.approver,
            reason=rejection.reason,
            now=clock(),
        )
        return JSONResponse({"rejected": installation_id})

    async def list_audit(request: Request) -> Response:
        fields = dict(request.query_params)
        if len(fields) != len(request.query_params.multi_items()):
            return _error(422, "audit_query_invalid")
        if set(fields) - {"installation_id", "limit"}:
            return _error(422, "audit_query_invalid")
        installation_id = fields.get("installation_id")
        if installation_id is not None and not installation_id.strip():
            return _error(422, "audit_query_invalid")
        limit = 100
        if "limit" in fields:
            raw_limit = fields["limit"]
            if not raw_limit.isascii() or not raw_limit.isdecimal():
                return _error(422, "audit_query_invalid")
            limit = int(raw_limit)
            if not 1 <= limit <= 200:
                return _error(422, "audit_query_invalid")
        return JSONResponse(
            await run_in_threadpool(
                partial(store.audit_records, installation_id=installation_id, limit=limit)
            )
        )

    async def post_suppression(request: Request) -> Response:
        if error := _decision_request_error(request):
            return error
        body = await _read_limited(request, MAX_APPROVAL_BYTES)
        if body is None:
            return _error(413, "request_too_large")
        try:
            command = SuppressionCommandRequest.model_validate_json(body)
            window = SuppressionWindow(
                command.scope, command.starts_at, command.ends_at, origin="manual"
            )
        except (ValidationError, ValueError):
            return _error(422, "suppression_invalid")
        installation_id = request.path_params["installation_id"]
        if command.confirmation != f"suppress {installation_id} {command.scope}":
            return _error(422, "suppression_invalid")
        try:
            await run_in_threadpool(store.add_suppression, installation_id, window, now=clock())
        except ValueError:
            return _error(422, "suppression_invalid")
        return JSONResponse(
            {
                "suppressed": installation_id,
                "scope": command.scope,
                "ends_at": command.ends_at.isoformat(),
            }
        )

    async def post_lift_suppression(request: Request) -> Response:
        if error := _decision_request_error(request):
            return error
        body = await _read_limited(request, MAX_APPROVAL_BYTES)
        if body is None:
            return _error(413, "request_too_large")
        try:
            command = LiftSuppressionRequest.model_validate_json(body)
        except ValidationError:
            return _error(422, "suppression_invalid")
        installation_id = request.path_params["installation_id"]
        if command.confirmation != f"lift suppression {installation_id} {command.scope}":
            return _error(422, "suppression_invalid")
        try:
            await run_in_threadpool(
                store.lift_suppressions, installation_id, command.scope, now=clock()
            )
        except ValueError:
            return _error(409, "suppression_not_active")
        return JSONResponse({"lifted": installation_id, "scope": command.scope})

    async def not_found(request: Request, exc: Exception) -> Response:
        return _error(404, "not_found")

    async def exists(request: Request, exc: Exception) -> Response:
        return _error(409, "installation_exists")

    async def conflict(request: Request, exc: Exception) -> Response:
        return _error(409, "report_conflict")

    async def report_attempt_gap(request: Request, exc: Exception) -> Response:
        return _error(409, "report_attempt_gap")

    async def report_invalid(request: Request, exc: Exception) -> Response:
        return _error(422, "report_invalid")

    async def digest_mismatch(request: Request, exc: Exception) -> Response:
        return _error(409, "plan_digest_mismatch")

    async def not_pending(request: Request, exc: Exception) -> Response:
        return _error(409, "not_pending")

    async def key_mismatch(request: Request, exc: Exception) -> Response:
        return _error(422, "installation_key_mismatch")

    async def retry(request: Request, exc: Exception) -> Response:
        response = _error(503, "concurrent_write")
        response.headers["Retry-After"] = "1"
        return response

    routes: list[BaseRoute] = [
        *execution_settings_routes(store, clock, authenticated=remote_auth is not None),
        *native_ownership_routes(
            store,
            clock,
            authenticated=remote_auth is not None,
            transition_key=transition_key,
        ),
        *key_routes(
            ConfigurationKeyStore(store.engine),
            clock,
            authenticated=remote_auth is not None,
            recovery_authorization=(
                None if remote_auth is None else remote_auth.development_recovery
            ),
        ),
        Route("/auth/config", lambda request: JSONResponse({"profile": "local-development"})),
        Route("/healthz", healthz),
        Route("/v1/installations/{installation_id}/enrollment", post_enrollment, methods=["POST"]),
        Route("/v1/installations/{installation_id}/plan", get_plan),
        Route(
            "/v1/installations/{installation_id}/entitlement-handoff",
            get_entitlement_handoff,
        ),
        Route(
            "/v1/installations/{installation_id}/plans/{plan_id}/reports",
            post_report,
            methods=["POST"],
        ),
        Route("/v1/installations/{installation_id}/state", post_state, methods=["POST"]),
        # Operator UI routes: read-only, plus enrollment approval and suppression commands.
        Route("/v1/installations", list_installations),
        Route("/v1/configurations", list_configurations),
        Route("/v1/audit", list_audit),
        Route("/v1/installations/{installation_id}", get_installation),
        Route("/v1/installations/{installation_id}/plans/{plan_id}", get_plan_detail),
        Route(
            "/v1/installations/{installation_id}/suppressions",
            post_suppression,
            methods=["POST"],
        ),
        Route(
            "/v1/installations/{installation_id}/suppressions/lift",
            post_lift_suppression,
            methods=["POST"],
        ),
        Route("/v1/enrollments/pending", list_pending),
        Route("/v1/enrollments/pending/{installation_id}", get_pending),
        Route(
            "/v1/installations/{installation_id}/enrollment/approve",
            post_approve,
            methods=["POST"],
        ),
        Route(
            "/v1/installations/{installation_id}/enrollment/reject",
            post_reject,
            methods=["POST"],
        ),
    ]
    if remote_auth is not None and remote_auth.agent_principals:
        routes.append(Route("/v1/enrollments/bindable", list_bindable))
        routes.append(
            Route(
                "/v1/installations/{installation_id}/enrollment-request",
                post_agent_enrollment,
                methods=["POST"],
            )
        )
        routes.append(
            Route(
                "/v1/enrollments/{installation_id}/requests",
                post_operator_enrollment,
                methods=["POST"],
            )
        )
    if static_dir is not None:
        # The UI is a single-page app: any built file (an asset, the brand image, the favicon)
        # is served as-is; any other path (a route the UI's own router reads) gets `index.html`.
        index_file = static_dir / "index.html"
        resolved_static_dir = static_dir.resolve()

        async def serve_ui(request: Request) -> Response:
            if request.url.path.startswith("/v1/"):
                return _error(404, "not_found")
            requested = (static_dir / request.path_params["path"]).resolve()
            if requested.is_relative_to(resolved_static_dir) and requested.is_file():
                return FileResponse(requested)
            if not index_file.is_file():
                return _error(404, "not_found")
            return FileResponse(index_file)

        routes.append(Route("/{path:path}", serve_ui))

    async def migration_pending(request: Request, error: Exception) -> Response:
        return _error(503, "schema_migration_pending")

    app = Starlette(
        routes=routes,
        exception_handlers={
            UnknownInstallationError: not_found,
            UnknownPlanError: not_found,
            # The agent API serves nothing to an installation that isn't enrolled.
            NotEnrolledError: not_found,
            InstallationExistsError: exists,
            ReportConflictError: conflict,
            ReportAttemptGapError: report_attempt_gap,
            ReportProgressionError: report_invalid,
            PlanDigestMismatchError: digest_mismatch,
            NotPendingError: not_pending,
            InstallationKeyMismatchError: key_mismatch,
            ConcurrentWriteError: retry,
            SchemaMigrationPendingError: migration_pending,
        },
    )
    return (
        secure_app(app, remote_auth, vendor=False, origin=remote_origin)
        if remote_auth is not None or remote_origin is not None
        else app
    )


def _decision_request_error(request: Request) -> Response | None:
    """Reject browser cross-origin decisions before reading their body.

    Vite preserves the browser Host and Origin when proxying to the Hub. Clients
    without Origin must still use JSON and a loopback Host; no CORS is enabled.
    """
    if not hasattr(request.state, "operator") and request.url.hostname not in {
        "localhost",
        "127.0.0.1",
        "::1",
    }:
        return _error(403, "untrusted_host")
    origin = request.headers.get("origin")
    if (
        not hasattr(request.state, "operator")
        and origin is not None
        and origin != str(request.base_url).rstrip("/")
    ):
        return _error(403, "untrusted_origin")
    if request.headers.get("sec-fetch-site") == "cross-site":
        return _error(403, "untrusted_origin")
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        return _error(415, "json_required")
    return None


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


__all__ = [
    "DEFAULT_UI_DIST",
    "GovernedEntitlementRotationReceipt",
    "HubEntitlementHandoffStore",
    "MAX_APPROVAL_BYTES",
    "MAX_ENROLLMENT_BYTES",
    "MAX_REPORT_BYTES",
    "MAX_STATE_BYTES",
    "OpaqueEntitlementCarrierHandoff",
    "create_app",
]
