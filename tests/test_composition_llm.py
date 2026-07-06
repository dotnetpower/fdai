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
