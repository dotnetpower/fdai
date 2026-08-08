"""Read-only channel runtime skill disclosure tests."""

from __future__ import annotations

import hashlib

from fdai.core.conversation import (
    DescribeRuntimeSkillTool,
    ListRuntimeSkillsTool,
    LoadRuntimeSkillTool,
    Principal,
    ReadRuntimeSkillReferenceTool,
    Role,
)
from fdai.core.skills import RuntimeSkill, RuntimeSkillDisclosure, SkillCatalog, skill_body_digest


class _Verifier:
    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return True


def _raw_skill(name: str, *, content: bytes = b"reference text") -> bytes:
    body = f"private body for {name}"
    return f"""---
name: {name}
version: 1.0.0
description: Evidence for {name}.
source: source:{name}
body_sha256: "{skill_body_digest(body)}"
required_tools: [query_inventory]
allowed_agents: [Bragi]
references:
  - path: references/guide.bin
    sha256: "{hashlib.sha256(content).hexdigest()}"
    size_bytes: {len(content)}
    media_type: application/octet-stream
---
{body}
""".encode()


def _catalog() -> SkillCatalog:
    verifier = _Verifier()
    catalog = SkillCatalog()
    for name in ("alpha-evidence", "beta-evidence"):
        catalog = catalog.install_bundle(
            _raw_skill(name),
            {"references/guide.bin": b"reference text"},
            verifier=verifier,
        ).enable(
            name,
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )
    return catalog


def test_reader_lists_describes_loads_and_reads_without_changing_enablement() -> None:
    catalog = _catalog()
    disclosure = RuntimeSkillDisclosure(
        catalog=catalog,
        verifier=_Verifier(),
        agent="Bragi",
        available_tools=frozenset({"query_inventory"}),
    )
    principal = Principal(id="reader-1", role=Role.READER)
    before = tuple(skill.enabled for skill in catalog.list())

    listed = ListRuntimeSkillsTool(disclosure).call(
        arguments={"query": "evidence", "limit": 1},
        principal=principal,
    )
    described = DescribeRuntimeSkillTool(disclosure).call(
        arguments={"name": "alpha-evidence"}, principal=principal
    )
    loaded = LoadRuntimeSkillTool(disclosure).call(
        arguments={"name": "alpha-evidence"}, principal=principal
    )
    reference = ReadRuntimeSkillReferenceTool(disclosure).call(
        arguments={"name": "alpha-evidence", "path": "references/guide.bin"},
        principal=principal,
    )

    assert [entry["descriptor"]["name"] for entry in listed.data["entries"]] == ["alpha-evidence"]
    assert described.data["descriptor"]["name"] == "alpha-evidence"
    assert loaded.data["body"] == "private body for alpha-evidence\n"
    assert reference.data["content"]["encoding"] == "utf-8"
    assert tuple(skill.enabled for skill in catalog.list()) == before
    tools = (
        ListRuntimeSkillsTool(disclosure),
        DescribeRuntimeSkillTool(disclosure),
        LoadRuntimeSkillTool(disclosure),
        ReadRuntimeSkillReferenceTool(disclosure),
    )
    assert all(tool.rbac_floor is Role.READER for tool in tools)
    assert all(tool.side_effect_class == "read" for tool in tools)


def test_ineligible_load_returns_stable_error_without_body_leakage() -> None:
    disclosure = RuntimeSkillDisclosure(
        catalog=_catalog(),
        verifier=_Verifier(),
        agent="Saga",
        available_tools=frozenset({"query_inventory"}),
    )

    result = LoadRuntimeSkillTool(disclosure).call(
        arguments={"name": "alpha-evidence"},
        principal=Principal(id="reader-1", role=Role.READER),
    )

    assert result.status == "error"
    assert result.data["error"] == {
        "code": "skill_access_rejected",
        "reason": "skill_agent_not_allowed",
    }
    assert "private body" not in repr(result)
    diagnostic = disclosure.diagnostics()[-1]
    assert diagnostic["status"] == "rejected"
    assert "private body for alpha-evidence" not in repr(diagnostic)
