"""RBAC-filtered runtime tool search and description."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Final

from fdai.core.conversation.narrator import ToolSchema
from fdai.core.conversation.session import Principal, Role, principal_has_role_at_least
from fdai.core.conversation.tools import SideEffectClass, ToolResult


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    name: str
    verb: str
    description: str
    argument_hint: str
    rbac_floor: str
    side_effect_class: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class ToolDiscoveryError(LookupError):
    """A tool is unavailable or not visible to the principal."""


class RuntimeToolDiscovery:
    """Search installed schema metadata without exposing invocation handles."""

    def __init__(
        self,
        *,
        schemas: tuple[ToolSchema, ...],
        installed_tool_names: frozenset[str],
    ) -> None:
        descriptors: dict[str, ToolDescriptor] = {}
        for schema in schemas:
            if schema.tool_name not in installed_tool_names:
                continue
            if schema.tool_name in descriptors:
                raise ValueError(f"duplicate tool schema {schema.tool_name!r}")
            _role(schema.rbac_floor)
            descriptors[schema.tool_name] = ToolDescriptor(
                name=schema.tool_name,
                verb=schema.verb,
                description=schema.summary,
                argument_hint=schema.argument_hint,
                rbac_floor=schema.rbac_floor,
                side_effect_class=schema.side_effect_class,
            )
        self._descriptors: Final = descriptors

    def search(
        self,
        query: str,
        *,
        principal: Principal,
        limit: int = 20,
    ) -> tuple[ToolDescriptor, ...]:
        if not query.strip():
            raise ValueError("tool search query MUST be non-empty")
        if not 1 <= limit <= 50:
            raise ValueError("tool search limit MUST be in [1, 50]")
        terms = tuple(query.lower().split())
        ranked: list[tuple[int, str, ToolDescriptor]] = []
        for descriptor in self._descriptors.values():
            if not _visible(descriptor, principal):
                continue
            haystack = " ".join(
                (
                    descriptor.name,
                    descriptor.verb,
                    descriptor.description,
                    descriptor.argument_hint,
                    descriptor.side_effect_class,
                )
            ).lower()
            if not all(term in haystack for term in terms):
                continue
            exact = 0 if query.lower() in {descriptor.name.lower(), descriptor.verb.lower()} else 1
            ranked.append((exact, descriptor.name, descriptor))
        ranked.sort(key=lambda item: (item[0], item[1]))
        return tuple(item[2] for item in ranked[:limit])

    def describe(self, tool_name: str, *, principal: Principal) -> ToolDescriptor:
        descriptor = self._descriptors.get(tool_name)
        if descriptor is None or not _visible(descriptor, principal):
            raise ToolDiscoveryError(f"tool {tool_name!r} is unavailable")
        return descriptor


class SearchRuntimeToolsTool:
    name = "search_tools"
    description = "Search installed tools visible to the current principal."
    rbac_floor = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, discovery: RuntimeToolDiscovery) -> None:
        self._discovery = discovery

    def call(self, *, arguments: dict[str, object], principal: Principal) -> ToolResult:
        query = arguments.get("query")
        limit = arguments.get("limit", 20)
        if not isinstance(query, str) or not query.strip():
            raise ValueError("tool search query MUST be non-empty")
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("tool search limit MUST be an integer")
        descriptors = self._discovery.search(query, principal=principal, limit=limit)
        return ToolResult(
            status="ok",
            data={"tools": [descriptor.to_dict() for descriptor in descriptors]},
            preview=f"found {len(descriptors)} visible tool(s)",
        )


class DescribeRuntimeTool:
    name = "describe_tool"
    description = "Describe one installed tool visible to the current principal."
    rbac_floor = Role.READER
    side_effect_class: SideEffectClass = "read"

    def __init__(self, discovery: RuntimeToolDiscovery) -> None:
        self._discovery = discovery

    def call(self, *, arguments: dict[str, object], principal: Principal) -> ToolResult:
        tool_name = arguments.get("tool_name")
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError("tool_name MUST be non-empty")
        descriptor = self._discovery.describe(tool_name, principal=principal)
        return ToolResult(
            status="ok",
            data={"tool": descriptor.to_dict()},
            preview=f"described tool {descriptor.name}",
        )


def _visible(descriptor: ToolDescriptor, principal: Principal) -> bool:
    return principal_has_role_at_least(principal.role, _role(descriptor.rbac_floor))


def _role(value: str) -> Role:
    try:
        return Role(value)
    except ValueError as exc:
        raise ValueError(f"tool schema has unknown RBAC floor {value!r}") from exc


__all__ = [
    "DescribeRuntimeTool",
    "RuntimeToolDiscovery",
    "SearchRuntimeToolsTool",
    "ToolDescriptor",
    "ToolDiscoveryError",
]
