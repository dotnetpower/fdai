"""Strict loader for the provider-neutral capacity graduation policy."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml

from fdai.core.capacity import CapacityGraduationPolicy


def load_capacity_graduation_policy(path: Path) -> CapacityGraduationPolicy:
    """Load one exact policy document or fail before runtime composition."""

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ValueError("invalid capacity graduation policy") from exc
    if not isinstance(raw, Mapping):
        raise ValueError("capacity graduation policy MUST be a mapping")
    return CapacityGraduationPolicy.from_catalog(dict(raw))


__all__ = ["load_capacity_graduation_policy"]
