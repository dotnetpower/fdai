"""Build localized Console facts from verified subscription identity rows."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import cast

from fdai_operator_service.families.conversation.contracts import JsonObject
from fdai_operator_service.families.conversation.presentation_artifact_v3 import (
    assemble_presentation_artifact_v3,
)

_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_MASKED_ID = re.compile(r"^[a-f0-9]{4}\.\.\.[a-f0-9]{4}$")
_STATES = frozenset({"Deleted", "Disabled", "Enabled", "PastDue", "Warned"})


def subscription_scope_artifact(
    *,
    output: Mapping[str, object],
    evidence_refs: list[str],
    locale: str,
    verified: bool,
) -> JsonObject | None:
    """Return localized fields only for one complete sanitized observation."""

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
        or not _bounded(observed_at, 64)
        or not isinstance(evidence_digest, str)
        or _DIGEST.fullmatch(evidence_digest) is None
    ):
        return None
    korean = locale.casefold().startswith("ko")
    labels = (
        ("이름", "상태", "구독", "관측 시각", "근거")
        if korean
        else ("Name", "State", "Subscription", "Observed at", "Evidence")
    )
    items = [
        {"label": labels[0], "value": display_name, "tone": "neutral"},
        {"label": labels[1], "value": state, "tone": "neutral"},
        {"label": labels[2], "value": masked_id, "tone": "neutral"},
        {"label": labels[3], "value": observed_at, "tone": "neutral"},
        {"label": labels[4], "value": evidence_digest, "tone": "neutral"},
    ]
    return assemble_presentation_artifact_v3(
        layout="operational_brief",
        blocks=cast(
            list[JsonObject],
            [
                {
                    "slot_id": "overview",
                    "kind": "summary",
                    "title": "검증된 구독 신원" if korean else "Verified subscription identity",
                    "emphasis": "primary",
                    "collapsed": False,
                    "evidence_refs": evidence_refs,
                    "data": {"items": items, "verified": verified},
                }
            ],
        ),
        evidence_refs=evidence_refs,
        locale=locale,
        input_kinds=("verified_semantic_result", "presentation_context", "operator_locale"),
    )


def _bounded(value: object, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= maximum
        and all(ord(char) >= 32 for char in value)
    )


__all__ = ["subscription_scope_artifact"]
