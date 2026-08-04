from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from starlette.applications import Starlette
from starlette.testclient import TestClient

from fdai.core.detection.configuration_drift import (
    ConfigurationObservation,
    ConfigurationResource,
    EvidenceCompleteness,
    FrozenConfigurationBaseline,
)
from fdai.core.detection.configuration_drift_service import ConfigurationDriftService
from fdai.delivery.configuration_drift_knowledge import (
    PinnedConfigurationBaselineKnowledgeSource,
)
from fdai.delivery.operator_api.routes.chat import make_chat_route
from fdai.delivery.operator_api.routes.chat_action_context import (
    ActionContextChatTools,
    needs_action_context,
)
from fdai.delivery.operator_api.routes.chat_configuration_drift import (
    ConfigurationDriftChatTools,
)
from fdai.shared.providers.knowledge import KnowledgeDocument

_NOW = datetime(2026, 8, 4, tzinfo=UTC)
_PROMPT = (
    "Treatment test with uploaded Knowledge: Use "
    "sre-s13-workload-infrastructure-baseline.docx only. Return baseline version, "
    "resources, and topology. Do not call Azure mutation or mitigation tools."
)


class _Backend:
    calls = 0

    async def answer(self, **kwargs: object) -> dict[str, str]:
        del kwargs
        self.calls += 1
        return {"answer": "fallback", "model": "test"}


@dataclass(frozen=True)
class _BaselineSource:
    baseline: FrozenConfigurationBaseline

    async def load(self) -> FrozenConfigurationBaseline:
        return self.baseline


@dataclass(frozen=True)
class _ObservationSource:
    observation: ConfigurationObservation

    async def observe(self, *, scope: str) -> ConfigurationObservation:
        assert scope == self.observation.scope
        return self.observation


async def _allow(_request: object) -> str:
    return "reader-1"


def _resolver() -> ConfigurationDriftChatTools:
    resources = (
        ConfigurationResource(
            local_name="redis-example",
            resource_type="microsoft.cache/redisenterprise",
            region="korea central",
            attributes={"sku_name": "Balanced_B0"},
        ),
        ConfigurationResource(
            local_name="vm-example",
            resource_type="microsoft.compute/virtualmachines",
            region="korea central",
            attributes={"sku_name": "Standard_B1s"},
        ),
        ConfigurationResource(
            local_name="aks-example",
            resource_type="microsoft.containerservice/managedclusters",
            region="korea central",
            attributes={"sku_name": "Base", "sku_tier": "Free"},
        ),
    )
    baseline = FrozenConfigurationBaseline(
        version="s13-v1",
        created_at=_NOW,
        scope="example-scope",
        source="reviewed inventory snapshot",
        document_sha256="a" * 64,
        resources=resources,
    )
    observation = ConfigurationObservation(
        scope=baseline.scope,
        observed_at=_NOW,
        source="authoritative inventory",
        completeness=EvidenceCompleteness.COMPLETE,
        resources=resources,
    )
    baseline_source = _BaselineSource(baseline)
    knowledge = PinnedConfigurationBaselineKnowledgeSource(
        KnowledgeDocument(
            doc_id=f"configuration-baseline:{baseline.version}",
            text="Reviewed configuration baseline inventory and topology.",
            source_ref="sre-s13-workload-infrastructure-baseline.docx",
            metadata={
                "baseline_version": baseline.version,
                "document_sha256": baseline.document_sha256,
            },
        )
    )
    service = ConfigurationDriftService(
        baseline_source=baseline_source,
        observation_source=_ObservationSource(observation),
        expected_version=baseline.version,
        expected_sha256=baseline.sha256,
        expected_scope=baseline.scope,
        knowledge_source=knowledge,
    )
    return ConfigurationDriftChatTools(
        baseline_source=baseline_source,
        service=service,
        document_name="sre-s13-workload-infrastructure-baseline.docx",
    )


def test_baseline_intent_precedes_negative_mitigation_phrase() -> None:
    backend = _Backend()
    resolver = _resolver().with_fallback(ActionContextChatTools())
    app = Starlette(
        routes=[make_chat_route(backend=backend, authorize=_allow, tool_resolver=resolver)]
    )

    payload = TestClient(app).post("/chat", json={"prompt": _PROMPT}).json()

    assert needs_action_context(_PROMPT)
    assert payload["verification"]["authority"] == "server_knowledge_context"
    assert payload["verification"]["reason_code"] == ("knowledge_configuration_baseline_grounded")
    assert "s13-v1" in payload["answer"]
    assert "sre-s13-workload-infrastructure-baseline.docx" in payload["answer"]
    assert "topology is unknown" in payload["answer"]
    assert "Mutation 0" in payload["answer"]
    assert backend.calls == 0


def test_non_baseline_mitigation_question_keeps_action_context_hold() -> None:
    backend = _Backend()
    resolver = _resolver().with_fallback(ActionContextChatTools())
    app = Starlette(
        routes=[make_chat_route(backend=backend, authorize=_allow, tool_resolver=resolver)]
    )

    payload = (
        TestClient(app)
        .post(
            "/chat",
            json={"prompt": "What is the mitigation outcome and approval status?"},
        )
        .json()
    )

    assert payload["verification"]["authority"] == "server_action_context"
    assert payload["verification"]["reason_code"] == "exact_action_context_required"
    assert backend.calls == 0
