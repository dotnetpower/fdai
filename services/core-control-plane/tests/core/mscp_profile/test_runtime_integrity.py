"""Tests for the MSCP-derived runtime safety manifest."""

from __future__ import annotations

import pytest
from fdai.core.mscp_profile import (
    RuntimeComponent,
    RuntimeIntegrityStatus,
    RuntimeSafetyManifest,
    default_runtime_manifest,
    verify_runtime_integrity,
)


def _component(name: str, revision: str = "1", digest_char: str = "a") -> RuntimeComponent:
    return RuntimeComponent(name=name, revision=revision, digest=digest_char * 64)


def test_manifest_digest_is_independent_of_component_order() -> None:
    first = default_runtime_manifest((_component("policy"), _component("pantheon", "2", "b")))
    second = default_runtime_manifest((_component("pantheon", "2", "b"), _component("policy")))
    assert first.digest() == second.digest()


def test_equal_manifests_are_verified() -> None:
    manifest = default_runtime_manifest((_component("policy"),))
    result = verify_runtime_integrity(manifest, manifest)
    assert result.status is RuntimeIntegrityStatus.VERIFIED
    assert result.changed_components == ()
    assert result.profile_mismatch is False


def test_component_drift_holds_and_names_every_change() -> None:
    expected = default_runtime_manifest((_component("policy"), _component("pantheon", "1", "b")))
    observed = default_runtime_manifest((_component("policy", "2"), _component("models", "1", "c")))
    result = verify_runtime_integrity(expected, observed)
    assert result.status is RuntimeIntegrityStatus.HOLD
    assert result.changed_components == ("models", "pantheon", "policy")


def test_profile_mismatch_holds_without_component_drift() -> None:
    components = (_component("policy"),)
    expected = default_runtime_manifest(components)
    observed = RuntimeSafetyManifest("another-profile", components)
    result = verify_runtime_integrity(expected, observed)
    assert result.status is RuntimeIntegrityStatus.HOLD
    assert result.profile_mismatch is True


def test_manifest_rejects_duplicate_names_and_invalid_digest() -> None:
    with pytest.raises(ValueError, match="unique"):
        default_runtime_manifest((_component("policy"), _component("policy", "2", "b")))
    with pytest.raises(ValueError, match="SHA-256"):
        RuntimeComponent(name="policy", revision="1", digest="not-a-digest")
    with pytest.raises(ValueError, match="at least one"):
        default_runtime_manifest(())
