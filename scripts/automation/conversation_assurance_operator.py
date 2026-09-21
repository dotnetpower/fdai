"""Bounded Operator HTTP evaluation for conversation assurance."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

from fdai.core.conversation_assurance import (  # noqa: E402
    CampaignHoldError,
    PantheonRubric,
    PantheonSemanticReview,
)

_ASSESSMENT_REASON = re.compile(r"^[a-z][A-Za-z0-9_.:-]{0,127}$")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def _open_operator_request(request: urllib.request.Request, *, timeout: int) -> Any:
    return urllib.request.build_opener(_NoRedirectHandler()).open(request, timeout=timeout)


def _terminal_payload(raw: str) -> dict[str, Any]:
    terminal: dict[str, Any] | None = None
    terminal_seen = False
    for frame in re.split(r"\r?\n\r?\n", raw.strip()):
        event = "message"
        data: list[str] = []
        for line in frame.splitlines():
            if line.startswith(":"):
                continue
            if line.startswith("event:"):
                event = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data.append(line.removeprefix("data:").strip())
        if not data:
            continue
        if terminal_seen or event == "error":
            raise CampaignHoldError("terminal_response_invalid")
        if event != "done":
            continue
        try:
            decoded = json.loads("\n".join(data))
        except json.JSONDecodeError as error:
            raise CampaignHoldError("terminal_response_invalid") from error
        if not isinstance(decoded, Mapping):
            raise CampaignHoldError("terminal_response_invalid")
        terminal = {str(key): value for key, value in decoded.items()}
        terminal_seen = True
    if terminal is None:
        raise CampaignHoldError("terminal_response_missing")
    return terminal


def _assessment_reasons(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 16:
        raise CampaignHoldError("assessment_reasons_invalid")
    reasons = tuple(value)
    if any(
        not isinstance(reason, str) or _ASSESSMENT_REASON.fullmatch(reason) is None
        for reason in reasons
    ):
        raise CampaignHoldError("assessment_reasons_invalid")
    return reasons


def _semantic_reviews(value: object) -> tuple[PantheonSemanticReview, ...]:
    if not isinstance(value, list):
        return ()
    reviews: list[PantheonSemanticReview] = []
    for raw in value[:3]:
        if not isinstance(raw, Mapping):
            continue
        results = raw.get("results")
        if not isinstance(results, Mapping):
            continue
        reviews.append(
            PantheonSemanticReview(
                reviewer_identity=str(raw.get("reviewer_identity", "")),
                model_family=str(raw.get("model_family", "")),
                confidence=float(raw.get("confidence", 0.0)),
                results=tuple(
                    (rubric, _boolean(results.get(rubric.value), rubric.value))
                    for rubric in tuple(PantheonRubric)[10:15]
                ),
            )
        )
    return tuple(reviews)


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{label} MUST be boolean")
    return value
