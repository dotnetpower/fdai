"""LlmConfig - validators and defaults."""

from __future__ import annotations

import pytest
from fdai.shared.config.models import LlmConfig, LlmMode


def test_default_llm_config_is_local_fake() -> None:
    cfg = LlmConfig()
    assert cfg.mode == LlmMode.LOCAL_FAKE
    assert cfg.resolved_models_path is None
    # Default capabilities MUST include the four core ones so the composition
    # root does not have to fabricate a fallback list.
    assert "t1.embedding" in cfg.capabilities
    assert "t2.reasoner.primary" in cfg.capabilities
    assert "t2.reasoner.secondary" in cfg.capabilities


def test_azure_mode_requires_resolved_models_path() -> None:
    with pytest.raises(ValueError, match="resolved_models_path"):
        LlmConfig(mode=LlmMode.AZURE)


def test_azure_mode_with_path_is_accepted() -> None:
    cfg = LlmConfig(mode=LlmMode.AZURE, resolved_models_path="kv://resolved-models")
    assert cfg.resolved_models_path == "kv://resolved-models"


def test_capabilities_reject_duplicates() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        LlmConfig(capabilities=("t1.embedding", "t1.embedding"))


def test_capabilities_reject_missing_tier_prefix() -> None:
    with pytest.raises(ValueError, match="capabilities"):
        LlmConfig(capabilities=("bare",))


def test_llm_config_is_frozen() -> None:
    from pydantic import ValidationError

    cfg = LlmConfig()
    with pytest.raises((AttributeError, TypeError, ValidationError)):
        cfg.mode = LlmMode.AZURE  # type: ignore[misc]
