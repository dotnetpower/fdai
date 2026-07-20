"""Command Deck runtime skill resolver tests."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from fdai.core.skills import RuntimeSkill, RuntimeSkillDisclosure, SkillCatalog, skill_body_digest
from fdai.core.skills.bundle_catalog import SkillBundleCatalog
from fdai.core.skills.bundle_manifest import RuntimeSkillBundle, encode_skill_bundle_manifest
from fdai.delivery.read_api.read_model import InMemoryConsoleReadModel
from fdai.delivery.read_api.routes.chat_registration import append_chat_routes
from fdai.delivery.read_api.routes.chat_skills import RuntimeSkillChatTools
from fdai.delivery.read_api.routes.skills import RuntimeSkillsPanel


class _Verifier:
    def verify(self, skill: RuntimeSkill, raw_markdown: bytes) -> bool:
        return True


class _BundleVerifier:
    def verify(self, bundle: RuntimeSkillBundle, raw_manifest: bytes) -> bool:
        return bundle.raw_manifest == raw_manifest


class _Fallback:
    async def resolve(self, prompt: str, *, principal_id: str) -> dict[str, object]:
        return {"tool": "fallback", "prompt": prompt, "principal_id": principal_id}


class _RecordingBackend:
    def __init__(self) -> None:
        self.view_context: dict[str, Any] | None = None

    async def answer(
        self,
        *,
        prompt: str,
        view_context: dict[str, Any],
        history: list[dict[str, str]],
    ) -> dict[str, str]:
        del prompt, history
        self.view_context = view_context
        return {"answer": "inspected skill", "model": "test-narrator"}


async def _allow(_request: Request) -> str:
    return "reader-1"


def _disclosure(*, include_bundle: bool = False) -> RuntimeSkillDisclosure:
    body = "Complete trusted instructions."
    reference = b"complete reference"
    raw = f"""---
name: inventory-evidence
version: 1.0.0
description: Collect inventory evidence.
source: publisher.example
body_sha256: "{skill_body_digest(body)}"
required_tools: [query_inventory]
allowed_agents: [Bragi]
references:
  - path: references/guide.txt
    sha256: "{hashlib.sha256(reference).hexdigest()}"
    size_bytes: {len(reference)}
    media_type: text/plain
---
{body}
""".encode()
    verifier = _Verifier()
    catalog = (
        SkillCatalog()
        .install_bundle(raw, {"references/guide.txt": reference}, verifier=verifier)
        .enable(
            "inventory-evidence",
            available_tools=frozenset({"query_inventory"}),
            known_agents=frozenset({"Bragi"}),
        )
    )
    bundles = None
    bundle_verifier = None
    if include_bundle:
        bundle_verifier = _BundleVerifier()
        raw_bundle = encode_skill_bundle_manifest(
            {
                "name": "inventory-pack",
                "version": "1.0.0",
                "description": "Reviewed inventory evidence procedure.",
                "source": "publisher.example",
                "members": [{"name": "inventory-evidence", "version": "==1.0.0"}],
                "allowed_agents": ["Bragi"],
                "required_tools": ["query_inventory"],
                "instruction": "Use complete inventory evidence.",
            }
        )
        bundles = (
            SkillBundleCatalog()
            .install(raw_bundle, verifier=bundle_verifier)
            .enable(
                "inventory-pack",
                skills=catalog,
                bundle_verifier=bundle_verifier,
                skill_verifier=verifier,
                available_tools=frozenset({"query_inventory"}),
                known_agents=frozenset({"Bragi"}),
            )
        )
    return RuntimeSkillDisclosure(
        catalog=catalog,
        verifier=verifier,
        agent="Bragi",
        available_tools=frozenset({"query_inventory"}),
        bundle_catalog=bundles,
        bundle_verifier=bundle_verifier,
    )


async def test_calls_all_skill_tools_and_preserves_complete_content() -> None:
    resolver = RuntimeSkillChatTools(_disclosure())

    listed = await resolver.resolve("list_skills inventory limit=1", principal_id="reader-1")
    described = await resolver.resolve("describe_skill inventory-evidence", principal_id="reader-1")
    loaded = await resolver.resolve("load_skill inventory-evidence", principal_id="reader-1")
    reference = await resolver.resolve(
        "read_skill_reference inventory-evidence references/guide.txt",
        principal_id="reader-1",
    )

    assert listed is not None and listed["result"]["returned_count"] == 1
    assert described is not None and described["result"]["descriptor"]["version"] == "1.0.0"
    assert loaded is not None and loaded["result"]["body"] == "Complete trusted instructions.\n"
    assert reference is not None
    assert reference["result"]["content"]["data"] == "complete reference"
    assert all(
        result is not None and result["authority"] == "trusted_skill_catalog"
        for result in (listed, described, loaded, reference)
    )


async def test_invalid_skill_command_is_bounded_and_other_prompts_fall_back() -> None:
    resolver = RuntimeSkillChatTools(_disclosure(), fallback=_Fallback())

    invalid = await resolver.resolve("load_skill", principal_id="reader-1")
    fallback = await resolver.resolve("show KPI", principal_id="reader-1")

    assert invalid is not None
    assert invalid["result"] == {
        "error": {
            "code": "invalid_skill_tool_arguments",
            "message": "invalid arguments for load_skill",
        }
    }
    assert "Complete trusted instructions" not in repr(invalid)
    assert fallback == {
        "tool": "fallback",
        "prompt": "show KPI",
        "principal_id": "reader-1",
    }


async def test_skills_panel_is_metadata_only_and_has_no_mutation_controls() -> None:
    disclosure = _disclosure()
    await RuntimeSkillChatTools(disclosure).resolve(
        "load_skill inventory-evidence",
        principal_id="reader-1",
    )

    payload = await RuntimeSkillsPanel(disclosure).render(params={})

    assert payload["installed_count"] == 1
    assert payload["eligible_count"] == 1
    assert payload["skills"][0]["required_tools"] == ["query_inventory"]
    assert payload["skills"][0]["eligibility_reason"] == "eligible_pending_trust_recheck"
    assert payload["diagnostics"][-1]["operation"] == "load"
    assert payload["mutation_controls"] is False
    assert payload["execution_eligibility"] is False
    assert "Complete trusted instructions" not in repr(payload)
    assert "complete reference" not in repr(payload)


def test_chat_registration_calls_skill_disclosure_before_narrator() -> None:
    backend = _RecordingBackend()
    disclosure = _disclosure()
    routes: list[Any] = []
    append_chat_routes(
        routes,
        backend=backend,
        skill_disclosure=disclosure,
        agent_delegate=None,
        authorize=_allow,
        read_model=InMemoryConsoleReadModel(),
        core_paths=(),
        panel_paths=(),
        logger=logging.getLogger("fdai.tests.skill-chat"),
    )

    response = TestClient(Starlette(routes=routes)).post(
        "/chat",
        json={"prompt": "load_skill inventory-evidence"},
    )

    assert response.status_code == 200
    assert response.json()["model"] == "test-narrator"
    assert backend.view_context is not None
    evidence = backend.view_context["_tool_evidence"]
    assert evidence["tool"] == "load_skill"
    assert evidence["result"]["body"] == "Complete trusted instructions.\n"
    assert disclosure.diagnostics()[-1]["operation"] == "load"
    assert disclosure.diagnostics()[-1]["status"] == "selected"


def test_chat_registration_loads_complete_governed_bundle_before_narrator() -> None:
    backend = _RecordingBackend()
    disclosure = _disclosure(include_bundle=True)
    routes: list[Any] = []
    append_chat_routes(
        routes,
        backend=backend,
        skill_disclosure=disclosure,
        agent_delegate=None,
        authorize=_allow,
        read_model=InMemoryConsoleReadModel(),
        core_paths=(),
        panel_paths=(),
        logger=logging.getLogger("fdai.tests.skill-bundle-chat"),
    )

    response = TestClient(Starlette(routes=routes)).post(
        "/chat",
        json={"prompt": "load_skill_bundle inventory-pack"},
    )

    assert response.status_code == 200
    assert response.json()["model"] == "test-narrator"
    assert backend.view_context is not None
    evidence = backend.view_context["_tool_evidence"]
    assert evidence["tool"] == "load_skill_bundle"
    assert evidence["result"]["instruction"] == "Use complete inventory evidence."
    assert evidence["result"]["members"][0]["body"] == "Complete trusted instructions.\n"
    assert disclosure.diagnostics()[-1]["operation"] == "load_bundle"
    assert disclosure.diagnostics()[-1]["status"] == "selected"
