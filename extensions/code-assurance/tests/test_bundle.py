"""Capability-bundle and provider integration tests."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from fdai.core.capability_catalog import (
    CapabilityReferences,
    CapabilityRuntime,
    ExtensionManager,
    ExtensionState,
)
from fdai.core.tools import DefaultToolExecutor, StaticToolRegistry, ToolArgumentValidationError
from fdai_code_assurance.assets import load_code_assurance_assets
from fdai_code_assurance.bundle import (
    PROVIDER_ID,
    build_code_assurance_bundle,
    build_code_assurance_extension,
)
from fdai_code_assurance.models import PullRequestFile, PullRequestSnapshot
from fdai_code_assurance.provider import CODE_REVIEW_TOOL_ID, SECURITY_REVIEW_TOOL_ID


@dataclass
class _Source:
    calls: list[tuple[str, int]]

    async def fetch(self, *, repository: str, pull_number: int) -> PullRequestSnapshot:
        self.calls.append((repository, pull_number))
        return PullRequestSnapshot(
            repository=repository,
            pull_number=pull_number,
            base_sha="a" * 40,
            head_sha="b" * 40,
            changed_files=1,
            files=(
                PullRequestFile(
                    path="src/example.py",
                    status="modified",
                    additions=1,
                    deletions=0,
                    patch="@@ -1 +1 @@\n+except:",
                ),
            ),
        )


def _runtime(source: _Source) -> CapabilityRuntime:
    return CapabilityRuntime().install(
        build_code_assurance_bundle(source),
        references=CapabilityReferences(),
    )


def test_bundle_is_self_contained_and_shadow_first() -> None:
    runtime = _runtime(_Source([]))

    assert runtime.bound_capability_ids() == (
        "assurance.code-review",
        "assurance.security-review",
    )
    assert {artifact.id for artifact in runtime.reasoning_tools} == {
        CODE_REVIEW_TOOL_ID,
        SECURITY_REVIEW_TOOL_ID,
    }
    assert all(artifact.default_mode.value == "shadow" for artifact in runtime.reasoning_tools)
    assert set(runtime.tool_providers) == {PROVIDER_ID}


def test_packaged_skill_assets_match_runtime_tools() -> None:
    assets = load_code_assurance_assets()

    assert len(assets.skills) == 2
    assert b"code-assurance.review-pack" in assets.skill_bundle


def test_extension_package_installs_disabled_before_atomic_enable() -> None:
    archive = b"synthetic reviewed wheel bytes"
    package = build_code_assurance_extension(_Source([]), archive=archive)
    manager = ExtensionManager(host_version="0.1.127", references=CapabilityReferences())

    class _Verifier:
        def verify(self, manifest: object, candidate: bytes) -> bool:
            return candidate == archive

    installed = manager.install(package, archive=archive, verifier=_Verifier())

    assert installed.list() == (("code-assurance.review-pack", ExtensionState.DISABLED, "0.1.0"),)
    assert installed.runtime().bound_capability_ids() == ()
    assert installed.enable("code-assurance.review-pack").runtime().bound_capability_ids() == (
        "assurance.code-review",
        "assurance.security-review",
    )


async def test_shadow_evaluation_dispatches_only_when_explicitly_enabled() -> None:
    source = _Source([])
    runtime = _runtime(source)
    executor = DefaultToolExecutor(
        registry=StaticToolRegistry(runtime.reasoning_tools),
        providers=runtime.tool_providers,
        allow_shadow_dispatch=True,
    )

    result = await executor.dispatch(
        tool_id=CODE_REVIEW_TOOL_ID,
        arguments={"repository": "example/project", "pull_number": 7},
    )

    assert source.calls == [("example/project", 7)]
    assert result.raw["profile"] == "code"
    assert result.raw["findings"][0]["rule_id"] == "code.bare-except"
    assert 'trusted="false"' in result.wrapped_text


async def test_tool_schema_rejects_unexpected_arguments_before_provider_call() -> None:
    source = _Source([])
    runtime = _runtime(source)
    executor = DefaultToolExecutor(
        registry=StaticToolRegistry(runtime.reasoning_tools),
        providers=runtime.tool_providers,
        allow_shadow_dispatch=True,
    )

    with pytest.raises(ToolArgumentValidationError):
        await executor.dispatch(
            tool_id=SECURITY_REVIEW_TOOL_ID,
            arguments={
                "repository": "example/project",
                "pull_number": 7,
                "write_token": "not-allowed",
            },
        )

    assert source.calls == []
