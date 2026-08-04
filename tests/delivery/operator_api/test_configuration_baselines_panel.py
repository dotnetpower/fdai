from __future__ import annotations

from datetime import UTC, datetime

from fdai.core.detection.configuration_drift import (
    ConfigurationBaselineRegistry,
    ConfigurationBaselineStatus,
    ConfigurationObservation,
    ConfigurationResource,
    ConfigurationReviewCampaign,
    EvidenceCompleteness,
    FrozenConfigurationBaseline,
    RegisteredConfigurationBaseline,
)
from fdai.core.detection.configuration_drift_service import ConfigurationDriftService
from fdai.delivery.configuration_drift_knowledge import (
    PinnedConfigurationBaselineKnowledgeSource,
)
from fdai.delivery.configuration_review_store import (
    StateStoreConfigurationReviewCampaignStore,
    configuration_review_campaign_id,
)
from fdai.delivery.operator_api.routes.chat_configuration_drift import (
    ConfigurationDriftChatTools,
)
from fdai.delivery.operator_api.routes.configuration_baselines import (
    ConfigurationBaselinesPanel,
)
from fdai.shared.providers.knowledge import KnowledgeDocument
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 8, 4, tzinfo=UTC)


class _BaselineSource:
    def __init__(self, baseline: FrozenConfigurationBaseline) -> None:
        self._baseline = baseline

    async def load(self) -> FrozenConfigurationBaseline:
        return self._baseline


class _ObservationSource:
    def __init__(self, observation: ConfigurationObservation) -> None:
        self._observation = observation

    async def observe(self, *, scope: str) -> ConfigurationObservation:
        assert scope == self._observation.scope
        return self._observation


async def test_panel_projects_baseline_drift_knowledge_safety_and_performance() -> None:
    resource = ConfigurationResource(
        local_name="service-a",
        resource_type="example/service",
        region="example-region",
        attributes={"sku": "Standard"},
    )
    baseline = FrozenConfigurationBaseline(
        version="v1",
        created_at=_NOW,
        scope="example-scope",
        source="reviewed snapshot",
        document_sha256="a" * 64,
        resources=(resource,),
    )
    observation = ConfigurationObservation(
        scope=baseline.scope,
        observed_at=_NOW,
        source="authoritative inventory",
        completeness=EvidenceCompleteness.COMPLETE,
        resources=(resource,),
    )
    knowledge = PinnedConfigurationBaselineKnowledgeSource(
        KnowledgeDocument(
            doc_id="configuration-baseline:v1",
            text="Configuration baseline v1 evidence.",
            source_ref="baseline.docx",
            metadata={
                "baseline_version": baseline.version,
                "document_sha256": baseline.document_sha256,
            },
        )
    )
    ticks = iter((0.0, 0.01, 0.02, 0.03, 0.04))
    context = ConfigurationDriftChatTools(
        baseline_source=_BaselineSource(baseline),
        service=ConfigurationDriftService(
            baseline_source=_BaselineSource(baseline),
            observation_source=_ObservationSource(observation),
            expected_version=baseline.version,
            expected_sha256=baseline.sha256,
            expected_scope=baseline.scope,
            knowledge_source=knowledge,
            monotonic=lambda: next(ticks),
        ),
        document_name="baseline.docx",
        baseline_registry=ConfigurationBaselineRegistry(
            (
                RegisteredConfigurationBaseline(
                    FrozenConfigurationBaseline(
                        version="v0",
                        created_at=datetime(2026, 8, 3, tzinfo=UTC),
                        scope=baseline.scope,
                        source="reviewed snapshot",
                        document_sha256="b" * 64,
                        resources=(
                            ConfigurationResource(
                                local_name="service-a",
                                resource_type="example/service",
                                region="example-region",
                                attributes={"sku": "Legacy"},
                            ),
                        ),
                    ),
                    ConfigurationBaselineStatus.SUPERSEDED,
                ),
                RegisteredConfigurationBaseline(
                    baseline,
                    ConfigurationBaselineStatus.ACTIVE,
                ),
                RegisteredConfigurationBaseline(
                    FrozenConfigurationBaseline(
                        version="other-v1",
                        created_at=_NOW,
                        scope="another-scope",
                        source="reviewed snapshot",
                        document_sha256="c" * 64,
                        resources=(),
                    ),
                    ConfigurationBaselineStatus.ACTIVE,
                ),
            )
        ),
    )
    review_store = StateStoreConfigurationReviewCampaignStore(InMemoryStateStore())
    await review_store.create(
        ConfigurationReviewCampaign(
            campaign_id=configuration_review_campaign_id(
                scope=baseline.scope,
                version=baseline.version,
            ),
            baseline_version=baseline.version,
            baseline_sha256=baseline.sha256,
            scope=baseline.scope,
        )
    )

    payload = await ConfigurationBaselinesPanel(
        context,
        review_store=review_store,
    ).render(params={})

    assert payload["baseline"]["version"] == "v1"
    assert payload["baseline"]["resource_count"] == 1
    assert [item["version"] for item in payload["versions"]] == ["v1", "v0"]
    assert payload["versions"][0]["status"] == "active"
    assert payload["versions"][1]["status"] == "superseded"
    assert payload["versions"][1]["comparison"]["verdict"] == "failed"
    assert payload["versions"][1]["comparison"]["counts"]["changed"] == 1
    assert payload["drift"]["verdict"] == "passed"
    assert payload["knowledge"]["status"] == "cited"
    assert payload["knowledge"]["citation_count"] == 1
    assert payload["safety"] == {
        "mutation_count": 0,
        "approval_request_count": 0,
        "mitigation_execution_count": 0,
        "unsupported_claim_count": 0,
    }
    assert payload["performance"]["total_ms"] == 40.0
    assert payload["review"] == {
        "configured": True,
        "state": "active",
        "completed_runs": 0,
        "required_runs": 3,
        "failed_attempts": 0,
    }
