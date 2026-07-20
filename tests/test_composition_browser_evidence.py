from __future__ import annotations

from fdai.composition import bind_browser_evidence, default_container
from fdai.core.browser_evidence.service import (
    InMemoryBrowserEvidenceArtifactStore,
    InMemoryBrowserEvidenceCustodySink,
)
from fdai.delivery.browser.adapter import IsolatedBrowserEvidenceProvider
from fdai.delivery.browser.protocols import BrowserDriverRequest, BrowserDriverResult
from fdai.shared.config.models import AppConfig
from fdai.shared.providers.browser_evidence import (
    BrowserCaptureLimits,
    BrowserOriginPolicy,
    BrowserRedirectPolicy,
    BrowserRuntimeIsolation,
)


def _config() -> AppConfig:
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
            "llm": {"mode": "local-fake"},
        }
    )


class Resolver:
    async def resolve(self, hostname: str) -> tuple[str, ...]:
        return ("93.184.216.34",)


class Driver:
    async def capture(
        self,
        request: BrowserDriverRequest,
        *,
        gate: object,
        auth_state: object,
    ) -> BrowserDriverResult:
        return BrowserDriverResult(
            final_url=request.url,
            screenshot=None,
            visible_text="safe",
            aria_snapshot=None,
            redacted_selectors=(),
            browser_version="fake",
            response_bytes=4,
        )


def test_browser_evidence_requires_explicit_composition_binding() -> None:
    container = default_container(_config())
    assert container.browser_evidence_capture_service is None
    assert container.browser_evidence_console_tool is None
    assert container.browser_evidence_workflow_dispatcher is None

    provider = IsolatedBrowserEvidenceProvider(
        driver=Driver(),
        resolver=Resolver(),
        isolation=BrowserRuntimeIsolation(
            executor_identity_present=False,
            host_filesystem_mounted=False,
            environment_scrubbed=True,
            restricted_egress=True,
            ephemeral_profile=True,
        ),
    )
    bound = bind_browser_evidence(
        container,
        provider=provider,
        policies=(
            BrowserOriginPolicy(
                policy_id="dashboard",
                version=1,
                allowed_schemes=("https",),
                allowed_hosts=("dashboard.example",),
                allowed_path_prefixes=("/evidence",),
                auth_profile_ref="reader",
                redirect_policy=BrowserRedirectPolicy(max_redirects=0),
                limits=BrowserCaptureLimits(
                    max_response_bytes=100,
                    max_text_chars=100,
                    max_snapshot_chars=100,
                    timeout_seconds=1,
                ),
            ),
        ),
        artifacts=InMemoryBrowserEvidenceArtifactStore(),
        custody=InMemoryBrowserEvidenceCustodySink(),
    )

    assert bound is not container
    assert bound.browser_evidence_capture_service is not None
    assert bound.browser_evidence_console_tool is not None
    assert bound.browser_evidence_workflow_dispatcher is not None
    assert bound.browser_evidence_console_tool.side_effect_class == "read"
    assert container.browser_evidence_capture_service is None
