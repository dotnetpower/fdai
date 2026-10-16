"""Exact argument parsing for governed ActionType promotion."""

from __future__ import annotations

from collections.abc import Mapping

from fdai.shared.contracts.models import Mode
from fdai.shared.providers.direct_api import DirectApiPreconditionError


def promotion_arguments(arguments: Mapping[str, object]) -> dict[str, str]:
    required = (
        "action_type_id",
        "fdai_revision",
        "scenario_set_version",
        "evidence_digest",
        "policy_digest",
    )
    values: dict[str, str] = {}
    for name in required:
        value = arguments.get(name)
        if not isinstance(value, str) or not value.strip():
            raise DirectApiPreconditionError(f"promotion argument {name} is required")
        values[name] = value
    if arguments.get("target_mode") != Mode.ENFORCE.value:
        raise DirectApiPreconditionError("promotion target_mode MUST be enforce")
    return values


__all__ = ["promotion_arguments"]
