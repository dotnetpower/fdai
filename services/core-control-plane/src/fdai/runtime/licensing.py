"""Runtime binding for signed capability licensing and local issuer mode."""

from __future__ import annotations

import dataclasses
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from fdai.core.capability_catalog import CapabilityCatalog
from fdai.core.executor import LicenseGatedThorExecutionPort, ThorExecutionPort
from fdai.core.licensing import (
    DeploymentBinding,
    LicenseEntitlementAuthority,
    LicenseVerifier,
)
from fdai.core.licensing.trial_entitlement import TrialEntitlementResolver
from fdai.delivery.persistence.postgres_licensing_trial import PostgresTrialStore
from fdai.delivery.repo_assets import repo_asset_root
from fdai.delivery.trust import (
    Ed25519LicenseVerifier,
    license_public_key_pem,
    private_key_matches_public_key,
)
from fdai.runtime.venue import ExecutionVenue, resolve_execution_venue
from fdai.shared.providers.state_store import StateStore

_LOGGER = logging.getLogger("fdai.startup")
_ISSUER_PRIVATE_KEY = Path("secrets/integrity-signing-key.pem")
_DEFAULT_DISTRIBUTION_ID = "fdai-upstream"
_BINDING = re.compile(r"[0-9a-f]{64}")


class _UnavailableLicenseVerifier:
    """Keep observation available when the packaged verifier cannot load."""

    def verify(self, document: bytes, signature: bytes) -> bool:
        raise ValueError("packaged license verifier is unavailable")


def build_runtime_license_authority(
    *,
    catalog: CapabilityCatalog,
    environment: Mapping[str, str],
    distribution_id: str = _DEFAULT_DISTRIBUTION_ID,
    root: Path | None = None,
    public_key_pem: bytes | None = None,
    evaluated_at: datetime | None = None,
) -> LicenseEntitlementAuthority:
    """Build the required-license authority for one Core process.

    Only a local source checkout may inspect the fixed upstream integrity
    private-key path. Deployed venues never open it, even if a file is mounted
    there. Missing or rejected issuer material leaves the runtime in ordinary
    Trial resolution rather than failing the observation path.
    """

    asset_root = root or repo_asset_root()
    packaged_key: bytes | None
    try:
        packaged_key = public_key_pem if public_key_pem is not None else license_public_key_pem()
        verifier: LicenseVerifier = Ed25519LicenseVerifier(packaged_key)
    except (OSError, TypeError, ValueError):
        packaged_key = None
        verifier = _UnavailableLicenseVerifier()
        _LOGGER.warning(
            "license_public_key_unavailable",
            extra={"reason": "packaged_key_invalid_or_missing"},
        )

    issuer_workstation = False
    venue = resolve_execution_venue(environment)
    if (
        venue is ExecutionVenue.LOCAL
        and (asset_root / ".git").exists()
        and packaged_key is not None
    ):
        try:
            issuer_workstation = private_key_matches_public_key(
                asset_root / _ISSUER_PRIVATE_KEY,
                packaged_key,
            )
        except FileNotFoundError:
            issuer_workstation = False
        except (OSError, TypeError, ValueError):
            issuer_workstation = False
            _LOGGER.warning(
                "license_local_issuer_key_rejected",
                extra={"reason": "invalid_permissions_format_or_file_type"},
            )
        else:
            if not issuer_workstation:
                _LOGGER.warning(
                    "license_local_issuer_key_rejected",
                    extra={"reason": "public_key_mismatch"},
                )

    authority = LicenseEntitlementAuthority(
        catalog=catalog,
        token=environment.get("FDAI_LICENSE_TOKEN"),
        verifier=verifier,
        binding=DeploymentBinding(
            distribution_id=distribution_id,
            image_digest=_optional_value(environment.get("FDAI_LICENSE_IMAGE_DIGEST")),
            tenant_binding=_optional_value(environment.get("FDAI_LICENSE_DEPLOYMENT_BINDING")),
        ),
        require_license=True,
        issuer_workstation=issuer_workstation,
        trial=_trial_resolver(catalog=catalog, environment=environment),
    )
    # The startup log reports the token decision only: the Trial store must not be
    # observed on the event loop that is starting the runtime.
    entitlement = dataclasses.replace(authority, trial=None).resolve(
        now=evaluated_at or datetime.now(tz=UTC)
    )
    _LOGGER.info(
        "license_entitlement_resolved",
        extra={
            "status": entitlement.status.value,
            "license_id": entitlement.license_id,
            "not_after": (
                entitlement.not_after.isoformat() if entitlement.not_after is not None else None
            ),
            "available_capability_count": len(entitlement.available_capability_ids),
            "trial_configured": authority.trial is not None,
        },
    )
    return authority


def _trial_resolver(
    *, catalog: CapabilityCatalog, environment: Mapping[str, str]
) -> TrialEntitlementResolver | None:
    """Bind the durable Trial when the deployment supplies its installation bindings."""

    installation = _optional_value(environment.get("FDAI_INSTALLATION_BINDING"))
    deployment = _optional_value(environment.get("FDAI_LICENSE_DEPLOYMENT_BINDING"))
    if installation is None:
        return None
    if (
        _BINDING.fullmatch(installation) is None
        or deployment is None
        or _BINDING.fullmatch(deployment) is None
    ):
        _LOGGER.warning("license_trial_unbound", extra={"reason": "binding_invalid"})
        return None
    dsn = _optional_value(environment.get("FDAI_STATE_STORE_DSN"))
    if dsn is None:
        _LOGGER.warning("license_trial_unbound", extra={"reason": "state_store_unconfigured"})
        return None
    return TrialEntitlementResolver(
        catalog=catalog,
        store=PostgresTrialStore(dsn=dsn),
        installation_binding=installation,
        deployment_binding=deployment,
        on_storage_error=_log_trial_storage_error,
    )


def _log_trial_storage_error(error: Exception) -> None:
    _LOGGER.warning("license_trial_storage_unavailable", extra={"error_type": type(error).__name__})


def gate_execution(
    delegate: ThorExecutionPort,
    authority: LicenseEntitlementAuthority | None,
    audit_store: StateStore,
) -> ThorExecutionPort:
    """Apply dynamic license checks to every Thor execution path when configured."""

    if authority is None:
        return delegate
    return LicenseGatedThorExecutionPort(
        delegate=delegate,
        authority=authority,
        audit_store=audit_store,
    )


def _optional_value(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


__all__ = ["build_runtime_license_authority", "gate_execution"]
