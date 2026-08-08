"""Composition seam for the shadow-only browser evidence capability."""

from __future__ import annotations

from dataclasses import replace

from fdai.composition._helpers import Container
from fdai.core.browser_evidence.service import (
    BrowserEvidenceCaptureService,
    BrowserOriginPolicyRegistry,
)
from fdai.core.browser_evidence.surfaces import (
    BrowserEvidenceConsoleTool,
    BrowserEvidenceWorkflowStepDispatcher,
)
from fdai.shared.providers.browser_evidence import (
    BrowserEvidenceArtifactStore,
    BrowserEvidenceCustodySink,
    BrowserEvidenceProvider,
    BrowserOriginPolicy,
)


def bind_browser_evidence(
    container: Container,
    *,
    provider: BrowserEvidenceProvider,
    policies: tuple[BrowserOriginPolicy, ...],
    artifacts: BrowserEvidenceArtifactStore,
    custody: BrowserEvidenceCustodySink,
) -> Container:
    """Return a container with one evidence-only capture facade bound."""

    service = BrowserEvidenceCaptureService(
        provider=provider,
        policies=BrowserOriginPolicyRegistry(policies),
        artifacts=artifacts,
        custody=custody,
    )
    return replace(
        container,
        browser_evidence_capture_service=service,
        browser_evidence_console_tool=BrowserEvidenceConsoleTool(service),
        browser_evidence_workflow_dispatcher=BrowserEvidenceWorkflowStepDispatcher(service),
    )


__all__ = ["bind_browser_evidence"]
