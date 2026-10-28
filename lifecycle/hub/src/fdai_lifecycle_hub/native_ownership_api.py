"""Native creation cannot self-authorize through an Agent identity."""

from __future__ import annotations

from fdai_deployment_cli.contracts import load_json_object
from fdai_deployment_cli.lifecycle_native import NativeOwnershipAcceptance, SignedNativeScope
from fdai_deployment_cli.lifecycle_native_reconciliation import (
    NativeScopeTransitionStateReconciliationApprovalRequest,
    NativeScopeTransitionStateReconciliationCompletion,
)
from fdai_deployment_cli.lifecycle_native_transition import (
    NativeScopeTransitionCompletion,
    SignedNativeScopeTransitionRequest,
)
from pydantic import TypeAdapter
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from fdai_lifecycle_hub.domain import Clock
from fdai_lifecycle_hub.native_ownership import NativeOwnershipError, NativeOwnershipStore
from fdai_lifecycle_hub.native_proofs import NativeProofStore
from fdai_lifecycle_hub.native_transition import NativeTransitionError, NativeTransitionStore
from fdai_lifecycle_hub.native_transition_reconciliation import (
    NativeTransitionReconciliationError,
    NativeTransitionReconciliationStore,
)
from fdai_lifecycle_hub.signing import HubSigningKey
from fdai_lifecycle_hub.store import HubStore

_RECONCILIATION_APPROVAL_REQUEST: TypeAdapter[
    NativeScopeTransitionStateReconciliationApprovalRequest
] = TypeAdapter(NativeScopeTransitionStateReconciliationApprovalRequest)


def native_ownership_routes(
    store: HubStore,
    clock: Clock,
    *,
    authenticated: bool,
    transition_key: HubSigningKey | None = None,
) -> list[Route]:
    async def submit(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _read_limited

        principal = getattr(request.state, "principal", None)
        if not authenticated or not principal or getattr(request.state, "operator", None):
            return JSONResponse({"error": "authenticated_agent_required"}, status_code=403)
        body = await _read_limited(request, 8192)
        if body is None:
            return JSONResponse({"error": "native_proof_too_large"}, status_code=413)
        try:
            load_json_object(body, label="native proof", max_bytes=8192, strict=True)
            proof = SignedNativeScope.model_validate_json(body)
        except ValueError:
            return JSONResponse({"error": "native_proof_invalid"}, status_code=422)
        try:
            changed = await run_in_threadpool(
                NativeProofStore(store).submit,
                request.path_params["installation_id"],
                proof,
                principal=principal,
                now=clock(),
            )
        except NativeOwnershipError as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        return JSONResponse({"received": True, "changed": changed}, status_code=202)

    async def accept(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _read_limited

        if not authenticated or not getattr(request.state, "operator", None):
            return JSONResponse({"error": "authenticated_operator_required"}, status_code=403)
        body = await _read_limited(request, 8192)
        if body is None:
            return JSONResponse({"error": "native_ownership_too_large"}, status_code=413)
        try:
            load_json_object(body, label="native ownership", max_bytes=8192, strict=True)
            command = NativeOwnershipAcceptance.model_validate_json(body)
        except ValueError:
            return JSONResponse({"error": "native_ownership_invalid"}, status_code=422)
        try:
            result = await run_in_threadpool(
                NativeOwnershipStore(store).accept,
                request.path_params["installation_id"],
                command,
                operator=request.state.operator,
                now=clock(),
            )
        except NativeOwnershipError as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        return JSONResponse(result)

    async def approve_transition(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _read_limited

        if not authenticated or not getattr(request.state, "operator", None):
            return JSONResponse({"error": "authenticated_operator_required"}, status_code=403)
        if transition_key is None:
            return JSONResponse({"error": "native_transition_signing_unavailable"}, status_code=503)
        body = await _read_limited(request, 16384)
        if body is None:
            return JSONResponse({"error": "native_transition_too_large"}, status_code=413)
        try:
            load_json_object(body, label="native transition", max_bytes=16384, strict=True)
            command = SignedNativeScopeTransitionRequest.model_validate_json(body)
        except ValueError:
            return JSONResponse({"error": "native_transition_invalid"}, status_code=422)
        try:
            result = await run_in_threadpool(
                NativeTransitionStore(store).approve,
                request.path_params["installation_id"],
                command,
                operator=request.state.operator,
                now=clock(),
                key=transition_key,
            )
        except NativeTransitionError as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        return JSONResponse(result.model_dump(mode="json"))

    async def complete_transition(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _read_limited

        principal = getattr(request.state, "principal", None)
        if not authenticated or not principal or getattr(request.state, "operator", None):
            return JSONResponse({"error": "authenticated_agent_required"}, status_code=403)
        if transition_key is None:
            return JSONResponse({"error": "native_transition_signing_unavailable"}, status_code=503)
        body = await _read_limited(request, 64 * 1024)
        if body is None:
            return JSONResponse(
                {"error": "native_transition_completion_too_large"}, status_code=413
            )
        try:
            load_json_object(
                body,
                label="native transition completion",
                max_bytes=64 * 1024,
                strict=True,
            )
            command = NativeScopeTransitionCompletion.model_validate_json(body)
        except ValueError:
            return JSONResponse({"error": "native_transition_completion_invalid"}, status_code=422)
        try:
            result = await run_in_threadpool(
                NativeTransitionStore(store).complete,
                request.path_params["installation_id"],
                command,
                principal=principal,
                now=clock(),
                key=transition_key,
            )
        except NativeTransitionError as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        return JSONResponse(result.model_dump(mode="json"))

    async def approve_reconciliation(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _read_limited

        if not authenticated or not getattr(request.state, "operator", None):
            return JSONResponse({"error": "authenticated_operator_required"}, status_code=403)
        if transition_key is None:
            return JSONResponse({"error": "native_transition_signing_unavailable"}, status_code=503)
        body = await _read_limited(request, 128 * 1024)
        if body is None:
            return JSONResponse(
                {"error": "native_transition_reconciliation_too_large"},
                status_code=413,
            )
        try:
            load_json_object(
                body,
                label="native transition reconciliation",
                max_bytes=128 * 1024,
                strict=True,
            )
            command = _RECONCILIATION_APPROVAL_REQUEST.validate_json(body)
        except ValueError:
            return JSONResponse(
                {"error": "native_transition_reconciliation_invalid"},
                status_code=422,
            )
        try:
            result = await run_in_threadpool(
                NativeTransitionReconciliationStore(store).approve,
                request.path_params["installation_id"],
                command,
                operator=request.state.operator,
                now=clock(),
                key=transition_key,
            )
        except NativeTransitionReconciliationError as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        return JSONResponse(result.model_dump(mode="json"))

    async def complete_reconciliation(request: Request) -> Response:
        from fdai_lifecycle_hub.api import _read_limited

        principal = getattr(request.state, "principal", None)
        if not authenticated or not principal or getattr(request.state, "operator", None):
            return JSONResponse({"error": "authenticated_agent_required"}, status_code=403)
        if transition_key is None:
            return JSONResponse({"error": "native_transition_signing_unavailable"}, status_code=503)
        body = await _read_limited(request, 192 * 1024)
        if body is None:
            return JSONResponse(
                {"error": "native_transition_reconciliation_completion_too_large"},
                status_code=413,
            )
        try:
            load_json_object(
                body,
                label="native transition reconciliation completion",
                max_bytes=192 * 1024,
                strict=True,
            )
            command = NativeScopeTransitionStateReconciliationCompletion.model_validate_json(body)
        except ValueError:
            return JSONResponse(
                {"error": "native_transition_reconciliation_completion_invalid"},
                status_code=422,
            )
        try:
            result = await run_in_threadpool(
                NativeTransitionReconciliationStore(store).complete,
                request.path_params["installation_id"],
                command,
                principal=principal,
                now=clock(),
                key=transition_key,
            )
        except NativeTransitionReconciliationError as error:
            return JSONResponse({"error": str(error)}, status_code=409)
        return JSONResponse(result.model_dump(mode="json"))

    return [
        Route(
            "/v1/installations/{installation_id}/native-proofs",
            submit,
            methods=["POST"],
        ),
        Route(
            "/v1/installations/{installation_id}/native-ownership",
            accept,
            methods=["POST"],
        ),
        Route(
            "/v1/installations/{installation_id}/native-transition-approval",
            approve_transition,
            methods=["POST"],
        ),
        Route(
            "/v1/installations/{installation_id}/native-transition-completion",
            complete_transition,
            methods=["POST"],
        ),
        Route(
            "/v1/installations/{installation_id}/native-transition-state-reconciliation-approval",
            approve_reconciliation,
            methods=["POST"],
        ),
        Route(
            "/v1/installations/{installation_id}/native-transition-state-reconciliation",
            complete_reconciliation,
            methods=["POST"],
        ),
    ]
