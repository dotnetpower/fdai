from __future__ import annotations

import pytest
from fdai_service_contracts import DocumentOcrPolicy


def test_document_ocr_policy_binds_provider_and_resource_intent() -> None:
    local = DocumentOcrPolicy(
        environment="dev",
        revision=1,
        desired_provider="local_python",
        azure_resource_desired=False,
    )
    azure = DocumentOcrPolicy(
        environment="dev",
        revision=2,
        desired_provider="azure_document_intelligence",
        azure_resource_desired=True,
    )
    retained = DocumentOcrPolicy(
        environment="dev",
        revision=3,
        desired_provider="local_python",
        azure_resource_desired=True,
    )
    assert local.digest() != azure.digest()
    assert retained.azure_resource_desired


def test_document_ocr_policy_rejects_implicit_resource_changes() -> None:
    with pytest.raises(ValueError, match="requires Azure resource intent"):
        DocumentOcrPolicy(
            environment="dev",
            revision=1,
            desired_provider="azure_document_intelligence",
            azure_resource_desired=False,
        )
    with pytest.raises(ValueError, match="deprovision"):
        DocumentOcrPolicy(
            environment="dev",
            revision=1,
            desired_provider="azure_document_intelligence",
            azure_resource_desired=True,
            deprovision_requested=True,
        )
    with pytest.raises(ValueError, match="deprovision"):
        DocumentOcrPolicy(
            environment="dev",
            revision=1,
            desired_provider="local_python",
            azure_resource_desired=True,
            deprovision_requested=True,
        )
