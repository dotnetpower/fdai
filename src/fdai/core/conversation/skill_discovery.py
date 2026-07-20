"""Read-only channel tools for runtime skill disclosure."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fdai.core.conversation.session import Principal, Role
from fdai.core.conversation.tools import SideEffectClass, ToolResult
from fdai.core.skills import RuntimeSkillDisclosure, SkillAccessError
from fdai.core.skills.bundle_catalog import SkillBundleResolutionError


class ListRuntimeSkillsTool:
    name = "list_skills"
    description = "List eligible runtime skill metadata without invoking tools."
    rbac_floor = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, disclosure: RuntimeSkillDisclosure) -> None:
        self._disclosure = disclosure

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        _require_keys(arguments, required=frozenset({"query"}), optional=frozenset({"limit"}))
        query = arguments["query"]
        limit = arguments.get("limit", 20)
        if not isinstance(query, str):
            raise ValueError("list_skills query MUST be a string")
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("list_skills limit MUST be an integer")
        try:
            payload = self._disclosure.list(query=query, limit=limit)
        except SkillAccessError as exc:
            return _rejected(exc)
        return ToolResult(
            status="ok",
            data=payload,
            preview=f"listed {payload['returned_count']} eligible skill(s)",
        )


class DescribeRuntimeSkillTool:
    name = "describe_skill"
    description = "Describe installed runtime skill metadata without loading its body."
    rbac_floor = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, disclosure: RuntimeSkillDisclosure) -> None:
        self._disclosure = disclosure

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        name = _required_string(arguments, key="name", operation=self.name)
        try:
            payload = self._disclosure.describe(name)
        except SkillAccessError as exc:
            return _rejected(exc)
        return ToolResult(status="ok", data=payload, preview=f"described skill {name}")


class LoadRuntimeSkillTool:
    name = "load_skill"
    description = "Load one eligible, trust-verified runtime skill body."
    rbac_floor = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, disclosure: RuntimeSkillDisclosure) -> None:
        self._disclosure = disclosure

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        name = _required_string(arguments, key="name", operation=self.name)
        try:
            payload = self._disclosure.load(name)
        except SkillAccessError as exc:
            return _rejected(exc)
        return ToolResult(status="ok", data=payload, preview=f"loaded skill {name}")


class ReadRuntimeSkillReferenceTool:
    name = "read_skill_reference"
    description = "Read one declared reference from an eligible, trust-verified runtime skill."
    rbac_floor = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, disclosure: RuntimeSkillDisclosure) -> None:
        self._disclosure = disclosure

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        _require_keys(arguments, required=frozenset({"name", "path"}))
        name = arguments["name"]
        path = arguments["path"]
        if not isinstance(name, str) or not name:
            raise ValueError("read_skill_reference name MUST be non-empty")
        if not isinstance(path, str) or not path:
            raise ValueError("read_skill_reference path MUST be non-empty")
        try:
            payload = self._disclosure.read_reference(name, path)
        except SkillAccessError as exc:
            return _rejected(exc)
        return ToolResult(status="ok", data=payload, preview=f"read skill reference {path}")


class ListRuntimeSkillBundlesTool:
    name = "list_skill_bundles"
    description = "List governed runtime skill bundle metadata without loading members."
    rbac_floor = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, disclosure: RuntimeSkillDisclosure) -> None:
        self._disclosure = disclosure

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        _require_keys(arguments, required=frozenset({"query"}), optional=frozenset({"limit"}))
        query = arguments["query"]
        limit = arguments.get("limit", 20)
        if not isinstance(query, str):
            raise ValueError("list_skill_bundles query MUST be a string")
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("list_skill_bundles limit MUST be an integer")
        payload = self._disclosure.list_bundles(query=query, limit=limit)
        return ToolResult(
            status="ok",
            data=payload,
            preview=f"listed {payload['returned_count']} governed skill bundle(s)",
        )


class DescribeRuntimeSkillBundleTool:
    name = "describe_skill_bundle"
    description = "Describe one governed runtime skill bundle without loading members."
    rbac_floor = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, disclosure: RuntimeSkillDisclosure) -> None:
        self._disclosure = disclosure

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        name = _required_string(arguments, key="name", operation=self.name)
        payload = self._disclosure.describe_bundle(name)
        return ToolResult(status="ok", data=payload, preview=f"described skill bundle {name}")


class LoadRuntimeSkillBundleTool:
    name = "load_skill_bundle"
    description = "Load one eligible governed bundle and all complete member bodies atomically."
    rbac_floor = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, disclosure: RuntimeSkillDisclosure) -> None:
        self._disclosure = disclosure

    def call(self, *, arguments: Mapping[str, Any], principal: Principal) -> ToolResult:
        name = _required_string(arguments, key="name", operation=self.name)
        try:
            payload = self._disclosure.load_bundle(name)
        except SkillBundleResolutionError as exc:
            return ToolResult(
                status="error",
                data={
                    "error": {
                        "code": "skill_bundle_access_rejected",
                        "reason": exc.reason.value,
                    }
                },
                preview=f"skill bundle read rejected: {exc.reason.value}",
            )
        return ToolResult(status="ok", data=payload, preview=f"loaded skill bundle {name}")


def _required_string(arguments: Mapping[str, Any], *, key: str, operation: str) -> str:
    _require_keys(arguments, required=frozenset({key}))
    value = arguments[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{operation} {key} MUST be non-empty")
    return value


def _require_keys(
    arguments: Mapping[str, Any],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    keys = set(arguments)
    missing = required - keys
    unknown = keys - required - optional
    if missing:
        raise ValueError(f"missing skill tool arguments: {sorted(missing)}")
    if unknown:
        raise ValueError(f"unknown skill tool arguments: {sorted(unknown)}")


def _rejected(error: SkillAccessError) -> ToolResult:
    return ToolResult(
        status="error",
        data={
            "error": {
                "code": "skill_access_rejected",
                "reason": error.reason.value,
            }
        },
        preview=f"skill read rejected: {error.reason.value}",
    )


__all__ = [
    "DescribeRuntimeSkillBundleTool",
    "DescribeRuntimeSkillTool",
    "ListRuntimeSkillBundlesTool",
    "ListRuntimeSkillsTool",
    "LoadRuntimeSkillBundleTool",
    "LoadRuntimeSkillTool",
    "ReadRuntimeSkillReferenceTool",
]
