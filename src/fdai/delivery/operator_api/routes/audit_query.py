"""Boundary parser for server-side audit query filters."""

from __future__ import annotations

import re
from collections.abc import Mapping

from fdai.delivery.operator_api.read_model import AuditQueryFilters

_WINDOW_RE = re.compile(r"^([1-9][0-9]{0,2})d$")
_VALID_MODES = frozenset({"shadow", "enforce"})
_VALID_TIERS = frozenset({"t0", "t1", "t2"})
_MAX_FILTER_LENGTH = 128
_MAX_BIGINT = 9_223_372_036_854_775_807


class AuditQueryError(ValueError):
    """Raised when an audit filter is malformed or unsupported."""


def parse_audit_filters(params: Mapping[str, str]) -> AuditQueryFilters:
    """Validate URL query values and return normalized read-model filters."""

    mode = _optional(params, "mode")
    if mode is not None and mode not in _VALID_MODES:
        raise AuditQueryError("mode MUST be shadow or enforce")
    tier_raw = _optional(params, "tier")
    tier = tier_raw.lower() if tier_raw is not None else None
    if tier is not None and tier not in _VALID_TIERS:
        raise AuditQueryError("tier MUST be t0, t1, or t2")
    action_kind = _optional(params, "action")
    outcome = _optional(params, "outcome")
    vertical = _optional(params, "vertical")
    window = _optional(params, "window")
    window_days = None
    if window is not None:
        match = _WINDOW_RE.fullmatch(window)
        if match is None or int(match.group(1)) > 365:
            raise AuditQueryError("window MUST be between 1d and 365d")
        window_days = int(match.group(1))
    from_seq = _optional_positive_bigint(params, "from_seq")
    through_seq = _optional_positive_bigint(params, "through_seq")
    if from_seq is not None and through_seq is not None and from_seq > through_seq:
        raise AuditQueryError("from_seq MUST be less than or equal to through_seq")
    return AuditQueryFilters(
        mode=mode,
        tier=tier,
        action_kind=action_kind,
        outcome=outcome,
        vertical=vertical.replace("_", "-").lower() if vertical is not None else None,
        window_days=window_days,
        from_seq=from_seq,
        through_seq=through_seq,
    )


def _optional(params: Mapping[str, str], key: str) -> str | None:
    raw = params.get(key)
    if raw is None or raw == "":
        return None
    value = raw.strip()
    if not value or len(value) > _MAX_FILTER_LENGTH:
        raise AuditQueryError(f"{key} MUST be between 1 and {_MAX_FILTER_LENGTH} characters")
    return value


def _optional_positive_bigint(params: Mapping[str, str], key: str) -> int | None:
    value = _optional(params, key)
    if value is None:
        return None
    if not value.isascii() or not value.isdecimal():
        raise AuditQueryError(f"{key} MUST be a positive integer")
    parsed = int(value)
    if parsed < 1 or parsed > _MAX_BIGINT:
        raise AuditQueryError(f"{key} MUST be between 1 and {_MAX_BIGINT}")
    return parsed


__all__ = ["AuditQueryError", "parse_audit_filters"]
