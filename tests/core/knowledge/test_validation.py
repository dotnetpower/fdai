"""Validation edge cases for knowledge models + report-feed adapters + catalog."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from fdai.core.capability_catalog import (
    Capability,
    CapabilityCategory,
    SideEffectClass,
)
from fdai.core.knowledge.models import (
    CodeRepoProvider,
    CodeRepoRegistration,
    KnowledgeSourceKind,
    RegisteredDocument,
)
from fdai.shared.contracts.models import Mode

_T = datetime(2026, 7, 10, tzinfo=UTC)


def test_registered_document_rejects_empty_doc_id() -> None:
    with pytest.raises(ValueError, match="doc_id"):
        RegisteredDocument(
            doc_id="",
            source_ref="r",
            kind=KnowledgeSourceKind.UPLOAD,
            title="t",
            chunk_count=0,
            registered_by="op",
            registered_at=_T,
        )


def test_registered_document_rejects_empty_registered_by() -> None:
    with pytest.raises(ValueError, match="registered_by"):
        RegisteredDocument(
            doc_id="d",
            source_ref="r",
            kind=KnowledgeSourceKind.UPLOAD,
            title="t",
            chunk_count=0,
            registered_by="",
            registered_at=_T,
        )


def test_code_repo_registration_rejects_empty_repo_id() -> None:
    with pytest.raises(ValueError, match="repo_id"):
        CodeRepoRegistration(
            repo_id="",
            provider=CodeRepoProvider.GITHUB,
            repository="o/n",
            default_branch="main",
            registered_by="op",
            registered_at=_T,
        )


def test_code_repo_registration_rejects_bad_repository_shape() -> None:
    with pytest.raises(ValueError, match="owner/name"):
        CodeRepoRegistration(
            repo_id="r",
            provider=CodeRepoProvider.GITHUB,
            repository="noslash",
            default_branch="main",
            registered_by="op",
            registered_at=_T,
        )


def test_code_repo_registration_rejects_empty_registered_by() -> None:
    with pytest.raises(ValueError, match="registered_by"):
        CodeRepoRegistration(
            repo_id="r",
            provider=CodeRepoProvider.GITHUB,
            repository="o/n",
            default_branch="main",
            registered_by="",
            registered_at=_T,
        )


def test_capability_rejects_empty_id() -> None:
    with pytest.raises(ValueError, match="capability_id"):
        Capability(
            capability_id="",
            name="n",
            category=CapabilityCategory.KNOWLEDGE,
            summary="s",
            side_effect_class=SideEffectClass.READ,
        )


def test_breakglass_capability_must_default_to_shadow() -> None:
    with pytest.raises(ValueError, match="shadow"):
        Capability(
            capability_id="bg",
            name="n",
            category=CapabilityCategory.REMEDIATION,
            summary="s",
            side_effect_class=SideEffectClass.BREAKGLASS,
            default_mode=Mode.ENFORCE,
        )
