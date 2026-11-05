"""Capability-bundle and provider integration tests."""

from __future__ import annotations

from dataclasses import dataclass, replace

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
    install_code_assurance_capabilities,
)
from fdai_code_assurance.models import PullRequestFile, PullRequestSnapshot
from fdai_code_assurance.provider import (
    CODE_REVIEW_TOOL_ID,
    SECURITY_REVIEW_TOOL_ID,
    CodeAssuranceProvider,
)


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


async def test_security_review_tool_and_provider_validation_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _Source([])
    runtime = _runtime(source)
    executor = DefaultToolExecutor(
        registry=StaticToolRegistry(runtime.reasoning_tools),
        providers=runtime.tool_providers,
        allow_shadow_dispatch=True,
    )
    sec_result = await executor.dispatch(
        tool_id=SECURITY_REVIEW_TOOL_ID,
        arguments={"repository": "example/project", "pull_number": 9},
    )
    assert sec_result.raw["profile"] == "security"

    provider = CodeAssuranceProvider(source)
    code_artifact = next(a for a in runtime.reasoning_tools if a.id == CODE_REVIEW_TOOL_ID)
    with pytest.raises(ValueError, match="repository MUST be a non-empty string"):
        await provider.call(artifact=code_artifact, arguments={"repository": "", "pull_number": 1})
    with pytest.raises(ValueError, match="pull_number MUST be a positive integer"):
        await provider.call(
            artifact=code_artifact,
            arguments={"repository": "example/project", "pull_number": True},
        )
    unknown_artifact = replace(code_artifact, id="code-assurance.unknown")
    with pytest.raises(ValueError, match="unsupported code-assurance tool id"):
        await provider.call(
            artifact=unknown_artifact,
            arguments={"repository": "example/project", "pull_number": 1},
        )

    installed_containers: list[object] = []
    monkeypatch.setattr(
        "fdai_code_assurance.bundle.install_capability_bundle",
        lambda container, bundle: installed_containers.append((container, bundle)) or container,
    )
    sentinel = object()
    assert install_code_assurance_capabilities(sentinel, source=source) is sentinel  # type: ignore[arg-type]
    assert len(installed_containers) == 1


def test_load_assets_rejects_member_or_tool_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    from fdai.core.skills import parse_skill_bundle_manifest as real_parse

    bundle_bytes = load_code_assurance_assets().skill_bundle
    parsed = real_parse(bundle_bytes)

    class _DriftMembers:
        manifest = type(
            "_M",
            (),
            {
                "members": (),
                "required_tools": parsed.manifest.required_tools,
            },
        )()

    monkeypatch.setattr(
        "fdai_code_assurance.assets.parse_skill_bundle_manifest",
        lambda _raw: _DriftMembers(),
    )
    with pytest.raises(ValueError, match="members do not match"):
        load_code_assurance_assets()

    class _DriftTools:
        manifest = type(
            "_M",
            (),
            {
                "members": parsed.manifest.members,
                "required_tools": ("other.tool",),
            },
        )()

    monkeypatch.setattr(
        "fdai_code_assurance.assets.parse_skill_bundle_manifest",
        lambda _raw: _DriftTools(),
    )
    with pytest.raises(ValueError, match="tools do not match"):
        load_code_assurance_assets()
