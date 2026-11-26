"""Validated reader for content-addressed retained Rule revision closures."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fdai_service_contracts.rule_activation_manifest import RuleRevisionIdentityRef

from fdai.rule_catalog.schema.revision_identity import (
    RuleRevisionIdentity,
    RuleRevisionRegistry,
)

_MAX_REGISTRY_BYTES = 16_000_000
_MAX_REVISION_BYTES = 2_000_000


class CatalogRuleRevisionRegistry:
    """Read exact retained closures without granting activation or retirement authority."""

    def __init__(self, repository_root: Path) -> None:
        root = repository_root.resolve()
        registry_path = root / "rule-catalog" / "rule-revision-identities.json"
        self._revisions_root = root / "rule-catalog" / "revisions"
        raw = _bounded_json(registry_path, _MAX_REGISTRY_BYTES)
        self._registry = RuleRevisionRegistry.model_validate(raw)

    def has_retained_closure(self, revision: object) -> bool:
        if not isinstance(revision, RuleRevisionIdentityRef):
            return False
        identity = self._registry.by_key().get((revision.rule_id, revision.rule_version))
        if identity is None or identity.revision_digest != revision.revision_digest:
            return False
        path = self._revisions_root / (identity.revision_digest.removeprefix("sha256:") + ".json")
        try:
            raw = _bounded_json(path, _MAX_REVISION_BYTES)
            retained = RuleRevisionIdentity.model_validate(raw.get("revision_identity"))
        except (OSError, ValueError):
            return False
        return retained == identity


def _bounded_json(path: Path, maximum_bytes: int) -> Mapping[str, Any]:
    if isinstance(maximum_bytes, bool) or maximum_bytes < 1:
        raise ValueError("maximum_bytes MUST be a positive integer")
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Rule revision registry artifact is unavailable: {path.name}")
    size = path.stat().st_size
    if size < 1 or size > maximum_bytes:
        raise ValueError(f"Rule revision registry artifact size is invalid: {path.name}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise ValueError(f"Rule revision registry artifact is not an object: {path.name}")
    return raw


__all__ = ["CatalogRuleRevisionRegistry"]
