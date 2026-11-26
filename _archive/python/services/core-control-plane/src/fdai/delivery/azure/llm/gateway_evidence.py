"""Validate APIM backend-selection evidence and persist a redacted transition."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import httpx

from fdai.delivery.azure.llm.latency_routed_cross_check import (
    ModelHealthTransition,
    ModelHealthTransitionSink,
)
from fdai.delivery.azure.llm.request_target import ModelRequestTarget
from fdai.rule_catalog.schema.model_endpoint import ModelRouteKind

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_CAPACITY_UNITS = frozenset(("tpm", "ptu", "gpu"))


async def record_gateway_route_evidence(
    *,
    response: httpx.Response,
    target: ModelRequestTarget,
    model_role: str,
    sink: ModelHealthTransitionSink | None,
) -> None:
    """Require APIM route headers and append only redacted backend selection."""
    if target.route_kind is not ModelRouteKind.APIM_GATEWAY:
        return
    backend = response.headers.get("x-fdai-model-backend", "")
    capacity_unit = response.headers.get("x-fdai-capacity-unit", "").casefold()
    spillover = response.headers.get("x-fdai-spillover", "").casefold()
    if (
        _SAFE_ID.fullmatch(backend) is None
        or capacity_unit not in _CAPACITY_UNITS
        or spillover not in {"true", "false"}
    ):
        raise RuntimeError("APIM model route evidence is missing or invalid")
    if sink is None:
        raise RuntimeError("APIM model route evidence has no durable sink")
    await sink.append(
        ModelHealthTransition(
            model_role=model_role,
            deployment=backend,
            status="selected",
            failure_kind=None,
            failure_count=0,
            cooldown_seconds=0,
            recorded_at=datetime.now(tz=UTC),
            reason=(
                f"apim_route:capacity_unit={capacity_unit}:spillover={spillover}:"
                f"binding={target.binding_id}"
            ),
        )
    )


__all__ = ["record_gateway_route_evidence"]
