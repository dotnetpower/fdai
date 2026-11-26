"""Public HMAC-authenticated route for notification publication receipts.

This route is the only public entry point for a publishing automation to report
that it posted (or failed to post) an already dispatched A2/A4 card. It carries
no human identity and no approval authority, so it MUST NOT be reachable from
the A1 approval surfaces in
:mod:`fdai_operator_service.families.iam.hil_callback` or
:mod:`fdai_operator_service.families.iam.hil_teams_callback`.
"""

from __future__ import annotations

from fdai_operator_service.families.iam.hil_callback_validation import (
    CallbackError,
    read_bounded_body,
)
from fdai_operator_service.families.iam.http import error_response
from fdai_operator_service.notification_receipt_ingress import (
    NotificationReceiptIngress,
    NotificationReceiptPublicationError,
)
from fdai_service_contracts.notification_receipt import (
    NotificationReceiptAuthenticationError,
    NotificationReceiptFormatError,
)
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

RECEIPT_ROUTE_PATH = "/runtime/integrations/notifications/delivery-receipt"


def make_notification_receipt_route(
    *,
    ingress: NotificationReceiptIngress | None,
) -> Route:
    """Build the bounded receipt route; a missing binding fails closed with 503."""

    async def handler(request: Request) -> Response:
        if ingress is None:
            return error_response(
                503,
                "notification delivery receipts are not configured",
                kind="receipt_unavailable",
            )
        try:
            raw = await read_bounded_body(request, ingress.config.max_body_bytes)
        except CallbackError as exc:
            return error_response(exc.status_code, str(exc), kind=exc.kind)
        try:
            receipt = await ingress.accept(headers=request.headers, body=raw)
        except NotificationReceiptAuthenticationError:
            return error_response(
                401,
                "notification receipt is not authenticated",
                kind="unauthorized",
            )
        except NotificationReceiptFormatError as exc:
            return error_response(400, str(exc), kind="invalid_receipt")
        except NotificationReceiptPublicationError as exc:
            return error_response(502, str(exc), kind="publication_error")
        return JSONResponse(
            {
                "receipt_id": receipt.idempotency_key,
                "accepted": True,
                "observed_at": receipt.observed_at.isoformat(),
            },
            status_code=202,
        )

    return Route(
        RECEIPT_ROUTE_PATH,
        handler,
        methods=["POST"],
        name="post_notification_delivery_receipt",
    )


__all__ = ["RECEIPT_ROUTE_PATH", "make_notification_receipt_route"]
