import asyncio
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from fdai.core.licensing.entitlement import LicenseStatus
from fdai.delivery.persistence.postgres_licensing_token import PostgresAcceptedEntitlementStore
from fdai.runtime.licensing import build_runtime_license_authority
from tests.core.licensing.test_accepted_entitlement_source import signed_authority
from tests.core.licensing.test_installation_entitlement import _DEPLOYMENT, _INSTALLATION, _NOW


async def test_accepted_source_is_not_observed_on_the_startup_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority, token, key = signed_authority()
    observed: list[bool] = []

    def read(_store) -> str:
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        observed.append(True)
        return token

    monkeypatch.setattr(PostgresAcceptedEntitlementStore, "read", read)
    runtime = build_runtime_license_authority(
        catalog=authority.catalog,
        root=tmp_path,
        public_key_pem=key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
        evaluated_at=_NOW,
        environment={
            "FDAI_ACCEPTED_INSTALLATION_ENTITLEMENT_SOURCE": "postgres",
            "FDAI_INSTALLATION_BINDING": _INSTALLATION,
            "FDAI_LICENSE_DEPLOYMENT_BINDING": _DEPLOYMENT,
            "FDAI_STATE_STORE_DSN": "not-a-live-dsn",
        },
    )
    assert not observed and runtime.token_source is not None
    assert (await asyncio.to_thread(runtime.resolve, now=_NOW)).status is LicenseStatus.ACTIVE
    assert observed == [True]


@pytest.mark.parametrize(
    "environment",
    [
        {"FDAI_ACCEPTED_INSTALLATION_ENTITLEMENT_SOURCE": "unknown"},
        {"FDAI_ACCEPTED_INSTALLATION_ENTITLEMENT_SOURCE": "postgres"},
        {
            "FDAI_ACCEPTED_INSTALLATION_ENTITLEMENT_SOURCE": "postgres",
            "FDAI_INSTALLATION_BINDING": _INSTALLATION,
            "FDAI_LICENSE_DEPLOYMENT_BINDING": "wrong-binding",
            "FDAI_STATE_STORE_DSN": "not-a-live-dsn",
        },
        {
            "FDAI_ACCEPTED_INSTALLATION_ENTITLEMENT_SOURCE": "postgres",
            "FDAI_INSTALLATION_BINDING": _INSTALLATION,
            "FDAI_LICENSE_DEPLOYMENT_BINDING": _DEPLOYMENT,
            "FDAI_STATE_STORE_DSN": "not-a-live-dsn",
            "FDAI_LICENSE_TOKEN": "another-source",
        },
    ],
)
def test_incomplete_or_competing_store_selection_fails_explicitly(
    environment: dict[str, str], tmp_path: Path
) -> None:
    authority, _token, key = signed_authority()
    with pytest.raises(ValueError):
        build_runtime_license_authority(
            catalog=authority.catalog,
            root=tmp_path,
            public_key_pem=key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            ),
            environment=environment,
        )
