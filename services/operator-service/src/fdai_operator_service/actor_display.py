"""Best-effort display names for human subject ids in audit projections."""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Mapping, Sequence
from typing import Final

from fdai_service_contracts import JsonObject, JsonValue

from fdai_operator_service.families.iam.contracts import HumanIdentityDirectory

_SUBJECT_ID: Final = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)
_MAX_LOOKUPS: Final = 20
_LOOKUP_TIMEOUT_SECONDS: Final = 2.0
_HIT_TTL_SECONDS: Final = 3600.0
_MISS_TTL_SECONDS: Final = 120.0
_MAX_DISPLAY_CHARS: Final = 256


class ActorDisplayResolver:
    """Resolve an authenticated human subject id to a bounded display label.

    The audit ledger keeps only the opaque subject id, so the label is derived at read time and
    never stored. A missing directory, a lookup failure, or a timeout leaves the item unchanged.
    """

    def __init__(self, directory: HumanIdentityDirectory | None) -> None:
        self._directory = directory
        self._cache: dict[str, tuple[float, str | None]] = {}

    async def annotate(self, payload: JsonValue) -> None:
        """Add ``actor_display`` in place to audit items whose actor is a human subject id."""
        if self._directory is None:
            return
        items = [item for item in _audit_items(payload) if _is_subject(item.get("actor"))]
        subjects = list(dict.fromkeys(str(item["actor"]) for item in items))[:_MAX_LOOKUPS]
        resolved = await asyncio.gather(*(self._label(subject) for subject in subjects))
        labels = dict(zip(subjects, resolved, strict=True))
        for item in items:
            label = labels.get(str(item["actor"]))
            if label is not None:
                item["actor_display"] = label

    async def _label(self, subject: str) -> str | None:
        now = time.monotonic()
        cached = self._cache.get(subject)
        if cached is not None and cached[0] > now:
            return cached[1]
        label: str | None = None
        ttl = _MISS_TTL_SECONDS
        if self._directory is not None:
            try:
                async with asyncio.timeout(_LOOKUP_TIMEOUT_SECONDS):
                    identity = await self._directory.get_by_subject_id(subject)
            except Exception:  # noqa: BLE001 - a directory outage never blocks the audit read
                identity = None
            if identity is not None:
                text = (identity.display_name or identity.username or "").strip()
                if text:
                    label = text[:_MAX_DISPLAY_CHARS]
                    ttl = _HIT_TTL_SECONDS
        self._cache[subject] = (now + ttl, label)
        return label


def _is_subject(value: object) -> bool:
    return isinstance(value, str) and _SUBJECT_ID.fullmatch(value) is not None


def _audit_items(payload: JsonValue) -> list[JsonObject]:
    if not isinstance(payload, Mapping):
        return []
    items = payload.get("items")
    if not isinstance(items, Sequence) or isinstance(items, str | bytes):
        return []
    return [item for item in items if isinstance(item, dict) and "action_kind" in item]


__all__ = ["ActorDisplayResolver"]
