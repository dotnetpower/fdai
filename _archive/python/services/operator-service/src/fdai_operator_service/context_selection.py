"""Process-local server-issued context selection registry."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from uuid import uuid4

from fdai_service_contracts import canonical_ordinary_role

_MAX_SELECTIONS = 512
_MAX_SELECTION_IDS = 512
_TOKEN_PREFIX = "context-selection:"  # noqa: S105


class ContextSelectionRegistry:
    """Issue opaque, bounded selections and resolve them only for exact auth context."""

    def __init__(self, *, max_entries: int = _MAX_SELECTIONS) -> None:
        if max_entries < 1:
            raise ValueError("context selection registry max_entries must be positive")
        self._max_entries = max_entries
        self._entries: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def issue(self, selection: Mapping[str, Any]) -> str:
        """Issue an opaque token for one complete, authenticated selection."""
        stored = deepcopy(dict(selection))
        role = stored.get("role")
        try:
            stored["role"] = canonical_ordinary_role(role) if isinstance(role, str) else None
        except ValueError as exc:
            raise ValueError("context selection role must be an ordinary role") from exc
        resource_ids = stored.get("resource_ids")
        if (
            not isinstance(resource_ids, (list, tuple))
            or not resource_ids
            or len(resource_ids) > _MAX_SELECTION_IDS
            or any(not isinstance(item, str) or not item for item in resource_ids)
            or len(set(resource_ids)) != len(resource_ids)
        ):
            raise ValueError("context selection resource_ids must contain 1-512 unique ids")
        if stored.get("kind") == "screen":
            if (
                not isinstance(stored.get("screen_id"), str)
                or stored.get("resource_group_id") is not None
            ):
                raise ValueError("screen context selection identity is exclusive")
        elif stored.get("kind") == "resource_group":
            if (
                not isinstance(stored.get("resource_group_id"), str)
                or stored.get("screen_id") is not None
            ):
                raise ValueError("resource-group context selection identity is exclusive")
        else:
            raise ValueError("context selection kind is unsupported")
        if stored.get("complete") is not True:
            raise ValueError("context selection must be complete")
        for field in (
            "principal_id",
            "purpose",
            "ontology_release_digest",
            "source_generation",
            "selection_digest",
        ):
            if not isinstance(stored.get(field), str) or not stored[field]:
                raise ValueError(f"context selection {field} must be non-empty")
        token = f"{_TOKEN_PREFIX}{uuid4().hex}"
        self._entries[token] = stored
        self._entries.move_to_end(token)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return token

    def resolve(
        self,
        token: str,
        *,
        principal_id: str,
        role: str,
        purpose: str,
    ) -> dict[str, Any] | None:
        """Resolve only when the token and current authenticated scope agree."""
        if not isinstance(token, str) or not token.startswith(_TOKEN_PREFIX):
            return None
        selection = self._entries.get(token)
        if selection is None:
            return None
        try:
            canonical_role = canonical_ordinary_role(role)
        except ValueError:
            return None
        if (
            selection.get("principal_id") != principal_id
            or selection.get("role") != canonical_role
            or selection.get("purpose") != purpose
        ):
            return None
        self._entries.move_to_end(token)
        return deepcopy(selection)


__all__ = ["ContextSelectionRegistry"]
