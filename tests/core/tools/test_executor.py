"""Unit tests for :mod:`aiopspilot.core.tools.executor`.

Every case builds a bespoke tool catalog in a tmp path (via the same
helpers as ``test_registry.py``) and pairs it with an
:class:`InMemoryToolProvider` so the dispatch surface is exercised end
-to-end without touching a real Azure endpoint.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from aiopspilot.core.tools import (
    DefaultToolExecutor,
    FileSystemToolRegistry,
    MissingProviderError,
    ProviderCallError,
    ShadowToolBlockedError,
    ToolArgumentValidationError,
    ToolExecutorError,
    UnknownToolError,
)
from aiopspilot.core.tools.testing import InMemoryToolProvider, NoOpToolProvider

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "rule-catalog"
    / "prompts"
    / "tools"
    / "schema"
    / "tool.schema.json"
)


def _write_schema(root: Path) -> None:
    dst = root / "prompts" / "tools" / "schema" / "tool.schema.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(_SCHEMA_PATH.read_text())


def _write_tool(root: Path, filename: str, body: str) -> None:
    dst = root / "prompts" / "tools" / "catalog" / filename
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(body)


def _tool_yaml(
    *,
    tool_id: str = "rule.query",
    version: int = 1,
    default_mode: str = "enforce",
    provider: str | None = "RuleCatalogQueryProvider",
    output_wrapper: str | None = '<tool_result trusted="false" tool="rule.query">{}</tool_result>',
    input_schema: dict | None = None,
) -> str:
    doc: dict[str, object] = {
        "id": tool_id,
        "version": version,
        "description": f"{tool_id} description",
        "input_schema": input_schema
        or {
            "type": "object",
            "additionalProperties": False,
            "required": ["rule_id"],
            "properties": {"rule_id": {"type": "string"}},
        },
        "capability_gate": {
            "requires_tier": "T2",
            "cost_budget_usd_per_call": 0.01,
        },
        "default_mode": default_mode,
        "provenance": {"source": "test"},
    }
    if provider is not None:
        doc["provider"] = provider
    if output_wrapper is not None:
        doc["output_wrapper"] = output_wrapper
    return yaml.safe_dump(doc, sort_keys=False)


def _build_registry(tmp_path: Path, tool_yaml: str, *, filename: str) -> FileSystemToolRegistry:
    _write_schema(tmp_path)
    _write_tool(tmp_path, filename, tool_yaml)
    return FileSystemToolRegistry(tmp_path)


# ---------------------------------------------------------------------------
# Happy path + wrapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_returns_wrapped_result(tmp_path: Path) -> None:
    registry = _build_registry(
        tmp_path, _tool_yaml(default_mode="enforce"), filename="rule.query.v1.yaml"
    )
    provider = InMemoryToolProvider()
    provider.prime(
        tool_id="rule.query",
        arguments={"rule_id": "example.rule"},
        response={"severity": "high"},
    )
    executor = DefaultToolExecutor(
        registry=registry,
        providers={"RuleCatalogQueryProvider": provider},
    )

    result = await executor.dispatch(tool_id="rule.query", arguments={"rule_id": "example.rule"})

    assert result.tool_id == "rule.query"
    assert '<tool_result trusted="false"' in result.wrapped_text
    assert '"severity": "high"' in result.wrapped_text
    assert result.raw == {"severity": "high"}
    assert result.cost_usd == 0.01
    assert result.latency_ms >= 0
    # Provider was actually invoked exactly once.
    assert provider.calls == [("rule.query", {"rule_id": "example.rule"})]


@pytest.mark.asyncio
async def test_dispatch_passes_strings_through_wrapper_unchanged(tmp_path: Path) -> None:
    """A provider that returns a pre-formatted string should not get
    JSON-encoded a second time (matters for RAG-style tools)."""

    registry = _build_registry(
        tmp_path, _tool_yaml(default_mode="enforce"), filename="rule.query.v1.yaml"
    )
    provider = InMemoryToolProvider()
    provider.prime(
        tool_id="rule.query",
        arguments={"rule_id": "example.rule"},
        response="already-formatted-payload",
    )
    executor = DefaultToolExecutor(
        registry=registry,
        providers={"RuleCatalogQueryProvider": provider},
    )

    result = await executor.dispatch(tool_id="rule.query", arguments={"rule_id": "example.rule"})

    assert "already-formatted-payload" in result.wrapped_text
    assert '"already-formatted-payload"' not in result.wrapped_text


@pytest.mark.asyncio
async def test_dispatch_uses_canonical_wrapper_when_yaml_omits_one(tmp_path: Path) -> None:
    registry = _build_registry(
        tmp_path,
        _tool_yaml(default_mode="enforce", output_wrapper=None),
        filename="rule.query.v1.yaml",
    )
    provider = InMemoryToolProvider()
    provider.prime(
        tool_id="rule.query",
        arguments={"rule_id": "example.rule"},
        response={"ok": True},
    )
    executor = DefaultToolExecutor(
        registry=registry,
        providers={"RuleCatalogQueryProvider": provider},
    )

    result = await executor.dispatch(tool_id="rule.query", arguments={"rule_id": "example.rule"})

    # Canonical fallback still carries the ``trusted="false"`` marker so
    # the injection defense survives a missing wrapper.
    assert 'trusted="false"' in result.wrapped_text
    assert 'tool="rule.query"' in result.wrapped_text


# ---------------------------------------------------------------------------
# Fail-closed paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_rejects_unknown_tool(tmp_path: Path) -> None:
    registry = _build_registry(
        tmp_path, _tool_yaml(default_mode="enforce"), filename="rule.query.v1.yaml"
    )
    executor = DefaultToolExecutor(
        registry=registry,
        providers={"RuleCatalogQueryProvider": InMemoryToolProvider()},
    )
    with pytest.raises(UnknownToolError):
        await executor.dispatch(tool_id="web.search", arguments={})


@pytest.mark.asyncio
async def test_dispatch_rejects_shadow_tool_by_default(tmp_path: Path) -> None:
    registry = _build_registry(
        tmp_path, _tool_yaml(default_mode="shadow"), filename="rule.query.v1.yaml"
    )
    executor = DefaultToolExecutor(
        registry=registry,
        providers={"RuleCatalogQueryProvider": InMemoryToolProvider()},
    )
    with pytest.raises(ShadowToolBlockedError):
        await executor.dispatch(tool_id="rule.query", arguments={"rule_id": "example.rule"})


@pytest.mark.asyncio
async def test_dispatch_permits_shadow_when_opted_in(tmp_path: Path) -> None:
    registry = _build_registry(
        tmp_path, _tool_yaml(default_mode="shadow"), filename="rule.query.v1.yaml"
    )
    provider = InMemoryToolProvider()
    provider.prime(
        tool_id="rule.query",
        arguments={"rule_id": "example.rule"},
        response={"ok": True},
    )
    executor = DefaultToolExecutor(
        registry=registry,
        providers={"RuleCatalogQueryProvider": provider},
        allow_shadow_dispatch=True,
    )

    result = await executor.dispatch(tool_id="rule.query", arguments={"rule_id": "example.rule"})
    assert result.raw == {"ok": True}


@pytest.mark.asyncio
async def test_dispatch_rejects_arguments_violating_input_schema(tmp_path: Path) -> None:
    registry = _build_registry(
        tmp_path, _tool_yaml(default_mode="enforce"), filename="rule.query.v1.yaml"
    )
    executor = DefaultToolExecutor(
        registry=registry,
        providers={"RuleCatalogQueryProvider": InMemoryToolProvider()},
    )
    with pytest.raises(ToolArgumentValidationError):
        # required 'rule_id' missing
        await executor.dispatch(tool_id="rule.query", arguments={})


@pytest.mark.asyncio
async def test_dispatch_rejects_extra_arguments(tmp_path: Path) -> None:
    """additionalProperties=False in the schema must reject smuggled args.

    This is a prompt-injection defense: an attacker who steers the
    model into calling a tool with an extra unrecognized field must
    not slip past the executor.
    """

    registry = _build_registry(
        tmp_path, _tool_yaml(default_mode="enforce"), filename="rule.query.v1.yaml"
    )
    executor = DefaultToolExecutor(
        registry=registry,
        providers={"RuleCatalogQueryProvider": InMemoryToolProvider()},
    )
    with pytest.raises(ToolArgumentValidationError):
        await executor.dispatch(
            tool_id="rule.query",
            arguments={"rule_id": "example.rule", "evil": "payload"},
        )


@pytest.mark.asyncio
async def test_dispatch_missing_provider_fails_closed(tmp_path: Path) -> None:
    registry = _build_registry(
        tmp_path,
        _tool_yaml(default_mode="enforce", provider="NoSuchProvider"),
        filename="rule.query.v1.yaml",
    )
    executor = DefaultToolExecutor(
        registry=registry,
        providers={"OtherProvider": InMemoryToolProvider()},
    )
    with pytest.raises(MissingProviderError):
        await executor.dispatch(tool_id="rule.query", arguments={"rule_id": "example.rule"})


@pytest.mark.asyncio
async def test_dispatch_wraps_provider_exception(tmp_path: Path) -> None:
    registry = _build_registry(
        tmp_path, _tool_yaml(default_mode="enforce"), filename="rule.query.v1.yaml"
    )
    executor = DefaultToolExecutor(
        registry=registry,
        providers={"RuleCatalogQueryProvider": NoOpToolProvider()},
    )
    with pytest.raises(ProviderCallError) as excinfo:
        await executor.dispatch(tool_id="rule.query", arguments={"rule_id": "example.rule"})
    # The original exception is preserved on ``__cause__``.
    assert excinfo.value.__cause__ is not None
    assert "NoOpToolProvider" in str(excinfo.value.__cause__)


@pytest.mark.asyncio
async def test_dispatch_rejects_wrapper_without_placeholder(tmp_path: Path) -> None:
    """A wrapper the registry accepted but that lacks the ``{}`` payload
    slot is a defect in the fallback path - fail closed rather than
    render the payload outside the trusted envelope."""

    wrapper_without_slot = (
        '<tool_result trusted="false" tool="rule.query">no-payload-slot</tool_result>'
    )
    registry = _build_registry(
        tmp_path,
        _tool_yaml(default_mode="enforce", output_wrapper=wrapper_without_slot),
        filename="rule.query.v1.yaml",
    )
    provider = InMemoryToolProvider()
    provider.prime(
        tool_id="rule.query",
        arguments={"rule_id": "example.rule"},
        response={"ok": True},
    )
    executor = DefaultToolExecutor(
        registry=registry,
        providers={"RuleCatalogQueryProvider": provider},
    )
    with pytest.raises(ToolExecutorError, match="placeholder"):
        await executor.dispatch(tool_id="rule.query", arguments={"rule_id": "example.rule"})


@pytest.mark.asyncio
async def test_dispatch_error_carries_tool_id() -> None:
    err = UnknownToolError("some.tool", "not found")
    assert err.tool_id == "some.tool"
    assert "some.tool" in str(err)


@pytest.mark.asyncio
async def test_dispatch_preserves_provider_mapping_from_caller_mutation(
    tmp_path: Path,
) -> None:
    """A test tries to swap the provider out from under a live executor;
    the internal copy MUST hold, so the original provider still handles
    the second call.
    """

    registry = _build_registry(
        tmp_path, _tool_yaml(default_mode="enforce"), filename="rule.query.v1.yaml"
    )
    original = InMemoryToolProvider()
    original.prime(
        tool_id="rule.query",
        arguments={"rule_id": "example.rule"},
        response={"src": "original"},
    )
    replacement = InMemoryToolProvider()
    replacement.prime(
        tool_id="rule.query",
        arguments={"rule_id": "example.rule"},
        response={"src": "replacement"},
    )
    providers = {"RuleCatalogQueryProvider": original}
    executor = DefaultToolExecutor(registry=registry, providers=providers)

    # Attempt to mutate the caller's dict after construction.
    providers["RuleCatalogQueryProvider"] = replacement

    result = await executor.dispatch(tool_id="rule.query", arguments={"rule_id": "example.rule"})
    assert result.raw == {"src": "original"}


@pytest.mark.asyncio
async def test_in_memory_provider_raises_on_missing_prime() -> None:
    """The InMemoryToolProvider MUST fail loudly for unprimed calls so a
    test that forgets a fixture surfaces the omission."""

    from aiopspilot.core.prompts.types import PromptMode
    from aiopspilot.core.tools.types import CapabilityGate, ToolArtifact

    provider = InMemoryToolProvider()
    artifact = ToolArtifact(
        id="rule.query",
        version=1,
        description="",
        input_schema={"type": "object"},
        capability_gate=CapabilityGate(None, None, None),
        allowlist=None,
        output_wrapper=None,
        default_mode=PromptMode.ENFORCE,
        provider="RuleCatalogQueryProvider",
        provenance_source="test",
    )
    with pytest.raises(KeyError):
        await provider.call(artifact=artifact, arguments={"rule_id": "unprimed"})
