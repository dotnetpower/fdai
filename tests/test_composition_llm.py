"""Composition-root LLM wiring — local-fake vs azure."""

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
    )
    bindings = finalized.require_llm_bindings()
    assert len(bindings.cross_check_models) == 2
    # Second model is the deterministic disagree fake so quorum can never form.
    assert isinstance(bindings.cross_check_models[1], MismatchCrossCheckModel)
