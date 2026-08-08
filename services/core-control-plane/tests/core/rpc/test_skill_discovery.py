"""Typed RPC runtime skill disclosure tests."""

from __future__ import annotations

import base64
import hashlib

from fdai.core.rpc import RpcRegistry, RpcRequest, RpcScope, skill_discovery_rpc_methods
from fdai.core.skills import RuntimeSkill, RuntimeSkillDisclosure, SkillCatalog, skill_body_digest


class _Verifier:
    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return True


def _disclosure(*, agent: str = "Bragi") -> RuntimeSkillDisclosure:
    content = b"\x00\xffbinary"
    body = "private skill body"
    raw = f"""---
name: binary-evidence
version: 1.0.0
description: Binary evidence.
source: source:binary-evidence
body_sha256: "{skill_body_digest(body)}"
required_tools: [query_inventory]
allowed_agents: [Bragi]
references:
  - path: references/data.bin
    sha256: "{hashlib.sha256(content).hexdigest()}"
    size_bytes: {len(content)}
    media_type: application/octet-stream
---
{body}
""".encode()
    catalog = (
        SkillCatalog()
        .install_bundle(raw, {"references/data.bin": content}, verifier=_Verifier())
        .enable(
            "binary-evidence",
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )
    )
    return RuntimeSkillDisclosure(
        catalog=catalog,
        verifier=_Verifier(),
        agent=agent,
        available_tools=frozenset({"query_inventory"}),
    )


def _registry(disclosure: RuntimeSkillDisclosure) -> RpcRegistry:
    registry = RpcRegistry()
    for method in skill_discovery_rpc_methods(disclosure):
        registry = registry.register(method)
    return registry


async def test_skill_methods_are_read_scoped_and_reference_is_lossless_base64() -> None:
    disclosure = _disclosure()
    registry = _registry(disclosure)

    discovered = registry.discover(frozenset({RpcScope.READ}))
    response = await registry.invoke(
        RpcRequest(
            request_id="r1",
            method="skills.read_reference",
            params={"name": "binary-evidence", "path": "references/data.bin"},
        ),
        scopes=frozenset({RpcScope.READ}),
    )

    assert {method["name"] for method in discovered} == {
        "skill_bundles.describe",
        "skill_bundles.list",
        "skill_bundles.load",
        "skills.describe",
        "skills.diagnostics",
        "skills.list",
        "skills.load",
        "skills.read_reference",
    }
    assert all(method["required_scope"] == RpcScope.READ.value for method in discovered)
    assert response.ok is True
    encoded = response.result["content"]
    assert encoded["encoding"] == "base64"
    assert base64.b64decode(encoded["data"]) == b"\x00\xffbinary"
    assert encoded["media_type"] == "application/octet-stream"
    assert encoded["sha256"] == hashlib.sha256(b"\x00\xffbinary").hexdigest()


async def test_rpc_rejection_and_invalid_params_use_stable_errors_without_content() -> None:
    disclosure = _disclosure(agent="Saga")
    registry = _registry(disclosure)

    rejected = await registry.invoke(
        RpcRequest(
            request_id="r1",
            method="skills.load",
            params={"name": "binary-evidence"},
        ),
        scopes=frozenset({RpcScope.READ}),
    )
    invalid = await registry.invoke(
        RpcRequest(
            request_id="r2",
            method="skills.list",
            params={"query": "evidence", "unexpected": True},
        ),
        scopes=frozenset({RpcScope.READ}),
    )
    diagnostics = await registry.invoke(
        RpcRequest(request_id="r3", method="skills.diagnostics", params={}),
        scopes=frozenset({RpcScope.READ}),
    )

    assert rejected.error_code == "skill_access_rejected"
    assert rejected.error_message == "skill_agent_not_allowed"
    assert "private skill body" not in repr(rejected)
    assert invalid.error_code == "invalid_params"
    assert diagnostics.ok is True
    assert diagnostics.result["diagnostics"][-1]["status"] == "rejected"
    assert "private skill body" not in repr(diagnostics.result)
