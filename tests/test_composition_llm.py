"""Composition-root LLM wiring - local-fake vs azure."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from fdai.composition import (
    LlmBindings,
    LlmBindingsUnavailableError,
    bind_azure_llm_bindings,
    default_container,
    install_capability_bundle,
)
from fdai.shared.config import AppConfig
from fdai.shared.config.models import LlmMode
from fdai.shared.providers.workload_identity import (
    IdentityToken,
    WorkloadIdentity,
)

# Non-empty placeholder for the required Wave 2 ``system_prompt`` argument.
# The real prompt is composed from ``rule-catalog/prompts/`` via the
# PromptComposer; these tests only care that the wiring threads it through.
_TEST_SYSTEM_PROMPT = "unit-test system prompt"


def _config(
    *,
    mode: str = LlmMode.LOCAL_FAKE,
    resolved_path: str | None = None,
    t2_primary_latency_routing: bool = False,
) -> AppConfig:
    llm: dict[str, Any] = {"mode": mode}
    if resolved_path is not None:
        llm["resolved_models_path"] = resolved_path
    # Set explicitly (both True and False) so tests stay deterministic
    # regardless of the model-level default.
    llm["t2_primary_latency_routing"] = t2_primary_latency_routing
    return AppConfig.model_validate(
        {
            "schema_version": "1.0.0",
            "azure": {
                "tenant_id": "00000000-0000-0000-0000-000000000000",
                "subscription_id": "00000000-0000-0000-0000-000000000000",
                "region": "krc",
            },
            "kafka": {
                "bootstrap_servers": "example:9093",
                "topic_events": "aw.change.events",
            },
            "postgres": {"host": "example.local", "database": "fdai"},
            "runtime": {"env": "dev"},
            "llm": llm,
        }
    )


def test_install_capability_bundle_is_public_and_immutable() -> None:
    from fdai.core.capability_catalog import (
        Capability,
        CapabilityBinding,
        CapabilityBindingKind,
        CapabilityBundle,
        CapabilityCategory,
        SideEffectClass,
    )
    from fdai.core.prompts.types import PromptMode
    from fdai.core.tools import CapabilityGate, ToolArtifact
    from fdai.core.tools.testing import InMemoryToolProvider

    container = default_container(_config())
    provider = InMemoryToolProvider()
    artifact = ToolArtifact(
        id="fork.query",
        version=1,
        description="Read fork data.",
        input_schema={"type": "object"},
        capability_gate=CapabilityGate(None, None, 0.0),
        allowlist=None,
        output_wrapper=None,
        default_mode=PromptMode.SHADOW,
        provider="ForkQueryProvider",
        provenance_source="fork",
    )
    bundle = CapabilityBundle(
        capabilities=(
            Capability(
                capability_id="fork.query",
                name="Fork query",
                category=CapabilityCategory.INVESTIGATION,
                summary="Read fork-owned data.",
                side_effect_class=SideEffectClass.READ,
            ),
        ),
        bindings=(
            CapabilityBinding(
                capability_id="fork.query",
                kind=CapabilityBindingKind.REASONING_TOOL,
                target_ref="fork.query",
                provider_id="ForkQueryProvider",
            ),
        ),
        tool_providers={"ForkQueryProvider": provider},
    )

    installed = install_capability_bundle(
        container,
        bundle,
        reasoning_tools=(artifact,),
    )

    assert container.capability_runtime.bound_capability_ids() == ()
    assert installed.capability_runtime.resolve("fork.query").provider is provider
    assert installed.capability_runtime.catalog.get("knowledge.register") is not None


class _StaticIdentity(WorkloadIdentity):
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="test-token",
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
            audience=audience,
        )


# ---------------------------------------------------------------------------
# local-fake path
# ---------------------------------------------------------------------------


def test_local_fake_mode_binds_deterministic_fakes() -> None:
    container = default_container(_config(mode=LlmMode.LOCAL_FAKE))
    bindings = container.require_llm_bindings()
    assert isinstance(bindings, LlmBindings)
    assert bindings.embedding_model is not None
    assert bindings.embedding_model.dim == 384
    # Two fake cross-check models so the quality-gate default quorum (2) works.
    assert len(bindings.cross_check_models) == 2
    assert bindings.require_t2_proposer() is not None


def test_local_fake_container_never_imports_delivery_azure_llm() -> None:
    """The local-fake path MUST not pull the AOAI adapters into memory."""
    import sys

    # Purge cached modules first (safe: we re-import as needed).
    for mod in list(sys.modules):
        if mod.startswith("fdai.delivery.azure.llm"):
            sys.modules.pop(mod, None)
    default_container(_config(mode=LlmMode.LOCAL_FAKE))
    assert "fdai.delivery.azure.llm" not in sys.modules
    assert "fdai.delivery.azure.llm.embeddings" not in sys.modules
    assert "fdai.delivery.azure.llm.cross_check" not in sys.modules


# ---------------------------------------------------------------------------
# azure path
# ---------------------------------------------------------------------------


def _resolved_models_json() -> str:
    return """{
  "schema_version": "1.0.0",
  "region": "koreacentral",
  "subscription_id": "00000000-0000-0000-0000-000000000000",
  "deployer_object_id": "00000000-0000-0000-0000-000000000001",
  "mixed_model_mode": "azure-foundry",
  "capabilities": [
    {"name": "t1.embedding", "status": "resolved", "publisher": "OpenAI",
     "family": "text-embedding-3-small", "sku": "Standard",
     "capacity_tpm": 100000, "invocation": "always", "reasons": []},
    {"name": "t2.reasoner.primary", "status": "resolved", "publisher": "OpenAI",
     "family": "gpt-4o", "sku": "Standard",
     "capacity_tpm": 20000, "invocation": "always", "reasons": []},
    {"name": "t2.reasoner.secondary", "status": "resolved",
     "publisher": "Anthropic", "family": "claude-opus-4", "sku": "Standard",
     "capacity_tpm": 10000, "invocation": "always", "reasons": []}
  ]
}
"""


def test_azure_mode_container_is_unbound_until_finalized(tmp_path: Path) -> None:
    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    assert container.llm_bindings is None
    with pytest.raises(LlmBindingsUnavailableError, match="bind_azure_llm_bindings"):
        container.require_llm_bindings()


def test_bind_azure_llm_bindings_attaches_adapters(tmp_path: Path) -> None:
    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = bind_azure_llm_bindings(
        container,
        identity=_StaticIdentity(),
        http_client=http,
        endpoint="https://oai-test.openai.azure.com",
        system_prompt=_TEST_SYSTEM_PROMPT,
    )
    bindings = finalized.require_llm_bindings()
    assert bindings.embedding_model is not None
    assert len(bindings.cross_check_models) == 2


def _resolved_models_json_with_endpoint_bindings() -> str:
    payload = json.loads(_resolved_models_json())
    observed_at = "2026-07-17T00:00:00+00:00"

    def binding(
        capability: str,
        *,
        deployment: str,
        publisher: str,
        family: str,
        provider_kind: str,
        capacity_unit: str,
        capacity_value: int,
        embeddings: bool = False,
    ) -> dict[str, Any]:
        return {
            "binding_id": capability.replace(".", "-") + "-prod",
            "capability": capability,
            "provider_kind": provider_kind,
            "route_kind": "apim-gateway",
            "api_style": "openai-v1",
            "endpoint_ref": capability.replace(".", "-"),
            "deployment": deployment,
            "api_version": None,
            "auth": {"kind": "entra", "audience": "api://fdai-model-gateway"},
            "model": {"publisher": publisher, "family": family, "version": None},
            "capacity": {"unit": capacity_unit, "value": capacity_value},
            "features": {
                "streaming": True,
                "embeddings": embeddings,
                "structured_output": not embeddings,
                "tool_calling": not embeddings,
            },
            "discovery": {
                "source": (
                    "signed-registration" if provider_kind == "self-hosted" else "apim-management"
                ),
                "resource_ref_digest": "a" * 64,
                "verified_at": observed_at,
            },
        }

    payload["endpoint_bindings"] = [
        binding(
            "t1.embedding",
            deployment="embedding-model",
            publisher="OpenAI",
            family="text-embedding-3-small",
            provider_kind="azure-openai",
            capacity_unit="tpm",
            capacity_value=100_000,
            embeddings=True,
        ),
        binding(
            "t2.reasoner.primary",
            deployment="primary-model",
            publisher="OpenAI",
            family="gpt-4o",
            provider_kind="azure-openai",
            capacity_unit="ptu",
            capacity_value=30,
        ),
        binding(
            "t2.reasoner.secondary",
            deployment="secondary-model",
            publisher="Anthropic",
            family="claude-opus-4",
            provider_kind="self-hosted",
            capacity_unit="gpu",
            capacity_value=2,
        ),
    ]
    return json.dumps(payload)


class _RecordingIdentity(WorkloadIdentity):
    def __init__(self) -> None:
        self.audiences: list[str] = []

    async def get_token(self, audience: str) -> IdentityToken:
        self.audiences.append(audience)
        return IdentityToken(
            token="test-token",
            expires_at=datetime.now(tz=UTC) + timedelta(minutes=10),
            audience=audience,
        )


async def test_endpoint_bindings_drive_apim_openai_v1_runtime(tmp_path: Path) -> None:
    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json_with_endpoint_bindings(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"embedding": [0.1] * 384}]})
        return httpx.Response(
            200,
            headers={
                "x-fdai-model-backend": "primary-ptu",
                "x-fdai-capacity-unit": "ptu",
                "x-fdai-spillover": "false",
            },
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"action_type": "remediate.tag-add", "params": {}}
                            )
                        }
                    }
                ]
            },
        )

    identity = _RecordingIdentity()
    from fdai.delivery.azure.llm.latency_routed_cross_check import (
        InMemoryModelHealthTransitionSink,
    )

    route_sink = InMemoryModelHealthTransitionSink()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        finalized = bind_azure_llm_bindings(
            container,
            identity=identity,
            http_client=http,
            endpoint="https://legacy.example.com",
            endpoint_resolver=lambda _ref: "https://models.example.com",
            system_prompt=_TEST_SYSTEM_PROMPT,
            model_health_sink=route_sink,
        )
        bindings = finalized.require_llm_bindings()
        await bindings.embedding_model.embed("hello")
        from fdai.core.quality_gate.gate import QualityCandidate

        await bindings.cross_check_models[0].propose(
            QualityCandidate(
                action_type="remediate.tag-add",
                target_resource_ref="resource:example/one",
                params={},
                cited_rule_ids=("rule.one",),
            )
        )

    assert [request.url.path for request in requests] == [
        "/v1/embeddings",
        "/v1/chat/completions",
    ]
    assert all(request.url.host == "models.example.com" for request in requests)
    assert identity.audiences == [
        "api://fdai-model-gateway",
        "api://fdai-model-gateway",
    ]
    assert route_sink.transitions[0].deployment == "primary-ptu"
    assert "spillover=false" in route_sink.transitions[0].reason


def test_endpoint_bindings_require_reference_resolver(tmp_path: Path) -> None:
    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json_with_endpoint_bindings(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))

    with pytest.raises(LlmBindingsUnavailableError, match="endpoint_ref resolver"):
        bind_azure_llm_bindings(
            container,
            identity=_StaticIdentity(),
            http_client=httpx.AsyncClient(),
            endpoint="https://legacy.example.com",
            system_prompt=_TEST_SYSTEM_PROMPT,
        )


def test_bind_accepts_inline_json_in_resolved_models_path() -> None:
    """Container Apps secret refs may deliver the resolver output as an
    env var - the composition MUST accept the JSON document inline, not
    just a filesystem path."""
    container = default_container(
        _config(mode=LlmMode.AZURE, resolved_path=_resolved_models_json())
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = bind_azure_llm_bindings(
        container,
        identity=_StaticIdentity(),
        http_client=http,
        endpoint="https://oai-test.openai.azure.com",
        system_prompt=_TEST_SYSTEM_PROMPT,
    )
    bindings = finalized.require_llm_bindings()
    assert bindings.embedding_model is not None
    assert len(bindings.cross_check_models) == 2


def test_bind_rejects_non_azure_mode() -> None:
    container = default_container(_config(mode=LlmMode.LOCAL_FAKE))
    http = httpx.AsyncClient()
    with pytest.raises(ValueError, match="llm.mode"):
        bind_azure_llm_bindings(
            container,
            identity=_StaticIdentity(),
            http_client=http,
            endpoint="https://x",
            system_prompt=_TEST_SYSTEM_PROMPT,
        )


def test_bind_rejects_missing_resolved_file(tmp_path: Path) -> None:
    container = default_container(
        _config(mode=LlmMode.AZURE, resolved_path=str(tmp_path / "missing.json"))
    )
    http = httpx.AsyncClient()
    with pytest.raises(LlmBindingsUnavailableError, match="not found"):
        bind_azure_llm_bindings(
            container,
            identity=_StaticIdentity(),
            http_client=http,
            endpoint="https://x",
            system_prompt=_TEST_SYSTEM_PROMPT,
        )


def test_bind_rejects_hil_only_embedding(tmp_path: Path) -> None:
    resolved = tmp_path / "resolved-models.json"
    payload = _resolved_models_json().replace(
        '"t1.embedding", "status": "resolved"',
        '"t1.embedding", "status": "hil-only"',
    )
    resolved.write_text(payload, encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient()
    with pytest.raises(LlmBindingsUnavailableError, match="t1.embedding"):
        bind_azure_llm_bindings(
            container,
            identity=_StaticIdentity(),
            http_client=http,
            endpoint="https://oai-test",
            system_prompt=_TEST_SYSTEM_PROMPT,
        )


def test_bind_rejects_hil_only_reasoner(tmp_path: Path) -> None:
    resolved = tmp_path / "resolved-models.json"
    payload = _resolved_models_json().replace(
        '"t2.reasoner.secondary", "status": "resolved"',
        '"t2.reasoner.secondary", "status": "hil-only"',
    )
    resolved.write_text(payload, encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient()
    with pytest.raises(LlmBindingsUnavailableError, match="T2 reasoner"):
        bind_azure_llm_bindings(
            container,
            identity=_StaticIdentity(),
            http_client=http,
            endpoint="https://oai-test",
            system_prompt=_TEST_SYSTEM_PROMPT,
        )


def test_bind_hil_only_mode_uses_disagree_fake_for_secondary(tmp_path: Path) -> None:
    """`mixed_model_mode='hil-only'` MUST bind cleanly with an
    always-disagree fake as the secondary, so every T2 quality-gate
    call resolves to DISAGREE and routes to HIL by design."""
    from fdai.core.quality_gate.testing import MismatchCrossCheckModel

    resolved = tmp_path / "resolved-models.json"
    payload = (
        _resolved_models_json()
        .replace('"mixed_model_mode": "azure-foundry"', '"mixed_model_mode": "hil-only"')
        .replace(
            '"t2.reasoner.secondary", "status": "resolved"',
            '"t2.reasoner.secondary", "status": "hil-only"',
        )
    )
    resolved.write_text(payload, encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = bind_azure_llm_bindings(
        container,
        identity=_StaticIdentity(),
        http_client=http,
        endpoint="https://oai-test.openai.azure.com",
        system_prompt=_TEST_SYSTEM_PROMPT,
    )
    bindings = finalized.require_llm_bindings()
    assert len(bindings.cross_check_models) == 2
    # Second model is the deterministic disagree fake so quorum can never form.
    assert isinstance(bindings.cross_check_models[1], MismatchCrossCheckModel)


def test_bind_rejects_empty_system_prompt(tmp_path: Path) -> None:
    """Wave 2 requires a composed prompt; a bare empty string means the
    entry point forgot to invoke PromptComposer and MUST fail fast."""

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient()
    with pytest.raises(ValueError, match="system_prompt"):
        bind_azure_llm_bindings(
            container,
            identity=_StaticIdentity(),
            http_client=http,
            endpoint="https://oai-test.openai.azure.com",
            system_prompt="",
        )


# ---------------------------------------------------------------------------
# Wave 3 step C-2: per-event composer threaded to both T2 reasoners
# ---------------------------------------------------------------------------


def test_bind_forwards_composer_and_capability_id_to_both_reasoners(
    tmp_path: Path,
) -> None:
    """When ``prompt_composer`` is supplied, both T2 reasoners MUST be
    constructed with their role-specific capability id so cross-check
    sees consistent instruction context per role, not a shared prompt.
    """

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))

    class _Sentinel:
        async def compose(
            self, *, capability_id: str, scope: object = None
        ) -> object:  # pragma: no cover - never awaited in this test
            raise AssertionError("not used")

    composer = _Sentinel()
    finalized = bind_azure_llm_bindings(
        container,
        identity=_StaticIdentity(),
        http_client=http,
        endpoint="https://oai-test.openai.azure.com",
        system_prompt=_TEST_SYSTEM_PROMPT,
        prompt_composer=composer,
    )
    bindings = finalized.require_llm_bindings()
    primary, secondary = bindings.cross_check_models
    # Narrow to the concrete adapter for private-attribute inspection.
    from fdai.delivery.azure.llm.cross_check import AzureOpenAICrossCheckModel

    assert isinstance(primary, AzureOpenAICrossCheckModel)
    assert isinstance(secondary, AzureOpenAICrossCheckModel)
    # The composer must be the same object for both reasoners.
    assert primary._prompt_composer is composer
    assert secondary._prompt_composer is composer
    # Capability ids differ per role (primary vs secondary).
    assert primary._capability_id == "t2.reasoner.primary"
    assert secondary._capability_id == "t2.reasoner.secondary"
    # ``scope_resolver`` stays None upstream (fork-only).
    assert primary._scope_resolver is None
    assert secondary._scope_resolver is None


def test_bind_omits_composer_wiring_when_not_supplied(tmp_path: Path) -> None:
    """Backwards compat: no composer -> both reasoners fall back to
    ``system_prompt`` and carry no capability id / scope resolver."""

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = bind_azure_llm_bindings(
        container,
        identity=_StaticIdentity(),
        http_client=http,
        endpoint="https://oai-test.openai.azure.com",
        system_prompt=_TEST_SYSTEM_PROMPT,
    )
    primary, secondary = finalized.require_llm_bindings().cross_check_models
    from fdai.delivery.azure.llm.cross_check import AzureOpenAICrossCheckModel

    assert isinstance(primary, AzureOpenAICrossCheckModel)
    assert isinstance(secondary, AzureOpenAICrossCheckModel)
    assert primary._prompt_composer is None
    assert secondary._prompt_composer is None
    assert primary._capability_id is None
    assert secondary._capability_id is None


# ---------------------------------------------------------------------------
# Wave 4 beta-2: Critic binding is opt-in (capability + system prompt)
# ---------------------------------------------------------------------------


def _resolved_models_json_with_critic() -> str:
    """The upstream ``rule-catalog/llm-registry.yaml`` now declares a
    ``t2.critic`` capability; the resolver output has to include a
    matching entry when the region can provide it."""

    return """{
  "schema_version": "1.0.0",
  "region": "koreacentral",
  "subscription_id": "00000000-0000-0000-0000-000000000000",
  "deployer_object_id": "00000000-0000-0000-0000-000000000001",
  "mixed_model_mode": "azure-foundry",
  "capabilities": [
    {"name": "t1.embedding", "status": "resolved", "publisher": "OpenAI",
     "family": "text-embedding-3-small", "sku": "Standard",
     "capacity_tpm": 100000, "invocation": "always", "reasons": []},
    {"name": "t2.reasoner.primary", "status": "resolved", "publisher": "OpenAI",
     "family": "gpt-4o", "sku": "Standard",
     "capacity_tpm": 20000, "invocation": "always", "reasons": []},
    {"name": "t2.reasoner.secondary", "status": "resolved",
     "publisher": "Anthropic", "family": "claude-opus-4", "sku": "Standard",
     "capacity_tpm": 10000, "invocation": "always", "reasons": []},
    {"name": "t2.critic", "status": "resolved",
     "publisher": "Anthropic", "family": "claude-opus-4", "sku": "Standard",
     "capacity_tpm": 5000, "invocation": "on_disagreement", "reasons": []}
  ]
}
"""


def test_bind_wires_critic_when_capability_resolves_and_prompt_supplied(
    tmp_path: Path,
) -> None:
    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json_with_critic(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = bind_azure_llm_bindings(
        container,
        identity=_StaticIdentity(),
        http_client=http,
        endpoint="https://oai-test.openai.azure.com",
        system_prompt=_TEST_SYSTEM_PROMPT,
        critic_system_prompt="unit-test critic system prompt",
    )
    bindings = finalized.require_llm_bindings()
    from fdai.delivery.azure.llm.critic import AzureOpenAICriticModel

    assert isinstance(bindings.critic_model, AzureOpenAICriticModel)


def test_bind_leaves_critic_none_when_capability_missing(tmp_path: Path) -> None:
    """Baseline resolver output (no ``t2.critic``) MUST NOT bind a
    critic even when the caller supplies a prompt - the capability
    absence is the authoritative opt-out signal."""

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = bind_azure_llm_bindings(
        container,
        identity=_StaticIdentity(),
        http_client=http,
        endpoint="https://oai-test.openai.azure.com",
        system_prompt=_TEST_SYSTEM_PROMPT,
        critic_system_prompt="unit-test critic system prompt",
    )
    assert finalized.require_llm_bindings().critic_model is None


def test_bind_leaves_critic_none_when_prompt_missing(tmp_path: Path) -> None:
    """Capability resolved but no prompt supplied -> no critic. This
    lets a fork that ships the capability but hasn't authored a critic
    prompt yet still boot cleanly."""

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json_with_critic(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = bind_azure_llm_bindings(
        container,
        identity=_StaticIdentity(),
        http_client=http,
        endpoint="https://oai-test.openai.azure.com",
        system_prompt=_TEST_SYSTEM_PROMPT,
        # critic_system_prompt omitted
    )
    assert finalized.require_llm_bindings().critic_model is None


# ---------------------------------------------------------------------------
# Wave 4.5 delta-1: Judge + DebateOrchestrator opt-in (4-way matrix)
# ---------------------------------------------------------------------------


def _resolved_models_json_with_debate() -> str:
    """Resolver output where BOTH ``t2.critic`` and ``t1.judge``
    resolve. Debate orchestrator should auto-construct when both
    role system prompts are supplied."""

    return """{
  "schema_version": "1.0.0",
  "region": "koreacentral",
  "subscription_id": "00000000-0000-0000-0000-000000000000",
  "deployer_object_id": "00000000-0000-0000-0000-000000000001",
  "mixed_model_mode": "azure-foundry",
  "capabilities": [
    {"name": "t1.embedding", "status": "resolved", "publisher": "OpenAI",
     "family": "text-embedding-3-small", "sku": "Standard",
     "capacity_tpm": 100000, "invocation": "always", "reasons": []},
    {"name": "t1.judge", "status": "resolved", "publisher": "OpenAI",
     "family": "gpt-4o-mini", "sku": "Standard",
     "capacity_tpm": 40000, "invocation": "always", "reasons": []},
    {"name": "t2.reasoner.primary", "status": "resolved", "publisher": "OpenAI",
     "family": "gpt-4o", "sku": "Standard",
     "capacity_tpm": 20000, "invocation": "always", "reasons": []},
    {"name": "t2.reasoner.secondary", "status": "resolved",
     "publisher": "Anthropic", "family": "claude-opus-4", "sku": "Standard",
     "capacity_tpm": 10000, "invocation": "always", "reasons": []},
    {"name": "t2.critic", "status": "resolved",
     "publisher": "Anthropic", "family": "claude-opus-4", "sku": "Standard",
     "capacity_tpm": 5000, "invocation": "on_disagreement", "reasons": []}
  ]
}
"""


def _resolved_models_json_with_judge_only() -> str:
    """Judge capability resolves, Critic does not. Debate orchestrator
    MUST stay None even when both prompts are supplied - the
    orchestrator needs both role models."""

    return """{
  "schema_version": "1.0.0",
  "region": "koreacentral",
  "subscription_id": "00000000-0000-0000-0000-000000000000",
  "deployer_object_id": "00000000-0000-0000-0000-000000000001",
  "mixed_model_mode": "azure-foundry",
  "capabilities": [
    {"name": "t1.embedding", "status": "resolved", "publisher": "OpenAI",
     "family": "text-embedding-3-small", "sku": "Standard",
     "capacity_tpm": 100000, "invocation": "always", "reasons": []},
    {"name": "t1.judge", "status": "resolved", "publisher": "OpenAI",
     "family": "gpt-4o-mini", "sku": "Standard",
     "capacity_tpm": 40000, "invocation": "always", "reasons": []},
    {"name": "t2.reasoner.primary", "status": "resolved", "publisher": "OpenAI",
     "family": "gpt-4o", "sku": "Standard",
     "capacity_tpm": 20000, "invocation": "always", "reasons": []},
    {"name": "t2.reasoner.secondary", "status": "resolved",
     "publisher": "Anthropic", "family": "claude-opus-4", "sku": "Standard",
     "capacity_tpm": 10000, "invocation": "always", "reasons": []}
  ]
}
"""


def test_debate_orchestrator_auto_constructs_when_both_capabilities_and_prompts(
    tmp_path: Path,
) -> None:
    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json_with_debate(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = bind_azure_llm_bindings(
        container,
        identity=_StaticIdentity(),
        http_client=http,
        endpoint="https://oai-test.openai.azure.com",
        system_prompt=_TEST_SYSTEM_PROMPT,
        critic_system_prompt="unit-test critic",
        judge_system_prompt="unit-test judge",
    )
    bindings = finalized.require_llm_bindings()
    from fdai.core.quality_gate.debate import DebateOrchestrator
    from fdai.delivery.azure.llm.critic import AzureOpenAICriticModel
    from fdai.delivery.azure.llm.judge import AzureOpenAIJudgeModel

    assert isinstance(bindings.critic_model, AzureOpenAICriticModel)
    assert isinstance(bindings.judge_model, AzureOpenAIJudgeModel)
    assert isinstance(bindings.debate_orchestrator, DebateOrchestrator)


def test_debate_orchestrator_is_none_when_critic_missing(tmp_path: Path) -> None:
    """Judge capability + judge prompt supplied, but no critic capability.
    Debate orchestrator MUST stay None; a fork that wired only one role
    keeps the pre-Wave-4.5 shape."""

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json_with_judge_only(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = bind_azure_llm_bindings(
        container,
        identity=_StaticIdentity(),
        http_client=http,
        endpoint="https://oai-test.openai.azure.com",
        system_prompt=_TEST_SYSTEM_PROMPT,
        critic_system_prompt="unit-test critic",  # supplied but capability absent
        judge_system_prompt="unit-test judge",
    )
    bindings = finalized.require_llm_bindings()
    assert bindings.critic_model is None
    assert bindings.judge_model is not None
    assert bindings.debate_orchestrator is None


def test_debate_orchestrator_is_none_when_judge_missing(tmp_path: Path) -> None:
    """Critic capability + critic prompt supplied, but no judge
    capability. Debate orchestrator MUST stay None."""

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json_with_critic(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = bind_azure_llm_bindings(
        container,
        identity=_StaticIdentity(),
        http_client=http,
        endpoint="https://oai-test.openai.azure.com",
        system_prompt=_TEST_SYSTEM_PROMPT,
        critic_system_prompt="unit-test critic",
        judge_system_prompt="unit-test judge",  # supplied but capability absent
    )
    bindings = finalized.require_llm_bindings()
    assert bindings.critic_model is not None
    assert bindings.judge_model is None
    assert bindings.debate_orchestrator is None


def test_debate_orchestrator_is_none_when_judge_prompt_missing(tmp_path: Path) -> None:
    """Both capabilities resolve but ``judge_system_prompt`` is omitted -
    Judge stays unbound and the orchestrator degrades to None."""

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json_with_debate(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = bind_azure_llm_bindings(
        container,
        identity=_StaticIdentity(),
        http_client=http,
        endpoint="https://oai-test.openai.azure.com",
        system_prompt=_TEST_SYSTEM_PROMPT,
        critic_system_prompt="unit-test critic",
        # judge_system_prompt omitted
    )
    bindings = finalized.require_llm_bindings()
    assert bindings.critic_model is not None
    assert bindings.judge_model is None
    assert bindings.debate_orchestrator is None


def test_llm_bindings_rejects_manual_orchestrator_without_both_role_models() -> None:
    """The dataclass __post_init__ refuses an inconsistent manual
    construction so a fork bug is caught at build time, not deep
    inside the orchestrator on the first event."""

    from fdai.core.quality_gate.debate import DebateOrchestrator, DebateOrchestratorConfig
    from fdai.core.quality_gate.testing import MatchTypeCrossCheckModel
    from fdai.core.tiers.t1_lightweight.testing import DeterministicEmbeddingModel

    # Fake critic/judge for the orchestrator - never called here.
    class _FakeCritic:
        async def critique(self, *args, **kwargs):  # pragma: no cover - never called
            raise NotImplementedError

    class _FakeJudge:
        async def judge(self, *args, **kwargs):  # pragma: no cover - never called
            raise NotImplementedError

    orch = DebateOrchestrator(
        critic=_FakeCritic(),  # type: ignore[arg-type]
        judge=_FakeJudge(),  # type: ignore[arg-type]
        config=DebateOrchestratorConfig(max_rounds=1),
    )
    with pytest.raises(ValueError, match="requires both critic_model and judge_model"):
        LlmBindings(
            embedding_model=DeterministicEmbeddingModel(),
            cross_check_models=(MatchTypeCrossCheckModel(model_id="x"),),
            critic_model=None,
            judge_model=None,
            debate_orchestrator=orch,
        )


# ---------------------------------------------------------------------------
# wire_azure_container (public fork API)
# ---------------------------------------------------------------------------


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SHIPPED_CATALOG_ROOT = _REPO_ROOT / "rule-catalog"


def test_azure_wire_overrides_rejects_empty_endpoint(tmp_path: Path) -> None:
    """Fork bug: forgot to fill in AzureWireOverrides.endpoint. Caught at
    build time, before any I/O."""
    from fdai.composition import AzureWireOverrides
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore

    with pytest.raises(ValueError, match="endpoint MUST be non-empty"):
        AzureWireOverrides(
            endpoint="",
            catalog_root=tmp_path,
            operator_memory_store=InMemoryOperatorMemoryStore(),
        )


def test_azure_wire_overrides_rejects_none_operator_memory_store(
    tmp_path: Path,
) -> None:
    """Fork bug: forgot to pass a store. Caught at build time so the
    composer never sees a None-shaped seam."""
    from fdai.composition import AzureWireOverrides

    with pytest.raises(ValueError, match="operator_memory_store MUST be"):
        AzureWireOverrides(
            endpoint="https://oai-fork.openai.azure.com",
            catalog_root=tmp_path,
            operator_memory_store=None,  # type: ignore[arg-type]
        )


async def test_wire_azure_container_rejects_non_azure_mode(tmp_path: Path) -> None:
    from fdai.composition import AzureWireOverrides, wire_azure_container
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore

    container = default_container(_config(mode=LlmMode.LOCAL_FAKE))
    http = httpx.AsyncClient()
    with pytest.raises(ValueError, match="llm.mode='azure'"):
        await wire_azure_container(
            container,
            http_client=http,
            identity=_StaticIdentity(),
            overrides=AzureWireOverrides(
                endpoint="https://oai-fork.openai.azure.com",
                catalog_root=tmp_path,
                operator_memory_store=InMemoryOperatorMemoryStore(),
            ),
        )


async def test_wire_azure_container_attaches_full_stack(tmp_path: Path) -> None:
    """End-to-end: default_container + wire_azure_container against the
    shipped rule-catalog produces a container with LLM bindings and a
    populated prompt composer, without touching the __main__ helpers."""
    from fdai.composition import AzureWireOverrides, wire_azure_container
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = await wire_azure_container(
        container,
        http_client=http,
        identity=_StaticIdentity(),
        overrides=AzureWireOverrides(
            endpoint="https://oai-fork.openai.azure.com",
            catalog_root=_SHIPPED_CATALOG_ROOT,
            operator_memory_store=InMemoryOperatorMemoryStore(),
        ),
    )
    bindings = finalized.require_llm_bindings()
    assert bindings.embedding_model is not None
    assert len(bindings.cross_check_models) == 2


async def test_wire_azure_container_propagates_scope_resolver(tmp_path: Path) -> None:
    """A fork's ScopeResolver reaches the cross-check adapters."""
    from fdai.composition import AzureWireOverrides, wire_azure_container
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore

    seen: list[str] = []

    def fake_resolver(candidate: object) -> None:  # noqa: ARG001
        seen.append("called")  # pragma: no cover - never actually invoked here
        return None

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = await wire_azure_container(
        container,
        http_client=http,
        identity=_StaticIdentity(),
        overrides=AzureWireOverrides(
            endpoint="https://oai-fork.openai.azure.com",
            catalog_root=_SHIPPED_CATALOG_ROOT,
            operator_memory_store=InMemoryOperatorMemoryStore(),
            scope_resolver=fake_resolver,
        ),
    )
    bindings = finalized.require_llm_bindings()
    # The primary + secondary cross-check adapters both carry the
    # fork's resolver reference on their config.
    primary, secondary = bindings.cross_check_models
    assert getattr(primary, "_scope_resolver", None) is fake_resolver
    assert getattr(secondary, "_scope_resolver", None) is fake_resolver


async def test_wire_azure_container_forwards_tool_providers(tmp_path: Path) -> None:
    """Fork-provided tool providers reach the tool executor."""
    from fdai.composition import AzureWireOverrides, wire_azure_container
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore

    class _FakeProvider:
        async def invoke(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover
            return None

    providers: dict[str, Any] = {"rule.query": _FakeProvider()}

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = await wire_azure_container(
        container,
        http_client=http,
        identity=_StaticIdentity(),
        overrides=AzureWireOverrides(
            endpoint="https://oai-fork.openai.azure.com",
            catalog_root=_SHIPPED_CATALOG_ROOT,
            operator_memory_store=InMemoryOperatorMemoryStore(),
            tool_providers=providers,
        ),
    )
    assert finalized.require_llm_bindings() is not None
    # Providers dict is defensively copied inside wire_azure_container so
    # the fork can mutate its own map post-wire without affecting the
    # executor.
    providers["rule.query"] = "mutation-should-not-leak"
    # We cannot introspect the executor's private providers dict without
    # reaching into implementation, but the fact that wire succeeded with
    # a non-empty mapping already exercises the branch that used to
    # hardcode ``providers={}`` in __main__.


async def test_wire_azure_container_rejects_duplicate_runtime_provider(
    tmp_path: Path,
) -> None:
    """A fork cannot silently shadow a capability-bundle provider."""
    from dataclasses import replace

    from fdai.composition import AzureWireOverrides, wire_azure_container
    from fdai.core.capability_catalog import (
        Capability,
        CapabilityBinding,
        CapabilityBindingKind,
        CapabilityBundle,
        CapabilityCategory,
        CapabilityReferences,
        SideEffectClass,
    )
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore
    from fdai.core.tools.testing import InMemoryToolProvider

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    provider = InMemoryToolProvider()
    runtime = container.capability_runtime.install(
        CapabilityBundle(
            capabilities=(
                Capability(
                    capability_id="evidence.audit",
                    name="Audit evidence",
                    category=CapabilityCategory.INVESTIGATION,
                    summary="Read audit evidence.",
                    side_effect_class=SideEffectClass.READ,
                ),
            ),
            bindings=(
                CapabilityBinding(
                    capability_id="evidence.audit",
                    kind=CapabilityBindingKind.REASONING_TOOL,
                    target_ref="audit.query",
                    provider_id="AuditLogQueryProvider",
                ),
            ),
            tool_providers={"AuditLogQueryProvider": provider},
        ),
        references=CapabilityReferences(reasoning_tools={"audit.query": "AuditLogQueryProvider"}),
    )
    container = replace(container, capability_runtime=runtime)
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))

    with pytest.raises(ValueError, match="duplicate tool providers"):
        await wire_azure_container(
            container,
            http_client=http,
            identity=_StaticIdentity(),
            overrides=AzureWireOverrides(
                endpoint="https://oai-fork.openai.azure.com",
                catalog_root=_SHIPPED_CATALOG_ROOT,
                operator_memory_store=InMemoryOperatorMemoryStore(),
                tool_providers={"AuditLogQueryProvider": provider},
            ),
        )


# ---------------------------------------------------------------------------
# Azure Monitor Logs metric-provider auto-bind (upstream default -> live
# adapter when the deploy exposes ``FDAI_MONITOR_WORKSPACE_ID`` / passes
# ``AzureWireOverrides.monitor_workspace_id``). Keeps the detection
# pipeline honest: no workspace -> NoopMetricProvider stays; workspace
# supplied -> the shipped SRE-demo query catalog binds without a fork.
# ---------------------------------------------------------------------------


async def test_wire_azure_container_skips_monitor_without_workspace(tmp_path: Path) -> None:
    """Upstream parity: no ``monitor_workspace_id`` -> NoopMetricProvider stays."""
    from fdai.composition import AzureWireOverrides, wire_azure_container
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore
    from fdai.shared.providers.metric import NoopMetricProvider

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = await wire_azure_container(
        container,
        http_client=http,
        identity=_StaticIdentity(),
        overrides=AzureWireOverrides(
            endpoint="https://oai-fork.openai.azure.com",
            catalog_root=_SHIPPED_CATALOG_ROOT,
            operator_memory_store=InMemoryOperatorMemoryStore(),
        ),
    )
    assert isinstance(finalized.metric_provider, NoopMetricProvider)


async def test_wire_azure_container_binds_monitor_with_workspace(tmp_path: Path) -> None:
    """Workspace supplied -> RoutedMetricProvider with the Azure Monitor
    Metrics REST route (fast, direct-mapped metrics) in front of the AML
    KQL route (slow, catalog fallback). Both bind together on a single
    ``monitor_workspace_id`` because they share the same identity."""
    from fdai.composition import AzureWireOverrides, wire_azure_container
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore
    from fdai.delivery.azure.demo_queries import (
        METRIC_APIM_HTTP_5XX_RATE,
        METRIC_MYSQL_CPU_PERCENT,
        sre_demo_analyzer_queries,
        sre_demo_capture_queries,
    )
    from fdai.delivery.azure.metric_logs import AzureMonitorLogsMetricProvider
    from fdai.delivery.azure.metrics_api import AzureMonitorMetricsProvider
    from fdai.delivery.azure.telemetry_query import (
        AzureLogAnalyticsRcaLogProvider,
        AzureLogAnalyticsTraceProvider,
    )
    from fdai.shared.providers.routed_metric import RoutedMetricProvider

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = await wire_azure_container(
        container,
        http_client=http,
        identity=_StaticIdentity(),
        overrides=AzureWireOverrides(
            endpoint="https://oai-fork.openai.azure.com",
            catalog_root=_SHIPPED_CATALOG_ROOT,
            operator_memory_store=InMemoryOperatorMemoryStore(),
            monitor_workspace_id="00000000-0000-0000-0000-000000000000",
        ),
    )
    routed = finalized.metric_provider
    assert isinstance(routed, RoutedMetricProvider)
    assert isinstance(finalized.log_query_provider, AzureLogAnalyticsRcaLogProvider)
    assert isinstance(finalized.trace_query_provider, AzureLogAnalyticsTraceProvider)
    # Direct-mapped metric goes to the fast Metrics API route.
    assert routed.route_for(METRIC_MYSQL_CPU_PERCENT) == (AzureMonitorMetricsProvider.__name__)
    # Rate-based metric (needs client-side compute) falls through to AML.
    assert routed.route_for(METRIC_APIM_HTTP_5XX_RATE) == (AzureMonitorLogsMetricProvider.__name__)
    # The AML tail still carries the full shipped catalog (demo capture
    # + every analyzer-referenced metric) so nothing goes unrouted.
    assert set(sre_demo_capture_queries()).issubset(routed.routed_metrics())
    assert set(sre_demo_analyzer_queries()).issubset(routed.routed_metrics())


async def test_wire_azure_container_forwards_custom_monitor_queries(tmp_path: Path) -> None:
    """A fork's own query map replaces the shipped default when supplied."""
    from fdai.composition import AzureWireOverrides, wire_azure_container
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore
    from fdai.delivery.azure.metric_logs import (
        AzureMonitorLogsMetricProvider,
        MetricKqlTemplate,
    )

    custom = {
        "fork.metric.foo": MetricKqlTemplate(
            kql="Perf | project TimeGenerated, v = 1.0, resource_id = 'x'",
            value_column="v",
            label_columns=("resource_id",),
        )
    }
    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = await wire_azure_container(
        container,
        http_client=http,
        identity=_StaticIdentity(),
        overrides=AzureWireOverrides(
            endpoint="https://oai-fork.openai.azure.com",
            catalog_root=_SHIPPED_CATALOG_ROOT,
            operator_memory_store=InMemoryOperatorMemoryStore(),
            monitor_workspace_id="00000000-0000-0000-0000-000000000000",
            monitor_queries=custom,
        ),
    )
    # monitor_workspace_id triggers both the Metrics API + AML KQL
    # routes; the custom monitor_queries override only replaces the AML
    # tail's catalog, so the composite router now serves 4 Metrics API
    # templates + 1 custom AML template.
    from fdai.shared.providers.routed_metric import RoutedMetricProvider

    routed = finalized.metric_provider
    assert isinstance(routed, RoutedMetricProvider)
    assert routed.route_for("fork.metric.foo") == (AzureMonitorLogsMetricProvider.__name__)


def test_azure_wire_overrides_rejects_queries_without_workspace(tmp_path: Path) -> None:
    """Config-time fail-closed: queries without a workspace bind nothing."""
    from fdai.composition import AzureWireOverrides
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore
    from fdai.delivery.azure.metric_logs import MetricKqlTemplate

    with pytest.raises(ValueError, match="monitor_queries requires monitor_workspace_id"):
        AzureWireOverrides(
            endpoint="https://oai-fork.openai.azure.com",
            catalog_root=tmp_path,
            operator_memory_store=InMemoryOperatorMemoryStore(),
            monitor_queries={
                "x": MetricKqlTemplate(kql="Perf", value_column="v"),
            },
        )


def test_azure_wire_overrides_rejects_prom_queries_without_endpoint(
    tmp_path: Path,
) -> None:
    """Symmetric guard on the Prom side."""
    from fdai.composition import AzureWireOverrides
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore

    with pytest.raises(ValueError, match="prometheus_queries requires prometheus_base_url"):
        AzureWireOverrides(
            endpoint="https://oai-fork.openai.azure.com",
            catalog_root=tmp_path,
            operator_memory_store=InMemoryOperatorMemoryStore(),
            prometheus_queries={"node_cpu_percent": "1"},
        )


def test_azure_wire_overrides_rejects_prom_audience_without_endpoint(
    tmp_path: Path,
) -> None:
    from fdai.composition import AzureWireOverrides
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore

    with pytest.raises(ValueError, match="prometheus_audience requires prometheus_base_url"):
        AzureWireOverrides(
            endpoint="https://oai-fork.openai.azure.com",
            catalog_root=tmp_path,
            operator_memory_store=InMemoryOperatorMemoryStore(),
            prometheus_audience="https://prometheus.monitor.azure.com",
        )


async def test_wire_azure_container_binds_prometheus_only_when_only_prom_supplied(
    tmp_path: Path,
) -> None:
    """Prom endpoint alone -> PrometheusMetricProvider bound solo (no routing)."""
    from fdai.composition import AzureWireOverrides, wire_azure_container
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore
    from fdai.delivery.prometheus import PrometheusMetricProvider

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = await wire_azure_container(
        container,
        http_client=http,
        identity=_StaticIdentity(),
        overrides=AzureWireOverrides(
            endpoint="https://oai-fork.openai.azure.com",
            catalog_root=_SHIPPED_CATALOG_ROOT,
            operator_memory_store=InMemoryOperatorMemoryStore(),
            prometheus_base_url="http://prometheus.monitor:9090",
        ),
    )
    assert isinstance(finalized.metric_provider, PrometheusMetricProvider)


async def test_wire_azure_container_routes_prom_primary_aml_fallback(
    tmp_path: Path,
) -> None:
    """Both backends set -> RoutedMetricProvider with three tiers in
    latency order: Prom (AKS-scoped, sub-minute) -> Metrics API (Azure
    PaaS direct metrics, ~1-3 min) -> AML KQL (computed / catalog
    fallback, 2-5 min). Each analyzer query lands on the fastest
    backend that can serve it."""
    from fdai.composition import AzureWireOverrides, wire_azure_container
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore
    from fdai.delivery.azure.demo_queries import (
        METRIC_APIM_HTTP_5XX_RATE,
        METRIC_MYSQL_CPU_PERCENT,
        METRIC_NODE_CPU_PERCENT,
    )
    from fdai.delivery.azure.metric_logs import AzureMonitorLogsMetricProvider
    from fdai.delivery.azure.metrics_api import AzureMonitorMetricsProvider
    from fdai.delivery.prometheus import PrometheusMetricProvider
    from fdai.shared.providers.routed_metric import RoutedMetricProvider

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = await wire_azure_container(
        container,
        http_client=http,
        identity=_StaticIdentity(),
        overrides=AzureWireOverrides(
            endpoint="https://oai-fork.openai.azure.com",
            catalog_root=_SHIPPED_CATALOG_ROOT,
            operator_memory_store=InMemoryOperatorMemoryStore(),
            monitor_workspace_id="00000000-0000-0000-0000-000000000000",
            prometheus_base_url="http://prometheus.monitor:9090",
        ),
    )
    assert isinstance(finalized.metric_provider, RoutedMetricProvider)
    # AKS-scoped metric served by Prom (route #1).
    assert finalized.metric_provider.route_for(METRIC_NODE_CPU_PERCENT) == (
        PrometheusMetricProvider.__name__
    )
    # Direct-mapped Azure PaaS metric served by the Metrics API (route #2).
    assert finalized.metric_provider.route_for(METRIC_MYSQL_CPU_PERCENT) == (
        AzureMonitorMetricsProvider.__name__
    )
    # Computed rate falls all the way through to AML KQL (route #3).
    assert finalized.metric_provider.route_for(METRIC_APIM_HTTP_5XX_RATE) == (
        AzureMonitorLogsMetricProvider.__name__
    )


# ---------------------------------------------------------------------------
# T2 RCA reasoner binding is opt-in (capability + system prompt), symmetric
# to the Critic / Judge bindings.
# ---------------------------------------------------------------------------


def _resolved_models_json_with_rca() -> str:
    """Resolver output that additionally declares the ``t2.rca``
    capability so the RCA T2 reasoner can bind."""

    return """{
  "schema_version": "1.0.0",
  "region": "koreacentral",
  "subscription_id": "00000000-0000-0000-0000-000000000000",
  "deployer_object_id": "00000000-0000-0000-0000-000000000001",
  "mixed_model_mode": "azure-foundry",
  "capabilities": [
    {"name": "t1.embedding", "status": "resolved", "publisher": "OpenAI",
     "family": "text-embedding-3-small", "sku": "Standard",
     "capacity_tpm": 100000, "invocation": "always", "reasons": []},
    {"name": "t2.reasoner.primary", "status": "resolved", "publisher": "OpenAI",
     "family": "gpt-4o", "sku": "Standard",
     "capacity_tpm": 20000, "invocation": "always", "reasons": []},
    {"name": "t2.reasoner.secondary", "status": "resolved",
     "publisher": "Anthropic", "family": "claude-opus-4", "sku": "Standard",
     "capacity_tpm": 10000, "invocation": "always", "reasons": []},
    {"name": "t2.rca", "status": "resolved", "publisher": "OpenAI",
     "family": "gpt-4o", "sku": "Standard",
     "capacity_tpm": 5000, "invocation": "on_novel_case", "reasons": []}
  ]
}
"""


def test_bind_wires_rca_reasoner_when_capability_resolves_and_prompt_supplied(
    tmp_path: Path,
) -> None:
    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json_with_rca(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = bind_azure_llm_bindings(
        container,
        identity=_StaticIdentity(),
        http_client=http,
        endpoint="https://oai-test.openai.azure.com",
        system_prompt=_TEST_SYSTEM_PROMPT,
        rca_system_prompt="unit-test rca system prompt",
    )
    bindings = finalized.require_llm_bindings()
    from fdai.core.rca import LlmRcaReasoner

    assert isinstance(bindings.rca_reasoner, LlmRcaReasoner)


def test_bind_leaves_rca_reasoner_none_when_capability_missing(tmp_path: Path) -> None:
    """Baseline resolver output (no ``t2.rca``) MUST NOT bind an RCA
    reasoner even when the caller supplies a prompt - so a deployment
    without the capability keeps T2 RCA dark and only T0 RCA runs."""

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = bind_azure_llm_bindings(
        container,
        identity=_StaticIdentity(),
        http_client=http,
        endpoint="https://oai-test.openai.azure.com",
        system_prompt=_TEST_SYSTEM_PROMPT,
        rca_system_prompt="unit-test rca system prompt",
    )
    assert finalized.require_llm_bindings().rca_reasoner is None


def test_bind_leaves_rca_reasoner_none_when_prompt_missing(tmp_path: Path) -> None:
    """Capability resolved but no ``rca_system_prompt`` supplied -> no
    reasoner. Lets a deployment ship the capability before authoring
    the RCA prompt without failing startup."""

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json_with_rca(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = bind_azure_llm_bindings(
        container,
        identity=_StaticIdentity(),
        http_client=http,
        endpoint="https://oai-test.openai.azure.com",
        system_prompt=_TEST_SYSTEM_PROMPT,
        # rca_system_prompt omitted
    )
    assert finalized.require_llm_bindings().rca_reasoner is None


async def test_wire_azure_container_binds_rca_reasoner_from_shipped_prompt(
    tmp_path: Path,
) -> None:
    """End-to-end: with the ``t2.rca`` capability resolved and the
    shipped ``base/t2-rca.v1.yaml`` prompt, wire_azure_container composes
    the RCA base layer and binds a live ``LlmRcaReasoner`` - proving the
    composer resolves the prompt via ``applies_to`` and the bind step
    attaches the adapter."""
    from fdai.composition import AzureWireOverrides, wire_azure_container
    from fdai.core.operator_memory import InMemoryOperatorMemoryStore
    from fdai.core.rca import LlmRcaReasoner

    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json_with_rca(), encoding="utf-8")
    container = default_container(_config(mode=LlmMode.AZURE, resolved_path=str(resolved)))
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = await wire_azure_container(
        container,
        http_client=http,
        identity=_StaticIdentity(),
        overrides=AzureWireOverrides(
            endpoint="https://oai-fork.openai.azure.com",
            catalog_root=_SHIPPED_CATALOG_ROOT,
            operator_memory_store=InMemoryOperatorMemoryStore(),
        ),
    )
    assert isinstance(finalized.require_llm_bindings().rca_reasoner, LlmRcaReasoner)


# ---------------------------------------------------------------------------
# T2 Primary Latency Pool (invariant-safe, opt-in)
# ---------------------------------------------------------------------------


def _resolved_models_json_with_primary_pool(pool_size: int = 2) -> str:
    names = ("t2primary-gpt-4o", "t2primary-gpt-4-1")[:pool_size]
    families = ("gpt-4o", "gpt-4.1")[:pool_size]
    pool = [
        {
            "endpoint": "https://oai-test.openai.azure.com/",
            "deployment": name,
            "api_version": "2024-06-01",
        }
        for name in names
    ]
    import json as _json

    base = _json.loads(_resolved_models_json())
    base["reasoner_primary_candidates"] = pool
    # Companion Terraform deployment capabilities (what --emit-primary-pool
    # writes) so wiring attributes each member's metering to its own family.
    for name, family in zip(names, families, strict=True):
        base["capabilities"].append(
            {
                "name": name,
                "status": "resolved",
                "publisher": "OpenAI",
                "family": family,
                "sku": "Standard",
                "capacity_tpm": 20000,
                "invocation": "always",
                "reasons": [],
            }
        )
    return _json.dumps(base)


def _bind_with_pool(tmp_path: Path, *, flag: bool, pool_size: int) -> Any:
    resolved = tmp_path / "resolved-models.json"
    resolved.write_text(_resolved_models_json_with_primary_pool(pool_size), encoding="utf-8")
    container = default_container(
        _config(
            mode=LlmMode.AZURE,
            resolved_path=str(resolved),
            t2_primary_latency_routing=flag,
        )
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200)))
    finalized = bind_azure_llm_bindings(
        container,
        identity=_StaticIdentity(),
        http_client=http,
        endpoint="https://oai-test.openai.azure.com",
        system_prompt=_TEST_SYSTEM_PROMPT,
    )
    return finalized.require_llm_bindings()


def test_primary_router_engaged_when_flag_on_and_pool_present(tmp_path: Path) -> None:
    from fdai.delivery.azure.llm.latency_routed_cross_check import (
        LatencyRoutedCrossCheckModel,
    )

    bindings = _bind_with_pool(tmp_path, flag=True, pool_size=2)
    assert isinstance(bindings.cross_check_models[0], LatencyRoutedCrossCheckModel)


def test_primary_not_routed_when_flag_off(tmp_path: Path) -> None:
    from fdai.delivery.azure.llm.cross_check import AzureOpenAICrossCheckModel
    from fdai.delivery.azure.llm.latency_routed_cross_check import (
        LatencyRoutedCrossCheckModel,
    )

    bindings = _bind_with_pool(tmp_path, flag=False, pool_size=2)
    assert isinstance(bindings.cross_check_models[0], AzureOpenAICrossCheckModel)
    assert not isinstance(bindings.cross_check_models[0], LatencyRoutedCrossCheckModel)


def test_primary_not_routed_when_pool_below_two(tmp_path: Path) -> None:
    from fdai.delivery.azure.llm.cross_check import AzureOpenAICrossCheckModel
    from fdai.delivery.azure.llm.latency_routed_cross_check import (
        LatencyRoutedCrossCheckModel,
    )

    bindings = _bind_with_pool(tmp_path, flag=True, pool_size=1)
    assert isinstance(bindings.cross_check_models[0], AzureOpenAICrossCheckModel)
    assert not isinstance(bindings.cross_check_models[0], LatencyRoutedCrossCheckModel)
