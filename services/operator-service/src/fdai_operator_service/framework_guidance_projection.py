"""Attach one source-matched, inert guide to an authenticated control detail."""

from collections.abc import Mapping

from fdai_service_contracts.framework_guidance import framework_guidance_detail
from starlette.exceptions import HTTPException


def attach_framework_guidance(
    detail: Mapping[str, object], *, framework_id: str
) -> dict[str, object]:
    try:
        return framework_guidance_detail(detail, framework_id=framework_id)
    except ValueError:
        raise HTTPException(
            status_code=503, detail="Framework guidance source validation failed"
        ) from None
