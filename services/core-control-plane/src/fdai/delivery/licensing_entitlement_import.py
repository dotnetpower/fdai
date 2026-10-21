"""Explicit local licensing-owner intake of a confidential original full grant."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fdai_service_contracts.installation_entitlement_transport import (
    EntitlementRecipient,
    EntitlementTransportError,
    unseal_entitlement_token,
)

from fdai.core.capability_catalog.catalog import CapabilityCatalog
from fdai.core.licensing.entitlement import (
    DeploymentBinding,
    EntitlementSourceUnavailableError,
    LicenseEntitlementAuthority,
    LicenseVerifier,
)
from fdai.core.licensing.entitlement_source import EntitlementAcceptanceConflictError
from fdai.core.licensing.token import LicenseTokenError
from fdai.delivery.persistence.postgres_licensing_token import PostgresAcceptedEntitlementStore
from fdai.delivery.trust import Ed25519LicenseVerifier, license_public_key_pem
from fdai.delivery.trust.key_file import read_key_file

_LOGGER = logging.getLogger("fdai.licensing-owner")


def main(argv: Sequence[str] | None = None, *, verifier: LicenseVerifier | None = None) -> int:
    """Import under Core's packaged issuer trust; the CLI exposes no issuer override."""
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--carrier", type=Path)
    operation.add_argument("--inspect", action="store_true")
    parser.add_argument("--recipient-key", type=Path)
    parser.add_argument("--recipient-fingerprint")
    parser.add_argument("--installation-binding", required=True)
    parser.add_argument("--deployment-binding", required=True)
    args = parser.parse_args(argv)
    try:
        dsn = os.environ.get("FDAI_STATE_STORE_DSN", "")
        if not dsn:
            raise ValueError("entitlement import requires the configured Core state database")
        store = PostgresAcceptedEntitlementStore(
            dsn=dsn,
            installation_binding=args.installation_binding,
            deployment_binding=args.deployment_binding,
        )
        if args.inspect:
            receipt = store.inspect()
            print(
                json.dumps(
                    receipt.to_dict()
                    if receipt is not None
                    else {
                        "schema_version": "fdai.installation-entitlement-acceptance.v1",
                        "state": "absent",
                        "execution_authority": False,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 0
        if args.recipient_key is None or args.recipient_fingerprint is None:
            raise ValueError("entitlement import requires its independently bound recipient key")
        recipient = EntitlementRecipient(
            args.installation_binding, args.deployment_binding, args.recipient_fingerprint
        )
        private = serialization.load_pem_private_key(
            read_key_file(args.recipient_key, private=True), password=None
        )
        if not isinstance(private, X25519PrivateKey):
            raise EntitlementTransportError("entitlement import requires an X25519 recipient key")
        carrier = read_key_file(args.carrier, private=False)
        token = unseal_entitlement_token(carrier, recipient=recipient, private_key=private).decode(
            "ascii"
        )
        trusted = (
            verifier if verifier is not None else Ed25519LicenseVerifier(license_public_key_pem())
        )
        authority = LicenseEntitlementAuthority(
            catalog=CapabilityCatalog(),
            token=None,
            verifier=trusted,
            binding=DeploymentBinding(
                distribution_id="fdai-upstream",
                installation_binding=args.installation_binding,
                tenant_binding=args.deployment_binding,
            ),
            require_license=True,
        )
        _LOGGER.info(
            "entitlement_import_started",
            extra={"transport_digest": hashlib.sha256(carrier).hexdigest()},
        )
        receipt = store.accept(token, authority=authority, now=datetime.now(tz=UTC))
        print(json.dumps(receipt.to_dict(), sort_keys=True, separators=(",", ":")))
        return 0
    except (
        EntitlementTransportError,
        EntitlementAcceptanceConflictError,
        EntitlementSourceUnavailableError,
        LicenseTokenError,
        OSError,
        TypeError,
        UnsupportedAlgorithm,
        ValueError,
    ) as exc:
        _LOGGER.error("entitlement_import_rejected", extra={"error_type": type(exc).__name__})
        print(
            f"entitlement import not confirmed ({type(exc).__name__}); "
            "inspect retained acceptance before retrying; no authority inferred",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
