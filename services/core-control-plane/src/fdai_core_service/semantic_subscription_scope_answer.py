"""Render verified current-subscription identity without exposing raw scope."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime
from typing import cast

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_MASKED_ID = re.compile(r"^[a-f0-9]{4}\.\.\.[a-f0-9]{4}$")
_STATES = frozenset({"Deleted", "Disabled", "Enabled", "PastDue", "Warned"})


def render_subscription_scope_answer(
    outputs: list[dict[str, object]],
    *,
    korean: bool,
    output_shape: str | None,
) -> str | None:
    """Render only the single complete, sanitized provider observation."""

    if output_shape != "subscription_scope_identity":
        return None
    verified = _verified_values(outputs)
    if verified is None:
        return _unavailable(korean)
    display_name, state, masked_id, observed_at, evidence_digest = verified
    if korean:
        return "\n".join(
            (
                "## 현재 Azure 구독",
                "",
                f"- 이름: {display_name}",
                f"- 상태: {state}",
                f"- 구독: `{masked_id}`",
                f"- 관측 시각: {observed_at}",
                f"- 근거: `{evidence_digest}`",
                "",
                "Azure Resource Manager에서 확인한 읽기 전용 결과입니다. "
                "의미 모델은 구독 상세를 제공하거나 변경하지 않았으며 "
                "실행 작업도 발생하지 않았습니다.",
            )
        )
    return "\n".join(
        (
            "## Current Azure subscription",
            "",
            f"- Name: {display_name}",
            f"- State: {state}",
            f"- Subscription: `{masked_id}`",
            f"- Observed at: {observed_at}",
            f"- Evidence: `{evidence_digest}`",
            "",
            "This read-only result was verified from Azure Resource Manager. "
            "The semantic model did not supply or change subscription details, and no action ran.",
        )
    )


def _verified_values(
    outputs: list[dict[str, object]],
) -> tuple[str, str, str, str, str] | None:
    if len(outputs) != 1:
        return None
    output = outputs[0]
    rows = output.get("rows")
    if output.get("source_complete") is not True or not isinstance(rows, list) or len(rows) != 1:
        return None
    values = rows[0].get("values") if isinstance(rows[0], Mapping) else None
    if not isinstance(values, Mapping) or values.get("execution_authority") is not False:
        return None
    display_name = values.get("display_name")
    state = values.get("state")
    masked_id = values.get("masked_subscription_id")
    observed_at = values.get("observed_at")
    evidence_digest = values.get("evidence_digest")
    if (
        not _bounded(display_name, 256)
        or not isinstance(state, str)
        or state not in _STATES
        or not isinstance(masked_id, str)
        or _MASKED_ID.fullmatch(masked_id) is None
        or not isinstance(observed_at, str)
        or _timestamp(observed_at) is None
        or not isinstance(evidence_digest, str)
        or _DIGEST.fullmatch(evidence_digest) is None
    ):
        return None
    return (
        cast(str, display_name),
        state,
        masked_id,
        observed_at,
        evidence_digest,
    )


def _unavailable(korean: bool) -> str:
    return (
        "현재 Azure 구독 신원 근거를 사용할 수 없습니다. "
        "구독 상세를 생성하지 않았으며 실행 작업도 발생하지 않았습니다."
        if korean
        else (
            "Current Azure subscription identity evidence is unavailable. "
            "No subscription details were generated and no action ran."
        )
    )


def _bounded(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= maximum
        and all(ord(char) >= 32 for char in value)
    )


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


__all__ = ["render_subscription_scope_answer"]
