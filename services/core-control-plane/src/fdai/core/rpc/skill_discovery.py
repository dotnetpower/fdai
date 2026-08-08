"""Typed read-only RPC methods for runtime skill disclosure."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fdai.core.rpc.registry import RpcError, RpcMethod, RpcScope
from fdai.core.skills import RuntimeSkillDisclosure, SkillAccessError
from fdai.core.skills.bundle_catalog import SkillBundleResolutionError

_Handler = Callable[[Mapping[str, Any]], Awaitable[Mapping[str, Any]]]


def skill_discovery_rpc_methods(disclosure: RuntimeSkillDisclosure) -> tuple[RpcMethod, ...]:
    async def list_skills(params: Mapping[str, Any]) -> Mapping[str, Any]:
        _require_keys(params, required=frozenset({"query"}), optional=frozenset({"limit"}))
        query = params["query"]
        limit = params.get("limit", 20)
        if not isinstance(query, str):
            raise RpcError("invalid_params", "skills.list query MUST be a string")
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise RpcError("invalid_params", "skills.list limit MUST be an integer")
        return _invoke(lambda: disclosure.list(query=query, limit=limit))

    async def describe(params: Mapping[str, Any]) -> Mapping[str, Any]:
        name = _required_string(params, key="name", operation="skills.describe")
        return _invoke(lambda: disclosure.describe(name))

    async def load(params: Mapping[str, Any]) -> Mapping[str, Any]:
        name = _required_string(params, key="name", operation="skills.load")
        return _invoke(lambda: disclosure.load(name))

    async def read_reference(params: Mapping[str, Any]) -> Mapping[str, Any]:
        _require_keys(params, required=frozenset({"name", "path"}))
        name = params["name"]
        path = params["path"]
        if not isinstance(name, str) or not name:
            raise RpcError("invalid_params", "skills.read_reference name MUST be non-empty")
        if not isinstance(path, str) or not path:
            raise RpcError("invalid_params", "skills.read_reference path MUST be non-empty")
        return _invoke(lambda: disclosure.read_reference(name, path))

    async def diagnostics(params: Mapping[str, Any]) -> Mapping[str, Any]:
        _require_keys(params, required=frozenset())
        return {"diagnostics": list(disclosure.diagnostics())}

    async def list_bundles(params: Mapping[str, Any]) -> Mapping[str, Any]:
        _require_keys(params, required=frozenset({"query"}), optional=frozenset({"limit"}))
        query = params["query"]
        limit = params.get("limit", 20)
        if not isinstance(query, str):
            raise RpcError("invalid_params", "skill_bundles.list query MUST be a string")
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise RpcError("invalid_params", "skill_bundles.list limit MUST be an integer")
        return _invoke(lambda: disclosure.list_bundles(query=query, limit=limit))

    async def describe_bundle(params: Mapping[str, Any]) -> Mapping[str, Any]:
        name = _required_string(params, key="name", operation="skill_bundles.describe")
        return _invoke(lambda: disclosure.describe_bundle(name))

    async def load_bundle(params: Mapping[str, Any]) -> Mapping[str, Any]:
        name = _required_string(params, key="name", operation="skill_bundles.load")
        return _invoke(lambda: disclosure.load_bundle(name))

    definitions: tuple[tuple[str, str, _Handler], ...] = (
        ("skills.list", "List eligible runtime skill metadata.", list_skills),
        ("skills.describe", "Describe installed runtime skill metadata.", describe),
        ("skills.load", "Load an eligible, trust-verified runtime skill.", load),
        (
            "skills.read_reference",
            "Read a declared reference from an eligible runtime skill.",
            read_reference,
        ),
        ("skills.diagnostics", "Read bounded metadata-only skill diagnostics.", diagnostics),
        ("skill_bundles.list", "List governed skill bundle metadata.", list_bundles),
        ("skill_bundles.describe", "Describe one governed skill bundle.", describe_bundle),
        ("skill_bundles.load", "Load one complete governed skill bundle.", load_bundle),
    )
    return tuple(
        RpcMethod(
            name=name,
            description=description,
            required_scope=RpcScope.READ,
            handler=handler,
        )
        for name, description, handler in definitions
    )


def _invoke(call: Callable[[], dict[str, Any]]) -> Mapping[str, Any]:
    try:
        return call()
    except SkillAccessError as exc:
        raise RpcError("skill_access_rejected", exc.reason.value) from exc
    except SkillBundleResolutionError as exc:
        raise RpcError("skill_bundle_access_rejected", exc.reason.value) from exc
    except ValueError as exc:
        raise RpcError("invalid_params", str(exc)) from exc


def _required_string(params: Mapping[str, Any], *, key: str, operation: str) -> str:
    _require_keys(params, required=frozenset({key}))
    value = params[key]
    if not isinstance(value, str) or not value:
        raise RpcError("invalid_params", f"{operation} {key} MUST be non-empty")
    return value


def _require_keys(
    params: Mapping[str, Any],
    *,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    keys = set(params)
    missing = required - keys
    unknown = keys - required - optional
    if missing:
        raise RpcError("invalid_params", f"missing skill RPC params: {sorted(missing)}")
    if unknown:
        raise RpcError("invalid_params", f"unknown skill RPC params: {sorted(unknown)}")


__all__ = ["skill_discovery_rpc_methods"]
