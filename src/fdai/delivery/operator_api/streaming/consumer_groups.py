"""Derive one Kafka consumer group per Operator API stream replica."""

from __future__ import annotations

import re
from collections.abc import Mapping

_INSTANCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def instance_consumer_group(base: str, env: Mapping[str, str]) -> str:
    """Return a validated instance-scoped group or the test-harness base."""
    instance = (
        env.get("FDAI_OPERATOR_API_CONSUMER_INSTANCE", "").strip()
        or env.get("HOSTNAME", "").strip()
    )
    if not instance:
        return base
    if _INSTANCE_PATTERN.fullmatch(instance) is None:
        raise ValueError(
            "Operator API consumer instance MUST start with an alphanumeric character "
            "and contain at most 128 alphanumeric, dot, underscore, or hyphen characters"
        )
    return f"{base}.{instance}"


__all__ = ["instance_consumer_group"]
