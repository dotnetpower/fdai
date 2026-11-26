"""Production decision-evidence admission composition tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from fdai.composition import (
    bind_azure_decision_evidence_admission,
    bind_decision_evidence_admission,
    default_container,
)
from fdai.delivery.azure.decision_evidence import (
    AzureBlobDecisionEvidenceAdmissionProvider,
)
from fdai.delivery.persistence.state_store_decision_evidence import (
    StateStoreDecisionEvidenceAdmissionProvider,
)
from fdai.shared.config.models import AppConfig
from fdai.shared.providers.testing.state_store import InMemoryStateStore
from fdai.shared.providers.workload_identity import IdentityToken

_NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


class _Identity:
    async def get_token(self, audience: str) -> IdentityToken:
        return IdentityToken(
            token="transient",
            audience=audience,
            expires_at=_NOW + timedelta(minutes=5),
        )


def _container():
    return default_container(
        AppConfig.model_validate(
            {
                "schema_version": "1.0.0",
                "azure": {
                    "tenant_id": "00000000-0000-0000-0000-000000000000",
                    "subscription_id": "00000000-0000-0000-0000-000000000000",
                    "region": "koreacentral",
                },
                "kafka": {
                    "bootstrap_servers": "events.example.com:9093",
                    "topic_events": "fdai.events",
                },
                "postgres": {"host": "postgres.example.com", "database": "fdai"},
                "runtime": {"env": "dev"},
                "llm": {"mode": "local-fake"},
            }
        )
    )


def test_state_store_binding_is_immutable_and_fail_closed_by_default() -> None:
    original = _container()
    bound = bind_decision_evidence_admission(
        original,
        state_store=InMemoryStateStore(),
        clock=lambda: _NOW,
    )

    assert original.decision_evidence_admission_provider is None
    assert isinstance(
        bound.decision_evidence_admission_provider,
        StateStoreDecisionEvidenceAdmissionProvider,
    )


async def test_blob_binding_replaces_only_the_admission_provider() -> None:
    original = _container()
    async with httpx.AsyncClient() as client:
        bound = bind_azure_decision_evidence_admission(
            original,
            container_url="https://example.com/operational-history",
            identity=_Identity(),
            http_client=client,
        )

    assert isinstance(
        bound.decision_evidence_admission_provider,
        AzureBlobDecisionEvidenceAdmissionProvider,
    )
    assert bound.config is original.config
    assert bound.schema_registry is original.schema_registry
