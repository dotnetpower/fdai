"""Load deployment-owned operational history retention policies."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from fdai.core.ontology_platform.operational_history_retention import (
    ObservationRetentionPolicy,
    load_retention_policy_registry,
)

RETENTION_POLICY_PATH_ENV = "FDAI_OPERATIONAL_HISTORY_RETENTION_PATH"
_MAX_POLICY_FILE_BYTES = 256 * 1024


def load_operational_history_retention_policies(
    environ: Mapping[str, str],
) -> tuple[ObservationRetentionPolicy, ...]:
    """Load optional deployment policy; absence preserves the safe retain default."""

    raw_path = environ.get(RETENTION_POLICY_PATH_ENV, "").strip()
    if not raw_path:
        return ()
    path = Path(raw_path)
    if not path.is_file():
        raise ValueError(f"{RETENTION_POLICY_PATH_ENV} MUST identify a readable file")
    if path.stat().st_size > _MAX_POLICY_FILE_BYTES:
        raise ValueError("operational history retention policy file exceeds its byte bound")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("operational history retention policy file is invalid") from exc
    if not isinstance(raw, Mapping) or raw.get("schema_version") != "1.0.0":
        raise ValueError("operational history retention policy schema is unsupported")
    policies = raw.get("policies")
    if not isinstance(policies, Sequence) or isinstance(policies, str | bytes):
        raise ValueError("operational history retention policies MUST be an array")
    if not all(isinstance(value, Mapping) for value in policies):
        raise ValueError("operational history retention policy entries MUST be objects")
    registry = load_retention_policy_registry(policies)
    return tuple(registry[key] for key in sorted(registry))


__all__ = [
    "RETENTION_POLICY_PATH_ENV",
    "load_operational_history_retention_policies",
]
