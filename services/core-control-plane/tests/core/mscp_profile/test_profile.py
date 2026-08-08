"""Contract tests for the MSCP operational profile provenance."""

from __future__ import annotations

import pytest
from fdai.core.mscp_profile import DEFAULT_PROFILE, OperationalProfile


def test_default_profile_is_level_neutral_and_nonconformant() -> None:
    assert DEFAULT_PROFILE.profile_id == "mscp-operational-v1"
    assert "l2" not in DEFAULT_PROFILE.profile_id.lower()
    assert "l3" not in DEFAULT_PROFILE.profile_id.lower()
    assert DEFAULT_PROFILE.conformance_claimed is False


def test_default_profile_emits_stable_audit_provenance() -> None:
    assert DEFAULT_PROFILE.audit_context() == {
        "safety_profile": "mscp-operational-v1",
        "profile_source_ref": (
            "https://github.com/dotnetpower/mscp@b66401cb4d3b43ee8d66e6ce106c51defd4c6d3a"
        ),
        "conformance_claimed": False,
    }


def test_profile_rejects_a_conformance_claim() -> None:
    with pytest.raises(ValueError, match="MUST NOT claim"):
        OperationalProfile(
            profile_id="mscp-operational-v1",
            source_repository="https://github.com/dotnetpower/mscp",
            source_revision="0" * 40,
            conformance_claimed=True,
        )


@pytest.mark.parametrize("revision", ["", "abc", "G" * 40, "A" * 40])
def test_profile_rejects_invalid_source_revision(revision: str) -> None:
    with pytest.raises(ValueError, match="source_revision"):
        OperationalProfile(
            profile_id="mscp-operational-v1",
            source_repository="https://github.com/dotnetpower/mscp",
            source_revision=revision,
        )
