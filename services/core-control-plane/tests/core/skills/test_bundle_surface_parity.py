"""One authoritative bundle snapshot across Bragi, typed RPC, and Console.

The remaining-work item this file closes is that the bundle operations were
only registered, never invoked, and nothing proved the three read surfaces
answer from the same runtime snapshot
(governed-skill-bundles.md - Bragi commands, typed RPC, and read-only Console
inspection).
"""

from __future__ import annotations

import re

from fdai.core.conversation.session import Principal, Role
from fdai.core.conversation.skill_discovery import (
    DescribeRuntimeSkillBundleTool,
    ListRuntimeSkillBundlesTool,
    LoadRuntimeSkillBundleTool,
)
from fdai.core.rpc import (
    RpcRegistry,
    RpcRequest,
    RpcResponse,
    RpcScope,
    skill_discovery_rpc_methods,
)
from fdai.core.skills import RuntimeSkill, RuntimeSkillDisclosure, SkillCatalog, skill_body_digest
from fdai.core.skills.bundle_catalog import SkillBundleCatalog, SkillBundleRejectionReason
from fdai.core.skills.bundle_manifest import RuntimeSkillBundle, encode_skill_bundle_manifest

_BUNDLE = "incident-evidence-pack"
_READER = Principal(id="oid-reader", role=Role.READER, display_name="reader")


class _SkillVerifier:
    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return True


class _BundleVerifier:
    def verify(self, bundle: RuntimeSkillBundle, raw_manifest: bytes) -> bool:
        return bundle.raw_manifest == raw_manifest


def _runtime() -> tuple[RuntimeSkillDisclosure, SkillBundleCatalog]:
    skill_verifier = _SkillVerifier()
    skills = SkillCatalog()
    for name, version, tool, body in (
        ("inventory-evidence", "1.0.0", "query_inventory", "PRIVATE-INVENTORY-BODY"),
        ("log-evidence", "2.0.0", "query_log", "PRIVATE-LOG-BODY"),
    ):
        raw = f"""---
name: {name}
version: {version}
description: Evidence for {name}.
source: publisher.example
body_sha256: "{skill_body_digest(body)}"
required_tools: [{tool}]
allowed_agents: [Bragi]
---
{body}
""".encode()
        skills = skills.install(raw, verifier=skill_verifier).enable(
            name,
            available_tools=frozenset({tool}),
            known_agents=frozenset({"Bragi"}),
        )
    bundle_verifier = _BundleVerifier()
    raw_bundle = encode_skill_bundle_manifest(
        {
            "name": _BUNDLE,
            "version": "1.0.0",
            "description": "Reviewed incident evidence procedures.",
            "source": "publisher.example",
            "members": [
                {"name": "inventory-evidence", "version": "==1.0.0"},
                {"name": "log-evidence", "version": "==2.0.0"},
            ],
            "allowed_agents": ["Bragi"],
            "required_tools": ["query_inventory", "query_log"],
            "instruction": "PRIVATE-BUNDLE-INSTRUCTION",
        }
    )
    bundles = (
        SkillBundleCatalog()
        .install(raw_bundle, verifier=bundle_verifier)
        .enable(
            _BUNDLE,
            skills=skills,
            bundle_verifier=bundle_verifier,
            skill_verifier=skill_verifier,
            available_tools=frozenset({"query_inventory", "query_log"}),
            known_agents=frozenset({"Bragi"}),
        )
    )
    disclosure = RuntimeSkillDisclosure(
        catalog=skills,
        verifier=skill_verifier,
        agent="Bragi",
        available_tools=frozenset({"query_inventory", "query_log"}),
        bundle_catalog=bundles,
        bundle_verifier=bundle_verifier,
        known_agents=frozenset({"Bragi"}),
    )
    return disclosure, bundles


def _registry(disclosure: RuntimeSkillDisclosure) -> RpcRegistry:
    registry = RpcRegistry()
    for method in skill_discovery_rpc_methods(disclosure):
        registry = registry.register(method)
    return registry


async def _rpc(registry: RpcRegistry, method: str, **params: object) -> RpcResponse:
    return await registry.invoke(
        RpcRequest(request_id=method, method=method, params=params),
        scopes=frozenset({RpcScope.READ}),
    )


# --- Bragi commands --------------------------------------------------------


def test_bragi_bundle_commands_list_describe_and_load() -> None:
    disclosure, _ = _runtime()

    listed = ListRuntimeSkillBundlesTool(disclosure).call(
        arguments={"query": "incident", "limit": 10}, principal=_READER
    )
    described = DescribeRuntimeSkillBundleTool(disclosure).call(
        arguments={"name": _BUNDLE}, principal=_READER
    )
    loaded = LoadRuntimeSkillBundleTool(disclosure).call(
        arguments={"name": _BUNDLE}, principal=_READER
    )

    assert listed.status == "ok"
    assert listed.data["returned_count"] == 1
    assert described.status == "ok"
    assert described.data["bundle"]["compatible"] is True
    assert loaded.status == "ok"
    assert loaded.data["instruction"] == "PRIVATE-BUNDLE-INSTRUCTION"
    assert [member["body"] for member in loaded.data["members"]] == [
        "PRIVATE-INVENTORY-BODY\n",
        "PRIVATE-LOG-BODY\n",
    ]
    # Metadata-only commands never leak member or instruction content.
    assert "PRIVATE" not in repr(listed)
    assert "PRIVATE" not in repr(described)


def test_bragi_bundle_commands_reject_without_content_or_raising() -> None:
    disclosure, _ = _runtime()

    described = DescribeRuntimeSkillBundleTool(disclosure).call(
        arguments={"name": "not-installed"}, principal=_READER
    )
    loaded = LoadRuntimeSkillBundleTool(disclosure).call(
        arguments={"name": "not-installed"}, principal=_READER
    )

    for result in (described, loaded):
        assert result.status == "error"
        assert result.data["error"]["code"] == "skill_bundle_access_rejected"
        assert result.data["error"]["reason"] == "skill_bundle_not_installed"
        assert "PRIVATE" not in repr(result)
    # Both refused reads leave their own diagnostic, not just the load.
    operations = [
        (entry["operation"], entry["reason"])
        for entry in disclosure.diagnostics()
        if entry["status"] == "rejected"
    ]
    assert operations == [
        ("describe_bundle", "skill_bundle_not_installed"),
        ("load_bundle", "skill_bundle_not_installed"),
    ]


def test_every_bundle_rejection_reason_is_a_stable_content_free_token() -> None:
    # A future reason must stay a fixed English token so a diagnostic can never
    # carry a member body, a customer value, or a substrate identifier.
    for reason in SkillBundleRejectionReason:
        assert re.fullmatch(r"skill_bundle_[a-z_]+", reason.value), reason


def test_bragi_bundle_commands_stay_read_only_at_the_reader_floor() -> None:
    disclosure, _ = _runtime()
    tools = (
        ListRuntimeSkillBundlesTool(disclosure),
        DescribeRuntimeSkillBundleTool(disclosure),
        LoadRuntimeSkillBundleTool(disclosure),
    )

    assert [tool.rbac_floor for tool in tools] == [Role.READER] * 3
    assert [tool.side_effect_class for tool in tools] == ["read"] * 3
    # No bundle command may install, enable, disable, or uninstall.
    assert {tool.name for tool in tools} == {
        "describe_skill_bundle",
        "list_skill_bundles",
        "load_skill_bundle",
    }


# --- typed RPC -------------------------------------------------------------


async def test_bundle_rpc_operations_list_describe_and_load() -> None:
    disclosure, _ = _runtime()
    registry = _registry(disclosure)

    listed = await _rpc(registry, "skill_bundles.list", query="incident", limit=10)
    described = await _rpc(registry, "skill_bundles.describe", name=_BUNDLE)
    loaded = await _rpc(registry, "skill_bundles.load", name=_BUNDLE)

    assert listed.ok is True
    assert listed.result["returned_count"] == 1
    assert described.result["bundle"]["name"] == _BUNDLE
    assert loaded.result["instruction"] == "PRIVATE-BUNDLE-INSTRUCTION"
    assert "PRIVATE" not in repr(listed)
    assert "PRIVATE" not in repr(described)


async def test_bundle_rpc_rejection_uses_one_stable_content_free_reason() -> None:
    disclosure, _ = _runtime()
    registry = _registry(disclosure)

    described = await _rpc(registry, "skill_bundles.describe", name="not-installed")
    loaded = await _rpc(registry, "skill_bundles.load", name="not-installed")

    for response in (described, loaded):
        assert response.error_code == "skill_bundle_access_rejected"
        assert response.error_message == "skill_bundle_not_installed"
        assert "PRIVATE" not in repr(response)


async def test_bundle_rpc_parameters_are_validated_before_disclosure() -> None:
    disclosure, _ = _runtime()
    registry = _registry(disclosure)

    bad_query = await _rpc(registry, "skill_bundles.list", query=7)
    bad_limit = await _rpc(registry, "skill_bundles.list", query="", limit=999)
    empty_name = await _rpc(registry, "skill_bundles.describe", name="")

    assert bad_query.error_code == "invalid_params"
    assert bad_limit.error_code == "invalid_params"
    assert empty_name.error_code == "invalid_params"


async def test_bundle_rpc_operations_require_read_scope_only() -> None:
    disclosure, _ = _runtime()
    registry = _registry(disclosure)

    bundle_methods = [
        method
        for method in registry.discover(frozenset({RpcScope.READ}))
        if method["name"].startswith("skill_bundles.")
    ]

    assert {method["name"] for method in bundle_methods} == {
        "skill_bundles.describe",
        "skill_bundles.list",
        "skill_bundles.load",
    }
    assert all(method["required_scope"] == RpcScope.READ.value for method in bundle_methods)


# --- one authoritative snapshot -------------------------------------------


async def test_every_read_surface_answers_from_the_same_bundle_snapshot() -> None:
    disclosure, bundles = _runtime()
    registry = _registry(disclosure)

    def surfaces() -> tuple[object, object, object]:
        bragi = ListRuntimeSkillBundlesTool(disclosure).call(
            arguments={"query": ""}, principal=_READER
        )
        console = disclosure.inspect()
        return (bragi.data["bundles"], console["bundles"], console["mutation_controls"])

    before_bragi, before_console, mutation_controls = surfaces()
    before_rpc = (await _rpc(registry, "skill_bundles.list", query="")).result["bundles"]
    assert before_bragi == before_console == before_rpc
    assert [item["eligible"] for item in before_bragi] == [True]
    assert mutation_controls is False

    # A republished snapshot must move all three surfaces together; none of
    # them may keep answering from a catalog captured at construction time.
    disclosure.publish_bundle_snapshot(catalog=bundles.disable(_BUNDLE), verifier=_BundleVerifier())

    after_bragi, after_console, _ = surfaces()
    after_rpc = (await _rpc(registry, "skill_bundles.list", query="")).result["bundles"]
    assert after_bragi == after_console == after_rpc
    assert [item["eligible"] for item in after_bragi] == [False]

    rejected = LoadRuntimeSkillBundleTool(disclosure).call(
        arguments={"name": _BUNDLE}, principal=_READER
    )
    rpc_rejected = await _rpc(registry, "skill_bundles.load", name=_BUNDLE)
    assert rejected.data["error"]["reason"] == "skill_bundle_disabled"
    assert rpc_rejected.error_message == "skill_bundle_disabled"
