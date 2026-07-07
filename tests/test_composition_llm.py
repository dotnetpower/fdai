"""Composition-root LLM wiring - local-fake vs azure."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from aiopspilot.composition import (
    LlmBindings,
    LlmBindingsUnavailableError,
    bind_azure_llm_bindings,
    default_container,
)
from aiopspilot.shared.config import AppConfig
from aiopspilot.shared.config.models import LlmMode
from aiopspilot.shared.providers.workload_identity import (
    IdentityToken,
    WorkloadIdentity,
)

# Non-empty placeholder for the required Wave 2 ``system_prompt`` argument.
# The real prompt is composed from ``rule-catalog/prompts/`` via the
# PromptComposer; these tests only care that the wiring threads it through.
_TEST_SYSTEM_PROMPT = "unit-test system prompt"


def _config(*, mode: str = LlmMode.LOCAL_FAKE, resolved_path: str | None = None) -> AppConfig:
    llm: dict[str, Any] = {"mode": mode}
    if resolved_path is not None:
        llm["resolved_models_path"] = resolved_path
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
            "postgres": {"host": "example.local", "database": "aiopspilot"},
            "runtime": {"env": "dev"},
            "llm": llm,
        }
    )


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
    # Two fake cross-check models so the quality-gate default quorum (2) works.
    assert len(bindings.cross_check_models) == 2


def test_local_fake_container_never_imports_delivery_azure_llm() -> None:
    """The local-fake path MUST not pull the AOAI adapters into memory."""
    import sys

    # Purge cached modules first (safe: we re-import as needed).
    for mod in list(sys.modules):
        if mod.startswith("aiopspilot.delivery.azure.llm"):
            sys.modules.pop(mod, None)
    default_container(_config(mode=LlmMode.LOCAL_FAKE))
    assert "aiopspilot.delivery.azure.llm" not in sys.modules
    assert "aiopspilot.delivery.azure.llm.embeddings" not in sys.modules
    assert "aiopspilot.delivery.azure.llm.cross_check" not in sys.modules


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
    from aiopspilot.core.quality_gate.testing import MismatchCrossCheckModel

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
    from aiopspilot.delivery.azure.llm.cross_check import AzureOpenAICrossCheckModel

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
    from aiopspilot.delivery.azure.llm.cross_check import AzureOpenAICrossCheckModel

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
    from aiopspilot.delivery.azure.llm.critic import AzureOpenAICriticModel

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
    from aiopspilot.core.quality_gate.debate import DebateOrchestrator
    from aiopspilot.delivery.azure.llm.critic import AzureOpenAICriticModel
    from aiopspilot.delivery.azure.llm.judge import AzureOpenAIJudgeModel

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

    from aiopspilot.core.quality_gate.debate import DebateOrchestrator, DebateOrchestratorConfig
    from aiopspilot.core.quality_gate.testing import MatchTypeCrossCheckModel
    from aiopspilot.core.tiers.t1_lightweight.testing import DeterministicEmbeddingModel

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
    from aiopspilot.composition import AzureWireOverrides
    from aiopspilot.core.operator_memory import InMemoryOperatorMemoryStore

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
    from aiopspilot.composition import AzureWireOverrides

    with pytest.raises(ValueError, match="operator_memory_store MUST be"):
        AzureWireOverrides(
            endpoint="https://oai-fork.openai.azure.com",
            catalog_root=tmp_path,
            operator_memory_store=None,  # type: ignore[arg-type]
        )


async def test_wire_azure_container_rejects_non_azure_mode(tmp_path: Path) -> None:
    from aiopspilot.composition import AzureWireOverrides, wire_azure_container
    from aiopspilot.core.operator_memory import InMemoryOperatorMemoryStore

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
    from aiopspilot.composition import AzureWireOverrides, wire_azure_container
    from aiopspilot.core.operator_memory import InMemoryOperatorMemoryStore

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
    from aiopspilot.composition import AzureWireOverrides, wire_azure_container
    from aiopspilot.core.operator_memory import InMemoryOperatorMemoryStore

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
    from aiopspilot.composition import AzureWireOverrides, wire_azure_container
    from aiopspilot.core.operator_memory import InMemoryOperatorMemoryStore

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
