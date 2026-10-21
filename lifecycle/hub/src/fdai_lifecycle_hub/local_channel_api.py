"""Operator-only metadata requests; remote authentication stays with the owning Hub."""

from __future__ import annotations

import logging

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from fdai_lifecycle_hub.domain import Clock
from fdai_lifecycle_hub.local_channels import LocalChannelError, LocalChannelRequest
from fdai_lifecycle_hub.remote_catalog import RemoteCatalog

logger = logging.getLogger(__name__)


def local_channel_routes(catalog: RemoteCatalog, clock: Clock) -> list[Route]:
    async def view(request: Request) -> JSONResponse:
        try:
            result = await run_in_threadpool(catalog.local_channels, now=clock())
        except ValueError:
            logger.warning("hub_local_channels_unavailable reason=catalog_or_curation_unverified")
            return JSONResponse({"error": "Review catalog trust, expiry and local evidence."}, 503)
        except SQLAlchemyError:
            logger.error("hub_local_channels_unavailable reason=storage_unavailable")
            return JSONResponse({"error": "Local curation storage is unavailable."}, 503)
        return JSONResponse(result)

    async def add(request: Request) -> JSONResponse:
        from fdai_lifecycle_hub.api import _read_limited

        raw = await _read_limited(request, 4096)
        if raw is None:
            return JSONResponse({"error": "Local channel request exceeds its byte bound."}, 413)
        try:
            change = LocalChannelRequest.model_validate_json(raw)
            result = await run_in_threadpool(
                catalog.add_local_channel, change, actor=request.state.operator, now=clock()
            )
        except ValidationError:
            return JSONResponse(
                {"error": "Review local channel fields and exact confirmation."}, 422
            )
        except LocalChannelError as error:
            return JSONResponse({"error": str(error)}, error.status)
        except ValueError:
            logger.warning("hub_local_channel_denied reason=catalog_unverified")
            return JSONResponse(
                {"error": "Review the accepted catalog pin, source and expiry."}, 503
            )
        except SQLAlchemyError:
            logger.error("hub_local_channel_unconfirmed reason=storage_unavailable")
            return JSONResponse(
                {"error": "Request not confirmed; refresh retained evidence before retrying."},
                503,
            )
        return JSONResponse(result)

    return [
        Route("/v1/catalog/local-channels", view),
        Route("/v1/catalog/local-channels", add, methods=["POST"]),
    ]
