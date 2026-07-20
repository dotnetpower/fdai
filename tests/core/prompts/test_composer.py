"""Unit tests for :mod:`fdai.core.prompts.composer`.

Tests build a bespoke catalog per case (via the tmp_path helpers reused
from ``test_registry.py``) so the assembled output is fully controlled.
The shipped ``rule-catalog/prompts/`` tree is exercised in a small
integration test at the bottom.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from textwrap import dedent

import pytest

from fdai.core.prompts import (
    ComposedPrompt,
    DefaultPromptComposer,
    FileSystemPromptRegistry,
    PromptLayer,
    SkillDisclosureRequest,
    SkillSelectionStatus,
)
from fdai.core.prompts.testing import StaticPromptComposer

_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3]
    / "rule-catalog"
    / "prompts"
    / "schema"
    / "prompt.schema.json"
)


def _write_schema(root: Path) -> None:
    dst = root / "prompts" / "schema" / "prompt.schema.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(_SCHEMA_PATH.read_text())


def _write_prompt(root: Path, subdir: str, filename: str, body: str) -> Path:
    dst = root / "prompts" / subdir / filename
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(body)
    return dst


def _base(capability: str, body: str, *, name: str = "hello", version: int = 1) -> str:
    return dedent(
        f"""
        id: {name}
        version: {version}
        layer: base
        applies_to:
          - {capability}
        default_mode: enforce
        body: {body!r}
        provenance:
          source: test
        """
    )


def _pack(capability: str, body: str, *, name: str = "pack-a", version: int = 1) -> str:
    return dedent(
        f"""
        id: {name}
        version: {version}
        layer: pack
        applies_to:
          - {capability}
        default_mode: enforce
        body: {body!r}
        provenance:
          source: test
        """
    )


def _pack_shadow(capability: str, body: str, *, name: str = "shadow-pack", version: int = 1) -> str:
    return dedent(
        f"""
        id: {name}
        version: {version}
        layer: pack
        applies_to:
          - {capability}
        default_mode: shadow
        body: {body!r}
        provenance:
          source: test
        """
    )


@pytest.mark.asyncio
async def test_compose_returns_base_only_when_no_packs(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "hello"))
    registry = FileSystemPromptRegistry(tmp_path)
    composer = DefaultPromptComposer(registry=registry)

    out = await composer.compose(capability_id="t2.reasoner.primary")

    assert isinstance(out, ComposedPrompt)
    assert out.system_text == "hello"
    assert len(out.layer_manifest) == 1
    assert out.layer_manifest[0].id == "hello"
    assert out.layer_manifest[0].layer is PromptLayer.BASE
    assert out.token_estimate >= 1


@pytest.mark.asyncio
async def test_compose_appends_packs_in_deterministic_order(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    # Two packs on the same capability. Order MUST be alphabetical by id
    # regardless of the order files are found on disk.
    _write_prompt(
        tmp_path,
        "packs",
        "bravo.v1.yaml",
        _pack("t2.reasoner.primary", "BRAVO", name="bravo"),
    )
    _write_prompt(
        tmp_path,
        "packs",
        "alpha.v1.yaml",
        _pack("t2.reasoner.primary", "ALPHA", name="alpha"),
    )
    registry = FileSystemPromptRegistry(tmp_path)
    composer = DefaultPromptComposer(registry=registry)

    out = await composer.compose(capability_id="t2.reasoner.primary")

    assert out.system_text == "BASE\n\nALPHA\n\nBRAVO"
    ids = [ref.id for ref in out.layer_manifest]
    assert ids == ["hello", "alpha", "bravo"]


@pytest.mark.asyncio
async def test_compose_skips_packs_bound_to_other_capability(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    _write_prompt(
        tmp_path,
        "packs",
        "secondary-only.v1.yaml",
        _pack("t2.reasoner.secondary", "NOT-INJECTED", name="secondary-only"),
    )
    registry = FileSystemPromptRegistry(tmp_path)
    composer = DefaultPromptComposer(registry=registry)

    out = await composer.compose(capability_id="t2.reasoner.primary")

    assert "NOT-INJECTED" not in out.system_text
    assert [ref.id for ref in out.layer_manifest] == ["hello"]


@pytest.mark.asyncio
async def test_compose_selects_highest_pack_version(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    for version in (1, 3, 2):
        _write_prompt(
            tmp_path,
            "packs",
            f"pack.v{version}.yaml",
            _pack("t2.reasoner.primary", f"P{version}", name="pack", version=version),
        )
    registry = FileSystemPromptRegistry(tmp_path)
    composer = DefaultPromptComposer(registry=registry)

    out = await composer.compose(capability_id="t2.reasoner.primary")

    assert out.system_text.endswith("P3")
    # Only one pack row in the manifest even though 3 files exist.
    pack_refs = [ref for ref in out.layer_manifest if ref.layer is PromptLayer.PACK]
    assert len(pack_refs) == 1
    assert pack_refs[0].version == 3


@pytest.mark.asyncio
async def test_compose_raises_when_no_base(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(
        tmp_path,
        "base",
        "narrow.v1.yaml",
        _base("t2.reasoner.primary", "x", name="narrow"),
    )
    registry = FileSystemPromptRegistry(tmp_path)
    composer = DefaultPromptComposer(registry=registry)

    with pytest.raises(LookupError, match="no base prompt"):
        await composer.compose(capability_id="t2.reasoner.secondary")


@pytest.mark.asyncio
async def test_compose_token_estimate_matches_body_length(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    body = "a" * 40  # 40 chars / 4 chars-per-token = 10 tokens
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", body))
    registry = FileSystemPromptRegistry(tmp_path)
    composer = DefaultPromptComposer(registry=registry)

    out = await composer.compose(capability_id="t2.reasoner.primary")

    assert out.token_estimate == 10


@pytest.mark.asyncio
async def test_static_prompt_composer_records_capability_calls() -> None:
    fake = StaticPromptComposer("canned text", layer_id="stub", layer_version=1)

    out = await fake.compose(capability_id="t2.reasoner.primary")
    await fake.compose(capability_id="t2.reasoner.secondary")

    assert out.system_text == "canned text"
    # Wave 3 step C-1 widened the tracker to record scope alongside
    # capability. When callers pass no scope, ``None`` is recorded.
    assert fake.calls == [
        ("t2.reasoner.primary", None),
        ("t2.reasoner.secondary", None),
    ]


@pytest.mark.asyncio
async def test_compose_against_shipped_catalog_matches_base_body() -> None:
    """Integration guard: with the default ``include_shadow_packs=False``,
    the shipped catalog composes to the raw base body because every
    packs/*.yaml is currently shadow-mode. Promoting a pack to
    ``default_mode: enforce`` would surface here as an extra layer.
    """

    repo_root = Path(__file__).resolve().parents[3]
    registry = FileSystemPromptRegistry(repo_root / "rule-catalog")
    composer = DefaultPromptComposer(registry=registry)

    out = await composer.compose(capability_id="t2.reasoner.primary")
    base_body = registry.get_base("t2.reasoner.primary").body

    assert out.system_text == base_body
    assert len(out.layer_manifest) == 1


@pytest.mark.asyncio
async def test_compose_skips_shadow_packs_by_default(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    _write_prompt(
        tmp_path,
        "packs",
        "shadow-pack.v1.yaml",
        _pack_shadow("t2.reasoner.primary", "SHADOW", name="shadow-pack"),
    )
    _write_prompt(
        tmp_path,
        "packs",
        "enforce-pack.v1.yaml",
        _pack("t2.reasoner.primary", "ENFORCE", name="enforce-pack"),
    )
    registry = FileSystemPromptRegistry(tmp_path)
    composer = DefaultPromptComposer(registry=registry)

    out = await composer.compose(capability_id="t2.reasoner.primary")

    assert "ENFORCE" in out.system_text
    assert "SHADOW" not in out.system_text
    ids = [ref.id for ref in out.layer_manifest]
    assert ids == ["hello", "enforce-pack"]


@pytest.mark.asyncio
async def test_compose_includes_shadow_packs_when_opted_in(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    _write_prompt(
        tmp_path,
        "packs",
        "shadow-pack.v1.yaml",
        _pack_shadow("t2.reasoner.primary", "SHADOW", name="shadow-pack"),
    )
    registry = FileSystemPromptRegistry(tmp_path)
    composer = DefaultPromptComposer(registry=registry, include_shadow_packs=True)

    out = await composer.compose(capability_id="t2.reasoner.primary")

    assert "SHADOW" in out.system_text
    ids = [ref.id for ref in out.layer_manifest]
    assert ids == ["hello", "shadow-pack"]


@pytest.mark.asyncio
async def test_shipped_shadow_pack_lands_only_in_dev_mode() -> None:
    """The Wave 2.5 sample task pack ships in shadow. Production composer
    MUST NOT include it; the ``include_shadow_packs`` opt-in must pick it up.
    """

    repo_root = Path(__file__).resolve().parents[3]
    registry = FileSystemPromptRegistry(repo_root / "rule-catalog")
    prod_composer = DefaultPromptComposer(registry=registry)
    dev_composer = DefaultPromptComposer(registry=registry, include_shadow_packs=True)

    prod_out = await prod_composer.compose(capability_id="t2.reasoner.primary")
    dev_out = await dev_composer.compose(capability_id="t2.reasoner.primary")

    assert len(prod_out.layer_manifest) == 1
    prod_ids = {ref.id for ref in prod_out.layer_manifest}
    dev_ids = {ref.id for ref in dev_out.layer_manifest}
    assert "t2-cross-check-output-contract" not in prod_ids
    assert "t2-cross-check-output-contract" in dev_ids


# ---------------------------------------------------------------------------
# Tool manifest layer (Wave 2.5-B step 1)
# ---------------------------------------------------------------------------


class _FakeToolRegistry:
    """Minimal in-memory ToolRegistry so composer tests do not touch disk.

    Structurally satisfies :class:`fdai.core.tools.ToolRegistry`;
    the composer only calls :meth:`artifacts`, so :meth:`get` is a
    stub that fails loudly if any future composer version reaches for
    it (a signal to update these tests together with the composer).
    """

    def __init__(self, artifacts: tuple) -> None:
        self._artifacts = artifacts

    def artifacts(self) -> tuple:
        return self._artifacts

    def get(self, tool_id: str):  # pragma: no cover - defensive
        raise LookupError(f"stub does not support get({tool_id!r})")


def _fake_tool(tool_id: str, *, default_mode: str = "enforce", version: int = 1) -> object:
    """Build a bare :class:`ToolArtifact` for composer tests.

    Only the fields the composer reads (``id``, ``version``,
    ``description``, ``default_mode``) are populated with realistic
    values; every other required attribute gets a benign default so
    the frozen dataclass constructor is happy.
    """

    from fdai.core.prompts.types import PromptMode
    from fdai.core.tools import CapabilityGate, ToolArtifact

    return ToolArtifact(
        id=tool_id,
        version=version,
        description=f"{tool_id} description",
        input_schema={"type": "object"},
        capability_gate=CapabilityGate(
            requires_tier=None,
            requires_novelty_score=None,
            cost_budget_usd_per_call=None,
        ),
        allowlist=None,
        output_wrapper=None,
        default_mode=PromptMode(default_mode),
        provider=None,
        provenance_source="test",
    )


@pytest.mark.asyncio
async def test_compose_emits_no_manifest_when_no_tool_registry(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    composer = DefaultPromptComposer(registry=registry)  # no tool_registry

    out = await composer.compose(capability_id="t2.reasoner.primary")

    layers = [ref.layer for ref in out.layer_manifest]
    assert PromptLayer.TOOL not in layers


@pytest.mark.asyncio
async def test_compose_emits_no_manifest_when_registry_empty(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    composer = DefaultPromptComposer(
        registry=registry,
        tool_registry=_FakeToolRegistry(artifacts=()),
    )

    out = await composer.compose(capability_id="t2.reasoner.primary")

    assert not any(ref.layer is PromptLayer.TOOL for ref in out.layer_manifest)


@pytest.mark.asyncio
async def test_compose_skips_shadow_tools_by_default(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    tool_registry = _FakeToolRegistry(
        artifacts=(_fake_tool("rule.query", default_mode="shadow"),),
    )
    composer = DefaultPromptComposer(registry=registry, tool_registry=tool_registry)

    out = await composer.compose(capability_id="t2.reasoner.primary")

    assert not any(ref.layer is PromptLayer.TOOL for ref in out.layer_manifest)
    assert "rule.query" not in out.system_text


@pytest.mark.asyncio
async def test_compose_emits_manifest_for_enforce_tools(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    tool_registry = _FakeToolRegistry(
        artifacts=(_fake_tool("rule.query", default_mode="enforce"),),
    )
    composer = DefaultPromptComposer(registry=registry, tool_registry=tool_registry)

    out = await composer.compose(capability_id="t2.reasoner.primary")

    tool_refs = [ref for ref in out.layer_manifest if ref.layer is PromptLayer.TOOL]
    assert len(tool_refs) == 1
    assert tool_refs[0].id == "tool-manifest"
    assert tool_refs[0].version == 1
    assert "rule.query" in out.system_text


@pytest.mark.asyncio
async def test_compose_shadow_tools_opt_in(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    tool_registry = _FakeToolRegistry(
        artifacts=(_fake_tool("rule.query", default_mode="shadow"),),
    )
    composer = DefaultPromptComposer(
        registry=registry,
        tool_registry=tool_registry,
        include_shadow_tools=True,
    )

    out = await composer.compose(capability_id="t2.reasoner.primary")

    assert any(ref.layer is PromptLayer.TOOL for ref in out.layer_manifest)
    assert "rule.query" in out.system_text


@pytest.mark.asyncio
async def test_compose_tool_manifest_lists_tools_deterministically(
    tmp_path: Path,
) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    # Register in reverse-alphabetical order to prove sort is by id, not by input.
    tool_registry = _FakeToolRegistry(
        artifacts=(
            _fake_tool("state.query"),
            _fake_tool("audit.query"),
            _fake_tool("rule.query"),
        ),
    )
    composer = DefaultPromptComposer(registry=registry, tool_registry=tool_registry)

    out = await composer.compose(capability_id="t2.reasoner.primary")

    idx_audit = out.system_text.index("audit.query")
    idx_rule = out.system_text.index("rule.query")
    idx_state = out.system_text.index("state.query")
    assert idx_audit < idx_rule < idx_state


@pytest.mark.asyncio
async def test_shipped_tools_appear_in_dev_composer_only() -> None:
    """The three shipped tools are all shadow-mode; production composer
    MUST NOT surface them, dev composer with ``include_shadow_tools=True``
    MUST.
    """

    from fdai.core.tools import FileSystemToolRegistry

    repo_root = Path(__file__).resolve().parents[3]
    prompt_registry = FileSystemPromptRegistry(repo_root / "rule-catalog")
    tool_registry = FileSystemToolRegistry(repo_root / "rule-catalog")

    prod = DefaultPromptComposer(registry=prompt_registry, tool_registry=tool_registry)
    dev = DefaultPromptComposer(
        registry=prompt_registry,
        tool_registry=tool_registry,
        include_shadow_packs=True,
        include_shadow_tools=True,
    )

    prod_out = await prod.compose(capability_id="t2.reasoner.primary")
    dev_out = await dev.compose(capability_id="t2.reasoner.primary")

    prod_layers = {ref.layer for ref in prod_out.layer_manifest}
    dev_layers = {ref.layer for ref in dev_out.layer_manifest}
    assert PromptLayer.TOOL not in prod_layers
    assert PromptLayer.TOOL in dev_layers
    for tool_id in ("rule.query", "state.query", "audit.query"):
        assert tool_id not in prod_out.system_text
        assert tool_id in dev_out.system_text


# ---------------------------------------------------------------------------
# Operator memory layer (Wave 3 step C-1)
# ---------------------------------------------------------------------------


async def _memory_store_with(*entries):
    """Helper - append every entry to a fresh in-memory store."""

    from fdai.core.operator_memory import InMemoryOperatorMemoryStore

    store = InMemoryOperatorMemoryStore()
    for entry in entries:
        await store.append(entry)
    return store


def _mem_entry(
    *,
    scope_kind,
    scope_ref: str,
    body: str,
    author: str = "alice",
    approved_by: str = "bob",
    category=None,
):
    from datetime import UTC, datetime
    from uuid import uuid4

    from fdai.core.operator_memory import (
        MemoryCategory,
        MemorySource,
        OperatorMemoryEntry,
    )

    return OperatorMemoryEntry(
        id=uuid4(),
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        category=category or MemoryCategory.PREFERENCE,
        body=body,
        source_event=MemorySource.HIL_APPROVE_REASON,
        source_ref="audit:test",
        author=author,
        approved_by=approved_by,
        created_at=datetime.now(tz=UTC),
    )


@pytest.mark.asyncio
async def test_compose_emits_no_memory_layer_when_no_store(tmp_path: Path) -> None:
    from fdai.core.operator_memory import OperatorScope

    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    composer = DefaultPromptComposer(registry=registry)  # no operator_memory_store

    out = await composer.compose(
        capability_id="t2.reasoner.primary",
        scope=OperatorScope(resource_group_ref="rg-prod"),
    )

    assert not any(ref.layer.value == "operator-memory" for ref in out.layer_manifest)


@pytest.mark.asyncio
async def test_compose_emits_no_memory_layer_when_no_scope(tmp_path: Path) -> None:
    from fdai.core.operator_memory import ScopeKind

    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    store = await _memory_store_with(
        _mem_entry(
            scope_kind=ScopeKind.RESOURCE_GROUP,
            scope_ref="rg-prod",
            body="ignored without scope",
        ),
    )
    composer = DefaultPromptComposer(registry=registry, operator_memory_store=store)

    # No scope passed => memory layer MUST be omitted even though the
    # store has matching entries. The composer never guesses the
    # scope; startup composition uses this path.
    out = await composer.compose(capability_id="t2.reasoner.primary")

    assert not any(ref.layer.value == "operator-memory" for ref in out.layer_manifest)
    assert "ignored without scope" not in out.system_text


@pytest.mark.asyncio
async def test_compose_emits_no_memory_layer_when_store_empty(tmp_path: Path) -> None:
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore, OperatorScope

    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    composer = DefaultPromptComposer(
        registry=registry, operator_memory_store=InMemoryOperatorMemoryStore()
    )

    out = await composer.compose(
        capability_id="t2.reasoner.primary",
        scope=OperatorScope(resource_group_ref="rg-prod"),
    )

    assert not any(ref.layer.value == "operator-memory" for ref in out.layer_manifest)


@pytest.mark.asyncio
async def test_compose_emits_memory_layer_for_matching_rg(tmp_path: Path) -> None:
    from fdai.core.operator_memory import OperatorScope, ScopeKind

    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    store = await _memory_store_with(
        _mem_entry(
            scope_kind=ScopeKind.RESOURCE_GROUP,
            scope_ref="rg-prod",
            body="Do not touch during EU business hours.",
        ),
    )
    composer = DefaultPromptComposer(registry=registry, operator_memory_store=store)

    out = await composer.compose(
        capability_id="t2.reasoner.primary",
        scope=OperatorScope(resource_group_ref="rg-prod"),
    )

    memory_refs = [ref for ref in out.layer_manifest if ref.layer.value == "operator-memory"]
    assert len(memory_refs) == 1
    assert memory_refs[0].id == "operator-memory"
    assert memory_refs[0].version == 1
    # Body is wrapped with trusted="false" and carries the note text.
    assert 'trusted="false"' in out.system_text
    assert "Do not touch during EU business hours." in out.system_text


@pytest.mark.asyncio
async def test_compose_skips_memory_for_different_scope(tmp_path: Path) -> None:
    """A note authored for ``rg-a`` MUST NOT surface when the composer
    is asked about ``rg-b``. Scope isolation is the whole point of the
    Human Override contract."""

    from fdai.core.operator_memory import OperatorScope, ScopeKind

    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    store = await _memory_store_with(
        _mem_entry(
            scope_kind=ScopeKind.RESOURCE_GROUP,
            scope_ref="rg-a",
            body="rg-a specific guidance",
        ),
    )
    composer = DefaultPromptComposer(registry=registry, operator_memory_store=store)

    out = await composer.compose(
        capability_id="t2.reasoner.primary",
        scope=OperatorScope(resource_group_ref="rg-b"),
    )

    assert "rg-a specific guidance" not in out.system_text
    assert not any(ref.layer.value == "operator-memory" for ref in out.layer_manifest)


@pytest.mark.asyncio
async def test_compose_merges_rg_then_resource_notes(tmp_path: Path) -> None:
    """When the scope carries both a resource-group and a resource ref,
    the composer MUST fetch both and place the more-specific resource
    note AFTER the resource-group note so it lands closer to the model
    turn."""

    from fdai.core.operator_memory import OperatorScope, ScopeKind

    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    store = await _memory_store_with(
        _mem_entry(
            scope_kind=ScopeKind.RESOURCE_GROUP,
            scope_ref="rg-prod",
            body="RG-LEVEL-NOTE",
        ),
        _mem_entry(
            scope_kind=ScopeKind.RESOURCE,
            scope_ref="res-42",
            body="RESOURCE-LEVEL-NOTE",
        ),
    )
    composer = DefaultPromptComposer(registry=registry, operator_memory_store=store)

    out = await composer.compose(
        capability_id="t2.reasoner.primary",
        scope=OperatorScope(resource_group_ref="rg-prod", resource_ref="res-42"),
    )

    rg_index = out.system_text.index("RG-LEVEL-NOTE")
    resource_index = out.system_text.index("RESOURCE-LEVEL-NOTE")
    assert rg_index < resource_index


@pytest.mark.asyncio
async def test_compose_ignores_superseded_and_expired_notes(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from fdai.core.operator_memory import (
        InMemoryOperatorMemoryStore,
        MemoryCategory,
        MemorySource,
        OperatorMemoryEntry,
        OperatorScope,
        ScopeKind,
    )

    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    fixed_now = datetime(2026, 7, 6, 12, 0, 0, tzinfo=UTC)
    store = InMemoryOperatorMemoryStore(now_fn=lambda: fixed_now)
    # Expired entry (TTL 1h, created 2h ago) - MUST be skipped.
    expired = OperatorMemoryEntry(
        id=uuid4(),
        scope_kind=ScopeKind.RESOURCE_GROUP,
        scope_ref="rg-prod",
        category=MemoryCategory.PREFERENCE,
        body="EXPIRED",
        source_event=MemorySource.HIL_APPROVE_REASON,
        source_ref="a",
        author="alice",
        approved_by="bob",
        created_at=fixed_now - timedelta(hours=2),
        ttl_seconds=3600,
    )
    # Superseded original + its replacement.
    original = OperatorMemoryEntry(
        id=uuid4(),
        scope_kind=ScopeKind.RESOURCE_GROUP,
        scope_ref="rg-prod",
        category=MemoryCategory.PREFERENCE,
        body="SUPERSEDED",
        source_event=MemorySource.HIL_APPROVE_REASON,
        source_ref="a",
        author="alice",
        approved_by="bob",
        created_at=fixed_now - timedelta(minutes=5),
    )
    replacement = OperatorMemoryEntry(
        id=uuid4(),
        scope_kind=ScopeKind.RESOURCE_GROUP,
        scope_ref="rg-prod",
        category=MemoryCategory.PREFERENCE,
        body="REPLACEMENT",
        source_event=MemorySource.HIL_APPROVE_REASON,
        source_ref="a",
        author="alice",
        approved_by="bob",
        created_at=fixed_now - timedelta(minutes=1),
    )
    await store.append(expired)
    await store.append(original)
    await store.append(replacement)
    await store.supersede(entry_id=original.id, superseded_by=replacement.id)

    composer = DefaultPromptComposer(registry=registry, operator_memory_store=store)

    out = await composer.compose(
        capability_id="t2.reasoner.primary",
        scope=OperatorScope(resource_group_ref="rg-prod"),
    )

    assert "EXPIRED" not in out.system_text
    assert "SUPERSEDED" not in out.system_text
    assert "REPLACEMENT" in out.system_text


@pytest.mark.asyncio
async def test_compose_wraps_every_note_with_trusted_false(tmp_path: Path) -> None:
    """XML wrap must survive concatenation - each entry gets its own
    ``<operator_note trusted="false" ...>`` envelope."""

    from fdai.core.operator_memory import OperatorScope, ScopeKind

    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    store = await _memory_store_with(
        _mem_entry(scope_kind=ScopeKind.RESOURCE_GROUP, scope_ref="rg-prod", body="ONE"),
        _mem_entry(scope_kind=ScopeKind.RESOURCE_GROUP, scope_ref="rg-prod", body="TWO"),
    )
    composer = DefaultPromptComposer(registry=registry, operator_memory_store=store)

    out = await composer.compose(
        capability_id="t2.reasoner.primary",
        scope=OperatorScope(resource_group_ref="rg-prod"),
    )

    assert out.system_text.count('<operator_note trusted="false"') == 2
    assert out.system_text.count("</operator_note>") == 2


# ---------------------------------------------------------------------------
# Canary token injection (Wave 3 step D-2a)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compose_omits_canary_when_no_generator(tmp_path: Path) -> None:
    """Backward-compat guard: without an injected generator, the
    composer MUST NOT stamp any canary marker into the layer bodies
    and ``ComposedPrompt.canary_tokens`` MUST be empty."""

    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    composer = DefaultPromptComposer(registry=registry)

    out = await composer.compose(capability_id="t2.reasoner.primary")

    assert out.canary_tokens == {}
    assert "canary" not in out.system_text.lower()


@pytest.mark.asyncio
async def test_compose_stamps_canary_per_layer(tmp_path: Path) -> None:
    from fdai.core.measurement.prompt_probe import DeterministicCanaryGenerator

    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE_BODY"))
    _write_prompt(
        tmp_path,
        "packs",
        "extra-pack.v1.yaml",
        dedent(
            """
            id: extra-pack
            version: 1
            layer: pack
            applies_to: [t2.reasoner.primary]
            default_mode: enforce
            body: PACK_BODY
            provenance: {source: test}
            """
        ),
    )
    registry = FileSystemPromptRegistry(tmp_path)
    canaries = DeterministicCanaryGenerator(
        tokens={"hello": "CN_BASE_TOKEN", "extra-pack": "CN_PACK_TOKEN"}
    )
    composer = DefaultPromptComposer(registry=registry, canary_generator=canaries)

    out = await composer.compose(capability_id="t2.reasoner.primary")

    assert out.canary_tokens == {"hello": "CN_BASE_TOKEN", "extra-pack": "CN_PACK_TOKEN"}
    # Each token lands at the head of its respective layer body.
    assert out.system_text.startswith("[canary:hello=CN_BASE_TOKEN]\nBASE_BODY")
    assert "[canary:extra-pack=CN_PACK_TOKEN]\nPACK_BODY" in out.system_text


@pytest.mark.asyncio
async def test_compose_updates_layer_manifest_token_estimate_after_canary(tmp_path: Path) -> None:
    """The manifest's per-layer ``token_estimate`` MUST reflect the
    body length AFTER the canary was prepended - otherwise the
    recognition-probe KPIs would credit the composer with fewer
    tokens than the model actually saw."""

    from fdai.core.measurement.prompt_probe import DeterministicCanaryGenerator

    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "B"))
    registry = FileSystemPromptRegistry(tmp_path)
    composer = DefaultPromptComposer(
        registry=registry,
        canary_generator=DeterministicCanaryGenerator(tokens={"hello": "CN_X"}),
    )

    out = await composer.compose(capability_id="t2.reasoner.primary")

    # Body is exactly "[canary:hello=CN_X]\nB" = 21 chars, so at 4
    # chars per token (rounded up) the estimate is 6. The bare body
    # "B" was 1 char, so the pre-canary estimate would have been 1
    # token.
    assert out.layer_manifest[0].token_estimate == 6


@pytest.mark.asyncio
async def test_compose_stamps_canary_on_synthetic_operator_memory_layer(tmp_path: Path) -> None:
    """Synthetic layers (operator memory, tool manifest) MUST receive
    canaries too - a KPI that only measures YAML-authored layers
    misses the very sections a model is most likely to drop."""

    from datetime import UTC, datetime
    from uuid import uuid4

    from fdai.core.measurement.prompt_probe import DeterministicCanaryGenerator
    from fdai.core.operator_memory import (
        InMemoryOperatorMemoryStore,
        MemoryCategory,
        MemorySource,
        OperatorMemoryEntry,
        OperatorScope,
        ScopeKind,
    )

    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    store = InMemoryOperatorMemoryStore()
    await store.append(
        OperatorMemoryEntry(
            id=uuid4(),
            scope_kind=ScopeKind.RESOURCE_GROUP,
            scope_ref="rg-prod",
            category=MemoryCategory.PREFERENCE,
            body="operator guidance",
            source_event=MemorySource.HIL_APPROVE_REASON,
            source_ref="audit:x",
            author="alice",
            approved_by="bob",
            created_at=datetime.now(tz=UTC),
        )
    )
    canaries = DeterministicCanaryGenerator(
        tokens={
            "hello": "CN_BASE",
            "operator-memory": "CN_MEM",
        }
    )
    composer = DefaultPromptComposer(
        registry=registry, operator_memory_store=store, canary_generator=canaries
    )

    out = await composer.compose(
        capability_id="t2.reasoner.primary",
        scope=OperatorScope(resource_group_ref="rg-prod"),
    )

    assert out.canary_tokens == {"hello": "CN_BASE", "operator-memory": "CN_MEM"}
    assert "[canary:operator-memory=CN_MEM]\n" in out.system_text


def test_secrets_canary_generator_produces_unique_tokens() -> None:
    """Production generator MUST NOT collide across successive calls,
    even for the same layer id, so an attacker cannot pre-compute a
    canary echo."""

    from fdai.core.measurement.prompt_probe import SecretsCanaryGenerator

    gen = SecretsCanaryGenerator()
    tokens = {gen.next_token(layer_id="base") for _ in range(100)}
    # 100 12-hex-char tokens have collision probability under 1e-25;
    # a length below 100 signals a broken generator.
    assert len(tokens) == 100
    assert all(t.startswith("CN_") for t in tokens)


def test_deterministic_canary_generator_returns_stub_for_unprimed_layer() -> None:
    from fdai.core.measurement.prompt_probe import DeterministicCanaryGenerator

    gen = DeterministicCanaryGenerator(tokens={"base": "CN_KNOWN"})
    assert gen.next_token(layer_id="base") == "CN_KNOWN"
    assert gen.next_token(layer_id="unprimed") == "CN_stub_unprimed"


# ---------------------------------------------------------------------------
# Explicit runtime skill disclosure
# ---------------------------------------------------------------------------


class _SkillTrustVerifier:
    def __init__(self, *, trusted: bool = True) -> None:
        self.trusted = trusted

    def verify(self, skill, raw_markdown: bytes) -> bool:
        return self.trusted


def _raw_runtime_skill(
    *,
    name: str,
    body: str,
    required_tools: tuple[str, ...] = ("inventory.query",),
    allowed_agents: tuple[str, ...] = ("Bragi",),
    reference: tuple[str, bytes, str] | None = None,
) -> tuple[bytes, dict[str, bytes]]:
    import yaml

    from fdai.core.skills import skill_body_digest

    manifest: dict[str, object] = {
        "name": name,
        "version": "1.2.3",
        "description": f"Metadata for {name}.",
        "source": f"test:{name}",
        "body_sha256": skill_body_digest(body),
        "required_tools": list(required_tools),
        "allowed_agents": list(allowed_agents),
    }
    references: dict[str, bytes] = {}
    if reference is not None:
        path, content, media_type = reference
        manifest["references"] = [
            {
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "media_type": media_type,
            }
        ]
        references[path] = content
    front_matter = yaml.safe_dump(manifest, sort_keys=False)
    return f"---\n{front_matter}---\n{body}\n".encode(), references


def _runtime_skill_catalog(
    *skills: tuple[str, str, tuple[str, bytes, str] | None],
) -> tuple[object, _SkillTrustVerifier]:
    from fdai.core.skills import SkillCatalog

    verifier = _SkillTrustVerifier()
    catalog = SkillCatalog()
    for name, body, reference in skills:
        raw, references = _raw_runtime_skill(name=name, body=body, reference=reference)
        catalog = catalog.install_bundle(raw, references, verifier=verifier).enable(
            name,
            available_tools=frozenset({"inventory.query"}),
            known_agents=frozenset({"Bragi"}),
        )
    return catalog, verifier


def _skill_request(**overrides) -> SkillDisclosureRequest:
    values = {
        "agent": "Bragi",
        "available_tools": frozenset({"inventory.query"}),
        "query": "  inventory   evidence  ",
        "selected_skill_names": ("inventory-evidence",),
    }
    values.update(overrides)
    return SkillDisclosureRequest(**values)


@pytest.mark.asyncio
async def test_skill_disclosure_absence_and_unconfigured_catalog_are_exact_compatibility(
    tmp_path: Path,
) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    catalog, verifier = _runtime_skill_catalog(("inventory-evidence", "SECRET-SKILL-BODY", None))
    baseline = await DefaultPromptComposer(registry=registry).compose(
        capability_id="t2.reasoner.primary"
    )
    configured_without_request = await DefaultPromptComposer(
        registry=registry,
        skill_catalog=catalog,
        skill_trust_verifier=verifier,
    ).compose(capability_id="t2.reasoner.primary")
    unconfigured_with_request = await DefaultPromptComposer(registry=registry).compose(
        capability_id="t2.reasoner.primary",
        skill_disclosure=_skill_request(),
    )

    assert configured_without_request == baseline
    assert unconfigured_with_request == baseline


def test_skill_catalog_and_verifier_must_be_wired_as_a_pair(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    catalog, verifier = _runtime_skill_catalog()

    with pytest.raises(ValueError, match="provided together"):
        DefaultPromptComposer(registry=registry, skill_catalog=catalog)
    with pytest.raises(ValueError, match="provided together"):
        DefaultPromptComposer(registry=registry, skill_trust_verifier=verifier)


@pytest.mark.asyncio
async def test_skill_index_precedes_complete_body_and_contains_metadata_only(
    tmp_path: Path,
) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    registry = FileSystemPromptRegistry(tmp_path)
    catalog, verifier = _runtime_skill_catalog(("inventory-evidence", "COMPLETE-SKILL-BODY", None))
    composer = DefaultPromptComposer(
        registry=registry,
        skill_catalog=catalog,
        skill_trust_verifier=verifier,
    )

    result = await composer.compose(
        capability_id="t2.reasoner.primary",
        skill_disclosure=_skill_request(),
    )

    layers = [entry.layer for entry in result.layer_manifest]
    assert layers.index(PromptLayer.SKILL_INDEX) < layers.index(PromptLayer.SKILL_BODY)
    index_end = result.system_text.index("</skill-index>")
    body_start = result.system_text.index('<skill name="inventory-evidence"')
    assert "COMPLETE-SKILL-BODY" not in result.system_text[:index_end]
    assert result.system_text[body_start:].endswith("COMPLETE-SKILL-BODY\n</skill>")
    assert result.skill_records[0].version == "1.2.3"
    assert result.skill_records[0].body_sha256
    assert result.layer_manifest[-1].version == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("disclosure", "reason"),
    [
        (_skill_request(agent="Saga"), "skill_agent_not_allowed"),
        (_skill_request(available_tools=frozenset()), "skill_required_tools_unavailable"),
        (_skill_request(body_budget_chars=1), "skill_body_budget_exceeded"),
    ],
)
async def test_rejected_skill_is_recorded_without_body(
    tmp_path: Path,
    disclosure: SkillDisclosureRequest,
    reason: str,
) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    catalog, verifier = _runtime_skill_catalog(("inventory-evidence", "MUST-NOT-LEAK", None))
    composer = DefaultPromptComposer(
        registry=FileSystemPromptRegistry(tmp_path),
        skill_catalog=catalog,
        skill_trust_verifier=verifier,
    )

    result = await composer.compose(
        capability_id="t2.reasoner.primary",
        skill_disclosure=disclosure,
    )

    assert "MUST-NOT-LEAK" not in result.system_text
    assert not any(ref.layer is PromptLayer.SKILL_BODY for ref in result.layer_manifest)
    assert result.skill_records[0].status is SkillSelectionStatus.REJECTED
    assert result.skill_records[0].rejection_reason == reason


@pytest.mark.asyncio
async def test_untrusted_selected_skill_is_rejected_without_content(tmp_path: Path) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    catalog, verifier = _runtime_skill_catalog(("inventory-evidence", "UNTRUSTED-BODY", None))
    verifier.trusted = False
    composer = DefaultPromptComposer(
        registry=FileSystemPromptRegistry(tmp_path),
        skill_catalog=catalog,
        skill_trust_verifier=verifier,
    )

    result = await composer.compose(
        capability_id="t2.reasoner.primary",
        skill_disclosure=_skill_request(),
    )

    assert "UNTRUSTED-BODY" not in result.system_text
    assert result.skill_records[0].rejection_reason == "skill_trust_verification_failed"


@pytest.mark.asyncio
async def test_one_complete_reference_is_untrusted_data_with_replay_digest(
    tmp_path: Path,
) -> None:
    reference = ("references/guide.txt", b"COMPLETE <reference> DATA", "text/plain")
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    catalog, verifier = _runtime_skill_catalog(("inventory-evidence", "BODY", reference))
    composer = DefaultPromptComposer(
        registry=FileSystemPromptRegistry(tmp_path),
        skill_catalog=catalog,
        skill_trust_verifier=verifier,
    )

    result = await composer.compose(
        capability_id="t2.reasoner.primary",
        skill_disclosure=_skill_request(
            selected_skill_names=(),
            reference_selection=("inventory-evidence", reference[0]),
        ),
    )

    assert 'trusted="false"' in result.system_text
    assert "COMPLETE &lt;reference&gt; DATA" in result.system_text
    assert any(ref.layer is PromptLayer.SKILL_REFERENCE for ref in result.layer_manifest)
    record = result.skill_records[0]
    assert record.status is SkillSelectionStatus.SELECTED
    assert record.reference_sha256 == hashlib.sha256(reference[1]).hexdigest()


@pytest.mark.asyncio
async def test_rejected_reference_budget_records_declared_digest_without_content(
    tmp_path: Path,
) -> None:
    reference = ("references/guide.txt", b"REFERENCE-MUST-NOT-LEAK", "text/plain")
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    catalog, verifier = _runtime_skill_catalog(("inventory-evidence", "BODY", reference))
    composer = DefaultPromptComposer(
        registry=FileSystemPromptRegistry(tmp_path),
        skill_catalog=catalog,
        skill_trust_verifier=verifier,
    )

    result = await composer.compose(
        capability_id="t2.reasoner.primary",
        skill_disclosure=_skill_request(
            selected_skill_names=(),
            reference_selection=("inventory-evidence", reference[0]),
            reference_budget_bytes=1,
        ),
    )

    assert "REFERENCE-MUST-NOT-LEAK" not in result.system_text
    record = result.skill_records[0]
    assert record.status is SkillSelectionStatus.REJECTED
    assert record.rejection_reason == "skill_reference_budget_exceeded"
    assert record.reference_sha256 == hashlib.sha256(reference[1]).hexdigest()


def test_skill_disclosure_normalizes_query_and_enforces_selection_bounds() -> None:
    request = _skill_request(query="  inventory\n\t evidence ")
    assert request.query == "inventory evidence"

    with pytest.raises(ValueError, match="more than 4"):
        _skill_request(selected_skill_names=("a", "b", "c", "d", "e"))
    with pytest.raises(ValueError, match="duplicates"):
        _skill_request(selected_skill_names=("same", "same"))
    with pytest.raises(ValueError, match="one .* tuple"):
        _skill_request(reference_selection=(("a", "references/a"), ("b", "references/b")))


@pytest.mark.asyncio
async def test_same_skill_request_and_catalog_produce_identical_replay_manifest(
    tmp_path: Path,
) -> None:
    _write_schema(tmp_path)
    _write_prompt(tmp_path, "base", "hello.v1.yaml", _base("t2.reasoner.primary", "BASE"))
    catalog, verifier = _runtime_skill_catalog(("inventory-evidence", "DETERMINISTIC-BODY", None))
    composer = DefaultPromptComposer(
        registry=FileSystemPromptRegistry(tmp_path),
        skill_catalog=catalog,
        skill_trust_verifier=verifier,
    )
    request = _skill_request()

    first = await composer.compose(capability_id="t2.reasoner.primary", skill_disclosure=request)
    second = await composer.compose(capability_id="t2.reasoner.primary", skill_disclosure=request)

    assert first.replay_manifest() == second.replay_manifest()
