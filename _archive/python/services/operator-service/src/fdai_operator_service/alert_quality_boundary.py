"""Bounded exact HTTP decoding and no-store alert-quality response serialization."""

from __future__ import annotations

import json
import re
from typing import cast

from fdai_service_contracts.executor_models import ContractBase
from starlette.requests import Request
from starlette.responses import JSONResponse

from fdai_operator_service.alert_quality_config import AlertQualityDependencies, _unique_object
from fdai_operator_service.alert_quality_contracts import (
    MAX_ALERT_QUALITY_BODY_BYTES,
    AlertProposalBody,
    AlertQualityResponse,
    UnavailableReason,
)
from fdai_operator_service.alert_quality_records import (
    MAX_ALERT_QUALITY_BYTES,
    AlertQualityUnavailableError,
    validate_alert_quality_scope,
)


class _RequestError(Exception):
    """A bounded client error with a fixed public status and code."""

    def __init__(self, status: int, code: str) -> None:
        self.status, self.code = status, code


def _query_scope(request: Request) -> str:
    """Require one exact scope; discovery, not an implicit default, owns selection."""
    if len(request.url.query) > 512 or set(request.query_params) - {"scope_ref"}:
        raise _RequestError(400, "invalid_request")
    selected = request.query_params.getlist("scope_ref")
    if len(selected) != 1:
        raise _RequestError(400, "invalid_request")
    try:
        validate_alert_quality_scope(selected[0])
    except ValueError as exc:
        raise _RequestError(400, "invalid_request") from exc
    return selected[0]


async def _body[T: ContractBase](request: Request, model: type[T]) -> T:
    """Decode one bounded JSON body without duplicate members or selector normalization."""
    if (
        request.url.query
        or len(request.headers.getlist("content-encoding")) > 1
        or request.headers.get("content-encoding", "identity") != "identity"
    ):
        raise _RequestError(400, "invalid_request")
    if (
        len(request.headers.getlist("content-type")) != 1
        or request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json"
    ):
        raise _RequestError(400, "invalid_request")
    lengths = request.headers.getlist("content-length")
    if len(lengths) > 1 or (lengths and re.fullmatch(r"[0-9]{1,10}", lengths[0]) is None):
        raise _RequestError(400, "invalid_request")
    if lengths and int(lengths[0]) > MAX_ALERT_QUALITY_BODY_BYTES:
        raise _RequestError(413, "request_too_large")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_ALERT_QUALITY_BODY_BYTES:
            raise _RequestError(413, "request_too_large")
        raw.extend(chunk)
    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
        body = model.model_validate_json(json.dumps(parsed, allow_nan=False), strict=True)
        normalized = body.model_dump(mode="json", exclude_unset=True)
        if isinstance(body, AlertProposalBody):
            # RFC 3339 offsets may normalize to Z; opaque selectors may not change.
            for name in ("starts_at", "ends_at"):
                if name in parsed["treatment"]:
                    parsed["treatment"][name] = normalized["treatment"][name]
        # Shared reference validators must not silently normalize a request selector.
        if normalized != parsed:
            raise ValueError("request normalization is not supported")
    except (TypeError, ValueError, RecursionError) as exc:
        raise _RequestError(400, "invalid_request") from exc
    return body


def _unavailable(
    dependencies: AlertQualityDependencies,
    reason: UnavailableReason,
    *,
    enabled: bool | None = None,
) -> AlertQualityResponse:
    return AlertQualityResponse(
        source="alert-noise-governance",
        available=False,
        enabled=(
            (dependencies.enabled and dependencies.preference_store is None)
            if enabled is None
            else enabled
        ),
        requestable=False,
        authority="shadow",
        unavailable_reason=reason,
        assessment=None,
        plans=(),
    )


def _response(value: ContractBase, *, status: int = 200) -> JSONResponse:
    """Require an exact bounded response roundtrip and forbid cached or sniffed content."""
    encoded = value.model_dump_json()
    if len(encoded.encode()) > MAX_ALERT_QUALITY_BYTES:
        raise AlertQualityUnavailableError("alert quality response exceeds its bound")
    checked = type(value).model_validate_json(encoded, strict=True)
    if checked.model_dump_json() != encoded:
        raise AlertQualityUnavailableError("alert quality response roundtrip failed")
    return JSONResponse(
        cast(dict[str, object], json.loads(encoded)),
        status_code=status,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"status": status, "code": code}},
        status_code=status,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )
