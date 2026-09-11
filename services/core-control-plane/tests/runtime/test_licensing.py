"""Core runtime capability-license binding tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from fdai.core.capability_catalog import (
    Capability,
    CapabilityCatalog,
    CapabilityCategory,
    SideEffectClass,
)
from fdai.core.executor import ThorExecutionPort
from fdai.core.licensing import LicenseStatus
from fdai.runtime import licensing
from fdai.shared.providers.testing.state_store import InMemoryStateStore

_NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def _catalog() -> CapabilityCatalog:
    return CapabilityCatalog(
        (
            Capability(
                capability_id="observability.resource-discovery",
                name="Resource discovery",
                category=CapabilityCategory.DETECTION,
                summary="Read resources.",
                side_effect_class=SideEffectClass.READ,
            ),
            Capability(
                capability_id="operations.typed-mutation",
                name="Typed mutation",
                category=CapabilityCategory.REMEDIATION,
                summary="Run governed changes.",
                side_effect_class=SideEffectClass.EXECUTE,
            ),
        )
    )


def _key_pair() -> tuple[bytes, bytes]:
    private_key = Ed25519PrivateKey.generate()
    return (
        private_key.private_bytes(
            Encoding.PEM,
            PrivateFormat.PKCS8,
            NoEncryption(),
        ),
        private_key.public_key().public_bytes(
            Encoding.PEM,
            PublicFormat.SubjectPublicKeyInfo,
        ),
    )


def _write_checkout(root: Path, private_key_pem: bytes) -> None:
    (root / ".git").mkdir()
    secrets = root / "secrets"
    secrets.mkdir()
    private_path = secrets / "license-signing-key.pem"
    private_path.write_bytes(private_key_pem)
    private_path.chmod(0o600)


def test_matching_local_issuer_key_ignores_even_a_malformed_token(tmp_path: Path) -> None:
    private_pem, public_pem = _key_pair()
    _write_checkout(tmp_path, private_pem)

    authority = licensing.build_runtime_license_authority(
        catalog=_catalog(),
        environment={
            "FDAI_EXECUTION_VENUE": "local",
            "FDAI_LICENSE_TOKEN": "malformed-token",
        },
        root=tmp_path,
        public_key_pem=public_pem,
        evaluated_at=_NOW,
    )

    entitlement = authority.resolve(now=_NOW)
    assert entitlement.status is LicenseStatus.ISSUER_WORKSTATION
    assert entitlement.available_capability_ids == {
        "observability.resource-discovery",
        "operations.typed-mutation",
    }


def test_local_checkout_without_issuer_key_is_observation_only(tmp_path: Path) -> None:
    _private_pem, public_pem = _key_pair()
    (tmp_path / ".git").mkdir()

    authority = licensing.build_runtime_license_authority(
        catalog=_catalog(),
        environment={"FDAI_EXECUTION_VENUE": "local"},
        root=tmp_path,
        public_key_pem=public_pem,
        evaluated_at=_NOW,
    )

    entitlement = authority.resolve(now=_NOW)
    assert entitlement.status is LicenseStatus.ABSENT
    assert entitlement.available_capability_ids == {"observability.resource-discovery"}
    assert authority.binding.distribution_id == "fdai-upstream"


def test_downstream_distribution_identity_is_owned_by_composition(tmp_path: Path) -> None:
    _private_pem, public_pem = _key_pair()

    authority = licensing.build_runtime_license_authority(
        catalog=_catalog(),
        environment={
            "FDAI_EXECUTION_VENUE": "deployed",
            "FDAI_LICENSE_DISTRIBUTION_ID": "environment-cannot-relabel",
        },
        distribution_id="example-downstream",
        root=tmp_path,
        public_key_pem=public_pem,
        evaluated_at=_NOW,
    )

    assert authority.binding.distribution_id == "example-downstream"


def test_mismatched_local_private_key_grants_no_exception(tmp_path: Path) -> None:
    private_pem, _public_pem = _key_pair()
    _other_private_pem, other_public_pem = _key_pair()
    _write_checkout(tmp_path, private_pem)

    authority = licensing.build_runtime_license_authority(
        catalog=_catalog(),
        environment={"FDAI_EXECUTION_VENUE": "local"},
        root=tmp_path,
        public_key_pem=other_public_pem,
        evaluated_at=_NOW,
    )

    assert authority.resolve(now=_NOW).status is LicenseStatus.ABSENT


def test_deployed_runtime_never_opens_the_local_private_key(
    tmp_path: Path,
    monkeypatch,
) -> None:
    private_pem, public_pem = _key_pair()
    _write_checkout(tmp_path, private_pem)

    def fail_if_called(*_args, **_kwargs) -> bool:
        raise AssertionError("deployed runtime attempted to inspect a local private key")

    monkeypatch.setattr(licensing, "private_key_matches_public_key", fail_if_called)
    authority = licensing.build_runtime_license_authority(
        catalog=_catalog(),
        environment={"FDAI_EXECUTION_VENUE": "deployed"},
        root=tmp_path,
        public_key_pem=public_pem,
        evaluated_at=_NOW,
    )

    assert authority.resolve(now=_NOW).status is LicenseStatus.ABSENT


def test_runtime_execution_gate_is_optional_and_wraps_all_thor_paths(tmp_path: Path) -> None:
    _private_pem, public_pem = _key_pair()
    authority = licensing.build_runtime_license_authority(
        catalog=_catalog(),
        environment={"FDAI_EXECUTION_VENUE": "deployed"},
        root=tmp_path,
        public_key_pem=public_pem,
        evaluated_at=_NOW,
    )
    delegate = cast(
        ThorExecutionPort,
        SimpleNamespace(
            pr_native=object(),
            direct_api=None,
            tool_call=None,
            safeguard_lifecycle_ready=False,
        ),
    )
    store = InMemoryStateStore()

    assert licensing.gate_execution(delegate, None, store) is delegate
    assert licensing.gate_execution(delegate, authority, store) is not delegate
