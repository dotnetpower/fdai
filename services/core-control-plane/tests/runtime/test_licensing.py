"""Core runtime capability-license binding tests."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
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
from fdai.core.licensing.trial import TrialRecord
from fdai.core.licensing.trial_entitlement import TrialEntitlementResolver
from fdai.delivery.persistence.postgres_licensing_trial import PostgresTrialStore
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


def _write_checkout(
    root: Path, private_key_pem: bytes, name: str = "integrity-signing-key.pem"
) -> None:
    (root / ".git").mkdir()
    secrets = root / "secrets"
    secrets.mkdir()
    private_path = secrets / name
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


def test_retired_license_key_path_grants_no_issuer_exception(tmp_path: Path) -> None:
    private_pem, public_pem = _key_pair()
    _write_checkout(tmp_path, private_pem, name="license-signing-key.pem")

    authority = licensing.build_runtime_license_authority(
        catalog=_catalog(),
        environment={"FDAI_EXECUTION_VENUE": "local"},
        root=tmp_path,
        public_key_pem=public_pem,
        evaluated_at=_NOW,
    )

    assert authority.resolve(now=_NOW).status is LicenseStatus.ABSENT


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


_INSTALLATION = "c" * 64
_DEPLOYMENT = "d" * 64


def _trial_environment(**overrides: str) -> dict[str, str]:
    environment = {
        "FDAI_EXECUTION_VENUE": "deployed",
        "FDAI_INSTALLATION_BINDING": _INSTALLATION,
        "FDAI_LICENSE_DEPLOYMENT_BINDING": _DEPLOYMENT,
        "FDAI_STATE_STORE_DSN": "postgresql://fdai@db.invalid/fdai",
    }
    environment.update(overrides)
    return {name: value for name, value in environment.items() if value}


def test_deployment_bindings_compose_the_durable_trial(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _private_pem, public_pem = _key_pair()

    def fail_if_observed(self: object, *, now: datetime) -> None:
        raise AssertionError("startup observed the Trial store on the event-loop thread")

    monkeypatch.setattr(PostgresTrialStore, "observe", fail_if_observed)
    authority = licensing.build_runtime_license_authority(
        catalog=_catalog(),
        environment=_trial_environment(),
        root=tmp_path,
        public_key_pem=public_pem,
        evaluated_at=_NOW,
    )

    trial = authority.trial
    assert isinstance(trial, TrialEntitlementResolver)
    assert isinstance(trial.store, PostgresTrialStore)
    assert trial.installation_binding == _INSTALLATION
    assert trial.deployment_binding == _DEPLOYMENT
    assert authority.binding.tenant_binding == _DEPLOYMENT


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"FDAI_INSTALLATION_BINDING": "C" * 64}, "binding_invalid"),
        ({"FDAI_LICENSE_DEPLOYMENT_BINDING": ""}, "binding_invalid"),
        ({"FDAI_LICENSE_DEPLOYMENT_BINDING": "d" * 63}, "binding_invalid"),
        ({"FDAI_STATE_STORE_DSN": ""}, "state_store_unconfigured"),
    ],
)
def test_an_incomplete_trial_binding_composes_no_trial(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    overrides: dict[str, str],
    reason: str,
) -> None:
    _private_pem, public_pem = _key_pair()

    with caplog.at_level(logging.WARNING, logger="fdai.startup"):
        authority = licensing.build_runtime_license_authority(
            catalog=_catalog(),
            environment=_trial_environment(**overrides),
            root=tmp_path,
            public_key_pem=public_pem,
            evaluated_at=_NOW,
        )

    assert authority.trial is None
    assert authority.resolve(now=_NOW).available_capability_ids == {
        "observability.resource-discovery"
    }
    unbound = [record for record in caplog.records if record.message == "license_trial_unbound"]
    assert [getattr(record, "reason", None) for record in unbound] == [reason]


@pytest.mark.parametrize(
    ("record", "acting"),
    [
        (TrialRecord(_INSTALLATION, _DEPLOYMENT, _NOW - timedelta(days=29), _NOW), True),
        (TrialRecord(_INSTALLATION, _DEPLOYMENT, _NOW - timedelta(days=30), _NOW), False),
        (TrialRecord("0" * 64, _DEPLOYMENT, _NOW - timedelta(days=1), _NOW), False),
        (
            TrialRecord(
                _INSTALLATION, _DEPLOYMENT, _NOW - timedelta(days=1), _NOW, 3, clock_blocked=True
            ),
            False,
        ),
        (None, False),
    ],
)
def test_a_keyless_core_acts_only_while_its_committed_trial_is_active(
    tmp_path: Path,
    monkeypatch,
    record: TrialRecord | None,
    acting: bool,
) -> None:
    _private_pem, public_pem = _key_pair()
    observed: list[datetime] = []

    def committed(self: object, *, now: datetime) -> TrialRecord | None:
        observed.append(now)
        return record

    monkeypatch.setattr(PostgresTrialStore, "observe", committed)
    authority = licensing.build_runtime_license_authority(
        catalog=_catalog(),
        environment=_trial_environment(),
        root=tmp_path,
        public_key_pem=public_pem,
        evaluated_at=_NOW,
    )
    assert observed == []

    entitlement = authority.resolve(now=_NOW)

    assert observed == [_NOW]
    assert ("operations.typed-mutation" in entitlement.available_capability_ids) is acting
    assert "observability.resource-discovery" in entitlement.available_capability_ids


def test_an_installation_without_a_binding_has_no_trial_and_no_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _private_pem, public_pem = _key_pair()

    with caplog.at_level(logging.WARNING, logger="fdai.startup"):
        authority = licensing.build_runtime_license_authority(
            catalog=_catalog(),
            environment=_trial_environment(FDAI_INSTALLATION_BINDING=""),
            root=tmp_path,
            public_key_pem=public_pem,
            evaluated_at=_NOW,
        )

    assert authority.trial is None
    assert not [record for record in caplog.records if record.message == "license_trial_unbound"]


def test_trial_storage_failure_is_logged_without_details_and_denies(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch,
) -> None:
    _private_pem, public_pem = _key_pair()

    def unreachable(self: object, *, now: datetime) -> None:
        raise OSError("connection refused to db.invalid with secret material")

    monkeypatch.setattr(PostgresTrialStore, "observe", unreachable)
    authority = licensing.build_runtime_license_authority(
        catalog=_catalog(),
        environment=_trial_environment(),
        root=tmp_path,
        public_key_pem=public_pem,
        evaluated_at=_NOW,
    )

    with caplog.at_level(logging.WARNING, logger="fdai.startup"):
        entitlement = authority.resolve(now=_NOW)

    assert entitlement.available_capability_ids == {"observability.resource-discovery"}
    failures = [
        record for record in caplog.records if record.message == "license_trial_storage_unavailable"
    ]
    assert [getattr(record, "error_type", None) for record in failures] == ["OSError"]
    assert "db.invalid" not in caplog.text
